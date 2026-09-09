"""Tests for the Structured Streaming scoring job and its throughput harness
(execution plan W5 D3-D4 and D5).

    pytest tests/test_stream_job.py -q

No SparkSession and no champion model: starting Spark costs ~25 seconds and the parts
worth pinning here are not the parts that need it. What is pinned is the arithmetic the
D5 numbers are computed from, the alert writer's idempotency, and -- the reason this
file matters most -- that the Spark event schema and the alert records stay in step
with the two JSON Schemas three people agreed on. A contract that lives in two files
drifts; a test is what stops it.
"""

from __future__ import annotations

import json

import jsonschema
import pytest

from src.ml.baselines import FEATURES
from src.streaming import job
from src.streaming import throughput as harness
from src.streaming.schema import SCHEMA_PATH as EVENT_SCHEMA_PATH

ALERT_SCHEMA_PATH = EVENT_SCHEMA_PATH.parent / "alert.schema.json"


def _stats(**overrides) -> job.JobStats:
    stats = job.JobStats(batches=2, events=100, queries=60, facts_dropped=40, alerts=12)
    stats.started_at, stats.finished_at = 0.0, 10.0
    stats.batch_seconds = [3.0, 2.0]
    for name, value in overrides.items():
        setattr(stats, name, value)
    return stats


# ── the numbers D5 reports ───────────────────────────────────────────────────
def test_events_per_second_is_over_wall_clock():
    assert _stats().events_per_second == pytest.approx(10.0)


def test_scoring_rate_is_over_time_actually_spent_scoring():
    # 100 events, 5 seconds inside process_batch, regardless of the 10s wall clock.
    # This is the capacity figure; events_per_second is the offered-load figure.
    assert _stats().scoring_rate_eps == pytest.approx(20.0)


def test_rates_are_zero_rather_than_dividing_by_zero():
    empty = job.JobStats()
    assert empty.events_per_second == 0.0
    assert empty.scoring_rate_eps == 0.0


def test_latency_percentile_is_a_value_that_was_actually_measured():
    stats = _stats(latencies_ms=[10.0, 20.0, 30.0, 40.0])
    for pct in (25, 50, 75, 95, 100):
        assert stats.latency_percentile(pct) in stats.latencies_ms


def test_latency_percentile_picks_the_nearest_rank():
    stats = _stats(latencies_ms=[10.0, 20.0, 30.0, 40.0])
    assert stats.latency_percentile(50) == 20.0
    assert stats.latency_percentile(100) == 40.0


def test_no_alerts_means_no_latency_rather_than_zero():
    # Zero would read as "instant", which is the opposite of "never measured".
    assert job.JobStats().latency_percentile(50) is None
    assert job.JobStats().summary()["latency_p50_ms"] is None


def test_summary_carries_the_stage_breakdown():
    stats = _stats(stage_seconds={"score": 13.2, "count": 0.4})
    assert stats.summary()["stage_seconds"] == {"count": 0.4, "score": 13.2}


# ── the alert sink ───────────────────────────────────────────────────────────
def test_writing_a_batch_leaves_no_temporary_file_behind(tmp_path):
    # Krishna's panel polls this directory; a half-written file it can see is a parse
    # error at his end that looks like a bug in his code.
    writer = job.AlertWriter(tmp_path)
    path = writer.write([{"alert_id": "a"}], batch_id=7)
    assert path.name == "alerts_000007.jsonl"
    assert list(tmp_path.glob(".*")) == []


def test_replaying_a_batch_overwrites_rather_than_appends(tmp_path):
    # foreachBatch is at-least-once: a batch re-run after a restart must not double the
    # alerts a consumer sees.
    writer = job.AlertWriter(tmp_path)
    writer.write([{"alert_id": "a"}, {"alert_id": "b"}], batch_id=3)
    writer.write([{"alert_id": "a"}, {"alert_id": "b"}], batch_id=3)
    lines = (tmp_path / "alerts_000003.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2


def test_an_empty_batch_writes_nothing(tmp_path):
    assert job.AlertWriter(tmp_path).write([], batch_id=0) is None
    assert list(tmp_path.iterdir()) == []


def test_epoch_milliseconds_round_trip_to_an_offset_aware_timestamp():
    iso = job._to_iso(1_600_000_000_000)
    assert iso is not None and ("+" in iso or "-" in iso[10:])
    assert job._to_iso(None) is None


# ── the contracts, which is why this file exists ─────────────────────────────
def test_the_spark_event_schema_matches_the_json_schema():
    # `EVENT_SCHEMA` is hand-written because a streaming file source cannot infer one.
    # Hand-written means it can drift from `stream_event.schema.json`, and a field that
    # drifts silently arrives as a column of nulls, not as an error.
    declared = set(json.loads(EVENT_SCHEMA_PATH.read_text(encoding="utf-8"))["properties"])
    assert {f.name for f in job.EVENT_SCHEMA.fields} == declared


def test_every_alert_column_is_in_the_alert_schema():
    schema = json.loads(ALERT_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert set(job.ALERT_COLUMNS) == set(schema["properties"])


def test_the_alert_schema_requires_nothing_the_job_does_not_emit():
    schema = json.loads(ALERT_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert set(schema["required"]) <= set(job.ALERT_COLUMNS)


def test_a_record_in_the_jobs_own_shape_validates_against_the_alert_schema():
    schema = json.loads(ALERT_SCHEMA_PATH.read_text(encoding="utf-8"))
    record = {
        "alert_id": "query-trip-1|20180912000016|INDA>INDB",
        "leg_id": "trip-1|20180912000016|INDA>INDB",
        "trip_uuid": "trip-1",
        "corridor_id": "IND462022AAA>IND209304AAA",
        "source_center": "IND462022AAA",
        "destination_center": "IND209304AAA",
        "event_time": "2018-09-12T00:00:16.535741",
        "route_type": "FTL",
        "planned_min": 388.0,
        "planned_km": 544.8,
        "predicted_gap_min": 511.5,
        "predicted_total_min": 899.5,
        "threshold_gap_min": 388.0,
        "delay_threshold": 2.0,
        "corr_is_cold": 0,
        "src_is_cold": 0,
        "dst_is_cold": 0,
        "emit_time": "2026-09-09T15:47:26.000000+05:30",
        "alert_time": "2026-09-09T15:47:27.382715+05:30",
        "latency_ms": 1382.7,
        "batch_id": 0,
    }
    assert set(record) == set(job.ALERT_COLUMNS)
    jsonschema.validate(instance=record, schema=schema)


def test_scoring_columns_hold_every_feature_exactly_once():
    # Selecting a name twice is not a duplicate column to Spark, it is an ambiguous
    # one, and it fails at `model.transform` with an error that names the column but
    # not the two lists that both claimed it.
    assert len(job.SCORING_COLUMNS) == len(set(job.SCORING_COLUMNS))
    assert set(FEATURES) <= set(job.SCORING_COLUMNS)


def test_the_model_never_sees_an_identifier():
    # `leg_id` and `event_time` identify the row being scored. In the feature vector
    # they would be leakage wearing an identifier's name.
    for column in ("leg_id", "event_id", "trip_uuid", "event_time", "corridor_id"):
        assert column not in FEATURES


# ── the harness ──────────────────────────────────────────────────────────────
def test_the_drain_window_is_several_batch_times_not_one():
    # At 20s the drain was barely longer than one ~14s micro-batch, so "kept up" turned
    # on where the timer fell rather than on the pipeline (P-44).
    assert harness.DRAIN_SECONDS >= 45.0


def test_a_missing_measurement_prints_as_not_available():
    assert harness._fmt(None) == "n/a"
    assert harness._fmt(1234.6) == "1235"
