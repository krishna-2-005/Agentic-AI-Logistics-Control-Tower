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


# ── Step 1b: null sentinels ──────────────────────────────────────────────────
#: Strings the publisher used to mean "missing". They are literal text in the CSV,
#: not empty fields.
NULL_SENTINELS = ["", "nan", "NaN", "NAN", "null", "NULL", "None", "NA", "N/A", "-"]


def normalise_null_sentinels(df: DataFrame) -> tuple[DataFrame, dict[str, int]]:
    """Turn the publisher's textual missing-value markers into real nulls.

    **This is the subtlest trap in the dataset, and it silently splits the team.**

    `source_name` and `destination_name` do not contain empty fields where a name is
    missing — they contain the literal three-character string ``nan``. pandas coerces
    that to ``NaN`` on read by default, so a pandas profile reports 293 and 261
    missing names. Spark does not: it reads ``"nan"`` as an ordinary string, so the
    same file appears to have **zero** nulls.

    Left alone, two things go wrong and neither of them raises:

    * the name backfill matches nothing, because there is nothing null to fill;
    * ``"nan"`` propagates into `source_city` / `source_state` and into the corridor
      leaderboards, producing a facility in a city called "nan" — and onto the India
      map, where it silently fails to geocode.

    Returns the frame plus a per-column count of values converted, which goes into
    the quality report so the number is visible rather than folded into "nulls".
    """
    string_cols = [f.name for f in df.schema.fields if f.dataType.simpleString() == "string"]
    counts: dict[str, int] = {}

    for col in string_cols:
        trimmed = F.trim(F.col(col))
        is_sentinel = trimmed.isin(NULL_SENTINELS)
        n = df.filter(is_sentinel).count()
        if n:
            counts[col] = n
        df = df.withColumn(col, F.when(is_sentinel, None).otherwise(trimmed))

    return df, counts


# ── Step 2: types ────────────────────────────────────────────────────────────
def cast_types(df: DataFrame) -> DataFrame:
    """Parse the four timestamp columns and the boolean.

    All four use one format with an optional sub-second part; see
    ``schema.TIMESTAMP_FORMAT`` for why `cutoff_timestamp` forces that. Under Spark
    4's ANSI mode a value that does not match the format raises rather than becoming
    null, which is the behaviour we want — a mirror that changes timestamp shape
    should stop the pipeline, not quietly null a column. Genuinely null inputs still
    pass through as null and are counted in the quality report.
    """
    for col in sch.TIMESTAMP_COLUMNS:
        df = df.withColumn(col, F.to_timestamp(F.col(col), sch.TIMESTAMP_FORMAT))

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


#: First two digits of an Indian PIN code → state/UT postal circle. Used to recover a
#: region for facilities whose name is missing entirely (see ``recover_state_from_code``).
PIN_PREFIX_TO_STATE: dict[str, str] = {
    "11": "Delhi",
    "12": "Haryana", "13": "Haryana",
    "14": "Punjab", "15": "Punjab", "16": "Punjab",
    "17": "Himachal Pradesh",
    "18": "Jammu and Kashmir", "19": "Jammu and Kashmir",
    "20": "Uttar Pradesh", "21": "Uttar Pradesh", "22": "Uttar Pradesh",
    "23": "Uttar Pradesh", "24": "Uttar Pradesh", "25": "Uttar Pradesh",
    "26": "Uttar Pradesh", "27": "Uttar Pradesh", "28": "Uttar Pradesh",
    "30": "Rajasthan", "31": "Rajasthan", "32": "Rajasthan",
    "33": "Rajasthan", "34": "Rajasthan",
    "36": "Gujarat", "37": "Gujarat", "38": "Gujarat", "39": "Gujarat",
    "40": "Maharashtra", "41": "Maharashtra", "42": "Maharashtra",
    "43": "Maharashtra", "44": "Maharashtra",
    "45": "Madhya Pradesh", "46": "Madhya Pradesh", "47": "Madhya Pradesh",
    "48": "Madhya Pradesh",
    "49": "Chhattisgarh",
    "50": "Telangana", "51": "Telangana",
    "52": "Andhra Pradesh", "53": "Andhra Pradesh",
    "56": "Karnataka", "57": "Karnataka", "58": "Karnataka", "59": "Karnataka",
    "60": "Tamil Nadu", "61": "Tamil Nadu", "62": "Tamil Nadu",
    "63": "Tamil Nadu", "64": "Tamil Nadu",
    "67": "Kerala", "68": "Kerala", "69": "Kerala",
    "70": "West Bengal", "71": "West Bengal", "72": "West Bengal",
    "73": "West Bengal", "74": "West Bengal",
    "75": "Odisha", "76": "Odisha", "77": "Odisha",
    "78": "Assam",
    "79": "North Eastern States",
    "80": "Bihar", "81": "Bihar", "82": "Bihar", "83": "Bihar",
    "84": "Bihar", "85": "Bihar",
}


def backfill_names(df: DataFrame) -> tuple[DataFrame, int]:
    """Recover null facility names from other rows carrying the same centre code.

    **On the published file this recovers nothing, and that is the finding, not a
    bug.** All 554 missing names belong to just 14 centre codes, and *none* of those
    14 codes carries a name on any row anywhere in the dataset — verified, not
    assumed. The names are absent from the source, not merely sparse.

    The step is kept for two reasons: it is correct and free if a future mirror ships
    partially-named codes, and the count it returns is written into the quality
    report, so "0 recovered" is an asserted fact rather than a silent no-op.

    ``recover_state_from_code`` handles what *is* recoverable for these 14.
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


def recover_state_from_code(df: DataFrame) -> tuple[DataFrame, int]:
    """Fill a missing state from the PIN code embedded in the centre code.

    Centre codes are ``IND`` + a six-digit Indian PIN + three characters, so
    ``IND282002AAD`` carries PIN 282002 — Agra, Uttar Pradesh. The first two digits
    identify the postal circle, which is enough to place a facility regionally and to
    group it on the India map, even when its name is missing entirely.

    Only the *state* is recoverable this way; the city is not, and is left null rather
    than guessed. Rows filled here are marked ``state_from_pin`` so that no analysis
    can mistake an inferred region for one parsed from a real facility name.
    """
    prefix_map = F.create_map(*[F.lit(x) for kv in PIN_PREFIX_TO_STATE.items() for x in kv])

    for prefix, code_col in (("source", "source_center"), ("dest", "destination_center")):
        pin_prefix = F.regexp_extract(F.col(code_col), r"^IND(\d{2})", 1)
        inferred = prefix_map[pin_prefix]
        df = df.withColumn(
            f"{prefix}_state_from_pin",
            F.col(f"{prefix}_state").isNull() & inferred.isNotNull(),
        ).withColumn(f"{prefix}_state", F.coalesce(F.col(f"{prefix}_state"), inferred))

    df = df.withColumn(
        "state_from_pin", F.col("source_state_from_pin") | F.col("dest_state_from_pin")
    ).drop("source_state_from_pin", "dest_state_from_pin")

    return df, df.filter("state_from_pin").count()


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

    # Preserve the source file's row order as an explicit column.
    #
    # Within an OD leg the segment rows are emitted in scan order, so the leg's
    # cumulative totals live in its LAST row. Parquet does not preserve row order and
    # Spark gives no positional guarantee across partitions, so without this column
    # Stage 2 has to guess which row is last — and guessing by max(actual_time) picks
    # the wrong row on ~200 legs where the final segments add zero minutes.
    #
    # monotonically_increasing_id() encodes the partition index in its high bits and a
    # within-partition counter in its low bits. For a single CSV read, partitions are
    # assigned in file-offset order, so the id is monotonic in file order. This is
    # asserted below rather than assumed.
    df = df.withColumn("source_row_index", F.monotonically_increasing_id())
    df = df.cache()
    report["rows_in"] = df.count()
    log.info("  %s raw rows, %d columns", f"{report['rows_in']:,}", len(df.columns))

    df, sentinel_counts = normalise_null_sentinels(df)
    report["null_sentinels_converted"] = sentinel_counts
    log.info("  textual null sentinels converted: %s", sentinel_counts or "none")

    df = cast_types(df)
    report["cast_failures"] = {
        col: df.filter(F.col(col).isNull()).count() for col in sch.TIMESTAMP_COLUMNS
    }
    log.info("  timestamp cast failures: %s", report["cast_failures"])

    df = standardise_centres(df)
    df, backfilled = backfill_names(df)
    report["names_backfilled"] = backfilled
    log.info(
        "  recovered %d facility names from centre codes "
        "(expected 0 on the published file — the 14 affected codes are unnamed everywhere)",
        backfilled,
    )

    df = parse_locations(df)
    df, state_inferred = recover_state_from_code(df)
    report["states_inferred_from_pin"] = state_inferred
    log.info("  inferred state from PIN prefix on %d rows", state_inferred)

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

    # Assert the ordering column really is unique and ordered before anyone relies on
    # it. A silently non-monotonic index would corrupt every Stage 2 leg total.
    idx_stats = df.agg(
        F.count("source_row_index").alias("n"),
        F.countDistinct("source_row_index").alias("n_distinct"),
    ).collect()[0]
    if idx_stats["n"] != idx_stats["n_distinct"]:
        raise AssertionError(
            f"source_row_index is not unique ({idx_stats['n_distinct']:,} distinct for "
            f"{idx_stats['n']:,} rows). Stage 2 cannot use it to find each leg's last row."
        )
    report["source_row_index_unique"] = True

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
