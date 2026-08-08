"""Stage 1 — ingestion and cleaning (PySpark).

    python -m src.pipeline.clean
    python -m src.pipeline.clean --input data/raw/delhivery_data.csv --output data/processed/clean_v1

Reads the immutable raw CSV, produces a typed and standardised Parquet cache plus a
``_quality_report.json`` that accounts for every row and every repair.

Design rules this stage follows:

* **Raw is never modified.** This is the only script that reads ``data/raw/``.
* **Nothing is dropped silently.** A row is either kept, or dropped with a named
  reason that appears in the quality report with a count.
* **Suspect rows are flagged, not deleted.** Negative segment times and zero-valued
  OSRM segments are real artefacts of the source system. Deleting them would quietly
  bias the corridor audit, so they are marked with boolean quality flags and left in
  place; downstream stages filter on the flag and say so in writing.

Columns added by this stage
---------------------------
``corridor_id``          ``SOURCE>DEST`` centre-code pair — the key for Stage 3's audit
``source_state``         state parsed out of the facility name, e.g. "Gujarat"
``source_city``          city parsed out of the facility name, e.g. "Anand"
``dest_state`` / ``dest_city``   same for the destination
``od_duration_min``      wall-clock minutes between od_start_time and od_end_time
``is_negative_segment``  segment_actual_time <= 0 — clock skew in the source scans
``is_zero_osrm_segment`` segment_osrm_time == 0 — routing engine returned nothing
``is_suspect``           either of the above; the flag downstream stages filter on
``name_backfilled``      the facility name was null and was recovered from its code
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
from src.pipeline import schema as sch

log = get_logger("pipeline.clean")


# ── Step 1: load ─────────────────────────────────────────────────────────────
def load_raw(spark: SparkSession, path: Path) -> DataFrame:
    """Read the raw CSV with the pinned schema and verify its column set."""
    df = spark.read.csv(
        str(path),
        schema=sch.RAW_SCHEMA,
        header=True,
        mode="PERMISSIVE",
        nullValue="",
    )
    if df.columns != sch.RAW_COLUMNS:
        missing = set(sch.RAW_COLUMNS) - set(df.columns)
        extra = set(df.columns) - set(sch.RAW_COLUMNS)
        raise ValueError(
            f"Raw CSV column set does not match the pinned schema. "
            f"Missing: {sorted(missing)}. Unexpected: {sorted(extra)}. "
            f"You may have a different mirror — check the SHA-256 in data/README.md."
        )
    return df


# ── Step 2: types ────────────────────────────────────────────────────────────
def cast_types(df: DataFrame) -> DataFrame:
    """Parse timestamps and the boolean, leaving unparseable values as null.

    Cast failures are counted in the quality report rather than being allowed to
    disappear — a timestamp format change in a future mirror should be loud.
    """
    for col in sch.TIMESTAMP_COLUMNS:
        df = df.withColumn(col, F.to_timestamp(F.col(col), sch.TIMESTAMP_FORMAT))

    df = df.withColumn(
        sch.CUTOFF_TIMESTAMP_COLUMN,
        F.to_timestamp(F.col(sch.CUTOFF_TIMESTAMP_COLUMN), sch.CUTOFF_TIMESTAMP_FORMAT),
    )

    df = df.withColumn("is_cutoff", F.lower(F.trim(F.col("is_cutoff"))) == F.lit("true"))
    df = df.withColumn("route_type", F.trim(F.col("route_type")))
    df = df.withColumn("data", F.lower(F.trim(F.col("data"))))
    return df


# ── Step 3: centre codes ─────────────────────────────────────────────────────
def standardise_centres(df: DataFrame) -> DataFrame:
    """Upper-case and trim centre codes, then build the corridor key.

    Centre codes look like ``IND388121AAA``. They are the join key for the whole
    project, so any whitespace or case drift here silently splits one corridor into
    two in the Stage 3 audit.
    """
    for col in ("source_center", "destination_center"):
        df = df.withColumn(col, F.upper(F.trim(F.col(col))))

    return df.withColumn(
        "corridor_id", F.concat_ws(">", F.col("source_center"), F.col("destination_center"))
    )


def backfill_names(df: DataFrame) -> tuple[DataFrame, int]:
    """Recover the 554 null facility names from their centre codes.

    A facility name is missing on some rows but present on others for the same
    centre code, so the mapping is recoverable from the dataset itself — no external
    lookup needed. Names that appear under one code with more than one spelling
    resolve to the most frequent spelling.
    """
    sources = df.select(
        F.col("source_center").alias("centre"), F.col("source_name").alias("name")
    )
    dests = df.select(
        F.col("destination_center").alias("centre"), F.col("destination_name").alias("name")
    )

    lookup = (
        sources.union(dests)
        .filter(F.col("centre").isNotNull() & F.col("name").isNotNull())
        .groupBy("centre", "name")
        .count()
        # ties broken by name so the map is deterministic across runs
        .withColumn(
            "rank",
            F.row_number().over(
                Window.partitionBy("centre").orderBy(
                    F.col("count").desc(), F.col("name").asc()
                )
            ),
        )
        .filter(F.col("rank") == 1)
        .select("centre", "name")
    )

    before_null = df.filter(
        F.col("source_name").isNull() | F.col("destination_name").isNull()
    ).count()

    df = (
        df.join(lookup.withColumnRenamed("name", "_src_name"), df.source_center == lookup.centre, "left")
        .drop("centre")
        .withColumn("name_backfilled_src", F.col("source_name").isNull() & F.col("_src_name").isNotNull())
        .withColumn("source_name", F.coalesce(F.col("source_name"), F.col("_src_name")))
        .drop("_src_name")
    )

    lookup2 = lookup.withColumnRenamed("name", "_dst_name")
    df = (
        df.join(lookup2, df.destination_center == lookup2.centre, "left")
        .drop("centre")
        .withColumn(
            "name_backfilled_dst", F.col("destination_name").isNull() & F.col("_dst_name").isNotNull()
        )
        .withColumn("destination_name", F.coalesce(F.col("destination_name"), F.col("_dst_name")))
        .drop("_dst_name")
    )

    df = df.withColumn(
        "name_backfilled", F.col("name_backfilled_src") | F.col("name_backfilled_dst")
    ).drop("name_backfilled_src", "name_backfilled_dst")

    after_null = df.filter(
        F.col("source_name").isNull() | F.col("destination_name").isNull()
    ).count()

    return df, before_null - after_null


# ── Step 4: location parsing ─────────────────────────────────────────────────
def parse_locations(df: DataFrame) -> DataFrame:
    """Split ``Anand_VUNagar_DC (Gujarat)`` into city and state.

    The convention is ``City_Facility_Type (State)``. Rows that do not match keep a
    null city/state rather than a wrong guess — the India map (Week 2) plots only
    what parsed cleanly.
    """
    for prefix, name_col in (("source", "source_name"), ("dest", "destination_name")):
        df = (
            df.withColumn(
                f"{prefix}_state",
                F.regexp_extract(F.col(name_col), r"\(([^)]+)\)\s*$", 1),
            )
            .withColumn(
                f"{prefix}_state",
                F.when(F.col(f"{prefix}_state") == "", None).otherwise(
                    F.trim(F.col(f"{prefix}_state"))
                ),
            )
            .withColumn(
                f"{prefix}_city",
                F.regexp_extract(F.col(name_col), r"^([^_]+)_", 1),
            )
            .withColumn(
                f"{prefix}_city",
                F.when(F.col(f"{prefix}_city") == "", None).otherwise(
                    F.trim(F.col(f"{prefix}_city"))
                ),
            )
        )
    return df


# ── Step 5: quality flags ────────────────────────────────────────────────────
def add_quality_flags(df: DataFrame) -> DataFrame:
    """Mark the source system's artefacts. Flag, never delete — see module docstring."""
    df = (
        df.withColumn("is_negative_segment", F.col("segment_actual_time") <= 0)
        .withColumn("is_zero_osrm_segment", F.col("segment_osrm_time") == 0)
        .withColumn(
            "is_suspect", F.col("is_negative_segment") | F.col("is_zero_osrm_segment")
        )
    )

    # Recompute segment_factor. The raw column is NOT a ratio everywhere: on the
    # 2,347 rows where segment_osrm_time == 0 the publisher wrote the sentinel -1.0.
    # A sentinel that looks like a number is worse than an infinity — it survives
    # every mean, join, and model fit without complaint — so it becomes null here.
    df = df.withColumn(
        "segment_factor",
        F.when(F.col("segment_osrm_time") > 0, F.col("segment_actual_time") / F.col("segment_osrm_time")),
    )

    df = df.withColumn(
        "od_duration_min",
        (F.col("od_end_time").cast("long") - F.col("od_start_time").cast("long")) / 60.0,
    )
    return df


# ── Step 6: drops ────────────────────────────────────────────────────────────
DROP_RULES: list[tuple[str, str]] = [
    ("null_trip_uuid", "trip_uuid IS NULL"),
    ("null_centre_code", "source_center IS NULL OR destination_center IS NULL"),
    ("unparseable_od_window", "od_start_time IS NULL OR od_end_time IS NULL"),
    ("inverted_od_window", "od_end_time < od_start_time"),
    ("nonpositive_osrm_time", "osrm_time IS NULL OR osrm_time <= 0"),
    ("nonpositive_actual_time", "actual_time IS NULL OR actual_time <= 0"),
]


def apply_drops(df: DataFrame) -> tuple[DataFrame, dict[str, int]]:
    """Drop unusable rows, counting each reason.

    Reasons are evaluated independently against the incoming frame, so a row failing
    two rules is counted under both — the counts diagnose data problems and are not
    meant to sum to the total dropped.
    """
    counts = {reason: df.filter(expr).count() for reason, expr in DROP_RULES}
    keep = " AND ".join(f"NOT ({expr})" for _, expr in DROP_RULES)
    return df.filter(keep), counts


def drop_exact_duplicates(df: DataFrame) -> tuple[DataFrame, int]:
    """Remove fully identical rows. The raw file has none; this guards re-downloads."""
    before = df.count()
    df = df.dropDuplicates()
    return df, before - df.count()


# ── Orchestration ────────────────────────────────────────────────────────────
def clean(spark: SparkSession, input_path: Path, output_path: Path) -> dict:
    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input": str(input_path),
        "output": str(output_path),
        "stage": "1-clean",
    }

    log.info("Reading %s", input_path)
    df = load_raw(spark, input_path)
    df = df.cache()
    report["rows_in"] = df.count()
    log.info("  %s raw rows, %d columns", f"{report['rows_in']:,}", len(df.columns))

    df = cast_types(df)
    report["cast_failures"] = {
        col: df.filter(F.col(col).isNull()).count()
        for col in sch.TIMESTAMP_COLUMNS + [sch.CUTOFF_TIMESTAMP_COLUMN]
    }
    log.info("  timestamp cast failures: %s", report["cast_failures"])

    df = standardise_centres(df)
    df, backfilled = backfill_names(df)
    report["names_backfilled"] = backfilled
    log.info("  backfilled %d null facility names from centre codes", backfilled)

    df = parse_locations(df)
    df = add_quality_flags(df)

    df, dup_dropped = drop_exact_duplicates(df)
    report["exact_duplicates_dropped"] = dup_dropped

    df, drop_counts = apply_drops(df)
    report["dropped_by_reason"] = drop_counts
    log.info("  drop reasons: %s", drop_counts)

    df = df.cache()
    report["rows_out"] = df.count()
    report["rows_dropped_total"] = report["rows_in"] - report["rows_out"]

    report["quality_flags"] = {
        "is_negative_segment": df.filter("is_negative_segment").count(),
        "is_zero_osrm_segment": df.filter("is_zero_osrm_segment").count(),
        "is_suspect": df.filter("is_suspect").count(),
    }
    report["distinct"] = {
        "trip_uuid": df.select("trip_uuid").distinct().count(),
        "od_legs": df.select(*sch.OD_KEY).distinct().count(),
        "corridor_id": df.select("corridor_id").distinct().count(),
        "source_center": df.select("source_center").distinct().count(),
        "destination_center": df.select("destination_center").distinct().count(),
    }
    bounds = df.agg(
        F.min("od_start_time").alias("min_od_start"),
        F.max("od_end_time").alias("max_od_end"),
    ).collect()[0]
    report["time_range"] = {
        "min_od_start": str(bounds["min_od_start"]),
        "max_od_end": str(bounds["max_od_end"]),
    }
    report["split_counts"] = {
        row["data"]: row["count"] for row in df.groupBy("data").count().collect()
    }
    report["route_type_counts"] = {
        row["route_type"]: row["count"] for row in df.groupBy("route_type").count().collect()
    }

    log.info("Writing Parquet to %s", output_path)
    (
        df.repartition("route_type")
        .write.mode("overwrite")
        .partitionBy("route_type")
        .parquet(str(output_path))
    )

    report["columns_out"] = sorted(df.columns)
    report_path = output_path / "_quality_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("Quality report → %s", report_path)

    df.unpersist()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 1 — clean the raw Delhivery CSV")
    parser.add_argument("--input", type=Path, default=config.RAW_CSV)
    parser.add_argument("--output", type=Path, default=config.CLEAN_V1)
    args = parser.parse_args()

    if not args.input.exists():
        log.error("Raw input not found: %s — see data/README.md", args.input)
        return 1

    spark = get_spark("stage1-clean")
    try:
        report = clean(spark, args.input, args.output)
    finally:
        stop_spark(spark)

    kept = report["rows_out"] / report["rows_in"] * 100
    log.info(
        "Done. %s -> %s rows (%.2f%% kept), %s corridors, %s OD legs.",
        f"{report['rows_in']:,}",
        f"{report['rows_out']:,}",
        kept,
        f"{report['distinct']['corridor_id']:,}",
        f"{report['distinct']['od_legs']:,}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
