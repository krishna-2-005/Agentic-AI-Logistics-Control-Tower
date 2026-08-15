"""Stage 3 — corridor audit: where is the production planner systematically wrong?

    python -m src.ml.audit
    python -m src.ml.audit --min-support 10

Reads the OD legs cached by Stage 2 (`trips_v1`) and produces one row per corridor
with enough support to say something about, writing
`benchmarks/raw/w2_corridor_audit.csv`.

What this is testing, and what it is deliberately not testing
-------------------------------------------------------------
Week 1 established that OSRM under-predicts on **98.3% of legs** and the median leg
runs at 2.00x the planned time. So the question "is this corridor slower than the
plan?" has the same answer everywhere — yes — and a test of it would rank nothing.

The audit's claim is **localisation**, not bias: *given* that the whole network runs
over plan, which corridors run over plan by more than the network's own typical leg?
Every statistic here is therefore relative to the network baseline, never to the
planner's estimate of 1.0.

The statistic is `log_gap_ratio = log(actual_time / osrm_time)` at OD-leg grain
(D-002), computed in Stage 2. Logs rather than the raw ratio because the ratio is
right-skewed — a handful of legs run at 50x plan and would drag any corridor mean
they land in.

Compute shape
-------------
One Spark pass produces the per-corridor aggregate; the network totals come from the
same pass. Everything after that runs on the ~100-row corridor table in pandas, which
is where the tests belong: `scipy` on 100 rows is not a distributed workload and
pretending it is would only hide the aggregation that genuinely is one.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from src.common import config
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark

log = get_logger("ml.audit")

#: The test statistic. Set once here so the aggregate, the tests and the writeup
#: cannot drift onto different columns.
STAT = "log_gap_ratio"


def load_legs(spark: SparkSession, path: Path) -> DataFrame:
    """Read `trips_v1`, keeping only legs the statistic is defined on.

    Stage 2 already guarantees `osrm_time > 0` on every published leg, so nothing is
    expected to drop here. The filter stays because the audit must not silently
    average a null away if a future Stage 2 loosens that guarantee — the count of
    dropped legs is reported.
    """
    legs = spark.read.parquet(str(path))
    usable = legs.filter(
        F.col(STAT).isNotNull() & ~F.isnan(STAT) & (F.col("osrm_time") > 0)
    )
    return usable


def network_baseline(legs: DataFrame) -> dict:
    """Network-wide totals for `STAT`, as sums so a corridor's complement subtracts.

    Returning sums rather than mean/variance is what lets every corridor's
    "rest of the network" comparison group be derived by subtraction instead of by
    re-scanning the legs once per corridor.
    """
    row = legs.agg(
        F.count("*").alias("n"),
        F.sum(STAT).alias("sum"),
        F.sum(F.col(STAT) * F.col(STAT)).alias("sumsq"),
        F.mean("gap_min").alias("mean_gap_min"),
        F.expr("percentile_approx(gap_ratio, 0.5)").alias("median_gap_ratio"),
    ).collect()[0]
    n, s, ss = row["n"], float(row["sum"]), float(row["sumsq"])
    mean = s / n
    return {
        "n": int(n),
        "sum": s,
        "sumsq": ss,
        "mean_log": mean,
        "var_log": (ss - n * mean * mean) / (n - 1),
        "mean_gap_min": float(row["mean_gap_min"]),
        "median_gap_ratio": float(row["median_gap_ratio"]),
    }


def corridor_aggregate(legs: DataFrame) -> DataFrame:
    """One row per corridor: support, gap statistics, and the sums the tests need.

    `sum_log` / `sumsq_log` are carried through deliberately — they are what the
    Welch comparison group is built from, and recomputing them later would mean a
    second pass over 26,369 legs for no gain.
    """
    return (
        legs.groupBy("corridor_id")
        .agg(
            F.count("*").alias("n_legs"),
            F.countDistinct("trip_uuid").alias("n_trips"),
            F.first("source_center").alias("source_center"),
            F.first("destination_center").alias("destination_center"),
            F.first("source_name").alias("source_name"),
            F.first("destination_name").alias("destination_name"),
            F.first("source_city").alias("source_city"),
            F.first("dest_city").alias("dest_city"),
            F.first("source_state").alias("source_state"),
            F.first("dest_state").alias("dest_state"),
            F.sum(STAT).alias("sum_log"),
            F.sum(F.col(STAT) * F.col(STAT)).alias("sumsq_log"),
            F.mean("gap_ratio").alias("mean_gap_ratio"),
            F.expr("percentile_approx(gap_ratio, 0.5)").alias("median_gap_ratio"),
            F.mean("gap_min").alias("mean_gap_min"),
            F.expr("percentile_approx(gap_min, 0.5)").alias("median_gap_min"),
            F.mean("osrm_time").alias("mean_osrm_time"),
            F.mean("actual_time").alias("mean_actual_time"),
            F.mean("osrm_distance").alias("mean_osrm_km"),
            F.mean("dwell_min").alias("mean_dwell_min"),
            F.mean(F.col("route_type").eqNullSafe("FTL").cast("double")).alias("ftl_share"),
        )
        .withColumn("mean_log", F.col("sum_log") / F.col("n_legs"))
    )


def to_pandas(agg: DataFrame, min_support: int) -> pd.DataFrame:
    """Collect the supported corridors to the driver.

    Safe by construction: the support threshold (D-004) caps this at ~100 rows out of
    2,783 corridors. `--min-support 1` would collect all of them, which is why the
    row count is logged rather than assumed.
    """
    pdf = (
        agg.filter(F.col("n_legs") >= min_support)
        .orderBy(F.col("n_legs").desc())
        .toPandas()
    )
    log.info("  %s corridors at >= %s legs", f"{len(pdf):,}", min_support)
    return pdf


def build(spark: SparkSession, input_path: Path, min_support: int) -> tuple[pd.DataFrame, dict]:
    """Run the aggregation and return (supported corridors, network baseline)."""
    legs = load_legs(spark, input_path).cache()
    n_usable = legs.count()
    n_total = spark.read.parquet(str(input_path)).count()
    if n_usable != n_total:
        log.warning(
            "%s of %s legs have no usable %s and are excluded from the audit",
            f"{n_total - n_usable:,}",
            f"{n_total:,}",
            STAT,
        )

    baseline = network_baseline(legs)
    log.info(
        "Network baseline: %s legs, median gap ratio %.2fx, mean gap %.0f min",
        f"{baseline['n']:,}",
        baseline["median_gap_ratio"],
        baseline["mean_gap_min"],
    )

    agg = corridor_aggregate(legs)
    n_corridors = agg.count()
    pdf = to_pandas(agg, min_support)
    baseline["corridors_total"] = int(n_corridors)
    baseline["corridors_supported"] = len(pdf)
    baseline["legs_covered"] = int(pdf["n_legs"].sum())
    baseline["min_support"] = min_support

    legs.unpersist()
    return pdf, baseline


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 3 — corridor audit")
    parser.add_argument("--input", type=Path, default=config.TRIPS_V1)
    parser.add_argument(
        "--min-support",
        type=int,
        default=config.MIN_CORRIDOR_SUPPORT,
        help="minimum observed legs before a corridor is audited (D-004)",
    )
    args = parser.parse_args()

    if not args.input.exists():
        log.error("Missing %s — run `python -m src.pipeline.reconstruct` first.", args.input)
        return 1

    config.ensure_dirs()
    spark = get_spark("stage3-audit")
    try:
        corridors, baseline = build(spark, args.input, args.min_support)
    finally:
        stop_spark(spark)

    out = config.BENCHMARKS_RAW_DIR / "w2_corridor_audit.csv"
    corridors.to_csv(out, index=False)
    log.info("Corridor table → %s", out)
    log.info(
        "%s of %s corridors carry >= %s legs, covering %.1f%% of the network's legs.",
        f"{baseline['corridors_supported']:,}",
        f"{baseline['corridors_total']:,}",
        baseline["min_support"],
        baseline["legs_covered"] / baseline["n"] * 100,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
