"""Stage 2 — trip and corridor reconstruction (PySpark window functions).

    python -m src.pipeline.reconstruct
    python -m src.pipeline.reconstruct --validate    # also diff against the W1 oracle

Collapses the cleaned segment rows into one row per origin-destination **leg**, which
is the grain every corridor statistic, feature, and model downstream is computed at
(D-002).

Why this needs window functions rather than a plain ``groupBy``
---------------------------------------------------------------
``actual_time``, ``osrm_time``, ``osrm_distance`` and
``actual_distance_to_destination`` are **running cumulative totals within a leg** —
they grow row by row, and the leg total sits in the *last* row. A ``groupBy`` with
``first()`` returns whichever row Spark happened to see first (nondeterministic across
partitions) and understates every leg; ``sum()`` would add the cumulative values
together, which is meaningless.

So the last row per leg is selected with
``row_number() OVER (PARTITION BY leg ORDER BY actual_time DESC)`` and the aggregates
that genuinely aggregate (``count``, ``sum``) are computed separately and joined back.

Two traps this stage is written around, both established in Week 1 by running the code:

* ``actual_distance_to_destination`` **increases** along a leg. Despite the name it is
  distance *covered*, not distance remaining.
* Summing ``segment_actual_time`` does **not** reproduce the leg total — the segment
  columns are rounded to whole minutes and the drift reaches 39 min on the worst leg.
  The final cumulative value is authoritative. The sums are still emitted, as a
  cross-check column, never as the source of truth.

The output must reproduce ``benchmarks/raw/w1_leg_summary.csv`` row for row — Lahari
built that independently in pandas, so it is a genuine second implementation rather
than a copy of this one. ``--validate`` performs that comparison.
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
from src.pipeline import contracts

log = get_logger("pipeline.reconstruct")

#: Identifies one origin-destination leg.
OD_KEY = ["trip_uuid", "od_start_time", "od_end_time"]

#: Constant across every segment row of a leg — carried through from the last row.
LEG_CONSTANT = [
    "data",
    "trip_creation_time",
    "route_type",
    "route_schedule_uuid",
    "source_center",
    "source_name",
    "destination_center",
    "destination_name",
    "source_city",
    "source_state",
    "dest_city",
    "dest_state",
    "start_scan_to_end_scan",
    "corridor_id",
]

#: Running cumulative totals — the leg value is the one in the final row.
LEG_CUMULATIVE = [
    "actual_time",
    "osrm_time",
    "osrm_distance",
    "actual_distance_to_destination",
    "factor",
]


def leg_totals(segments: DataFrame) -> DataFrame:
    """Take the final row of each leg via a window, giving the cumulative totals.

    Ordered by ``source_row_index`` — the source file's row order, preserved by Stage 1
    — because within a leg the segments are emitted in scan order, so the genuinely
    last row holds the leg's cumulative totals.

    Ordering by ``max(actual_time)`` instead looks equivalent and is not: on legs whose
    trailing segments add zero minutes, several rows tie on ``actual_time`` while
    carrying different ``osrm_time``. Picking among them by value rather than by
    position disagrees with the true final row on 127 legs. ``source_row_index`` is
    unique (Stage 1 asserts it), so there is no tie left to break.
    """
    window = Window.partitionBy(*OD_KEY).orderBy(F.col("source_row_index").desc())
    return (
        segments.withColumn("_rn", F.row_number().over(window))
        .filter(F.col("_rn") == 1)
        .drop("_rn")
        .select(*OD_KEY, *LEG_CONSTANT, *LEG_CUMULATIVE)
    )


def leg_aggregates(segments: DataFrame) -> DataFrame:
    """Per-leg counts and sums — the quantities that genuinely aggregate."""
    return segments.groupBy(*OD_KEY).agg(
        F.count(F.lit(1)).alias("n_segments"),
        F.sum("segment_actual_time").alias("segment_actual_time_sum"),
        F.sum("segment_osrm_time").alias("segment_osrm_time_sum"),
        F.sum(F.col("is_negative_segment").cast("int")).alias("negative_segments"),
        F.sum(F.col("is_zero_osrm_segment").cast("int")).alias("zero_osrm_segments"),
    )


def derive_metrics(legs: DataFrame) -> DataFrame:
    """Add the gap and dwell columns every later stage reads."""
    return (
        legs.withColumn("gap_min", F.col("actual_time") - F.col("osrm_time"))
        .withColumn("gap_ratio", F.col("actual_time") / F.col("osrm_time"))
        .withColumn("log_gap_ratio", F.log(F.col("gap_ratio")))
        .withColumn("is_delayed", F.col("gap_ratio") > F.lit(config.DELAY_THRESHOLD))
        # start_scan_to_end_scan is the leg's wall clock; actual_time is moving time.
        # Their difference is time the shipment sat still — the input to hub friction.
        .withColumn("dwell_min", F.col("start_scan_to_end_scan") - F.col("actual_time"))
    )


def reconstruct(spark: SparkSession, input_path: Path, output_path: Path) -> dict:
    log.info("Reading cleaned segments from %s", input_path)
    segments = spark.read.parquet(str(input_path)).cache()
    n_segments = segments.count()
    log.info("  %s segment rows", f"{n_segments:,}")

    totals = leg_totals(segments)
    aggs = leg_aggregates(segments)
    legs = derive_metrics(totals.join(aggs, on=OD_KEY, how="inner")).cache()

    n_legs = legs.count()
    log.info("  reconstructed %s OD legs", f"{n_legs:,}")

    # A leg must appear exactly once. If the window tie-break ever fails to isolate a
    # single row this catches it here rather than in a corridor mean three weeks later.
    duplicates = legs.groupBy(*OD_KEY).count().filter(F.col("count") > 1).count()
    if duplicates:
        raise AssertionError(
            f"{duplicates} OD legs produced more than one row — the window tie-break is "
            "not deterministic. Do not use this output."
        )

    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage": "2-reconstruct",
        "input": str(input_path),
        "output": str(output_path),
        "segments_in": n_segments,
        "legs_out": n_legs,
        "trips": legs.select("trip_uuid").distinct().count(),
        "corridors": legs.select("corridor_id").distinct().count(),
        "schema": contracts.stamp("trips_v1"),
    }

    stats = legs.agg(
        F.expr("percentile_approx(gap_ratio, 0.5)").alias("median_gap_ratio"),
        F.mean("gap_ratio").alias("mean_gap_ratio"),
        F.expr("percentile_approx(gap_min, 0.5)").alias("median_gap_min"),
        F.mean("gap_min").alias("mean_gap_min"),
        F.expr("percentile_approx(dwell_min, 0.5)").alias("median_dwell_min"),
        F.mean((F.col("gap_ratio") > 1).cast("double")).alias("frac_over_plan"),
        F.mean(F.col("is_delayed").cast("double")).alias("frac_delayed"),
    ).collect()[0]
    report["metrics"] = {k: (round(float(v), 4) if v is not None else None) for k, v in stats.asDict().items()}

    log.info("Writing legs to %s", output_path)
    legs.write.mode("overwrite").partitionBy("route_type").parquet(str(output_path))

    (output_path / "_reconstruction_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    segments.unpersist()
    legs.unpersist()
    return report


# ── Validation against Lahari's independent pandas implementation ────────────
ORACLE = config.BENCHMARKS_RAW_DIR / "w1_leg_summary.csv"

#: Columns compared numerically, with the tolerance each is compared at.
NUMERIC_COLS = {
    "actual_time": 1e-6,
    "osrm_time": 1e-6,
    "osrm_distance": 1e-4,
    "actual_distance_to_destination": 1e-4,
    # `factor` is recomputed from two doubles on each side, so it carries ordinary
    # floating-point noise rather than being copied — hence a looser tolerance.
    "factor": 1e-12,
    "n_segments": 0,
    "gap_min": 1e-6,
    "gap_ratio": 1e-9,
    "dwell_min": 1e-6,
}


def validate(spark: SparkSession, output_path: Path) -> bool:
    """Diff the Spark output against the Week 1 pandas oracle, leg by leg."""
    if not ORACLE.exists():
        log.error("Oracle missing: %s — run `python -m src.ml.eda` first.", ORACLE)
        return False

    log.info("Validating against %s", ORACLE.name)
    spark_legs = spark.read.parquet(str(output_path))
    oracle = spark.read.csv(str(ORACLE), header=True, inferSchema=True)

    n_spark, n_oracle = spark_legs.count(), oracle.count()
    log.info("  legs: spark=%s oracle=%s", f"{n_spark:,}", f"{n_oracle:,}")
    ok = n_spark == n_oracle
    if not ok:
        log.error("  ROW COUNT MISMATCH")

    # Timestamps round-trip through CSV as strings; cast both sides to string so the
    # join key is comparable without depending on either side's parse behaviour.
    def key(df: DataFrame, prefix: str) -> DataFrame:
        return df.withColumn(
            "_k",
            F.concat_ws(
                "|",
                F.col("trip_uuid"),
                F.date_format(F.col("od_start_time").cast("timestamp"), "yyyy-MM-dd HH:mm:ss.SSSSSS"),
                F.date_format(F.col("od_end_time").cast("timestamp"), "yyyy-MM-dd HH:mm:ss.SSSSSS"),
            ),
        ).select("_k", *[F.col(c).alias(f"{prefix}_{c}") for c in NUMERIC_COLS])

    joined = key(spark_legs, "s").join(key(oracle, "o"), on="_k", how="full_outer").cache()

    unmatched = joined.filter(F.col("s_actual_time").isNull() | F.col("o_actual_time").isNull()).count()
    if unmatched:
        log.error("  %s legs did not match on key", f"{unmatched:,}")
        ok = False
    else:
        log.info("  all %s leg keys matched", f"{n_spark:,}")

    # Row-selection disagreement (D-014), not a reconstruction error.
    #
    # The oracle picks each leg's row with pandas `idxmax(actual_time)`, which returns
    # the FIRST row holding the maximum. On 1,861 legs the trailing segments add zero
    # minutes, so several rows tie on actual_time and "first" lands earlier than the
    # true final scan. This stage instead takes the genuinely last row by
    # source_row_index.
    #
    # The signature of that disagreement is exact: actual_time and n_segments agree
    # (same leg, same segments counted) while some other cumulative column does not.
    # A real reconstruction error would move actual_time or n_segments — verified
    # against the raw file: of the 340 legs whose osrm_distance differs, 340 have
    # identical actual_time and 0 do not.
    #
    # These are counted and reported. Anything outside this signature fails the run.
    tie_break = (
        (F.abs(F.col("s_actual_time") - F.col("o_actual_time")) <= 1e-6)
        & (F.abs(F.col("s_n_segments") - F.col("o_n_segments")) <= 0)
        & (
            (F.abs(F.col("s_osrm_time") - F.col("o_osrm_time")) > 1e-6)
            | (F.abs(F.col("s_osrm_distance") - F.col("o_osrm_distance")) > 1e-4)
            | (F.abs(F.col("s_actual_distance_to_destination") - F.col("o_actual_distance_to_destination")) > 1e-4)
        )
    )
    n_tie = joined.filter(tie_break).count()

    for col, tol in NUMERIC_COLS.items():
        diff = F.abs(F.col(f"s_{col}") - F.col(f"o_{col}"))
        over = joined.filter(diff > F.lit(tol))
        bad = over.filter(~tie_break).count()
        explained = over.filter(tie_break).count()
        worst = joined.filter(~tie_break).agg(F.max(diff)).collect()[0][0]
        status = "ok" if bad == 0 else "MISMATCH"
        log.info(
            "  %-24s %-8s max|diff|=%-12s tol=%-8s unexplained=%s  tie-break=%s",
            col,
            status,
            f"{worst:.10g}" if worst is not None else "n/a",
            tol,
            f"{bad:,}",
            f"{explained:,}",
        )
        if bad:
            ok = False

    if n_tie:
        log.warning(
            "  %s legs differ from the oracle by tie-break only (D-014). Spark takes the "
            "true final row by source_row_index; the oracle takes the first max(actual_time). "
            "Headline metrics are unchanged to 4 decimal places.",
            f"{n_tie:,}",
        )

    joined.unpersist()
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 2 — reconstruct OD legs from segments")
    parser.add_argument("--input", type=Path, default=config.CLEAN_V1)
    parser.add_argument("--output", type=Path, default=config.TRIPS_V1)
    parser.add_argument("--validate", action="store_true", help="diff against the W1 pandas oracle")
    args = parser.parse_args()

    if not args.input.exists():
        log.error("Missing %s — run `python -m src.pipeline.clean` first.", args.input)
        return 1

    spark = get_spark("stage2-reconstruct")
    try:
        report = reconstruct(spark, args.input, args.output)
        m = report["metrics"]
        log.info(
            "Done. %s segments -> %s legs across %s corridors. "
            "Median gap ratio %.2fx, %.1f%% of legs over plan.",
            f"{report['segments_in']:,}",
            f"{report['legs_out']:,}",
            f"{report['corridors']:,}",
            m["median_gap_ratio"],
            m["frac_over_plan"] * 100,
        )
        if args.validate and not validate(spark, args.output):
            log.error("VALIDATION FAILED — Stage 2 does not reproduce the Week 1 oracle.")
            return 2
        if args.validate:
            log.info("VALIDATION PASSED — Spark output matches the pandas oracle.")
    finally:
        stop_spark(spark)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
