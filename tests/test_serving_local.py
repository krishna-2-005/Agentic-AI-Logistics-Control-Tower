"""Tests for serving without Spark or data: the numpy tree walker and the aggregates-only
history snapshot (WP-04, D-073).

    pytest tests/test_serving_local.py -q

The full proofs need the data and run elsewhere (`src.ml.gbt_local --verify`: 26,369 of
26,369 identical to Spark; `export_snapshot`: 52,738 of 52,738 identical to the fold).
These pin the rules those proofs depend on, on synthetic inputs, in seconds.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ml import gbt_local, history_snapshot
from src.streaming.state import HistoryBook


def _forest() -> gbt_local.Forest:
    # Two stumps on feature 0 (threshold 1.0) and feature 1 (threshold 5.0).
    return gbt_local.Forest(
        feature_names=["a", "b"], weights=np.array([1.0, 0.5]),
        feature=np.array([0, -1, -1, 1, -1, -1]), threshold=np.array([1.0, 0, 0, 5.0, 0, 0]),
        left=np.array([1, -1, -1, 4, -1, -1]), right=np.array([2, -1, -1, 5, -1, -1]),
        value=np.array([0.0, 10.0, 20.0, 0.0, 100.0, 200.0]), roots=np.array([0, 3]),
    )


def test_a_value_equal_to_the_threshold_goes_left():
    frame = pd.DataFrame({"a": [1.0, 1.0000001], "b": [5.0, 5.1]})
    assert gbt_local.predict(_forest(), frame).tolist() == [10.0 + 50.0, 20.0 + 100.0]


def test_the_json_round_trip_changes_no_prediction(tmp_path):
    forest = _forest()
    gbt_local.to_json(forest, tmp_path / "f.json.gz")
    again = gbt_local.from_json(tmp_path / "f.json.gz")
    frame = pd.DataFrame({"a": np.linspace(0, 2, 9), "b": np.linspace(4, 6, 9)})
    assert np.array_equal(gbt_local.predict(forest, frame), gbt_local.predict(again, frame))


def test_four_lane_summation_is_the_one_chosen_and_groups_as_blas_does():
    assert gbt_local.WEIGHTED_SUM == "lanes4"
    outputs = np.array([[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]])
    weights = np.ones(9)
    lanes = [0.1 + 0.5, 0.2 + 0.6, 0.3 + 0.7, 0.4 + 0.8]
    expected = ((lanes[0] + lanes[1]) + lanes[2]) + lanes[3] + 0.9
    assert gbt_local.unrolled_sum(outputs, weights, 4)[0] == expected


def _facts():
    def fact(i, when, gap, corridor="A>B", hour=8):
        return {"kind": "fact", "leg_id": f"f{i}", "event_time": when, "gap_min": gap,
                "log_gap_ratio": gap / 100, "dwell_min": 10.0 + i, "created_hour": hour,
                "corridor_id": corridor, "source_center": corridor[0], "destination_center": corridor[-1]}
    return [fact(0, "2018-09-12T08:00:00", 10.0), fact(1, "2018-09-13T09:30:00", 30.0),
            fact(2, "2018-09-14T10:00:00", 25.0, corridor="C>B", hour=20)]


def test_the_snapshot_reads_exactly_what_the_full_fold_reads():
    facts = _facts()
    snap = history_snapshot.build(facts)
    check = history_snapshot.verify(facts, snap, [snap["valid_from"], "2026-10-04T09:00:00"])
    assert check["differing"] == 0 and check["queries"] == 6


def test_the_snapshot_refuses_a_departure_it_cannot_answer_exactly():
    snap = history_snapshot.build(_facts())
    with pytest.raises(ValueError, match="serves departures from"):
        history_snapshot.read(snap, {**_facts()[0], "kind": "query", "event_time": "2018-09-15T00:00:00"})


def test_a_key_the_snapshot_never_saw_reads_as_cold():
    snap = history_snapshot.build(_facts())
    query = {"kind": "query", "leg_id": "q", "event_time": "2026-10-04T09:00:00", "created_hour": 9,
             "corridor_id": "X>Y", "source_center": "X", "destination_center": "Y"}
    row = history_snapshot.read(snap, query)
    assert row == HistoryBook().read(query)
    assert row["corr_n_prior"] == 0 and row["corr_median_gap_min"] is None


def test_the_snapshot_holds_aggregates_not_records():
    snap = history_snapshot.build(_facts())
    text = repr(snap)
    assert "f0" not in text and "2018-09-12T08:00:00" not in text
