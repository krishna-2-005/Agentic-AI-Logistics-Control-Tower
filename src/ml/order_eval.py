"""Order Entry Agent evaluation (execution plan W5 D5) -- Lahari's 50-case set and harness.

    python -m src.ml.order_eval --build              # write the authored eval set
    python -m src.ml.order_eval --run --budget 20    # next 20 unrun cases, one LLM call each
    python -m src.ml.order_eval --report             # score whatever has run so far

Krishna built the agent (D1-D2) and tested it on his own corpus. This is the judge's
half of D-028's builder/judge split: a set he has never seen, written in phrasings his
corpus never uses, scored for **success rate** and **clarification rate** as the plan
asks, and for the two failure modes that actually matter in an order-entry clerk.

The set: 10 templates x 5 real records
--------------------------------------
Every case is built from a real `ConsignmentRecord` (real audited corridors, real centre
codes -- D-021), drawn with a different seed from Krishna's corpus, and phrased by one of
ten templates that each test one thing his corpus does not:

=====================  =======  ==================================================
template               expect   what it tests
=====================  =======  ==================================================
``clean_table``        file     key/value layout, "Full Truck Load" for FTL
``tonnes``             file     weight given in tonnes (prompt rule 5: convert)
``pieces_in_words``    file     "twelve cartons" rather than 12
``prose_reversed``     file     destination named before origin, in running prose
``correction``         file     a forwarded mail whose top line corrects the weight
``weight_range``       ask      "between 2 and 3 tonnes" -- rule 5 says ask
``city_destination``   ask      destination is a city, not a code (Krishna only
                                ever tests a vague *origin*)
``no_service``         ask      FTL/Carting simply never mentioned
``pieces_approx``      ask      "roughly 10-12 boxes"
``missing_two``        ask      weight AND service missing; rule 2 says ask about
                                weight first, so only ``weight_kg`` is correct
=====================  =======  ==================================================

Every email is signed by a *person* at the sending company, so all 50 cases also test
rule 6 (the customer is the company, not the signatory).

The quota, and why this runs over several days
----------------------------------------------
Gemini's free tier allows 20 calls a day (D-032), and this set needs 50. The run is
resumable: each finished case is appended to `benchmarks/raw/w5_order_eval_runs.jsonl`
with the date it ran, `--run` only takes cases that have not run yet, and a quota
refusal **stops the run without recording the case**, so a 429 is never mistaken for an
agent failure. `--report` scores whatever has run and says plainly how many of the 50
that is. The run refuses any provider but Gemini -- the model the agent was built on.

Cases run with `dry_run=True`: extract and validate, no `POST`. What is being judged is
the agent's decision and its fields. The `POST` path was verified end to end at D1-D2
(three real orders, idempotency checked), and filing 25 more synthetic orders into the
TMS would test the network, not the agent.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.agents.doc_corpus.records import ConsignmentRecord, generate_records
from src.agents.llm import DEFAULT_MODELS
from src.agents.order_agent import process_email
from src.agents.order_corpus import OrderEmail
from src.agents.prompts.registry import load_prompt
from src.common import config, docs
from src.common.logging_setup import get_logger

log = get_logger("ml.order_eval")

EVAL_SET_JSON = config.BENCHMARKS_RAW_DIR / "w5_order_eval_set.json"
RUNS_JSONL = config.BENCHMARKS_RAW_DIR / "w5_order_eval_runs.jsonl"
SCORES_CSV = config.BENCHMARKS_RAW_DIR / "w5_order_eval_scores.csv"
SUMMARY_JSON = config.BENCHMARKS_RAW_DIR / "w5_order_eval_summary.json"
DOC_PATH = config.DOCS_DIR / "W5_lahari_stream_validation.md"

#: A different seed from Krishna's corpus (42) and a seq range his never reaches, so no
#: record, and no `external_ref`, is shared between the builder's set and the judge's.
EVAL_SEED = 2026
SEQ_OFFSET = 5000
CASES_PER_TEMPLATE = 5
DAILY_BUDGET = 20

SIGNATORIES = ["Ravi Kumar", "Anita Sharma", "Suresh Iyer", "Meena Das", "Arjun Patel"]

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty", 6: "sixty", 7: "seventy", 8: "eighty", 9: "ninety"}


def number_in_words(n: int) -> str:
    """1-99 in words; anything larger stays digits (the template then says so)."""
    if 0 <= n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")
    return str(n)


def _service_phrase(route_type: str) -> str:
    return "Full Truck Load" if route_type == "FTL" else "Carting (part load)"


def _sign(record: ConsignmentRecord, i: int) -> str:
    return f"Best regards,\n{SIGNATORIES[i % len(SIGNATORIES)]}\nLogistics desk, {record.shipper_name}"


def _truth(record: ConsignmentRecord, **overrides) -> dict:
    fields = {
        "customer_name": record.shipper_name,
        "origin_centre": record.source_center,
        "dest_centre": record.dest_center,
        "route_type": record.route_type,
        "pieces": record.pieces,
        "weight_kg": record.weight_kg,
    }
    fields.update(overrides)
    return {k: v for k, v in fields.items() if v is not None}


# ── the ten templates: (subject, body, expected_fields) ─────────────────────
def t_clean_table(r: ConsignmentRecord, i: int):
    body = (
        "Dear team,\n\nKindly arrange the following consignment.\n\n"
        f"Origin hub code:       {r.source_center} ({r.source_name})\n"
        f"Destination hub code:  {r.dest_center} ({r.dest_name})\n"
        f"No. of packages:       {r.pieces}\n"
        f"Gross weight:          {r.weight_kg} kg\n"
        f"Mode:                  {_service_phrase(r.route_type)}\n"
        f"Receiver:              {r.consignee_name}\n\n{_sign(r, i)}"
    )
    return f"Consignment request - {r.source_center}", body, _truth(r)


def t_tonnes(r: ConsignmentRecord, i: int):
    tonnes = round(r.weight_kg / 1000, 3)
    body = (
        f"Hello,\n\nWe have {r.pieces} pallets ready at {r.source_name} (code {r.source_center}) "
        f"for {r.dest_name} (code {r.dest_center}), consignee {r.consignee_name}.\n"
        f"Total load is {tonnes} tonnes. {_service_phrase(r.route_type)} please.\n\n{_sign(r, i)}"
    )
    return "Pallets ready for pickup", body, _truth(r, weight_kg=round(tonnes * 1000, 1))


def t_pieces_in_words(r: ConsignmentRecord, i: int):
    body = (
        f"Hi,\n\nPlease collect {number_in_words(r.pieces)} carton{'' if r.pieces == 1 else 's'} from {r.source_name} "
        f"({r.source_center}) and deliver to {r.consignee_name} at {r.dest_name} "
        f"({r.dest_center}). Combined weight {r.weight_kg} kg. Service: {r.route_type}.\n\n{_sign(r, i)}"
    )
    return "Carton collection", body, _truth(r)


def t_prose_reversed(r: ConsignmentRecord, i: int):
    body = (
        f"Good morning,\n\nThis needs to reach {r.consignee_name} at {r.dest_name}, hub "
        f"{r.dest_center}. It will be collected from our {r.source_name} premises, hub code "
        f"{r.source_center}. {r.pieces} crates, {r.weight_kg} kg altogether, on "
        f"{_service_phrase(r.route_type)}.\n\n{_sign(r, i)}"
    )
    return f"Delivery to {r.dest_city or r.dest_center}", body, _truth(r)


def t_correction(r: ConsignmentRecord, i: int):
    wrong = round(r.weight_kg * 1.3, 1)
    body = (
        f"Hi again,\n\nCorrection to my mail below: the weight is {r.weight_kg} kg, not {wrong} kg. "
        "Everything else stands.\n\n---------- Forwarded message ----------\n"
        f"Please book {r.pieces} pieces from {r.source_name} ({r.source_center}) to "
        f"{r.dest_name} ({r.dest_center}), consignee {r.consignee_name}. Weight {wrong} kg. "
        f"{r.route_type}.\n\n{_sign(r, i)}"
    )
    return "Fwd: booking (weight corrected)", body, _truth(r)


def t_weight_range(r: ConsignmentRecord, i: int):
    lo = max(1, int(r.weight_kg // 1000))
    body = (
        f"Hello,\n\nBooking needed from {r.source_name} ({r.source_center}) to {r.dest_name} "
        f"({r.dest_center}) for {r.consignee_name}. {r.pieces} pieces, {r.route_type}.\n"
        f"Total weight should be somewhere between {lo} and {lo + 1} tonnes.\n\n{_sign(r, i)}"
    )
    return "Booking request", body, _truth(r, weight_kg=None)


def t_city_destination(r: ConsignmentRecord, i: int):
    city = r.dest_city or r.dest_state or "the usual"
    body = (
        f"Hi,\n\nPlease move {r.pieces} pieces ({r.weight_kg} kg) from {r.source_name} "
        f"({r.source_center}) to our {city} depot, attention {r.consignee_name}. "
        f"{_service_phrase(r.route_type)}.\n\n{_sign(r, i)}"
    )
    return f"Shipment to {city}", body, _truth(r, dest_centre=None)


def t_no_service(r: ConsignmentRecord, i: int):
    body = (
        f"Dear team,\n\nPickup from {r.source_name} ({r.source_center}), drop at {r.dest_name} "
        f"({r.dest_center}). Consignee {r.consignee_name}. {r.pieces} pieces, {r.weight_kg} kg.\n"
        f"Please confirm the pickup time.\n\n{_sign(r, i)}"
    )
    return "Pickup request", body, _truth(r, route_type=None)


def t_pieces_approx(r: ConsignmentRecord, i: int):
    p = max(2, r.pieces)
    body = (
        f"Hello,\n\nWe need roughly {p}-{p + 2} boxes moved from {r.source_name} "
        f"({r.source_center}) to {r.dest_name} ({r.dest_center}), consignee {r.consignee_name}. "
        f"Total {r.weight_kg} kg, {r.route_type}.\n\n{_sign(r, i)}"
    )
    return "Boxes to move", body, _truth(r, pieces=None)


def t_missing_two(r: ConsignmentRecord, i: int):
    body = (
        f"Hi,\n\n{r.pieces} pieces to go from {r.source_name} ({r.source_center}) to "
        f"{r.dest_name} ({r.dest_center}) for {r.consignee_name}. We are still weighing the "
        f"load and will decide on the vehicle once we know it.\n\n{_sign(r, i)}"
    )
    return "Upcoming shipment", body, _truth(r, weight_kg=None, route_type=None)


#: name -> (builder, expected action, the one field a correct question is about)
TEMPLATES = {
    "clean_table": (t_clean_table, "file", None),
    "tonnes": (t_tonnes, "file", None),
    "pieces_in_words": (t_pieces_in_words, "file", None),
    "prose_reversed": (t_prose_reversed, "file", None),
    "correction": (t_correction, "file", None),
    "weight_range": (t_weight_range, "clarify", "weight_kg"),
    "city_destination": (t_city_destination, "clarify", "dest_centre"),
    "no_service": (t_no_service, "clarify", "route_type"),
    "pieces_approx": (t_pieces_approx, "clarify", "pieces"),
    "missing_two": (t_missing_two, "clarify", "weight_kg"),
}


def build_eval_set() -> list[OrderEmail]:
    """50 cases, deterministic in `EVAL_SEED`, templates interleaved so any prefix of the
    set -- which is what a 20-a-day run takes -- covers every template."""
    names = list(TEMPLATES)
    records = generate_records(len(names) * CASES_PER_TEMPLATE, seed=EVAL_SEED)
    cases = []
    for i, record in enumerate(records):
        name = names[i % len(names)]
        builder, action, missing = TEMPLATES[name]
        subject, body, truth = builder(record, i)
        cases.append(OrderEmail(
            seq=SEQ_OFFSET + i + 1, variant=name, subject=subject, body=body,
            expected_action=action, expected_missing=missing, expected_fields=truth,
        ))
    return cases


def write_eval_set(path: Path = EVAL_SET_JSON) -> list[OrderEmail]:
    cases = build_eval_set()
    path.write_text(json.dumps([asdict(c) for c in cases], indent=2), encoding="utf-8")
    log.info("%d eval cases (%d templates) -> %s", len(cases), len(TEMPLATES), path)
    return cases


def load_eval_set(path: Path = EVAL_SET_JSON) -> list[OrderEmail]:
    if not path.exists():
        return write_eval_set(path)
    return [OrderEmail(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


def load_runs(path: Path = RUNS_JSONL) -> dict[int, dict]:
    if not path.exists():
        return {}
    runs = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            runs[record["seq"]] = record
    return runs


def is_quota_error(error: str | None) -> bool:
    text = (error or "").lower()
    return any(marker in text for marker in ("429", "resource_exhausted", "quota"))


def run(budget: int = DAILY_BUDGET, eval_path: Path = EVAL_SET_JSON, runs_path: Path = RUNS_JSONL) -> int:
    """Run the next `budget` unrun cases. Returns how many were recorded."""
    if config.LLM_PROVIDER.lower() != "gemini":
        raise RuntimeError(
            f"LLM_PROVIDER is {config.LLM_PROVIDER!r}; this eval runs on gemini only -- the model "
            "the agent was built on. Set LLM_PROVIDER=gemini."
        )
    model = os.environ.get("LLM_MODEL") or DEFAULT_MODELS["gemini"]
    prompt = load_prompt("order_entry")
    cases, done = load_eval_set(eval_path), load_runs(runs_path)
    todo = [c for c in cases if c.seq not in done][:budget]
    log.info("%d of %d already run; running %d now on %s", len(done), len(cases), len(todo), model)

    recorded = 0
    for case in todo:
        outcome = process_email(case, prompt, dry_run=True)
        if outcome.action is None and is_quota_error(outcome.error):
            log.warning("quota reached after %d case(s) -- stopping; case %d not recorded", recorded, case.seq)
            break
        record = {
            "seq": case.seq, "template": case.variant,
            "ran_on": datetime.now().astimezone().date().isoformat(),
            "provider": "gemini", "model": model, "prompt_version": prompt.label,
            "outcome": asdict(outcome),
        }
        with runs_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        recorded += 1
    log.info("recorded %d; %d of %d now run", recorded, len(done) + recorded, len(cases))
    return recorded


# ── scoring ──────────────────────────────────────────────────────────────────
def field_matches(name: str, got, want) -> bool:
    if got is None or isinstance(got, bool):
        return False
    if name == "weight_kg":
        try:
            return abs(float(got) - float(want)) <= max(1.0, 0.005 * float(want))
        except (TypeError, ValueError):
            return False
    if name == "pieces":
        try:
            return float(got).is_integer() and int(float(got)) == int(want)
        except (TypeError, ValueError):
            return False
    return str(got).strip().upper() == str(want).strip().upper()


def score_case(case: OrderEmail, outcome: dict) -> dict:
    """One case's verdict. `success` is the plan's success rate; the rest say *why*."""
    action = outcome.get("action")
    order = outcome.get("order") or {}
    action_correct = action == case.expected_action
    mismatched = [
        name for name, want in case.expected_fields.items()
        if not field_matches(name, order.get(name), want)
    ]
    right_field = action == "clarify" and outcome.get("missing_field") == case.expected_missing
    if case.expected_action == "file":
        success = action_correct and not mismatched and not outcome.get("validation_errors")
    else:
        success = right_field
    return {
        "seq": case.seq,
        "template": case.variant,
        "expected_action": case.expected_action,
        "action": action,
        "expected_missing": case.expected_missing,
        "missing_field": outcome.get("missing_field"),
        "action_correct": action_correct,
        "right_field": right_field,
        "mismatched_fields": ",".join(mismatched) if case.expected_action == "file" else "",
        # The dangerous error: filing an order the email did not fully specify. Every
        # such order carries at least one value the model invented (prompt rule 1).
        "invented_order": case.expected_action == "clarify" and action == "file",
        # The annoying error: asking a customer something they already answered.
        "needless_question": case.expected_action == "file" and action == "clarify",
        "extraction_failed": action is None,
        "success": success,
        "question": (outcome.get("question") or "")[:160],
    }


def summarise(scores: pd.DataFrame, n_cases: int) -> dict:
    if scores.empty:
        return {"n_run": 0, "n_cases": n_cases}
    should_file = scores[scores["expected_action"] == "file"]
    should_ask = scores[scores["expected_action"] == "clarify"]
    asked = scores[scores["action"] == "clarify"]

    def rate(frame: pd.DataFrame, column: str) -> float | None:
        return round(float(frame[column].mean()), 4) if len(frame) else None

    return {
        "n_run": len(scores),
        "n_cases": n_cases,
        "success_rate": rate(scores, "success"),
        "clarification_rate": round(float((scores["action"] == "clarify").mean()), 4),
        "expected_clarification_rate": round(float((scores["expected_action"] == "clarify").mean()), 4),
        "file_success_rate": rate(should_file, "success"),
        "clarify_success_rate": rate(should_ask, "success"),
        "clarify_recall": rate(should_ask, "action_correct"),
        "clarify_precision": round(float((asked["expected_action"] == "clarify").mean()), 4) if len(asked) else None,
        "invented_orders": int(scores["invented_order"].sum()),
        "needless_questions": int(scores["needless_question"].sum()),
        "extraction_failures": int(scores["extraction_failed"].sum()),
        "run_dates": sorted(scores["ran_on"].unique().tolist()) if "ran_on" in scores else [],
    }


def score_all(eval_path: Path = EVAL_SET_JSON, runs_path: Path = RUNS_JSONL) -> tuple[pd.DataFrame, dict]:
    cases = {c.seq: c for c in load_eval_set(eval_path)}
    runs = load_runs(runs_path)
    rows = []
    for seq, record in sorted(runs.items()):
        row = score_case(cases[seq], record["outcome"])
        row["ran_on"] = record.get("ran_on")
        row["model"] = record.get("model")
        rows.append(row)
    scores = pd.DataFrame(rows)
    return scores, summarise(scores, len(cases))


def render_doc(scores: pd.DataFrame, summary: dict) -> str:
    n_run, n_cases = summary["n_run"], summary["n_cases"]
    lines = [
        "## Order Entry Agent evaluation (D5)",
        "",
        "*Generated by `python -m src.ml.order_eval --report` -- regenerate rather than editing numbers by hand.*",
        "",
        f"Generated: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "",
    ]
    if n_run < n_cases:
        lines += [
            (
                f"> **Partial: {n_run} of {n_cases} cases have run.** Gemini's free tier allows 20 calls "
                "a day, so the set runs over several days (`--run --budget 20` resumes where it stopped). "
                "Every rate below is over the cases that have run, not over the full set."
            ),
            "",
        ]
    if not n_run:
        return "\n".join(lines + ["No cases have run yet."])

    model = scores["model"].dropna().unique().tolist()
    lines += [
        (
            f"Agent: `order_entry/v1`, `dry_run` (extract + validate, no `POST`), on {', '.join(model)}. "
            f"Run on {', '.join(summary['run_dates'])}."
        ),
        "",
        "| | |",
        "|---|---|",
        f"| **Success rate** | **{summary['success_rate']:.1%}** ({int(scores['success'].sum())} of {n_run}) |",
        f"| **Clarification rate** | **{summary['clarification_rate']:.1%}** (the set's correct rate is {summary['expected_clarification_rate']:.1%}) |",
        f"| Should file -> filed with every field right | {summary['file_success_rate']:.1%} |" if summary["file_success_rate"] is not None else "| Should file | none run yet |",
        f"| Should ask -> asked about the right field | {summary['clarify_success_rate']:.1%} |" if summary["clarify_success_rate"] is not None else "| Should ask | none run yet |",
        f"| Clarify recall / precision | {summary['clarify_recall'] if summary['clarify_recall'] is not None else 'n/a'} / {summary['clarify_precision'] if summary['clarify_precision'] is not None else 'n/a'} |",
        f"| **Orders filed on invented values** | **{summary['invented_orders']}** |",
        f"| Needless questions | {summary['needless_questions']} |",
        f"| Extraction failures | {summary['extraction_failures']} |",
        "",
        "### By template",
        "",
        "| template | expect | run | success | what went wrong |",
        "|---|---|---|---|---|",
    ]
    for name, (_, action, missing) in TEMPLATES.items():
        group = scores[scores["template"] == name]
        if group.empty:
            lines.append(f"| `{name}` | {action}{f' `{missing}`' if missing else ''} | 0 | -- | not run yet |")
            continue
        failures = group[~group["success"]]
        reasons = []
        for _, f in failures.iterrows():
            if f["extraction_failed"]:
                reasons.append("extraction failed")
            elif f["invented_order"]:
                reasons.append("filed anyway")
            elif f["needless_question"] or f["expected_action"] == "clarify":
                reasons.append(f"asked about `{f['missing_field']}`")
            else:
                reasons.append(f"wrong `{f['mismatched_fields']}`")
        lines.append(
            f"| `{name}` | {action}{f' `{missing}`' if missing else ''} | {len(group)} | "
            f"{int(group['success'].sum())}/{len(group)} | {'; '.join(sorted(set(reasons))) or '--'} |"
        )
    lines += [
        "",
        (
            "Per-case verdicts: `benchmarks/raw/w5_order_eval_scores.csv`; raw agent outcomes: "
            "`w5_order_eval_runs.jsonl`; the authored set: `w5_order_eval_set.json`."
        ),
    ]
    return "\n".join(lines)


def report(eval_path: Path = EVAL_SET_JSON, runs_path: Path = RUNS_JSONL, out_md: Path = DOC_PATH) -> dict:
    scores, summary = score_all(eval_path, runs_path)
    if not scores.empty:
        scores.to_csv(SCORES_CSV, index=False)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    docs.write_section(out_md, "order-eval", render_doc(scores, summary))
    log.info("%d of %d scored -> %s, section in %s", summary["n_run"], summary["n_cases"], SUMMARY_JSON.name, out_md)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Order Entry Agent evaluation (W5 D5)")
    parser.add_argument("--build", action="store_true", help="(re)write the authored eval set")
    parser.add_argument("--run", action="store_true", help="run the next --budget unrun cases")
    parser.add_argument("--budget", type=int, default=DAILY_BUDGET)
    parser.add_argument("--report", action="store_true", help="score what has run, write the doc section")
    args = parser.parse_args()
    if not (args.build or args.run or args.report):
        parser.error("choose at least one of --build, --run, --report")

    if args.build:
        write_eval_set()
    if args.run:
        try:
            run(args.budget)
        except RuntimeError as exc:
            log.error("%s", exc)
            return 1
    if args.report:
        report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
