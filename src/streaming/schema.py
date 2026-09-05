"""Stream event schema (execution plan W4 D5) -- validation and real example events.

    python -m src.streaming.schema                  # validate the schema itself
    python -m src.streaming.schema --examples 5      # write real sample events

Defines nothing new: `docs/schemas/stream_event.schema.json`'s query/fact split, field
names, and ordering rule all reuse D-020's `as_of_history` design
(`src/pipeline/features.py`) rather than inventing a second event shape for the same
idea. This module's only job is to turn that design into JSON events a Week 5 Kafka
producer can actually emit, and to prove real rows from the frozen `features_v1`
cache validate against the schema before a producer is built against it.

`--examples` writes to `demo/sample_events/` -- a directory GIT_RULES §3 already
reserves for exactly this ("small JSON event samples for the replay") but that no
prior week had populated.
"""

from __future__ import annotations

import argparse
import json
from datetime import timedelta

import jsonschema
import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark

log = get_logger("streaming.schema")

SCHEMA_PATH = config.REPO_ROOT / "docs" / "schemas" / "stream_event.schema.json"
SAMPLE_EVENTS_DIR = config.DEMO_DIR / "sample_events"

#: The columns `--examples` needs from `features_v1` -- everything the schema's two
#: event kinds carry except `od_end_time`, which is not a features_v1 column and is
#: instead derived below from `leg_id` (carries od_start_time) and `gap_min`
#: (`actual_time = gap_min + planned_min`, `src.ml.baselines`'s own TARGET
#: definition) -- exact, not an approximation, since od_start_time plus the leg's
#: actual elapsed minutes is what od_end_time already means (Stage 2, D-002).
EXAMPLE_COLUMNS = [
    "leg_id", "trip_uuid", "corridor_id", "source_center", "destination_center",
    "trip_creation_time", "route_type", "planned_min", "planned_km",
    "created_hour", "created_dayofweek", "created_is_weekend",
    "gap_min", "log_gap_ratio", "is_delayed",
]


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_event(event: dict, schema: dict) -> None:
    jsonschema.validate(instance=event, schema=schema)


def _od_start_time(leg_id: str) -> pd.Timestamp:
    """`leg_id` is `trip_uuid|od_start_time (yyyyMMddHHmmss)|corridor_id` (D-020)."""
    _, ts, _ = leg_id.split("|")
    return pd.to_datetime(ts, format="%Y%m%d%H%M%S")


def query_event(row: pd.Series) -> dict:
    return {
        "event_id": f"query-{row['leg_id']}",
        "kind": "query",
        "event_time": pd.Timestamp(row["trip_creation_time"]).isoformat(),
        "corridor_id": row["corridor_id"],
        "source_center": row["source_center"],
        "destination_center": row["destination_center"],
        "trip_uuid": row["trip_uuid"],
        "leg_id": row["leg_id"],
        "route_type": row["route_type"],
        "planned_min": float(row["planned_min"]),
        "planned_km": float(row["planned_km"]),
        "created_hour": int(row["created_hour"]),
        "created_dayofweek": int(row["created_dayofweek"]),
        "created_is_weekend": int(row["created_is_weekend"]),
    }


def fact_event(row: pd.Series) -> dict:
    actual_time = row["gap_min"] + row["planned_min"]
    od_end_time = _od_start_time(row["leg_id"]) + timedelta(minutes=float(actual_time))
    return {
        "event_id": f"fact-{row['leg_id']}",
        "kind": "fact",
        "event_time": od_end_time.isoformat(),
        "corridor_id": row["corridor_id"],
        "source_center": row["source_center"],
        "destination_center": row["destination_center"],
        "trip_uuid": row["trip_uuid"],
        "leg_id": row["leg_id"],
        "gap_min": float(row["gap_min"]),
        "log_gap_ratio": float(row["log_gap_ratio"]),
        "is_delayed": int(row["is_delayed"]),
    }


def generate_examples(n: int) -> list[dict]:
    """Real query/fact events from `features_v1` -- 2n events for n legs, sorted by
    `event_time` the way a replay would actually emit them (a fact can sort before or
    after another leg's query; only a leg's own fact sorts after its own query).
    """
    schema = load_schema()
    spark = get_spark("stream-schema-examples")
    try:
        sdf = spark.read.parquet(str(config.FEATURES_V1)).select(*EXAMPLE_COLUMNS).limit(n)
        pdf = sdf.toPandas()
    finally:
        stop_spark(spark)

    events = []
    for _, row in pdf.iterrows():
        for event in (query_event(row), fact_event(row)):
            validate_event(event, schema)
            events.append(event)
    events.sort(key=lambda e: e["event_time"])
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--examples", type=int, nargs="?", const=5, default=None, help="write N legs' worth of real query+fact events")
    args = parser.parse_args()

    schema = load_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    log.info("%s is a valid JSON Schema (draft 2020-12)", SCHEMA_PATH.name)

    if args.examples:
        if not config.FEATURES_V1.exists():
            log.error("Missing %s -- run `python -m src.pipeline.features` first.", config.FEATURES_V1)
            return 1
        events = generate_examples(args.examples)
        SAMPLE_EVENTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = SAMPLE_EVENTS_DIR / "trip_replay_sample.json"
        out_path.write_text(json.dumps(events, indent=2), encoding="utf-8")
        log.info(
            "%d events (%d legs) validated against the schema -> %s",
            len(events), args.examples, out_path,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
