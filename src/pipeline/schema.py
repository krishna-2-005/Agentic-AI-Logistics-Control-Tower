"""Pinned schema for the raw Delhivery CSV.

Reading with an explicit schema instead of ``inferSchema=True`` matters for three
reasons: it is one pass over the file instead of two, it fails loudly if a mirror
ships a different column set, and it stops Spark from guessing a type differently
on a filtered subset than on the full file.

Everything numeric is read as double and everything temporal as string; casting
happens in ``clean.py`` where a failed cast can be counted and reported rather than
silently nulled at read time.
"""

from __future__ import annotations

from pyspark.sql.types import DoubleType, StringType, StructField, StructType

RAW_SCHEMA = StructType(
    [
        StructField("data", StringType(), True),  # training / test split marker
        StructField("trip_creation_time", StringType(), True),
        StructField("route_schedule_uuid", StringType(), True),
        StructField("route_type", StringType(), True),  # FTL / Carting
        StructField("trip_uuid", StringType(), True),
        StructField("source_center", StringType(), True),
        StructField("source_name", StringType(), True),
        StructField("destination_center", StringType(), True),
        StructField("destination_name", StringType(), True),
        StructField("od_start_time", StringType(), True),
        StructField("od_end_time", StringType(), True),
        StructField("start_scan_to_end_scan", DoubleType(), True),
        StructField("is_cutoff", StringType(), True),  # "True"/"False" text
        StructField("cutoff_factor", DoubleType(), True),
        StructField("cutoff_timestamp", StringType(), True),
        StructField("actual_distance_to_destination", DoubleType(), True),
        StructField("actual_time", DoubleType(), True),
        StructField("osrm_time", DoubleType(), True),
        StructField("osrm_distance", DoubleType(), True),
        StructField("factor", DoubleType(), True),
        StructField("segment_actual_time", DoubleType(), True),
        StructField("segment_osrm_time", DoubleType(), True),
        StructField("segment_osrm_distance", DoubleType(), True),
        StructField("segment_factor", DoubleType(), True),
    ]
)

RAW_COLUMNS = [f.name for f in RAW_SCHEMA.fields]

# All four timestamp columns, parsed with ONE format.
#
# The sub-second part is optional — `[.SSSSSS]` — and that is not defensive
# programming, it is the data. `trip_creation_time`, `od_start_time` and
# `od_end_time` always carry microseconds ("2018-09-20 02:35:36.476840"), but
# `cutoff_timestamp` is mixed: 141,438 rows are second-precision
# ("2018-09-20 04:27:55") and 3,429 rows (2.37%) carry microseconds. Parsing that
# column with a second-precision format throws on those 3,429 rows under Spark 4's
# ANSI mode, which is exactly how this was found.
#
# The format stays explicit rather than letting Spark infer, so a genuinely new
# shape still fails loudly instead of silently becoming null.
TIMESTAMP_COLUMNS = [
    "trip_creation_time",
    "od_start_time",
    "od_end_time",
    "cutoff_timestamp",
]
TIMESTAMP_FORMAT = "yyyy-MM-dd HH:mm:ss[.SSSSSS]"

# Trip-level columns: constant across every segment row of one OD leg. Stage 2
# collapses on these; listed here so Stage 2 does not re-derive the list.
OD_KEY = ["trip_uuid", "od_start_time", "od_end_time"]

TRIP_LEVEL_COLUMNS = [
    "data",
    "trip_creation_time",
    "route_schedule_uuid",
    "route_type",
    "trip_uuid",
    "source_center",
    "source_name",
    "destination_center",
    "destination_name",
    "od_start_time",
    "od_end_time",
    "start_scan_to_end_scan",
    "actual_distance_to_destination",
    "actual_time",
    "osrm_time",
    "osrm_distance",
    "factor",
]

# Segment-level columns: vary row to row within one OD leg.
SEGMENT_LEVEL_COLUMNS = [
    "is_cutoff",
    "cutoff_factor",
    "cutoff_timestamp",
    "segment_actual_time",
    "segment_osrm_time",
    "segment_osrm_distance",
    "segment_factor",
]
