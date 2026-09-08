"""Tests for the stream-equals-batch correctness test (execution plan W5 D1-D2).

    pytest tests/test_stream_validation.py -q

No Spark and no champion model: `run()` needs both and is exercised by its own CLI.
What is pinned here is the part that would silently corrupt a prediction --
`schema.temporal_features`' day-of-week encoding (P-39) and the event-carried /
history split -- because those are the pieces a future streaming job will re-derive
and could get subtly wrong.
"""

# ruff: noqa: DTZ001 -- every timestamp in this project is naive local time (D-013),
# including the ones these tests construct; a tz-aware datetime here would not match
# what Stage 4 actually put in features_v1.
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from src.ml import stream_validation as sv
from src.ml.baselines import FEATURES
from src.streaming.schema import query_event, temporal_features


# ── the day-of-week trap (P-39) ──────────────────────────────────────────────
def test_dayofweek_uses_sparks_sunday_is_one_encoding():
    # Stage 4 builds this feature with Spark's F.dayofweek: Sunday = 1 .. Saturday = 7.
    assert temporal_features(datetime(2018, 9, 16))["created_dayofweek"] == 1  # Sunday
    assert temporal_features(datetime(2018, 9, 17))["created_dayofweek"] == 2  # Monday
    assert temporal_features(datetime(2018, 9, 12))["created_dayofweek"] == 4  # Wednesday
    assert temporal_features(datetime(2018, 9, 15))["created_dayofweek"] == 7  # Saturday


def test_dayofweek_is_not_pythons_weekday():
    # The whole point of the helper: the obvious Python reading disagrees, and on a
    # Wednesday it disagrees by 2 with no error anywhere.
    when = datetime(2018, 9, 12)
    assert temporal_features(when)["created_dayofweek"] != when.weekday()


def test_is_weekend_agrees_with_both_conventions():
    # is_weekend is genuinely convention-independent -- Spark's isin(1, 7) and Python's
    # weekday() >= 5 both mean Saturday-or-Sunday. Pinned so a "fix" to the encoding
    # cannot quietly change what counts as a weekend.
    for day in range(12, 19):
        when = datetime(2018, 9, day)
        assert temporal_features(when)["created_is_weekend"] == int(when.weekday() >= 5)


def test_hour_is_taken_straight_from_the_timestamp():
    assert temporal_features(datetime(2018, 9, 12, 17, 45))["created_hour"] == 17


# ── the event-carried / history split ────────────────────────────────────────
def test_every_feature_is_either_event_carried_or_history():
    assert set(sv.EVENT_CARRIED) | set(sv.HISTORY_CARRIED) == set(FEATURES)
    assert not set(sv.EVENT_CARRIED) & set(sv.HISTORY_CARRIED)


def test_event_carried_is_exactly_what_the_event_can_supply():
    # Derived from FEATURES rather than hand-listed, so a new feature cannot be added
    # to the model and silently skip this test.
    assert sorted(sv.EVENT_CARRIED) == sorted(
        ["planned_min", "planned_km", "created_hour", "created_dayofweek", "created_is_weekend", "is_ftl"]
    )


# ── rebuild_from_event ───────────────────────────────────────────────────────
def _row() -> pd.Series:
    base = {name: 0.0 for name in sv.HISTORY_CARRIED}
    base.update(
        {
            "leg_id": "t1|20180912000000|A>B",
            "trip_uuid": "t1",
            "corridor_id": "A>B",
            "source_center": "A",
            "destination_center": "B",
            "trip_creation_time": pd.Timestamp("2018-09-12T08:30:00"),
            "route_type": "FTL",
            "planned_min": 123.5,
            "planned_km": 210.25,
            "created_hour": 8,
            "created_dayofweek": 4,
            "created_is_weekend": 0,
            "corr_mean_gap_min": 42.5,
        }
    )
    return pd.Series(base)


def test_rebuild_produces_every_model_feature():
    row = _row()
    rebuilt = sv.rebuild_from_event(query_event(row), row)
    assert set(rebuilt) == set(FEATURES)


def test_rebuild_survives_a_json_round_trip_exactly():
    # The step where a float or an int can quietly change shape on the way through a
    # sink. Values must come back bit-identical or the stream scores differently.
    row = _row()
    event = json.loads(json.dumps(query_event(row)))
    rebuilt = sv.rebuild_from_event(event, row)
    assert rebuilt["planned_min"] == 123.5
    assert rebuilt["planned_km"] == 210.25
    assert rebuilt["created_hour"] == 8
    assert rebuilt["created_dayofweek"] == 4
    assert rebuilt["is_ftl"] == 1


def test_rebuild_maps_route_type_to_is_ftl():
    row = _row()
    row["route_type"] = "Carting"
    assert sv.rebuild_from_event(query_event(row), row)["is_ftl"] == 0


def test_rebuild_takes_history_from_the_broadcast_row_not_the_event():
    # The event does not carry history at all (D-031); it has to come from the join.
    row = _row()
    assert sv.rebuild_from_event(query_event(row), row)["corr_mean_gap_min"] == 42.5


# ── compare_temporal ─────────────────────────────────────────────────────────
def test_compare_temporal_flags_the_naive_reading_as_differing():
    row = _row()
    frame = sv.compare_temporal([query_event(row)])
    assert bool(frame["agrees_with_shared"].iloc[0]) is True
    assert bool(frame["naive_would_differ"].iloc[0]) is True
    assert frame["carried_created_dayofweek"].iloc[0] == 4
    assert frame["naive_created_dayofweek"].iloc[0] == 2
