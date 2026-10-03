"""Stream-equals-batch for the served v2 model, through the running job (WP-11, D-053).

    python -m src.streaming.validate_v2              # full replay, 500-leg comparison
    python -m src.streaming.validate_v2 --limit 500 --events-per-file 4000

The Week 8 check (`src.ml.stream_validation.run_adopted`, 500 of 500) tested the event
format only: both of its paths read their history from the same `features_v2` row,
because the stream could not build that history yet. This one tests the pipeline.

1. Every leg becomes its query and fact events (`src.streaming.producer`), and the
   whole replay is written as tick files -- 52,738 events.
2. **The stream job runs twice over one checkpoint.** The first run drains the first
   half of the files and stops; the second is a fresh query on the same checkpoint that
   drains the rest. The second half's queries can only score correctly if the history
   the first run built came back out of the state store, so a persistence failure shows
   up as a wrong prediction rather than having to be looked for.
3. Every query the job scored -- not only the alerted ones -- is compared with the
   batch prediction for the same leg: `features_v2` -> the same served model -> median
   plus correction. The acceptance comparison is 500 legs spread across the timeline
   (the W8 sampling rule); every leg and every one of the 26 history features is
   compared as well, because 500 was a floor, not a ceiling.

Latency is not reported: the tick files are written before the job starts, so the
time from file to alert measures this script, not the pipeline.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark
from src.ml import serving
from src.ml.baselines import TARGET, time_split
from src.streaming import job, producer
from src.streaming.state import FEATURE_COLUMNS

log = get_logger("streaming.validate_v2")

WORK_DIR = config.STREAM_DIR / "validation_v2"
REPORT_JSON = config.BENCHMARKS_RAW_DIR / "w10_stream_validation_v2.json"
SAMPLE_CSV = config.BENCHMARKS_RAW_DIR / "w10_stream_equals_batch_v2.csv"

#: The headline v2 figure, from `w7_model_metrics_v2_stepsize.csv` via the freeze. The
#: stream's own predictions on the same test legs have to land on it.
REPORTED_TEST_MAE = 30.90


def write_ticks(events: list[dict], directory: Path, per_file: int) -> list[Path]:
    """The replay as tick files, with strictly increasing modification times.

    Spark's file source orders files by modification time. Written back to back, two
    files can share a timestamp at the file system's resolution, and a later file
    processed first would hand a query history from its own future. Spacing them a
    second apart takes that off the table instead of leaving it to luck.
    """
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    first = time.time() - len(events) // per_file - 10
    for n, start in enumerate(range(0, len(events), per_file)):
        path = directory / f"tick_{n:06d}.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in events[start:start + per_file]) + "\n", encoding="utf-8")
        os.utime(path, (first + n, first + n))
        paths.append(path)
    return paths


def read_scored(directory: Path) -> pd.DataFrame:
    rows = [json.loads(line) for path in sorted(directory.glob("*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines() if line]
    return pd.DataFrame(rows)


def spread_sample(frame: pd.DataFrame, limit: int) -> pd.DataFrame:
    """The W8 rule: evenly spaced across the timeline, not the first N legs, which are
    nearly all on corridors with no history yet."""
    ordered = frame.sort_values("trip_creation_time").reset_index(drop=True)
    return ordered.iloc[:: max(1, len(ordered) // limit)].head(limit).reset_index(drop=True)


def feature_agreement(stream: pd.DataFrame, batch: pd.DataFrame) -> dict:
    """Per history column: legs where the stream's value is not the batch table's."""
    out = {}
    for column in FEATURE_COLUMNS:
        s = pd.to_numeric(stream[column], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(batch[column], errors="coerce").to_numpy(dtype=float)
        both_null = np.isnan(s) & np.isnan(b)
        differ = ~((s == b) | both_null)
        diff = np.where(both_null, 0.0, np.abs(s - b))
        out[column] = {"differ": int(differ.sum()), "max_abs_difference": float(np.nanmax(diff)) if len(diff) else 0.0}
    return out


def run(limit: int = 500, per_file: int = 4000, files_per_trigger: int = 2) -> dict:
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    source, scored_dir = WORK_DIR / "source", WORK_DIR / "scored"
    alerts_dir, checkpoint = WORK_DIR / "alerts", WORK_DIR / "checkpoint"

    legs = producer.load_legs()
    # Through JSON exactly as a sink would carry them, so the job reads what a
    # consumer of the real topic would read.
    events = [json.loads(json.dumps(e)) for e in producer.build_events(legs)]
    staging = WORK_DIR / "staging"
    paths = write_ticks(events, staging, per_file)
    half = len(paths) // 2
    log.info("%s events in %d files; first run drains %d, second run the rest", f"{len(events):,}", len(paths), half)

    spark = get_spark("stream-validate-v2")
    runs = []
    try:
        for label, batch in (("first", paths[:half]), ("resumed", paths[half:])):
            source.mkdir(parents=True, exist_ok=True)
            for path in batch:
                stat = path.stat()
                target = source / path.name
                shutil.copy2(path, target)
                os.utime(target, (stat.st_atime, stat.st_mtime))
            stats = job.run(
                source_dir=source, alerts_dir=alerts_dir, checkpoint_dir=checkpoint, once=True,
                max_files_per_trigger=files_per_trigger, spark=spark, model="v2", scored_dir=scored_dir,
            )
            summary = stats.summary()
            for key in ("latency_p50_ms", "latency_p95_ms", "latency_max_ms"):
                summary.pop(key, None)
            runs.append({"run": label, "files": len(batch), **summary})
            log.info("%s run: %s", label, json.dumps({k: summary[k] for k in ("events", "facts_applied", "queries", "out_of_order")}))

        batch_frame = pd.read_parquet(config.FEATURES_V2)
        batch_scored = serving.score(spark, serving.load_model(), batch_frame)
    finally:
        stop_spark(spark)

    stream = read_scored(scored_dir)
    features = pd.json_normalize(stream["features"].tolist())
    stream = pd.concat([stream.drop(columns=["features"]), features], axis=1)
    if stream["leg_id"].duplicated().any():
        raise RuntimeError("a leg was scored twice -- the resumed run replayed a batch it had already committed")

    batch = batch_frame[["leg_id", "trip_creation_time", TARGET, *FEATURE_COLUMNS]].assign(
        batch_prediction=batch_scored["predicted_gap_min"].to_numpy(),
        baseline_median=batch_scored["baseline_median"].to_numpy(),
    )
    merged = batch.merge(
        stream.rename(columns={c: f"s_{c}" for c in FEATURE_COLUMNS})[
            ["leg_id", "predicted_gap_min", *[f"s_{c}" for c in FEATURE_COLUMNS]]
        ].rename(columns={"predicted_gap_min": "stream_prediction"}),
        on="leg_id", how="left",
    )
    missing = int(merged["stream_prediction"].isna().sum())
    merged["abs_difference"] = (merged["batch_prediction"] - merged["stream_prediction"]).abs()

    sample = spread_sample(merged, limit)
    identical = int((sample["abs_difference"] == 0).sum())
    all_identical = int((merged["abs_difference"] == 0).sum())

    _, test, _ = time_split(merged.sort_values("trip_creation_time").reset_index(drop=True))
    stream_mae = float(np.mean(np.abs(test[TARGET] - test["stream_prediction"])))
    batch_mae = float(np.mean(np.abs(test[TARGET] - test["batch_prediction"])))

    stream_features = merged[[f"s_{c}" for c in FEATURE_COLUMNS]].set_axis(FEATURE_COLUMNS, axis=1)
    agreement = feature_agreement(stream_features, merged[FEATURE_COLUMNS])

    sample[["leg_id", "trip_creation_time", "baseline_median", "batch_prediction", "stream_prediction",
            "abs_difference"]].to_csv(SAMPLE_CSV, index=False)
    report = {
        "model": f"{serving.MODEL_ID} (the reported model, D-050)",
        "served_by_the_streaming_job": True,
        "history": "event-time state: applyInPandasWithState over five key types, watermark "
                   f"{job.WATERMARK_DELAY}, state persisted in the checkpoint's state store",
        "legs": limit,
        "identical_predictions": identical,
        "identical_rate": round(identical / len(sample), 6) if len(sample) else 0.0,
        "max_abs_difference": float(sample["abs_difference"].max()) if len(sample) else 0.0,
        "cold_corridors_in_sample": int((sample["baseline_median"] == 0).sum()),
        "all_legs": {
            "legs": len(merged),
            "scored_by_stream": len(merged) - missing,
            "identical_predictions": all_identical,
            "max_abs_difference": float(merged["abs_difference"].max()),
        },
        "history_features_compared": len(FEATURE_COLUMNS),
        "history_features_differing_legs": sum(v["differ"] for v in agreement.values()),
        "feature_agreement": agreement,
        "test_split": {
            "legs": len(test),
            "stream_mae_min": round(stream_mae, 4),
            "batch_mae_min": round(batch_mae, 4),
            "reported_mae_min": REPORTED_TEST_MAE,
            "stream_matches_reported": round(stream_mae, 2) == REPORTED_TEST_MAE,
        },
        "restart": {
            "runs": runs,
            "note": "the second run is a new query on the first run's checkpoint; its queries "
                    "read history only the restored state store could supply",
        },
        "latency": "not measured here: tick files are written before the job starts",
        "replaces": "w8_stream_validation_v2.json tested the event format only (history read "
                    "from features_v2 on both sides); this file tests the running job",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info(
        "served v2: %d of %d sampled legs identical; %s of %s overall; test MAE stream %.2f vs reported %.2f",
        identical, len(sample), f"{all_identical:,}", f"{len(merged):,}", stream_mae, REPORTED_TEST_MAE,
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=500, help="legs in the acceptance sample")
    parser.add_argument("--events-per-file", type=int, default=4000)
    parser.add_argument("--files-per-trigger", type=int, default=2)
    args = parser.parse_args()
    for path in (config.FEATURES_V1, config.FEATURES_V2, Path(serving.MODEL_PATH)):
        if not path.exists():
            log.error("Missing %s", path)
            return 1
    report = run(args.limit, args.events_per_file, args.files_per_trigger)
    return 0 if report["identical_predictions"] == report["legs"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
