"""Tests for the trip-replay producer (execution plan W5 D1-D2).

    pytest tests/test_producer.py -q

No Spark, no Kafka, no broker: `load_legs` is the only function that needs a
SparkSession and it is a thin `read.parquet` the streaming job's own run exercises.
What is tested here is the part that decides *what goes out and when* -- event
ordering, the time-compression maths, and the file sink's write-then-rename -- plus a
regression test for the mixed-precision timestamp bug that actually bit (P-38).
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.streaming import producer


def _leg(leg_id: str, created: str, planned_min: float = 60.0, gap_min: float = 30.0) -> pd.Series:
    """One `features_v1`-shaped row, minimal but complete for both event builders."""
    return pd.Series(
        {
            "leg_id": leg_id,
            "trip_uuid": leg_id.split("|")[0],
            "corridor_id": leg_id.split("|")[2],
            "source_center": leg_id.split("|")[2].split(">")[0],
            "destination_center": leg_id.split("|")[2].split(">")[1],
            "trip_creation_time": pd.Timestamp(created),
            "route_type": "FTL",
            "planned_min": planned_min,
            "planned_km": 100.0,
            "created_hour": pd.Timestamp(created).hour,
            "created_dayofweek": pd.Timestamp(created).weekday(),
            "created_is_weekend": int(pd.Timestamp(created).weekday() >= 5),
            "gap_min": gap_min,
            "log_gap_ratio": 0.4,
            "od_end_time": pd.Timestamp(created) + pd.Timedelta(minutes=planned_min + gap_min + 20),
            "is_delayed": 1,
        }
    )


# ── build_events ─────────────────────────────────────────────────────────────
def test_two_events_per_leg():
    pdf = pd.DataFrame([_leg("t1|20180912000000|A>B", "2018-09-12T00:00:00")])
    events = producer.build_events(pdf)
    assert len(events) == 2
    assert {e["kind"] for e in events} == {"query", "fact"}


def test_events_are_sorted_by_event_time():
    pdf = pd.DataFrame(
        [
            _leg("t2|20180913000000|A>B", "2018-09-13T00:00:00"),
            _leg("t1|20180912000000|A>B", "2018-09-12T00:00:00"),
        ]
    )
    events = producer.build_events(pdf)
    times = [e["event_time"] for e in events]
    assert times == sorted(times)


def test_a_fact_sorts_before_a_query_at_the_same_instant():
    # D-020's ordering rule: a leg finishing at the same instant another is created
    # is already history to it, so the fact has to go out first.
    events = [
        {"event_time": "2018-09-12T00:00:00", "kind": "query"},
        {"event_time": "2018-09-12T00:00:00", "kind": "fact"},
    ]
    events.sort(key=lambda e: (e["event_time"], producer.KIND_ORDER[e["kind"]]))
    assert [e["kind"] for e in events] == ["fact", "query"]


# ── compress_schedule ────────────────────────────────────────────────────────
def test_schedule_spans_zero_to_duration():
    pdf = pd.DataFrame(
        [
            _leg("t1|20180912000000|A>B", "2018-09-12T00:00:00"),
            _leg("t2|20180922000000|A>B", "2018-09-22T00:00:00"),
        ]
    )
    schedule = producer.compress_schedule(producer.build_events(pdf), duration_seconds=10.0)
    offsets = [offset for offset, _ in schedule]
    assert offsets[0] == pytest.approx(0.0)
    assert offsets[-1] == pytest.approx(10.0)
    assert offsets == sorted(offsets)


def test_schedule_keeps_gaps_proportional_not_uniform():
    # Two events close together then one far away: the third offset must be much
    # further out than the second, not simply one-third and two-thirds of the way.
    events = [
        {"event_time": "2018-09-12T00:00:00", "kind": "fact"},
        {"event_time": "2018-09-12T00:00:01", "kind": "fact"},
        {"event_time": "2018-09-12T01:00:00", "kind": "fact"},
    ]
    schedule = producer.compress_schedule(events, duration_seconds=60.0)
    offsets = [offset for offset, _ in schedule]
    assert offsets[1] < 0.1, "a one-second real gap must stay tiny after compression"
    assert offsets[2] == pytest.approx(60.0)


def test_schedule_handles_mixed_precision_timestamps():
    # P-38: a query event carries microseconds and a fact event can land on a whole
    # second. Letting pandas infer one format from the first element throws on the
    # other; this is the regression guard for that fix.
    events = [
        {"event_time": "2018-09-12T00:00:16.535741", "kind": "query"},
        {"event_time": "2018-09-12T00:23:34", "kind": "fact"},
    ]
    schedule = producer.compress_schedule(events, duration_seconds=4.0)
    assert [offset for offset, _ in schedule] == pytest.approx([0.0, 4.0])


def test_schedule_of_identical_timestamps_does_not_divide_by_zero():
    events = [{"event_time": "2018-09-12T00:00:00", "kind": "fact"}] * 3
    schedule = producer.compress_schedule(events, duration_seconds=5.0)
    assert [offset for offset, _ in schedule] == [0.0, 0.0, 0.0]


def test_empty_schedule():
    assert producer.compress_schedule([], duration_seconds=5.0) == []


# ── FileSink ─────────────────────────────────────────────────────────────────
def test_file_sink_writes_one_complete_jsonl_per_tick(tmp_path):
    sink = producer.FileSink(tmp_path)
    sink.emit([{"a": 1}, {"a": 2}], tick=0)

    written = sorted(tmp_path.glob("*.jsonl"))
    assert [p.name for p in written] == ["tick_000000.jsonl"]
    lines = written[0].read_text(encoding="utf-8").strip().split("\n")
    assert [json.loads(line) for line in lines] == [{"a": 1}, {"a": 2}]


def test_file_sink_leaves_no_staging_files_behind(tmp_path):
    sink = producer.FileSink(tmp_path)
    sink.emit([{"a": 1}], tick=0)
    # A Spark file source lists the directory; a leftover partial file would be read
    # as a malformed record at the consumer end.
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*")) == []


def test_file_sink_skips_an_empty_batch(tmp_path):
    sink = producer.FileSink(tmp_path)
    sink.emit([], tick=0)
    assert list(tmp_path.iterdir()) == []


# ── ReplayStats ──────────────────────────────────────────────────────────────
def test_events_per_second_does_not_divide_by_zero():
    stats = producer.ReplayStats(events=10, started_at=1.0, finished_at=1.0)
    assert stats.events_per_second == 0.0


def test_events_per_second():
    stats = producer.ReplayStats(events=100, started_at=0.0, finished_at=4.0)
    assert stats.events_per_second == pytest.approx(25.0)
