"""Order Entry Agent (execution plan W5 D1-D2).

    python -m src.agents.order_agent --count 6          # process 6 corpus emails
    python -m src.agents.order_agent --count 6 --dry-run  # extract, never POST

order email -> LLM extraction -> validation -> `POST /orders` on the mock TMS, **or**
a clarifying question when the email does not contain enough to file.

Three stages, kept separate on purpose
--------------------------------------
1. **`extract_order()`** -- one LLM call through `src.agents.llm.get_llm()` (D-007's
   single construction site), rendering the versioned `order_entry/v1.md` prompt
   (D-008). Returns the model's own `file` / `clarify` decision.
2. **`validate_order()`** -- pure Python, no model. Re-checks what the TMS's
   `OrderCreate` contract will check anyway: required fields present, centre codes the
   right shape, `pieces` a positive integer, `weight_kg` positive. A model that
   confidently returns `pieces: 0` should be caught here, one function from where it
   happened, rather than as a 422 from an HTTP call three layers away.
3. **`post_order()`** -- the actual `POST /orders`, carrying `external_ref` so the
   same email replayed twice cannot file two orders (D-017 built that key for exactly
   this).

The split matters because the failure modes are genuinely different and want
different fixes: a bad extraction is a prompt problem, a validation failure is a
contract problem, and a POST failure is an environment problem. Collapsing them into
one try/except would make all three look the same in the log.

**Scoring is not done here.** Lahari authors the 50-case evaluation set and measures
success and clarification rates at D5 (execution plan) -- the same builder/judge split
D-028 already applies to document extraction. This module's job ends at producing a
per-email outcome record and writing it where her harness can read it.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from src.agents.llm import get_llm
from src.agents.order_corpus import ORDER_CORPUS_JSON, OrderEmail
from src.agents.prompts.registry import Prompt, load_prompt
from src.agents.tracing import traced
from src.common import config
from src.common.logging_setup import get_logger
from src.tms.models import OrderSource

log = get_logger("agents.order_agent")

RUNS_JSON = config.BENCHMARKS_RAW_DIR / "w5_order_agent_runs.json"

#: The prompt asks for bare JSON (rule 8); models sometimes fence it anyway, because
#: that is a request the API does not enforce. Stripped rather than treated as a
#: failure -- the same allowance `document_agent` already makes for the same reason.
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```\s*$", re.MULTILINE)

#: `IND` + 6 digits + 3 letters, the shape D-002 keys every corridor on.
CENTRE_CODE_RE = re.compile(r"^IND\d{6}[A-Z]{3}$")

REQUIRED_FIELDS = ("customer_name", "origin_centre", "dest_centre", "route_type", "pieces", "weight_kg")


@dataclass
class OrderOutcome:
    """What happened to one email, whatever happened. Written for Lahari's D5 harness."""

    seq: int
    variant: str
    expected_action: str
    expected_missing: str | None
    action: str | None = None            # "file" | "clarify" | None if extraction failed
    missing_field: str | None = None
    question: str | None = None
    order: dict | None = None
    validation_errors: list[str] = field(default_factory=list)
    posted: bool = False
    order_ref: str | None = None
    http_status: int | None = None
    error: str | None = None
    prompt_version: str | None = None


def _response_text(response: object) -> str:
    """Flatten a chat model's `.content`, which is a string on some providers and a
    list of content blocks on others (P-35's own finding, same handling)."""
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        )
    return str(content)


def extract_order(subject: str, body: str, prompt: Prompt | None = None) -> dict:
    """One LLM call -> the `file` / `clarify` decision the prompt specifies."""
    prompt = prompt or load_prompt("order_entry")
    rendered = prompt.render(email_subject=subject, email_body=body)
    raw = _response_text(get_llm().invoke(rendered))
    cleaned = _JSON_FENCE_RE.sub("", raw.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{prompt.label} returned non-JSON: {cleaned[:300]!r}") from exc


def validate_order(order: dict | None) -> list[str]:
    """Everything the TMS's `OrderCreate` would reject, checked before the round trip.

    Returns a list of human-readable problems -- empty means the order is postable.
    Deliberately not raising: an agent that gets one field wrong should still produce
    a record showing exactly which one, not an exception that loses the other five.
    """
    if not order:
        return ["no order object returned"]

    problems: list[str] = []
    for name in REQUIRED_FIELDS:
        if order.get(name) in (None, ""):
            problems.append(f"{name} is missing")

    for name in ("origin_centre", "dest_centre"):
        value = order.get(name)
        if isinstance(value, str) and value and not CENTRE_CODE_RE.match(value.strip().upper()):
            problems.append(f"{name} {value!r} is not IND + 6 digits + 3 letters")

    origin, dest = order.get("origin_centre"), order.get("dest_centre")
    if origin and dest and str(origin).strip().upper() == str(dest).strip().upper():
        problems.append("origin and destination are the same centre")

    route_type = order.get("route_type")
    if route_type is not None and route_type not in config.ROUTE_TYPES:
        problems.append(f"route_type {route_type!r} is not one of {list(config.ROUTE_TYPES)}")

    pieces = order.get("pieces")
    if pieces is not None and (not isinstance(pieces, int) or isinstance(pieces, bool) or pieces < 1):
        problems.append(f"pieces {pieces!r} is not a positive whole number")

    weight = order.get("weight_kg")
    if weight is not None and (not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0):
        problems.append(f"weight_kg {weight!r} is not a positive number")

    return problems


def post_order(order: dict, external_ref: str, base_url: str | None = None) -> tuple[int, dict]:
    """`POST /orders`, carrying the idempotency key. Returns (status, body)."""
    payload = {
        "customer_name": order["customer_name"],
        "origin_centre": order["origin_centre"],
        "dest_centre": order["dest_centre"],
        "route_type": order["route_type"],
        "pieces": order["pieces"],
        "weight_kg": order["weight_kg"],
        "external_ref": external_ref,
        # The enum itself, not a string that looks like one. `"EMAIL"` seemed obvious
        # and is not a member -- the TMS answered 422 and the agent's own validation
        # had nothing to say, because `source` is set here rather than extracted and so
        # never passed through `validate_order` (P-41). Importing the enum makes an
        # invalid value impossible instead of merely detectable.
        "source": OrderSource.AGENT.value,
        "notes": order.get("notes"),
    }
    headers = {"X-API-Key": config.TMS_API_KEY} if config.TMS_API_KEY else {}
    response = httpx.post(
        f"{(base_url or config.TMS_BASE_URL).rstrip('/')}/orders",
        json=payload, headers=headers, timeout=15.0,
    )
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"detail": response.text[:300]}


def process_email(email: OrderEmail, prompt: Prompt, dry_run: bool = False) -> OrderOutcome:
    """Extract, validate, and (unless `dry_run`) file. Never raises for one email. Traced."""
    with traced("order_entry", inputs={"seq": email.seq, "variant": email.variant, "subject": email.subject,
                                       "body": email.body, "prompt": prompt.label, "dry_run": dry_run}) as span:
        outcome = _process_email(email, prompt, dry_run)
        span.outputs = asdict(outcome)
        return outcome


def _process_email(email: OrderEmail, prompt: Prompt, dry_run: bool) -> OrderOutcome:
    outcome = OrderOutcome(
        seq=email.seq,
        variant=email.variant,
        expected_action=email.expected_action,
        expected_missing=email.expected_missing,
        prompt_version=prompt.label,
    )
    try:
        result = extract_order(email.subject, email.body, prompt)
    except Exception as exc:  # noqa: BLE001 -- one bad email must not abort the run
        outcome.error = str(exc)
        log.warning("#%s %-16s -> extraction FAILED: %s", email.seq, email.variant, str(exc)[:120])
        return outcome

    outcome.action = result.get("action")
    outcome.order = result.get("order")
    outcome.missing_field = result.get("missing_field")
    outcome.question = result.get("question")

    if outcome.action == "clarify":
        log.info("#%s %-16s -> clarify (%s)", email.seq, email.variant, outcome.missing_field)
        return outcome

    outcome.validation_errors = validate_order(outcome.order)
    if outcome.validation_errors:
        log.warning("#%s %-16s -> invalid: %s", email.seq, email.variant, "; ".join(outcome.validation_errors))
        return outcome

    if dry_run:
        log.info("#%s %-16s -> would file (dry run)", email.seq, email.variant)
        return outcome

    try:
        status, body = post_order(outcome.order, email.external_ref)
        outcome.http_status = status
        outcome.posted = status == 201
        outcome.order_ref = body.get("order_ref")
        if outcome.posted:
            log.info("#%s %-16s -> filed %s", email.seq, email.variant, outcome.order_ref)
        else:
            outcome.error = str(body.get("detail"))[:300]
            log.warning("#%s %-16s -> POST %s: %s", email.seq, email.variant, status, outcome.error)
    except Exception as exc:  # noqa: BLE001 -- a TMS that is not running must say so
        outcome.error = f"POST failed: {exc}"
        log.warning("#%s %-16s -> %s", email.seq, email.variant, outcome.error)
    return outcome


def load_corpus(path: Path) -> list[OrderEmail]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [OrderEmail(**item) for item in raw]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=ORDER_CORPUS_JSON)
    parser.add_argument(
        "--count", type=int, default=6,
        help="emails to process -- default kept small because the free-tier LLM quota is "
             "20 calls a day (D-032)",
    )
    parser.add_argument("--dry-run", action="store_true", help="extract and validate, never POST")
    parser.add_argument("--prompt-version", type=str, default=None, help="pin a version, e.g. v1")
    parser.add_argument("--out", type=Path, default=RUNS_JSON)
    args = parser.parse_args()

    if not args.corpus.exists():
        log.error("Missing %s -- run `python -m src.agents.order_corpus` first.", args.corpus)
        return 1

    prompt = load_prompt("order_entry", args.prompt_version)
    emails = load_corpus(args.corpus)[: args.count]
    log.info("%d email(s), prompt %s%s", len(emails), prompt.label, " (dry run)" if args.dry_run else "")

    outcomes = [process_email(email, prompt, args.dry_run) for email in emails]

    filed = sum(1 for o in outcomes if o.posted)
    clarified = sum(1 for o in outcomes if o.action == "clarify")
    failed = sum(1 for o in outcomes if o.error and o.action is None)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "prompt_version": prompt.label,
                "n_emails": len(outcomes),
                "n_filed": filed,
                "n_clarified": clarified,
                "n_extraction_failed": failed,
                "dry_run": args.dry_run,
                "outcomes": [asdict(o) for o in outcomes],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    log.info("%d filed, %d clarified, %d extraction failures -> %s", filed, clarified, failed, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
