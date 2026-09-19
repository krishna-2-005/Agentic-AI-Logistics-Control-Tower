"""Experiments appendix (execution plan v3.1 W7 D5) -- every reported number, to a command.

    python -m src.ml.experiments_appendix          # writes benchmarks/experiments_appendix.md

The paper's claim is that nothing in it is unreproducible. This turns that into a table a
reader can act on: for each frozen number, the value, the cache file it is read from, and
the command that regenerates that cache.

Generated rather than written by hand, and generated from `results_freeze.ENTRIES` rather
than from a second list, because a hand-kept appendix drifts from the numbers the moment
one of them is rerun -- the same failure P-57 recorded for the MCP tool list, and the
reason D-046's freeze exists at all.

The producing command per cache file is the one piece that cannot be derived: it lives in
`PRODUCERS` below, and a cache file with no entry there is reported as a gap rather than
quietly omitted.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.common import config
from src.common.logging_setup import get_logger
from src.ml.results_freeze import ENTRIES, RAW, collect

log = get_logger("ml.experiments_appendix")

OUT_MD = config.BENCHMARKS_DIR / "experiments_appendix.md"

#: cache file -> (the command that writes it, the owner who runs it)
PRODUCERS: dict[str, tuple[str, str]] = {
    "w2_audit_report.json": ("python -m src.ml.audit", "Lahari"),
    "w3_baseline_metrics.csv": ("python -m src.ml.baselines", "Lahari"),
    "w3_baseline_report.json": ("python -m src.ml.baselines", "Lahari"),
    "w4_model_metrics.csv": ("python -m src.ml.models", "Lahari"),
    "w4_model_report.json": ("python -m src.ml.models", "Lahari"),
    "w4_doc_eval_summary.json": ("python -m src.ml.doc_eval", "Lahari"),
    "w5_order_eval_summary.json": ("python -m src.ml.order_eval --run --report", "Lahari"),
    "w5_stream_throughput_full.json": (
        "python -m src.streaming.producer --sink file, then python -m src.streaming.job --once",
        "Mounika",
    ),
    "w5_stream_validation_report.json": ("python -m src.ml.stream_validation", "Lahari"),
    "w6_invoice_audit_runs.json": ("python -m src.agents.invoice_auditor --count 20", "Krishna"),
    "w6_orchestrator_runs.json": ("python -m src.agents.orchestrator --cases 10 --no-llm", "Krishna"),
    # Week 7 caches, which the freeze does not carry because they are not Layer 1 results.
    "w7_ml_diagnostics.json": ("python -m src.ml.ml_diagnostics", "Lahari"),
    "w7_model_metrics_v2.csv": ("python -m src.ml.models_v2", "Lahari"),
    "w7_model_metrics_v2_stepsize.csv": ("python -m src.ml.models_v2_stepsize", "Lahari"),
    "w7_features_v2_report.json": ("python -m src.pipeline.features_v2", "Mounika"),
    "w7_doc_extraction_eval.json": ("python -m src.ml.eval_extraction --consignments 10", "Krishna"),
    "w7_mcp_stdio_transcript.json": ("python -m src.agents.mcp_stdio_client", "Krishna"),
    "w7_assistant_run_no_llm.json": ("python -m src.agents.assistant_eval --no-llm", "Krishna"),
    "w6_exception_eval.json": ("python -m src.ml.exception_eval", "Lahari"),
    "w6_invoice_eval.json": ("python -m src.ml.invoice_eval", "Lahari"),
    "w7_scale_benchmark.json": ("python -m src.pipeline.scale_benchmark --months 17", "Mounika"),
    "w8_replay_leakage.json": ("python -m src.ml.replay_leakage --legs 2000", "Lahari"),
    "w8_stream_validation_v2.json": ("python -m src.ml.stream_validation --adopted", "Lahari"),
    "w7_groundedness_summary.json": ("python -m src.ml.groundedness --precheck --report", "Lahari"),
    "w7_kafka_source_equivalence.json": (
        "scripts/kafka_native.ps1, then python -m src.streaming.compare_sources", "Mounika"),
    "w8_fresh_clone_rebuild.json": ("bash scripts/rebuild_all.sh on a fresh clone", "Mounika"),
}

#: Numbers that are reported but are not in the freeze, with where they come from. Kept
#: explicit so "every reported number" is a claim about a list, not a hope.
EXTRA_ROWS: list[tuple[str, str, str]] = [
    ("Week 7 agent evaluation table (five agents)", "benchmarks/agent_evaluation.md",
     "each row cites its own cache file in the Evidence table"),
    ("Streaming throughput and latency", "benchmarks/streaming_throughput.md",
     "python -m src.streaming.producer / job, full-replay run"),
    ("Scale appendix runtimes", "benchmarks/scale_appendix.md",
     "python -m src.pipeline.scale_benchmark --months 17"),
]


def rows() -> tuple[list[dict], list[dict]]:
    """(one row per frozen number, gaps) -- a gap is a cache nothing claims to produce."""
    values, problems = collect()
    by_id = {v.id: v for v in values}
    table, gaps = [], []
    for entry_id, week, label, unit, source, _ in ENTRIES:
        producer, owner = PRODUCERS.get(source, ("", ""))
        if not producer:
            gaps.append({"id": entry_id, "source": source, "problem": "no producing command recorded"})
        frozen = by_id.get(entry_id)
        table.append({
            "week": week, "id": entry_id, "label": label,
            "value": "—" if frozen is None else f"{frozen.value:,}" if isinstance(frozen.value, int) else frozen.value,
            "unit": unit, "source": source, "command": producer, "owner": owner,
            "present": (RAW / source).exists(),
        })
    for gap in problems:
        gaps.append({"id": gap["id"], "source": gap.get("source", ""), "problem": gap["problem"]})
    return table, gaps


def render(table: list[dict], gaps: list[dict]) -> str:
    lines = [
        "# Experiments appendix — every reported number, to a command",
        "",
        "**Owner: Lahari.** Generated by `python -m src.ml.experiments_appendix`; do not edit by hand.",
        "",
        (f"Generated {datetime.now(timezone.utc).date().isoformat()} from "
         "`src.ml.results_freeze.ENTRIES` (the frozen Layer 1 results, D-046) plus the "
         "producing command for each cache file."),
        "",
        ("Every value below is read from a file in `benchmarks/raw/`, and every file has a "
         "command that writes it. A number in the paper that cannot be traced to a row here "
         "is a bug in the paper."),
        "",
        "| Week | Number | Value | Unit | Read from | Regenerate with | Owner |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in table:
        mark = "" if row["present"] else " ⚠️ missing"
        command = f"`{row['command']}`" if row["command"] else "_not recorded_"
        lines.append(
            f"| W{row['week']} | {row['label']} | **{row['value']}** | {row['unit']} | "
            f"`benchmarks/raw/{row['source']}`{mark} | {command} | {row['owner']} |"
        )
    lines += ["", "## Reported elsewhere, not in the freeze", "",
              "| What | Where | Regenerate with |", "|---|---|---|"]
    for what, where, how in EXTRA_ROWS:
        lines.append(f"| {what} | `{where}` | {how} |")
    lines += ["", "## Gaps", ""]
    if gaps:
        lines += ["| Entry | Cache | Problem |", "|---|---|---|"]
        lines += [f"| {g['id']} | `{g['source']}` | {g['problem']} |" for g in gaps]
    else:
        lines.append("None: every frozen number has a cache file and a command that writes it.")
    lines += ["", "## What this table does not prove", "",
              ("That a command reproduces a number says the pipeline is deterministic given "
               "its inputs. It does not say the number is right — that is what the decisions "
               "log and the problem log argue about, and several entries here are numbers an "
               "earlier version of the same command got wrong (P-42, P-46, P-52)."), ""]
    return "\n".join(lines)


def run(out: Path = OUT_MD) -> dict:
    table, gaps = rows()
    out.write_text(render(table, gaps), encoding="utf-8")
    log.info("wrote %s: %d number(s), %d gap(s)", out, len(table), len(gaps))
    return {"numbers": len(table), "gaps": gaps}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
