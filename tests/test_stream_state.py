"""Tests for the event-time history the stream serves v2 from (WP-11, D-053).

    pytest tests/test_stream_state.py -q

No Spark. The full-data proof is `src.streaming.validate_v2` (every history column on
every leg against `features_v2`); these pin the semantics that proof depends on, so a
change that breaks them fails in seconds rather than after a ten-minute replay.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from src.pipeline import features_v2
from src.streaming import job
from src.streaming.state import (
    FEATURE_COLUMNS,
    HOUR_BUCKETS,
    KEY_TYPES,
    TRAILING_DAYS,
    CorridorDispersion,
    HistoryBook,
    KeyState,
    epoch_us,
    floor_seconds,
    hour_bucket,
    keys_for,
    spark_percentile,
)


def fact(leg, when, gap, ratio=0.1, dwell=10.0, hour=8, corridor="A>B", src="A", dst="B"):
    return {"kind": "fact", "leg_id": leg, "event_time": when, "gap_min": gap, "log_gap_ratio": ratio,
            "dwell_min": dwell, "created_hour": hour, "corridor_id": corridor,
            "source_center": src, "destination_center": dst}


def query(leg, when, hour=8, corridor="A>B", src="A", dst="B"):
    return {"kind": "query", "leg_id": leg, "event_time": when, "created_hour": hour,
            "corridor_id": corridor, "source_center": src, "destination_center": dst}


# ── one definition, not two ──────────────────────────────────────────────────
def test_constants_match_the_batch_feature_table():
    assert HOUR_BUCKETS == features_v2.HOUR_BUCKETS
    assert TRAILING_DAYS == features_v2.TRAILING_DAYS


def test_every_v2_history_column_is_produced():
    from src.ml.models_v2 import V2_COLUMNS

    assert set(V2_COLUMNS) <= set(FEATURE_COLUMNS)


def test_the_job_keys_events_exactly_as_the_state_does():
    assert set(job.KEY_TYPES) == set(KEY_TYPES)


# ── Spark's arithmetic ───────────────────────────────────────────────────────
@pytest.mark.parametrize("values", [[5.0], [1.0, 2.0], [3.0, 1.0, 2.0, 10.0], [1.0, 1.0, 4.0, 9.0, 9.5]])
@pytest.mark.parametrize("p", [0.25, 0.5, 0.75, 0.9])
def test_percentile_is_linear_between_ranks(values, p):
    assert spark_percentile(sorted(values), p) == pytest.approx(np.percentile(values, p * 100))


def test_percentile_of_equal_neighbours_is_that_value_exactly():
    assert spark_percentile([2.0, 7.0, 7.0, 9.0], 0.5) == 7.0


def test_seconds_floor_like_a_cast_to_long():
    assert floor_seconds(epoch_us("2018-09-12 10:00:00.999999")) == floor_seconds(epoch_us("2018-09-12 10:00:00"))


def test_a_zoned_timestamp_is_refused():
    with pytest.raises(ValueError):
        epoch_us("2018-09-12T10:00:00+05:30")


def test_hour_buckets_cover_the_day_once():
    assert [hour_bucket(h) for h in (0, 5, 6, 11, 12, 17, 18, 23)] == [
        "night", "night", "morning", "morning", "afternoon", "afternoon", "evening", "evening"]


# ── as-of semantics ──────────────────────────────────────────────────────────
def test_a_query_sees_only_what_finished_before_it():
    out = HistoryBook().fold([
        fact("f1", "2018-09-12T08:00:00", 10.0),
        query("q1", "2018-09-12T09:00:00"),
        fact("f2", "2018-09-12T10:00:00", 30.0),
        query("q2", "2018-09-12T11:00:00"),
    ])
    assert out["q1"]["corr_n_prior"] == 1 and out["q1"]["corr_median_gap_min"] == 10.0
    assert out["q2"]["corr_n_prior"] == 2 and out["q2"]["corr_median_gap_min"] == 20.0


def test_a_fact_at_the_same_instant_counts_for_the_query():
    out = HistoryBook().fold([query("q", "2018-09-12T08:00:00"), fact("f", "2018-09-12T08:00:00", 4.0)])
    assert out["q"]["corr_n_prior"] == 1


def test_a_cold_key_reads_as_unknown_not_zero():
    row = HistoryBook().fold([query("q", "2018-09-12T08:00:00")])["q"]
    assert row["corr_n_prior"] == 0
    assert row["corr_median_gap_min"] is None and row["corr_mean_gap_7d"] is None
    assert row["src_dwell_by_hour_min"] is None


def test_std_needs_two_observations():
    out = HistoryBook().fold([fact("f", "2018-09-12T08:00:00", 4.0), query("q", "2018-09-12T09:00:00")])
    assert out["q"]["corr_std_gap_min"] is None and out["q"]["corr_std_log_ratio"] is None


def test_sample_std_matches_the_textbook():
    events = [fact(f"f{i}", f"2018-09-12T0{i}:00:00", g) for i, g in enumerate([2.0, 4.0, 4.0, 5.0])]
    row = HistoryBook().fold([*events, query("q", "2018-09-12T09:00:00")])["q"]
    assert row["corr_std_gap_min"] == pytest.approx(np.std([2.0, 4.0, 4.0, 5.0], ddof=1))


def test_trailing_window_includes_exactly_seven_days_back():
    out = HistoryBook().fold([
        fact("old", "2018-09-01T08:00:00", 100.0),
        fact("edge", "2018-09-05T08:00:00", 10.0),
        query("q", "2018-09-12T08:00:00"),
    ])
    assert out["q"]["corr_n_prior_7d"] == 1 and out["q"]["corr_mean_gap_7d"] == 10.0
    assert out["q"]["corr_n_prior"] == 2


def test_dwell_is_keyed_by_the_finished_legs_own_part_of_day():
    out = HistoryBook().fold([
        fact("morning", "2018-09-12T08:00:00", 1.0, dwell=30.0, hour=8),
        fact("evening", "2018-09-12T08:30:00", 1.0, dwell=90.0, hour=20),
        query("q", "2018-09-12T09:00:00", hour=9),
    ])
    assert out["q"]["src_dwell_by_hour_min"] == 30.0


def test_hours_since_last_counts_whole_seconds():
    out = HistoryBook().fold([fact("f", "2018-09-12T08:00:00.9", 1.0), query("q", "2018-09-12T10:00:00.1")])
    assert out["q"]["corr_hours_since_last"] == 2.0


def test_every_event_belongs_to_five_keys():
    assert [k for k, _ in keys_for(query("q", "2018-09-12T20:00:00", hour=20))] == list(KEY_TYPES)
    assert keys_for(query("q", "2018-09-12T20:00:00", hour=20))[3] == ("src_dwell", "A|evening")


# ── the state store ──────────────────────────────────────────────────────────
def test_state_survives_its_own_serialisation_exactly():
    state = KeyState.new("corr")
    for i, gap in enumerate([0.1, 1 / 3, 2.718281828459045]):
        state.apply_fact(fact(f"f{i}", f"2018-09-12T0{i}:00:00", gap))
    restored = KeyState.from_json(json.loads(json.dumps(state.to_json())))
    q = query("q", "2018-09-12T09:00:00")
    assert restored.read(q) == state.read(q)


def test_pruning_keeps_what_a_query_at_the_watermark_can_reach():
    d = CorridorDispersion()
    d.add(epoch_us("2018-09-01T00:00:00"), 1.0)
    d.add(epoch_us("2018-09-10T00:00:00"), 2.0)
    assert d.prune(floor_seconds(epoch_us("2018-09-12T00:00:00"))) == 1
    assert len(d.ordered) == 2  # the all-history median keeps everything


def test_an_event_older_than_the_key_has_seen_is_counted():
    state = KeyState.new("src")
    state.apply_fact(fact("f", "2018-09-12T10:00:00", 1.0))
    state.read(query("q", "2018-09-12T09:00:00"))
    assert state.out_of_order == 1


def test_a_nan_dwell_from_pandas_is_skipped_not_averaged():
    state = KeyState.new("src_dwell")
    state.apply_fact({**fact("f", "2018-09-12T08:00:00", 1.0), "dwell_min": math.nan})
    assert state.dwell is not None and state.dwell.n == 0
