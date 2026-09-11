"""Stream-equals-batch correctness test (execution plan W5 D1-D2).

    python -m src.ml.stream_validation --limit 500

**The invariant:** an identical leg must produce an identical prediction whether it is
scored in batch off `features_v1` or arrives as a JSON event on the stream. Week 5's
gate hangs on a replayed event raising a live alert; an alert that fires on a
different number than the batch pipeline would have produced is worse than no alert,
because nothing downstream would ever notice.

What this module can and cannot test yet
----------------------------------------
A prediction needs 27 features. The stream event carries **6** of them
(`planned_min`, `planned_km`, `created_hour`, `created_dayofweek`,
`created_is_weekend`, and `route_type` which becomes `is_ftl`); the other **21** are
the `corr_*`/`src_*`/`dst_*` history that D-031 deliberately keeps *out* of the event
and expects a broadcast join to supply. So the round-trip splits in two:

* **The event half — tested here, now.** Serialise a leg to a query event, push it
  through `json.dumps` / `json.loads` exactly as Kafka or a file sink would, rebuild
  the model input from the parsed event, and score it. Any float that does not
  survive JSON, any int silently widened to float, any field name that drifts between
  the schema and `FEATURES` shows up as a changed prediction.
* **The broadcast half — not testable until D3-D4.** Both paths here take the 21
  history features from the same `features_v1` row, which is what a *correct*
  broadcast join delivers by definition. That assumption is the thing Mounika's
  streaming job has to earn, and this same assertion gets pointed at its output once
  it exists. Stated rather than glossed: a green run here does not yet mean the
  streaming job is correct, it means the event format is not what would break it.

A second check runs alongside, and it is the one that actually found something. The
event carries `created_hour` / `created_dayofweek` / `created_is_weekend` as explicit
fields, but a streaming job could just as reasonably recompute them from `event_time`.
Written the obvious Python way -- `datetime.weekday()` -- that recomputation disagrees
with **every single row**, because Stage 4 built the feature with Spark's `dayofweek`
(Sunday = 1) and Python counts from Monday = 0. The fix is a single shared
`schema.temporal_features()` that both sides import; this run asserts the carried
fields match it, and separately counts how many rows the naive reading would have
corrupted (P-39).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime

import pandas as pd
from pyspark.ml import PipelineModel

from src.common import config, docs
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark
from src.ml.baselines import (
    FEATURES,
    HISTORY_PREFIXES,
    load_features,
    prepare_model_features,
)
from src.streaming.schema import query_event, temporal_features

log = get_logger("ml.stream_validation")

#: Derived, not hand-listed: whatever in `FEATURES` is not one of D-020's history
#: prefixes is a feature the event itself has to carry. Hard-coding these six would
#: mean a new feature could be added to `FEATURES` and silently never tested.
EVENT_CARRIED = [f for f in FEATURES if not any(f.startswith(p + "_") for p in HISTORY_PREFIXES)]
HISTORY_CARRIED = [f for f in FEATURES if f not in EVENT_CARRIED]

W5_DOC_HEADER = """# W5 · Lahari — stream-equals-batch, threshold sensitivity, agent evaluation

Week 5 deliverables. The stream-equals-batch correctness test (D1-D2) is below;
delay-threshold sensitivity (D3-D4) and the Order Entry Agent evaluation (D5) land in
later sections of this same file, per GIT_RULES §2.

Regenerate rather than editing numbers by hand:

```bash
python -m src.ml.stream_validation --limit 500
```
"""


def rebuild_from_event(event: dict, history: pd.Series) -> dict:
    """One model-input row assembled the way a streaming consumer would assemble it.

    The six event-carried features come from the **parsed JSON**, so anything the
    round-trip does to them is visible in the prediction. The 21 history features come
    from `history`, standing in for the broadcast join — see the module docstring for
    why that half is assumed rather than tested here.
    """
    row = {name: history[name] for name in HISTORY_CARRIED}
    row["planned_min"] = float(event["planned_min"])
    row["planned_km"] = float(event["planned_km"])
    row["created_hour"] = int(event["created_hour"])
    row["created_dayofweek"] = int(event["created_dayofweek"])
    row["created_is_weekend"] = int(event["created_is_weekend"])
    row["is_ftl"] = int(event["route_type"] == "FTL")
    return row


def naive_temporal(event: dict) -> dict:
    """What a Python consumer reaching for `datetime.weekday()` would compute.

    Kept deliberately, and deliberately *wrong*: this is the reading a streaming job
    would land on by writing the obvious thing, and the run below counts how many rows
    it would have corrupted. Deleting it would remove the evidence for why
    `schema.temporal_features` has to exist (P-39).
    """
    when = datetime.fromisoformat(event["event_time"])
    return {
        "created_hour": when.hour,
        "created_dayofweek": when.weekday(),
        "created_is_weekend": int(when.weekday() >= 5),
    }


def compare_temporal(events: list[dict]) -> pd.DataFrame:
    """Carried fields vs. the shared helper, and vs. the naive Python reading.

    The helper column is the assertion -- it must match what the event carries, or the
    stream and the batch disagree on a feature the model was trained with. The naive
    column is evidence, not a target: it records how far off the obvious-but-wrong
    computation lands on real data.
    """
    rows = []
    for event in events:
        shared = temporal_features(datetime.fromisoformat(event["event_time"]))
        naive = naive_temporal(event)
        rows.append(
            {
                "leg_id": event["leg_id"],
                **{f"carried_{k}": event[k] for k in shared},
                **{f"shared_{k}": v for k, v in shared.items()},
                "naive_created_dayofweek": naive["created_dayofweek"],
                "agrees_with_shared": all(event[k] == v for k, v in shared.items()),
                "naive_would_differ": any(event[k] != v for k, v in naive.items()),
            }
        )
    return pd.DataFrame(rows)


def run(limit: int | None = None, out_md: str | None = None) -> dict:
    """Score `limit` legs both ways and compare. Returns the summary dict."""
    champion = config.MODELS_DIR / "champion"
    if not champion.exists():
        raise FileNotFoundError(
            f"No champion model at {champion} -- run `python -m src.automation.retrain` first."
        )

    spark = get_spark("stream-equals-batch")
    try:
        pdf = load_features(spark, config.FEATURES_V1)
        pdf = pdf.sort_values("trip_creation_time").reset_index(drop=True)
        if limit:
            pdf = pdf.head(limit)
        prepared = prepare_model_features(pdf)

        # The event path: serialise, round-trip through JSON exactly as a sink would,
        # parse back, rebuild. `json.loads(json.dumps(...))` is not ceremony -- it is
        # the step where a float or an int can quietly change shape.
        events = [json.loads(json.dumps(query_event(row))) for _, row in prepared.iterrows()]
        rebuilt = pd.DataFrame(
            [rebuild_from_event(event, prepared.iloc[i]) for i, event in enumerate(events)]
        )

        batch_input = prepared[FEATURES].copy()
        event_input = rebuilt[FEATURES].copy()

        model = PipelineModel.load(str(champion))
        batch_pred = _predict(spark, model, batch_input)
        event_pred = _predict(spark, model, event_input)
    finally:
        stop_spark(spark)

    comparison = pd.DataFrame(
        {
            "leg_id": prepared["leg_id"].to_numpy(),
            "batch_prediction": batch_pred,
            "stream_prediction": event_pred,
        }
    )
    comparison["abs_difference"] = (comparison["batch_prediction"] - comparison["stream_prediction"]).abs()
    identical = int((comparison["abs_difference"] == 0).sum())

    temporal = compare_temporal(events)
    temporal_agree = int(temporal["agrees_with_shared"].sum())
    naive_would_break = int(temporal["naive_would_differ"].sum())

    raw = config.BENCHMARKS_RAW_DIR
    comparison.to_csv(raw / "w5_stream_equals_batch.csv", index=False)
    temporal.to_csv(raw / "w5_stream_temporal_check.csv", index=False)

    summary = {
        "legs": len(comparison),
        "identical_predictions": identical,
        "identical_rate": round(identical / len(comparison), 6) if len(comparison) else 0.0,
        "max_abs_difference": float(comparison["abs_difference"].max()) if len(comparison) else 0.0,
        "event_carried_features": EVENT_CARRIED,
        "history_features_assumed": len(HISTORY_CARRIED),
        "temporal_fields_agree": temporal_agree,
        "temporal_fields_checked": len(temporal),
        "naive_python_dayofweek_would_break": naive_would_break,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    (raw / "w5_stream_validation_report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    docs.write_section(
        config.DOCS_DIR / (out_md or "W5_lahari_stream_validation.md"),
        "stream-equals-batch",
        render_doc(summary, comparison),
        header=W5_DOC_HEADER,
    )
    log.info(
        "%s legs: %s identical predictions (max |diff| %.10g), temporal agreement %s/%s",
        f"{summary['legs']:,}", f"{identical:,}", summary["max_abs_difference"],
        temporal_agree, len(temporal),
    )
    return summary


def _predict(spark, model: PipelineModel, features: pd.DataFrame) -> list[float]:
    """Score a feature frame, keeping input order.

    Spark makes no promise that `toPandas()` returns rows in the order they went in,
    so an explicit index column rides along and the result is sorted back by it --
    comparing two prediction lists that are each correct but differently ordered would
    fail loudly here and, worse, could pass by coincidence on a small sample.
    """
    frame = features.copy()
    frame["_row"] = range(len(frame))
    sdf = spark.createDataFrame(frame)
    out = model.transform(sdf).select("_row", "prediction").toPandas()
    return out.sort_values("_row")["prediction"].tolist()


def render_doc(summary: dict, comparison: pd.DataFrame) -> str:
    o: list[str] = []
    o.append("## Stream equals batch (D1-D2)\n")
    o.append(
        "*Generated by `python -m src.ml.stream_validation` -- regenerate rather than "
        "editing numbers by hand.*\n"
    )
    o.append(f"Generated: {summary['generated_at']}\n")
    o.append(
        "The invariant Week 5's gate rests on: an identical leg must score identically "
        "whether it is read from `features_v1` in batch or arrives as a JSON event on "
        "the stream. Both paths here run the same champion `PipelineModel` "
        "(`data/models/champion`, promoted by D-029's retrain loop).\n"
    )
    o.append("| Check | Result |")
    o.append("|---|---|")
    o.append(f"| Legs compared | {summary['legs']:,} |")
    o.append(
        f"| Identical predictions | **{summary['identical_predictions']:,} of "
        f"{summary['legs']:,}** ({summary['identical_rate']:.1%}) |"
    )
    o.append(f"| Largest absolute difference | **{summary['max_abs_difference']:.10g}** min |")
    o.append(
        f"| Temporal fields: carried == `schema.temporal_features()` | "
        f"**{summary['temporal_fields_agree']:,} of {summary['temporal_fields_checked']:,}** |"
    )
    o.append(
        f"| Rows the naive `datetime.weekday()` reading would corrupt | "
        f"**{summary['naive_python_dayofweek_would_break']:,} of "
        f"{summary['temporal_fields_checked']:,}** |"
    )
    o.append("")

    if summary["identical_rate"] == 1.0:
        o.append(
            "**Every prediction is bit-identical.** The event round-trip -- "
            "`query_event` -> `json.dumps` -> `json.loads` -> rebuilt feature row -- "
            "changes nothing the model reads. That is the result this test exists to "
            "produce, and it is worth being precise about what it licenses.\n"
        )
    else:
        o.append(
            f"**{summary['legs'] - summary['identical_predictions']} of "
            f"{summary['legs']} predictions differ**, largest by "
            f"{summary['max_abs_difference']:.10g} min. Rows are in "
            "`benchmarks/raw/w5_stream_equals_batch.csv`; this is a real divergence "
            "between the two paths and the streaming job cannot be trusted until it "
            "is explained.\n"
        )

    o.append("### What this does and does not license\n")
    o.append(
        f"A prediction needs {len(FEATURES)} features. The event carries "
        f"**{len(EVENT_CARRIED)}** of them (`{'`, `'.join(EVENT_CARRIED)}`); the other "
        f"**{summary['history_features_assumed']}** are the `corr_*`/`src_*`/`dst_*` "
        "history D-031 deliberately keeps out of the event for a broadcast join to "
        "supply. Both paths above take those from the same `features_v1` row -- which "
        "is what a *correct* broadcast join delivers by definition, and precisely the "
        "thing Mounika's streaming job (D3-D4) still has to earn.\n"
    )
    o.append(
        "So: this run says the **event format** is not what would break the stream. It "
        "does not yet say the streaming job is correct. The same assertion gets pointed "
        "at that job's output once it exists, and only then does the gate's claim hold "
        "end to end.\n"
    )
    o.append("### The day-of-week trap this test caught\n")
    o.append(
        f"The event carries the temporal features as explicit fields, but a streaming "
        f"job could just as reasonably recompute them from `event_time`. Written the "
        f"obvious way -- `datetime.weekday()` -- that recomputation disagrees with the "
        f"carried value on **{summary['naive_python_dayofweek_would_break']:,} of "
        f"{summary['temporal_fields_checked']:,} rows**, because Stage 4 built the "
        "feature with Spark's `dayofweek` (**Sunday = 1**, Saturday = 7) and Python's "
        "`weekday()` counts from **Monday = 0**. On a Wednesday that is 4 against 2.\n"
    )
    o.append(
        "Nothing raises when this happens. The model receives a number on a different "
        "scale for every event and answers confidently and wrongly -- no exception, no "
        "null, no row count that looks off. `src.streaming.schema.temporal_features()` "
        "is now the one place that conversion lives, so the streaming job and the batch "
        "pipeline cannot drift apart on it, and the row above is the regression guard. "
        "Full account: `docs/problems.md` P-39.\n"
    )
    o.append(
        "Full per-leg output: `benchmarks/raw/w5_stream_equals_batch.csv`, "
        "`w5_stream_temporal_check.csv`, `w5_stream_validation_report.json`.\n"
    )
    return "\n".join(o)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=500, help="legs to compare (default 500)")
    parser.add_argument("--all", action="store_true", help="compare every leg in features_v1")
    args = parser.parse_args()

    if not config.FEATURES_V1.exists():
        log.error("Missing %s -- run `python -m src.pipeline.features` first.", config.FEATURES_V1)
        return 1

    summary = run(limit=None if args.all else args.limit)
    return 0 if summary["identical_predictions"] == summary["legs"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
