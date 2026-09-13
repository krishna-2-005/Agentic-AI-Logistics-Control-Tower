"""Exception Agent evaluation (execution plan W6 D3-D4).

    python -m src.ml.exception_eval
    python -m src.ml.exception_eval --limit 500

Scores Krishna's Tracking & Exception Agent against what the replay actually did:
**notification precision** (of the shipments it would notify about, how many really ran
late) and **time-to-notification**.

Where the truth comes from
--------------------------
The replay carries its own outcome. Every leg emits a `query` event, which the streaming
job scores and may flag, and a `fact` event, which records what the leg really did
(`is_delayed`, D-003's label recomputed from the gap -- P-42's fix, so the label in the
stream is the decided 2.00x one and not the threshold the project rejected). Joining
alerts to facts on `leg_id` gives a labelled set with no extra labelling work and no
model in the loop.

The question this answers, and the one it does not
--------------------------------------------------
It measures **the agent as an alerting system**: if it tells an operations desk to chase
a shipment, how often is that shipment really late? That is the number a desk feels.

It is not a measurement of the *model*: the agent inherits whatever the streaming job
flagged, so its ceiling is the stream's precision, and D-040 already showed the stream's
flag is the weakest real classifier in the project. What the agent *can* add on top is
**ordering** -- if its severity grades track real lateness, then notifying only on the
higher grades is a policy that buys precision. That is the comparison this module is
really for.

No LLM and no TMS: severity is arithmetic (D-041), so the whole evaluation is
reproducible and costs nothing.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.agents.exception_agent import (
    SEVERITY_ORDER,
    Investigation,
    investigate,
    load_audit,
    load_friction,
    severity_for,
)
from src.common import config, docs
from src.common.logging_setup import get_logger
from src.dashboard.alerts import load_alerts

log = get_logger("ml.exception_eval")

OUT_JSON = config.BENCHMARKS_RAW_DIR / "w6_exception_eval.json"
OUT_CSV = config.BENCHMARKS_RAW_DIR / "w6_exception_eval_cases.csv"
DOC_PATH = config.DOCS_DIR / "W6_lahari_agent_eval.md"


@dataclass
class Truth:
    legs: int
    delayed: int


def load_facts(trips_dir: Path | None = None) -> dict[str, int]:
    """`leg_id -> is_delayed`, read from the replay's own fact events."""
    trips_dir = trips_dir or config.STREAM_TRIPS_DIR
    facts: dict[str, int] = {}
    for path in sorted(trips_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("kind") == "fact":
                facts[event["leg_id"]] = int(event["is_delayed"])
    return facts


def grade_alerts(alerts: pd.DataFrame, limit: int | None = None) -> pd.DataFrame:
    """Run the agent's investigation and severity rule over every alert.

    Timed per alert: the agent's own contribution to time-to-notification is its
    decision, and the stream's `latency_ms` is what came before it.
    """
    audit, friction = load_audit(), load_friction()
    rows = []
    subset = alerts.head(limit) if limit else alerts
    for _, alert in subset.iterrows():
        started = time.perf_counter()
        found: Investigation = investigate(alert, audit, friction, None)
        threshold_gap = float(alert["threshold_gap_min"])
        ratio = float(alert["predicted_gap_min"]) / threshold_gap if threshold_gap > 0 else float("inf")
        severity = severity_for(ratio, found)
        decide_ms = (time.perf_counter() - started) * 1000
        rows.append({
            "alert_id": alert["alert_id"],
            "leg_id": alert["leg_id"],
            "corridor_id": alert["corridor_id"],
            "severity": severity,
            "excess_ratio": round(ratio, 3),
            "predicted_gap_min": float(alert["predicted_gap_min"]),
            "confirmed_slow": found.confirmed_slow,
            "cold_history": found.cold_history,
            "stream_latency_ms": float(alert["latency_ms"]) if "latency_ms" in alert else None,
            "decide_ms": round(decide_ms, 2),
        })
    return pd.DataFrame(rows)


def score(graded: pd.DataFrame, facts: dict[str, int]) -> dict:
    """Precision overall and by severity, plus what a severity policy would buy."""
    graded = graded.copy()
    graded["truly_delayed"] = graded["leg_id"].map(facts)
    scored = graded[graded["truly_delayed"].notna()].copy()
    scored["truly_delayed"] = scored["truly_delayed"].astype(int)

    delayed_total = sum(facts.values())
    precision = float(scored["truly_delayed"].mean()) if len(scored) else None

    by_severity = []
    for severity in SEVERITY_ORDER:
        band = scored[scored["severity"] == severity]
        if band.empty:
            continue
        by_severity.append({
            "severity": severity,
            "notified": len(band),
            "truly_delayed": int(band["truly_delayed"].sum()),
            "precision": round(float(band["truly_delayed"].mean()), 4),
            "median_predicted_gap_min": round(float(band["predicted_gap_min"].median()), 1),
        })

    # What a "notify only at this grade or above" policy would do. The agent currently
    # notifies on everything it is handed, so this is the comparison that says whether
    # its severity grades are worth anything as a filter.
    policies = []
    for index, severity in enumerate(SEVERITY_ORDER):
        band = scored[scored["severity"].isin(SEVERITY_ORDER[index:])]
        if band.empty:
            continue
        policies.append({
            "notify_at_or_above": severity,
            "notified": len(band),
            "share_of_alerts": round(len(band) / len(scored), 4),
            "precision": round(float(band["truly_delayed"].mean()), 4),
            "recall_of_all_delayed": round(float(band["truly_delayed"].sum()) / delayed_total, 4)
            if delayed_total else None,
        })

    latency = scored["stream_latency_ms"].dropna() / 1000
    decide = scored["decide_ms"]
    return {
        "alerts_scored": len(scored),
        "alerts_without_truth": int(len(graded) - len(scored)),
        "legs_in_replay": len(facts),
        "legs_truly_delayed": delayed_total,
        "notification_precision": round(precision, 4) if precision is not None else None,
        "recall_of_all_delayed": round(float(scored["truly_delayed"].sum()) / delayed_total, 4)
        if delayed_total else None,
        "by_severity": by_severity,
        "policies": policies,
        "time_to_notification_s": {
            "stream_p50": round(float(latency.median()), 2) if len(latency) else None,
            "stream_p95": round(float(latency.quantile(0.95)), 2) if len(latency) else None,
            "agent_decision_p50_ms": round(float(decide.median()), 2),
            "agent_decision_p95_ms": round(float(decide.quantile(0.95)), 2),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def render_doc(summary: dict) -> str:
    lines = [
        "## Exception Agent evaluation (D3-D4)",
        "",
        (
            "*Generated by `python -m src.ml.exception_eval` -- regenerate rather than editing "
            "numbers by hand.*"
        ),
        "",
        f"Generated: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "",
        (
            f"Scored against the replay's own fact events: {summary['legs_in_replay']:,} legs, "
            f"{summary['legs_truly_delayed']:,} of them genuinely delayed at D-003's 2.00x. "
            f"The agent graded {summary['alerts_scored']:,} alerts. No model and no TMS -- "
            "severity is arithmetic (D-041), so this is reproducible to the digit."
        ),
        "",
        "| | |",
        "|---|---|",
        f"| **Notification precision** | **{summary['notification_precision']:.1%}** |",
        f"| Recall of all delayed legs | {summary['recall_of_all_delayed']:.1%} |",
        f"| Event-to-alert, median | {summary['time_to_notification_s']['stream_p50']} s |",
        f"| Event-to-alert, p95 | {summary['time_to_notification_s']['stream_p95']} s |",
        f"| The agent's own decision | {summary['time_to_notification_s']['agent_decision_p50_ms']} ms (p50) |",
        "",
        "### Precision by severity",
        "",
        "| severity | notified | truly delayed | precision | median predicted gap |",
        "|---|---|---|---|---|",
    ]
    for band in summary["by_severity"]:
        lines.append(
            f"| {band['severity']} | {band['notified']:,} | {band['truly_delayed']:,} | "
            f"{band['precision']:.1%} | {band['median_predicted_gap_min']:,.0f} min |"
        )

    lines += [
        "",
        "### What a severity policy would buy",
        "",
        (
            "The agent notifies on every alert it is handed. If its grades track real lateness, "
            "notifying only at a grade or above trades volume for precision -- this is the table "
            "that says whether they do."
        ),
        "",
        "| notify at or above | alerts sent | share | precision | recall of all delayed |",
        "|---|---|---|---|---|",
    ]
    for policy in summary["policies"]:
        recall = f"{policy['recall_of_all_delayed']:.1%}" if policy["recall_of_all_delayed"] is not None else "n/a"
        lines.append(
            f"| {policy['notify_at_or_above']} | {policy['notified']:,} | "
            f"{policy['share_of_alerts']:.1%} | {policy['precision']:.1%} | {recall} |"
        )
    lines += [
        "",
        "Per-alert verdicts: `benchmarks/raw/w6_exception_eval_cases.csv`.",
    ]
    return "\n".join(lines)


def run(limit: int | None = None, out_md: Path = DOC_PATH) -> dict:
    feed = load_alerts()
    if feed.empty:
        raise RuntimeError("no alerts in the sink -- run the producer and the streaming job first")
    facts = load_facts()
    if not facts:
        raise RuntimeError("no fact events in the replay -- the truth for this evaluation")

    graded = grade_alerts(feed.alerts, limit)
    summary = score(graded, facts)

    graded["truly_delayed"] = graded["leg_id"].map(facts)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    graded.to_csv(OUT_CSV, index=False)
    OUT_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    docs.write_section(out_md, "exception-eval", render_doc(summary), header=DOC_HEADER)
    log.info(
        "%d alert(s) scored: precision %.1f%%, %d of %d delayed legs reached",
        summary["alerts_scored"], 100 * summary["notification_precision"],
        int(summary["recall_of_all_delayed"] * summary["legs_truly_delayed"]),
        summary["legs_truly_delayed"],
    )
    return summary


DOC_HEADER = """# W6 · Lahari — results freeze, agent evaluations

Week 6's judging half: the Layer 1 results freeze (D1-D2), the Exception Agent
evaluation (D3-D4) and the Invoice Auditor evaluation (D5). Sections between the
markers are generated; the prose outside them is mine.

```bash
python -m src.ml.results_freeze --freeze --summary
python -m src.ml.exception_eval
python -m src.ml.invoice_eval
```
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the Exception Agent against the replay")
    parser.add_argument("--limit", type=int, default=None, help="grade only the first N alerts")
    parser.add_argument("--out-md", type=Path, default=DOC_PATH)
    args = parser.parse_args()
    try:
        run(limit=args.limit, out_md=args.out_md)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
