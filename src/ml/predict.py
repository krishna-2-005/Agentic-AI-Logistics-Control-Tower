"""What-if delay prediction (execution plan W4 D5) -- the one place the dashboard
starts a SparkSession, per D-034's documented exception to D-009.

    python -m src.ml.predict --corridor IND208012AAA>IND209304AAA \
        --planned-min 593 --planned-km 19.8 --route-type FTL \
        --departure "2018-09-20 14:30"

Loads the champion `PipelineModel` (Mounika's auto-retrain script promotes it,
D-029) and looks up the corridor's and both hubs' most recent as-of history straight
from `features_v1`, in the same Spark session -- not a second, independently
recomputed history. Reusing Stage 4's own numbers rather than a second cached copy
is the same reasoning D-029 gives for calling `src.ml.models.run()` instead of
reimplementing it, applied one level further downstream.

**A documented simplification, not a rigorous backtest.** The history looked up is
each key's single *most recent* known snapshot in `features_v1`, regardless of the
departure date/time the form is asking about. For a departure after the dataset's
observation window (the intended use -- "what if I ship this today") that is exactly
right: nothing has happened since. For a hypothetical departure date *inside* the
window, this can hand the model a snapshot that is technically from after that date,
which the batch pipeline's own as-of join (D-020) would never do. Accepted here
because rebuilding a live as-of join for one form submission would mean re-deriving
Stage 4's entire logic a second time (the exact duplication D-029 already avoided
once) for a page whose purpose is illustrating the model, not re-litigating D-020's
leakage guarantee.
"""

from __future__ import annotations

import argparse
from datetime import datetime

from pyspark.ml import PipelineModel
from pyspark.sql import SparkSession

from src.common import config
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark
from src.ml.baselines import (
    COLD_ONLY_NULL_STATS,
    FEATURES,
    HISTORY_PREFIXES,
    HISTORY_STATS,
)

log = get_logger("ml.predict")

#: Which features_v1 column each history prefix's "as of now" lookup keys on.
KEY_COLUMN = {"corr": "corridor_id", "src": "source_center", "dst": "destination_center"}


def _latest_history(spark: SparkSession, prefix: str, key_value: str) -> dict:
    """The single most recent known `{prefix}_*` snapshot for `key_value`, or the
    cold-start fill (D-023) if that key has never been seen in `features_v1` at all.
    """
    key_col = KEY_COLUMN[prefix]
    cols = [f"{prefix}_{s}" for s in HISTORY_STATS]
    row = (
        spark.read.parquet(str(config.FEATURES_V1))
        .filter(f"{key_col} = '{key_value}'")
        .orderBy("trip_creation_time", ascending=False)
        .select(*cols)
        .limit(1)
        .collect()
    )
    if not row:
        stats = dict.fromkeys((f"{prefix}_{s}" for s in HISTORY_STATS if s != "n_prior"), 0.0)
        stats[f"{prefix}_n_prior"] = 0
        stats[f"{prefix}_is_cold"] = 1
        return stats

    r = row[0].asDict()
    is_cold = r[f"{prefix}_n_prior"] == 0
    for s in HISTORY_STATS:
        col = f"{prefix}_{s}"
        if s == "n_prior":
            continue
        fill_null = is_cold if s in COLD_ONLY_NULL_STATS else r[col] is None
        if fill_null or r[col] is None:
            r[col] = 0.0
    r[f"{prefix}_is_cold"] = int(is_cold)
    return r


def predict_delay(
    corridor_id: str,
    source_center: str,
    destination_center: str,
    route_type: str,
    planned_min: float,
    planned_km: float,
    departure: datetime,
) -> dict:
    """One what-if prediction from the champion model. Returns predicted gap/total
    minutes, the D-003 delay call, and which history keys were cold -- so the page
    can say "this corridor has no history yet" rather than silently predicting off
    zeros that look identical to "this corridor is normally on time."
    """
    champion_path = config.MODELS_DIR / "champion"
    if not champion_path.exists():
        raise FileNotFoundError(
            f"No champion model at {champion_path} -- run `python -m src.automation.retrain` first."
        )

    spark = get_spark("what-if-predict")
    try:
        row: dict = {
            "planned_min": float(planned_min),
            "planned_km": float(planned_km),
            "created_hour": departure.hour,
            "created_dayofweek": departure.weekday(),
            "created_is_weekend": int(departure.weekday() >= 5),
            "is_ftl": int(route_type == "FTL"),
        }
        key_values = {"corr": corridor_id, "src": source_center, "dst": destination_center}
        cold_flags = {}
        for prefix in HISTORY_PREFIXES:
            history = _latest_history(spark, prefix, key_values[prefix])
            row.update(history)
            cold_flags[prefix] = bool(history[f"{prefix}_is_cold"])

        sdf = spark.createDataFrame([row]).select(*FEATURES)
        model = PipelineModel.load(str(champion_path))
        prediction = model.transform(sdf).select("prediction").collect()[0]["prediction"]
    finally:
        stop_spark(spark)

    return build_result(float(prediction), planned_min, cold_flags)


def build_result(predicted_gap_min: float, planned_min: float, cold_flags: dict) -> dict:
    """The part of a prediction that has nothing to do with Spark -- split out so it
    can be tested (`tests/test_predict.py`) without a SparkSession or a real
    champion model on disk.
    """
    threshold_gap = (config.DELAY_THRESHOLD - 1) * planned_min
    return {
        "predicted_gap_min": round(predicted_gap_min, 1),
        "predicted_total_min": round(planned_min + predicted_gap_min, 1),
        "is_delayed_predicted": predicted_gap_min > threshold_gap,
        "threshold_gap_min": round(threshold_gap, 1),
        "cold_flags": cold_flags,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corridor", required=True, help="corridor_id, e.g. IND208012AAA>IND209304AAA")
    parser.add_argument("--source", help="source_center; parsed from --corridor if omitted")
    parser.add_argument("--destination", help="destination_center; parsed from --corridor if omitted")
    parser.add_argument("--planned-min", type=float, required=True)
    parser.add_argument("--planned-km", type=float, required=True)
    parser.add_argument("--route-type", choices=["FTL", "Carting"], default="FTL")
    parser.add_argument("--departure", required=True, help="'YYYY-MM-DD HH:MM'")
    args = parser.parse_args()

    source = args.source or args.corridor.split(">")[0]
    destination = args.destination or args.corridor.split(">")[1]
    # Naive, matching D-013's timestamp convention -- every timestamp in this
    # project (trip_creation_time included) is naive local time, never tz-aware.
    departure = datetime.strptime(args.departure, "%Y-%m-%d %H:%M")  # noqa: DTZ007

    result = predict_delay(
        args.corridor, source, destination, args.route_type,
        args.planned_min, args.planned_km, departure,
    )
    log.info(
        "predicted gap %.1f min (total %.1f min), delayed=%s, cold=%s",
        result["predicted_gap_min"], result["predicted_total_min"],
        result["is_delayed_predicted"], result["cold_flags"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
