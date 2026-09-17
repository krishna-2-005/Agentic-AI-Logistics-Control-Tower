"""Stage 4b -- feature table v2 (execution plan v3.1 §2.1 Step 2, G-04).

    python -m src.pipeline.features_v2

`features_v1` plus the history the Week 7 ML sprint needs, written to a new cache. v1 is
never repointed or rewritten (D-016): every v1 column is carried through unchanged and
v2 only *adds*.

What is added, and what the plan asked for that is not
------------------------------------------------------
Added, all past-only, all computed with Stage 4's own fact/query union so the leakage
guarantee is the same one v1 carries (a prior leg counts only once it has *finished*,
at `od_end_time`; facts sort before queries at an identical timestamp):

* **Corridor dispersion** -- `corr_median_gap_min`, `corr_p90_gap_min`,
  `corr_iqr_gap_min`, `corr_std_gap_min`. The median is also the strongest statistical
  baseline D-048 found (33.04 min test MAE against the mean's 36.13), and the residual
  target in Step 3 is built on it.
* **Trailing 7-day corridor mean** -- `corr_mean_gap_7d`, `corr_n_prior_7d`. Drift the
  all-time mean smooths away.
* **Hub dwell by departure hour** -- `src_dwell_by_hour_min` and `dst_dwell_by_hour_min`:
  the as-of mean dwell of prior legs leaving (arriving at) the same hub in the same
  four-bucket part of the day. Week 2 found dwell is 34.6% of wall clock and varies by
  time of day; a corridor mean averages straight over it.

**Not added, with the reason, because the plan listed them:**

* **Segment count per leg.** `n_segments` and every `segment_*` column are in Stage 4's
  `BANNED_FEATURES`: they are produced by the journey and are not known when a leg is
  created. Adding them would be leakage by construction.
* **Trailing 30-day corridor mean.** The data spans 21 days (11 September to 3 October
  2018), so a 30-day window is the all-time mean v1 already carries as
  `corr_mean_gap_min` -- the same column twice.
* **Historical actual/OSRM ratio per corridor.** Already in v1 as
  `corr_mean_log_ratio`, the mean of `log(actual / osrm)`.
* **`is_festival_window`.** The window ends a week before Navratri 2018 (G-11, D-048).

Validated before it is written, and again by its judge
-------------------------------------------------------
The build refuses to write if an outcome column survives, if the row count differs from
v1, if a cold leg carries a corridor median (history from nowhere) or a warm leg lacks
one. The strongest check is Lahari's, not this module's: her residual step recomputes the
corridor median independently in pandas (`src.ml.ml_diagnostics`, itself verified at 100%
against v1) and refuses to train unless the two agree on every warm leg. Builder and judge
kept apart, as D-028 does for the agents.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from src.common import config
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark
from src.pipeline.features import BANNED_FEATURES, load_legs

log = get_logger("pipeline.features_v2")

REPORT_JSON = config.BENCHMARKS_RAW_DIR / "w7_features_v2_report.json"

TRAILING_DAYS = 7
SECONDS_PER_DAY = 86_400

#: Part-of-day buckets for the dwell history. Four, not 24: a corridor-hub pair sees a
#: handful of legs an hour, and a 24-way split would leave most cells with no history
#: at all -- a feature that is null for most legs teaches the model nothing.
HOUR_BUCKETS = {"night": (0, 5), "morning": (6, 11), "afternoon": (12, 17), "evening": (18, 23)}

NEW_COLUMNS = [
    "corr_median_gap_min", "corr_p90_gap_min", "corr_iqr_gap_min", "corr_std_gap_min",
    "corr_mean_gap_7d", "corr_n_prior_7d",
    "src_dwell_by_hour_min", "dst_dwell_by_hour_min",
]


def hour_bucket(timestamp_col: str) -> F.Column:
    hour = F.hour(timestamp_col)
    expr = None
    for name, (low, high) in HOUR_BUCKETS.items():
        clause = F.when((hour >= low) & (hour <= high), F.lit(name))
        expr = clause if expr is None else expr.when((hour >= low) & (hour <= high), F.lit(name))
    return expr


def _event_stream(legs: DataFrame, key: F.Column, value: F.Column) -> DataFrame:
    """Stage 4's fact/query union: a fact at `od_end_time` carrying `value`, a query at
    `trip_creation_time` carrying the leg id. Same ordering rule as
    `src.pipeline.features.as_of_history` -- facts before queries on a tie."""
    facts = legs.select(
        key.alias("k"), F.col("od_end_time").alias("event_time"), F.lit(0).alias("kind"),
        F.lit(None).cast("string").alias("leg_id"), value.cast("double").alias("f_val"),
    )
    queries = legs.select(
        key.alias("k"), F.col("trip_creation_time").alias("event_time"), F.lit(1).alias("kind"),
        F.col("leg_id"), F.lit(None).cast("double").alias("f_val"),
    )
    return facts.unionByName(queries)


def corridor_dispersion(legs: DataFrame) -> DataFrame:
    """Past-only median, p90, IQR and std of `gap_min` per corridor, plus a trailing
    7-day mean. Exact percentiles, not approximate: the median is a reported baseline and
    must match an independent recomputation, which an approximate quantile cannot."""
    stream = _event_stream(legs, F.col("corridor_id"), F.col("gap_min"))
    running = (
        Window.partitionBy("k").orderBy("event_time", "kind")
        .rowsBetween(Window.unboundedPreceding, Window.currentRow)
    )
    # Range frame on epoch seconds: peers at the same timestamp are inside the frame,
    # which is exactly facts-before-queries -- a fact known at T counts for a query at T.
    trailing = (
        Window.partitionBy("k").orderBy(F.col("event_time").cast("long"))
        .rangeBetween(-TRAILING_DAYS * SECONDS_PER_DAY, 0)
    )
    acc = stream.select(
        "kind", "leg_id",
        F.count("f_val").over(running).alias("n"),
        F.expr("percentile(f_val, 0.5)").over(running).alias("median"),
        F.expr("percentile(f_val, 0.9)").over(running).alias("p90"),
        F.expr("percentile(f_val, 0.75)").over(running).alias("p75"),
        F.expr("percentile(f_val, 0.25)").over(running).alias("p25"),
        F.stddev_samp("f_val").over(running).alias("std"),
        F.avg("f_val").over(trailing).alias("mean_7d"),
        F.count("f_val").over(trailing).alias("n_7d"),
    ).filter(F.col("kind") == 1)
    has = F.col("n") > 0
    return acc.select(
        "leg_id",
        F.when(has, F.col("median")).alias("corr_median_gap_min"),
        F.when(has, F.col("p90")).alias("corr_p90_gap_min"),
        F.when(has, F.col("p75") - F.col("p25")).alias("corr_iqr_gap_min"),
        F.when(F.col("n") > 1, F.col("std")).alias("corr_std_gap_min"),
        F.when(F.col("n_7d") > 0, F.col("mean_7d")).alias("corr_mean_gap_7d"),
        F.col("n_7d").cast("int").alias("corr_n_prior_7d"),
    )


def dwell_by_hour(legs: DataFrame, hub_col: str, prefix: str) -> DataFrame:
    """As-of mean dwell of prior legs at the same hub in the same part of the day.

    The key is `(hub, bucket)` where the bucket is each leg's *creation* hour, so a
    query leg created in the morning reads the dwell of earlier morning legs at its hub
    that have already finished. Dwell is `start_scan_to_end_scan - actual_time`
    (`reconstruct.py`'s definition) -- banned as a feature *of the leg itself*, legitimate
    as the history of other legs once they are over.
    """
    key = F.concat_ws("|", F.col(hub_col), hour_bucket("trip_creation_time"))
    dwell = F.col("start_scan_to_end_scan") - F.col("actual_time")
    stream = _event_stream(legs, key, dwell)
    running = (
        Window.partitionBy("k").orderBy("event_time", "kind")
        .rowsBetween(Window.unboundedPreceding, Window.currentRow)
    )
    acc = stream.select(
        "kind", "leg_id",
        F.count("f_val").over(running).alias("n"),
        F.avg("f_val").over(running).alias("mean"),
    ).filter(F.col("kind") == 1)
    return acc.select("leg_id", F.when(F.col("n") > 0, F.col("mean")).alias(f"{prefix}_dwell_by_hour_min"))


def build(spark: SparkSession, trips_path: Path = config.TRIPS_V1,
          v1_path: Path = config.FEATURES_V1) -> DataFrame:
    legs = load_legs(spark, trips_path).withColumn(
        "leg_id",
        F.concat_ws("|", "trip_uuid", F.date_format("od_start_time", "yyyyMMddHHmmss"), "corridor_id"),
    ).cache()
    v1 = spark.read.parquet(str(v1_path))
    v2 = (
        v1.join(corridor_dispersion(legs), on="leg_id", how="left")
        .join(dwell_by_hour(legs, "source_center", "src"), on="leg_id", how="left")
        .join(dwell_by_hour(legs, "destination_center", "dst"), on="leg_id", how="left")
    )
    return v2


def validate(v2: DataFrame, v1_rows: int) -> dict:
    """Refuse to write a table that fails any of these."""
    present = [c for c in BANNED_FEATURES if c in v2.columns]
    if present:
        raise ValueError(f"outcome columns leaked into features_v2: {present}")
    rows = v2.count()
    if rows != v1_rows:
        raise ValueError(f"features_v2 has {rows:,} rows, v1 has {v1_rows:,} -- a join duplicated or dropped legs")
    cold_with_median = v2.filter((F.col("corr_n_prior") == 0) & F.col("corr_median_gap_min").isNotNull()).count()
    if cold_with_median:
        raise ValueError(f"{cold_with_median} cold legs carry a corridor median: history from nowhere")
    warm_without = v2.filter((F.col("corr_n_prior") > 0) & F.col("corr_median_gap_min").isNull()).count()
    if warm_without:
        raise ValueError(f"{warm_without} warm legs have no corridor median")
    nulls = v2.select([F.avg(F.col(c).isNull().cast("double")).alias(c) for c in NEW_COLUMNS]).first().asDict()
    return {"rows": rows, "banned_columns_present": 0,
            "null_share": {k: round(float(v), 4) for k, v in nulls.items()}}


def run(out_path: Path = config.FEATURES_V2, report_path: Path = REPORT_JSON) -> dict:
    spark = get_spark("features-v2")
    try:
        v1_rows = spark.read.parquet(str(config.FEATURES_V1)).count()
        v2 = build(spark).cache()
        checks = validate(v2, v1_rows)
        v2.write.mode("overwrite").partitionBy("route_type").parquet(str(out_path))
        log.info("features_v2: %s rows, %d new columns -> %s", f"{checks['rows']:,}", len(NEW_COLUMNS), out_path)
    finally:
        stop_spark(spark)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "features_v2",
        "extends": "features_v1 (unchanged, D-016)",
        "new_columns": NEW_COLUMNS,
        "not_added": {
            "segment_count": "banned: produced by the journey (BANNED_FEATURES), leakage by construction",
            "trailing_30d_corridor_mean": "data spans 21 days; identical to v1 corr_mean_gap_min",
            "corridor_actual_osrm_ratio": "already in v1 as corr_mean_log_ratio",
            "is_festival_window": "window ends before Navratri 2018 (G-11, D-048)",
        },
        "hour_buckets": HOUR_BUCKETS,
        "trailing_days": TRAILING_DAYS,
        **checks,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build feature table v2 (G-04)")
    parser.add_argument("--out", type=Path, default=config.FEATURES_V2)
    args = parser.parse_args()
    if not config.FEATURES_V1.exists():
        log.error("Missing %s -- run `python -m src.pipeline.features` first.", config.FEATURES_V1)
        return 1
    report = run(args.out)
    print(json.dumps({k: report[k] for k in ("rows", "null_share")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
