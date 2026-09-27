"""
Orchestrator evaluation at scale (WP-02): 100 lifecycles, with path coverage.

    python -m src.ml.lifecycle_eval_scale --cases 100      # zero API calls
    python -m src.ml.lifecycle_eval_scale --route truth    # the Week 6 mode

What Week 6 actually measured
-----------------------------
The headline is "10 emails, 3 distinct paths, no human in the middle". Those ten
ran with `use_llm=False`, and until now that mode did this:

    # Demonstration mode: the case's own ground truth stands in for extraction.
    order = dict(state["expected_fields"])

Intake was handed the answer. The routing decision that makes this a graph
rather than a script -- `route_after_intake`, file or clarify -- was therefore
taken from the label, not from reading the email, and no case could route
wrongly because nothing was read. It is a demonstration that the wiring holds,
which is a fair thing to want, and it is not evidence about the agent.

That mode is still reachable as `--route truth` so the Week 6 result stays
reproducible. The default here is `--route rules`: the deterministic extractor
reads each email and the graph routes on what it found, which can be and
sometimes is wrong, at the same zero cost.

Path coverage
-------------
The graph admits exactly three terminal paths:

    intake -> clarify                        the email is not bookable
    intake -> book -> monitor -> done        booked, predicted on time
    intake -> book -> monitor -> triage -> done   booked, predicted late, ticketed

Coverage is the share of those three a run exercises. Ten cases hitting all three
is genuinely good news about the corpus; it says nothing about how often each is
taken, which is what 100 cases and a distribution are for.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.agents.orchestrator import run_case
from src.common import config
from src.common.logging_setup import get_logger
from src.ml.order_eval_scale import build_cases
from src.ml.stats import wilson

log = get_logger("ml.lifecycle_eval_scale")

RESULT_JSON = config.BENCHMARKS_RAW_DIR / "w9_lifecycle_eval.json"

#: Every terminal path the graph admits. Written out rather than discovered, so
#: an unreachable path shows up as a gap instead of simply never appearing.
ALL_PATHS = (
    "intake -> clarify",
    "intake -> book -> monitor -> done",
    "intake -> book -> monitor -> triage -> done",
)


class _Case:
    """`run_case` wants something with these five attributes."""

    def __init__(self, row: dict) -> None:
        self.seq = row["seq"]
        self.subject = row["subject"]
        self.body = row["body"]
        self.expected_action = row["expected_action"]
        self.expected_fields = row["expected_fields"]


def run(cases: int = 100, route: str = "rules", dry_run: bool = True) -> dict:
    """`cases` emails through the whole graph, no model call anywhere."""
    corpus = build_cases(per_template=max(1, cases // 20))[:cases]
    results = []
    for row in corpus:
        state = run_case(
            _Case(
                {
                    "seq": row.seq,
                    "subject": row.subject,
                    "body": row.body,
                    "expected_action": row.expected_action,
                    "expected_fields": row.expected_fields,
                }
            ),
            use_llm=False,
            dry_run=dry_run,
            no_llm_route=route,
        )
        results.append(
            {
                "seq": row.seq,
                "template": row.template,
                "adversarial": row.adversarial,
                "expected_action": row.expected_action,
                "path": " -> ".join(state.get("steps", [])),
                "action": state.get("action"),
                "missing_field": state.get("missing_field"),
                "booked": bool(state.get("shipment_ref")),
                "alerted": bool(state.get("alert")),
                "ticketed": bool(state.get("ticket_ref")),
                "error": state.get("error"),
            }
        )

    paths = Counter(r["path"] for r in results)
    exercised = {p for p in paths if p in ALL_PATHS}
    unexpected = {p: n for p, n in paths.items() if p not in ALL_PATHS}

    routed_right = sum(1 for r in results if r["action"] == r["expected_action"])
    adversarial = [r for r in results if r["adversarial"]]

    return {
        "n_cases": len(results),
        "route": route,
        "dry_run": dry_run,
        "used_llm": False,
        "path_coverage": {
            "exercised": len(exercised),
            "possible": len(ALL_PATHS),
            "rate": round(len(exercised) / len(ALL_PATHS), 4),
            "distribution": dict(paths),
            "never_taken": [p for p in ALL_PATHS if p not in exercised],
            "unexpected_paths": unexpected,
        },
        "routing_correct": wilson(routed_right, len(results)).as_dict(),
        "routing_correct_adversarial": wilson(
            sum(1 for r in adversarial if r["action"] == r["expected_action"]),
            len(adversarial),
        ).as_dict()
        if adversarial
        else None,
        "completed_without_error": wilson(
            sum(1 for r in results if not r["error"]), len(results)
        ).as_dict(),
        # Routed-to vs actually-posted are different things, and conflating them
        # made a dry run report "booked: 0" beside 37 cases that took the book
        # path. In a dry run nothing is POSTed by design, so the second number is
        # zero and says nothing about the graph.
        "reached_clarify": sum(1 for r in results if "clarify" in r["path"]),
        "routed_to_book": sum(1 for r in results if "book" in r["path"]),
        "routed_to_triage": sum(1 for r in results if "triage" in r["path"]),
        "posted_to_tms": sum(1 for r in results if r["booked"]),
        "tickets_filed_in_tms": sum(1 for r in results if r["ticketed"]),
        "errors": sum(1 for r in results if r["error"]),
        "note": (
            "route=truth hands intake the case's expected fields and cannot route "
            "wrongly; it measures the graph. route=rules reads the email and can."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": results,
    }


def render_markdown(s: dict) -> str:
    cov = s["path_coverage"]
    r = s["routing_correct"]
    lines = [
        f"### Orchestrator — {s['n_cases']} lifecycles, route `{s['route']}`",
        "",
        f"- Graph paths exercised **{cov['exercised']} of {cov['possible']}**",
        f"- Routed as the email deserved **{r['rate']:.1%}** "
        f"[{r['ci_low']:.1%}–{r['ci_high']:.1%}] ({r['successes']}/{r['total']})",
        f"- Completed without error **{s['completed_without_error']['rate']:.1%}**",
        f"- Stopped at a question: {s['reached_clarify']} · routed to booking: "
        f"{s['routed_to_book']} · routed to triage: {s['routed_to_triage']}",
        (
            f"- Written to the TMS: {s['posted_to_tms']} orders, "
            f"{s['tickets_filed_in_tms']} tickets"
            + (" — nothing is posted in a dry run, which this was" if s["dry_run"] else "")
        ),
        "",
        "| path | times taken |",
        "|---|---|",
    ]
    for path, n in sorted(cov["distribution"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{path}` | {n} |")
    if cov["never_taken"]:
        lines += ["", f"Never taken: {', '.join('`' + p + '`' for p in cov['never_taken'])}"]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=int, default=100)
    ap.add_argument("--route", default="rules", choices=["rules", "truth"])
    ap.add_argument("--no-dry-run", action="store_true", help="really POST to the TMS")
    ap.add_argument("--out", type=Path, default=RESULT_JSON)
    args = ap.parse_args()

    config.ensure_dirs()
    summary = run(args.cases, args.route, dry_run=not args.no_dry_run)
    args.out.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    log.info("%d lifecycles -> %s", summary["n_cases"], args.out)
    print()
    print(render_markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
