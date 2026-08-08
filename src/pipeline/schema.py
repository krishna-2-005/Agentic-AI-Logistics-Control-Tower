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

# Timestamp columns and their format in the raw file: "2018-09-20 02:35:36.476840"
TIMESTAMP_COLUMNS = ["trip_creation_time", "od_start_time", "od_end_time"]
TIMESTAMP_FORMAT = "yyyy-MM-dd HH:mm:ss.SSSSSS"

# cutoff_timestamp carries no sub-second component: "2018-09-20 04:27:55"
CUTOFF_TIMESTAMP_COLUMN = "cutoff_timestamp"
CUTOFF_TIMESTAMP_FORMAT = "yyyy-MM-dd HH:mm:ss"

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
