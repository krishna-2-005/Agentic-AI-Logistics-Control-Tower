"""Layer 1 results freeze (execution plan W6 D1-D2).

    python -m src.ml.results_freeze --freeze     # lock every Layer 1 number
    python -m src.ml.results_freeze --verify     # has anything moved since?
    python -m src.ml.results_freeze --summary    # regenerate docs/RESULTS_SUMMARY.md

Collects every number Layer 1 reports into one file, records **where each came from and
what that file's contents hashed to**, and can tell you afterwards whether any of it has
changed.

What "freeze" means, and what it does not
-----------------------------------------
It does not make anything immutable -- the artefacts stay exactly where they were, and
re-running a stage overwrites them as it always did. What the freeze adds is
**detection**: `--verify` recomputes every value and every source hash, and reports what
moved. That is the property the paper actually needs. A number in a report is only
trustworthy if someone can tell whether the file behind it still says the same thing,
and six weeks of regenerating tables is exactly how a figure quietly stops matching its
source.

Every entry names its source file. An entry whose source is missing is reported as
missing rather than skipped: a Layer 1 number that cannot be traced is a finding, not an
absence.

Why this is Lahari's and not each author's
------------------------------------------
The same reason D-028 keeps builder and judge apart. The person who produced a number is
the worst-placed to notice it no longer matches its file, because they remember what it
said.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("ml.results_freeze")

RAW = config.BENCHMARKS_RAW_DIR
#: v1 froze Week 1-6 at the Week 6 sync. Week 7 reopened the results for the model
#: correction sprint (D-048) and closed it with a different reported model (D-050), so the
#: current freeze is v2 and v1 stays exactly as it was -- the same rule D-016 applies to
#: data versions. `--path` still points anywhere, and `--verify` compares against whichever
#: file it is given, so "what moved since Week 6" remains answerable.
FREEZE_JSON_V1 = config.BENCHMARKS_DIR / "results_freeze_v1.json"
FREEZE_JSON = config.BENCHMARKS_DIR / "results_freeze_v2.json"
SUMMARY_MD = config.DOCS_DIR / "RESULTS_SUMMARY.md"


@dataclass
class Frozen:
    id: str
    week: int
    label: str
    value: Any
    unit: str
    source: str


def _json(name: str) -> dict:
    return json.loads((RAW / name).read_text(encoding="utf-8"))


def _csv(name: str) -> pd.DataFrame:
    return pd.read_csv(RAW / name)


def _test_mae(frame: pd.DataFrame, model: str) -> float:
    row = frame[(frame["model"] == model) & (frame["split"] == "test")].iloc[0]
    return round(float(row["mae_min"]), 2)


#: Every Layer 1 number, with the file it comes from. Adding a reported number to the
#: paper means adding a line here; a number that is not here is not frozen, and
#: `--verify` will never notice it drifting.
ENTRIES: list[tuple[str, int, str, str, str, Callable[[], Any]]] = [
    # id, week, label, unit, source, extractor
    ("legs_total", 1, "Legs in the cleaned feature table", "legs", "w2_audit_report.json",
     lambda: _json("w2_audit_report.json")["n"]),
    ("corridors_total", 1, "Distinct corridors", "corridors", "w2_audit_report.json",
     lambda: _json("w2_audit_report.json")["corridors_total"]),
    ("median_gap_ratio", 1, "Median leg runs this many times its OSRM plan", "x", "w2_audit_report.json",
     lambda: _json("w2_audit_report.json")["median_gap_ratio"]),

    ("corridors_tested", 2, "Corridors above the 10-leg floor (D-018)", "corridors", "w2_audit_report.json",
     lambda: _json("w2_audit_report.json")["corridors_supported"]),
    ("bottlenecks", 2, "Significantly slower corridors (FDR 0.05)", "corridors", "w2_audit_report.json",
     lambda: _json("w2_audit_report.json")["bottlenecks"]),
    ("faster_corridors", 2, "Significantly faster corridors", "corridors", "w2_audit_report.json",
     lambda: _json("w2_audit_report.json")["faster_than_network"]),
    ("legs_covered", 2, "Legs covered by tested corridors", "legs", "w2_audit_report.json",
     lambda: _json("w2_audit_report.json")["legs_covered"]),
    ("robustness_bottlenecks", 2, "Bottlenecks at the old 30-leg floor", "corridors", "w2_audit_report.json",
     lambda: _json("w2_audit_report.json")["robustness_bottlenecks"]),

    ("split_train", 3, "Training legs (chronological, D-022)", "legs", "w3_baseline_report.json",
     lambda: _json("w3_baseline_report.json")["n_train"]),
    ("split_test", 3, "Held-out legs", "legs", "w3_baseline_report.json",
     lambda: _json("w3_baseline_report.json")["n_test"]),
    ("pct_delayed", 3, "Legs delayed at the decided 2.00x threshold (D-003)", "%", "w3_baseline_report.json",
     lambda: _json("w3_baseline_report.json")["pct_delayed"]),
    ("mae_osrm", 3, "OSRM test MAE", "min", "w3_baseline_metrics.csv",
     lambda: _test_mae(_csv("w3_baseline_metrics.csv"), "OSRM")),
    ("mae_corridor_mean", 3, "Corridor-mean baseline test MAE", "min", "w3_baseline_metrics.csv",
     lambda: _test_mae(_csv("w3_baseline_metrics.csv"), "corridor_mean")),

    ("champion_model", 4, "Champion model", "", "w4_model_report.json",
     lambda: _json("w4_model_report.json")["winner"]),
    ("mae_champion", 4, "Champion test MAE", "min", "w4_model_metrics.csv",
     lambda: _test_mae(_csv("w4_model_metrics.csv"), "random_forest")),
    ("corridors_improved", 4, "Test corridors the champion beats OSRM on", "corridors", "w4_model_report.json",
     lambda: _json("w4_model_report.json")["corridors_improved"]),
    ("doc_agent_f1_v1", 4, "Document agent field F1, prompt v1", "", "w4_doc_eval_summary.json",
     lambda: _json("w4_doc_eval_summary.json")["v1"]["f1"]),
    ("doc_agent_f1_v2", 4, "Document agent field F1, prompt v2", "", "w4_doc_eval_summary.json",
     lambda: _json("w4_doc_eval_summary.json")["v2"]["f1"]),

    ("stream_identical", 5, "Legs scoring identically in batch and stream", "of 500",
     "w5_stream_validation_report.json",
     lambda: _json("w5_stream_validation_report.json")["identical_predictions"]),
    ("stream_events", 5, "Events replayed end to end", "events", "w5_stream_throughput_full.json",
     lambda: _json("w5_stream_throughput_full.json")["steps"][0]["events_processed"]),
    ("stream_produced_eps", 5, "Producer rate sustained", "events/sec", "w5_stream_throughput_full.json",
     lambda: _json("w5_stream_throughput_full.json")["steps"][0]["produced_rate_eps"]),
    ("stream_scoring_eps", 5, "Saturated scoring rate", "events/sec", "w5_stream_throughput_full.json",
     lambda: _json("w5_stream_throughput_full.json")["steps"][0]["scoring_rate_eps"]),
    ("stream_latency_p50_s", 5, "Event-to-alert latency, median", "s", "w5_stream_throughput_full.json",
     lambda: round(_json("w5_stream_throughput_full.json")["steps"][0]["latency_p50_ms"] / 1000, 1)),
    ("order_eval_run", 5, "Order Entry eval cases run", "of 50", "w5_order_eval_summary.json",
     lambda: _json("w5_order_eval_summary.json")["n_run"]),
    ("order_eval_success", 5, "Order Entry eval success rate", "", "w5_order_eval_summary.json",
     lambda: _json("w5_order_eval_summary.json")["success_rate"]),
    ("order_eval_invented", 5, "Orders filed on invented values", "orders", "w5_order_eval_summary.json",
     lambda: _json("w5_order_eval_summary.json")["invented_orders"]),

    ("lifecycle_cases", 6, "Emails through the full lifecycle", "cases", "w6_orchestrator_runs.json",
     lambda: _json("w6_orchestrator_runs.json")["cases"]),
    ("lifecycle_booked", 6, "Lifecycle cases booked into the TMS", "cases", "w6_orchestrator_runs.json",
     lambda: _json("w6_orchestrator_runs.json")["booked"]),
    ("lifecycle_ticketed", 6, "Lifecycle cases reaching an exception ticket", "cases",
     "w6_orchestrator_runs.json", lambda: _json("w6_orchestrator_runs.json")["ticketed"]),
    ("invoice_cases", 6, "Invoices audited on the development corpus", "invoices",
     "w6_invoice_audit_runs.json", lambda: _json("w6_invoice_audit_runs.json")["cases"]),
    ("invoice_correct", 6, "Invoice verdicts matching the seeded truth", "invoices",
     "w6_invoice_audit_runs.json", lambda: _json("w6_invoice_audit_runs.json")["correct_verdicts"]),

    # Week 7 reopened the freeze for the model correction sprint (D-048) and closed it with
    # a different reported model (D-050). These are the numbers that replaced Week 4's.
    ("median_bar_mae", 7, "The fair baseline: per-corridor as-of median", "min",
     "w7_model_v2_stepsize_report.json",
     lambda: _json("w7_model_v2_stepsize_report.json")["adoption"]["median_bar_min"]),
    ("model_v2_mae", 7, "Reported model: v2 GBT on the median residual", "min",
     "w7_model_v2_stepsize_report.json",
     lambda: _json("w7_model_v2_stepsize_report.json")["adoption"]["overall_mae_min"]),
    ("doc_extraction_accuracy", 7, "Document extraction, per-field accuracy", "share",
     "w7_doc_extraction_eval.json", lambda: _json("w7_doc_extraction_eval.json")["overall"]["accuracy"]),
    ("doc_extraction_rows", 7, "Document rows scored (of 40 planned)", "rows",
     "w7_doc_extraction_eval.json", lambda: _json("w7_doc_extraction_eval.json")["documents_evaluated"]),
    ("assistant_route_accuracy", 7, "Analytics assistant, correct route on the fixed set", "share",
     "w7_assistant_run_no_llm.json", lambda: _json("w7_assistant_run_no_llm.json")["route_accuracy"]),
    ("scale_rows", 7, "Rows the Week 2 aggregation was run on at scale", "rows",
     "w7_scale_benchmark.json",
     lambda: max(r["rows"] for r in _json("w7_scale_benchmark.json")["runs"])),
]


def file_hash(name: str) -> str | None:
    """sha256 of a source file, or None when it is missing."""
    path = RAW / name
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def collect() -> tuple[list[Frozen], list[dict]]:
    """Every entry's current value. Returns (values, problems)."""
    values: list[Frozen] = []
    problems: list[dict] = []
    for entry_id, week, label, unit, source, extract in ENTRIES:
        if not (RAW / source).exists():
            problems.append({"id": entry_id, "problem": "source missing", "source": source})
            continue
        try:
            values.append(Frozen(entry_id, week, label, extract(), unit, source))
        except (KeyError, IndexError, ValueError) as exc:
            problems.append({"id": entry_id, "problem": f"{type(exc).__name__}: {exc}", "source": source})
    return values, problems


def freeze(out_path: Path = FREEZE_JSON) -> dict:
    values, problems = collect()
    sources = sorted({f.source for f in values} | {p["source"] for p in problems})
    snapshot = {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "layer": 1,
        "n_values": len(values),
        "values": [asdict(f) for f in values],
        "source_hashes": {name: file_hash(name) for name in sources},
        "problems": problems,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    log.info("froze %d value(s) from %d file(s) -> %s", len(values), len(sources), out_path)
    if problems:
        log.warning("%d entry(ies) could not be read: %s", len(problems), [p["id"] for p in problems])
    return snapshot


def verify(path: Path = FREEZE_JSON) -> dict:
    """Recompute everything and report what moved since the freeze."""
    if not path.exists():
        raise FileNotFoundError(f"no freeze at {path} -- run --freeze first")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    frozen = {v["id"]: v for v in snapshot["values"]}
    current, problems = collect()

    changed, missing, added = [], [], []
    for value in current:
        before = frozen.pop(value.id, None)
        if before is None:
            added.append(value.id)
        elif before["value"] != value.value:
            changed.append({"id": value.id, "was": before["value"], "now": value.value,
                            "source": value.source})
    missing = list(frozen)

    hashes_now = {name: file_hash(name) for name in snapshot["source_hashes"]}
    touched = [name for name, digest in snapshot["source_hashes"].items() if hashes_now.get(name) != digest]

    report = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "frozen_at": snapshot["frozen_at"],
        "values_checked": len(current),
        "changed": changed,
        "missing": missing,
        "added": added,
        # A file can be rewritten without any frozen value moving -- a regenerated table
        # with the same numbers. That is worth reporting and is not a failure, so the
        # two are separate lists rather than one verdict.
        "files_rewritten": touched,
        "problems": problems,
        "clean": not (changed or missing or problems),
    }
    if report["clean"]:
        log.info("all %d value(s) unchanged (%d file(s) rewritten)", len(current), len(touched))
    else:
        log.warning("%d changed, %d missing, %d unreadable", len(changed), len(missing), len(problems))
    return report


def render_summary(snapshot: dict) -> str:
    """The results-summary document: every Layer 1 number, by week, with its source."""
    lines = [
        "# Layer 1 results summary",
        "",
        (
            "*Generated by `python -m src.ml.results_freeze --summary` -- regenerate rather "
            "than editing numbers by hand.*"
        ),
        "",
        f"Frozen: {snapshot['frozen_at']}  ·  {snapshot['n_values']} values",
        "",
        (
            "Every number Layer 1 reports, and the file it comes from. `--verify` recomputes all "
            "of them and reports what moved; a figure in the paper is only trustworthy if someone "
            "can check whether its source still says the same thing."
        ),
        "",
    ]
    by_week: dict[int, list[dict]] = {}
    for value in snapshot["values"]:
        by_week.setdefault(value["week"], []).append(value)

    titles = {
        1: "Week 1 — the data", 2: "Week 2 — corridor audit", 3: "Week 3 — baselines",
        4: "Week 4 — batch ML and document extraction", 5: "Week 5 — streaming and order entry",
        6: "Week 6 — the lifecycle",
    }
    for week in sorted(by_week):
        lines += [f"## {titles.get(week, f'Week {week}')}", "", "| value | | source |", "|---|---|---|"]
        for value in by_week[week]:
            unit = f" {value['unit']}" if value["unit"] else ""
            lines.append(
                f"| {value['label']} | **{value['value']}**{unit} | "
                f"[`{value['source']}`](../benchmarks/raw/{value['source']}) |"
            )
        lines.append("")

    if snapshot.get("problems"):
        lines += ["## Entries that could not be read", "",
                  "A Layer 1 number that cannot be traced to its file is a finding, not an absence.",
                  "", "| id | problem | source |", "|---|---|---|"]
        for problem in snapshot["problems"]:
            lines.append(f"| `{problem['id']}` | {problem['problem']} | `{problem['source']}` |")
        lines.append("")

    lines += [
        "## What the freeze does not do",
        "",
        (
            "It does not make anything immutable. Re-running a stage overwrites its artefact "
            "exactly as before. What the freeze adds is **detection** -- `--verify` recomputes "
            "every value and every source hash and says what changed, which is the property a "
            "paper actually needs."
        ),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze and verify Layer 1's reported numbers")
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--summary", action="store_true", help="regenerate the results-summary doc")
    parser.add_argument("--path", type=Path, default=FREEZE_JSON)
    args = parser.parse_args()

    if not (args.freeze or args.verify or args.summary):
        parser.error("choose --freeze, --verify or --summary")

    snapshot = None
    if args.freeze:
        snapshot = freeze(args.path)
    if args.verify:
        report = verify(args.path)
        print(json.dumps({k: v for k, v in report.items() if k != "problems"}, indent=2))
        if not report["clean"]:
            return 1
    if args.summary:
        snapshot = snapshot or json.loads(args.path.read_text(encoding="utf-8"))
        SUMMARY_MD.write_text(render_summary(snapshot), encoding="utf-8")
        log.info("results summary -> %s", SUMMARY_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
