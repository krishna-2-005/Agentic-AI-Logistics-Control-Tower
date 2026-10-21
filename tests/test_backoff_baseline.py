"""The back-off baseline (D-075), on synthetic legs with known answers. No Spark, no data files.

    pytest tests/test_backoff_baseline.py -q
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pyspark")  # the fast job runs without PySpark: skip, do not error

from src.ml import backoff_baseline as bb


def legs(rows: list[tuple]) -> pd.DataFrame:
    """(created, ended, corridor, source, destination, route_type, km, gap) per leg, times in minutes."""
    base = pd.Timestamp("2018-09-12")
    frame = pd.DataFrame(rows, columns=["created", "ended", "corridor_id", "source_center", "destination_center",
                                        "route_type", "planned_km", "gap_min"])
    frame["trip_creation_time"] = base + pd.to_timedelta(frame.pop("created"), unit="m")
    frame["od_end_time"] = base + pd.to_timedelta(frame.pop("ended"), unit="m")
    return frame


CUTS = (30.0, 60.0)


def test_a_leg_sees_only_legs_that_finished_before_it_was_created():
    frame = legs([
        (0, 10, "A>B", "A", "B", "FTL", 10, 100.0),    # finishes at 10
        (5, 50, "A>B", "A", "B", "FTL", 10, 999.0),    # created at 5: sees nothing (leg 0 not finished)
        (20, 60, "A>B", "A", "B", "FTL", 10, 5.0),     # sees leg 0 only (leg 1 finishes at 50)
        (70, 80, "A>B", "A", "B", "FTL", 10, 1.0),     # sees all three
    ])
    count, median = bb.level_statistics(frame, CUTS)["corridor"]
    assert count.tolist() == [0, 0, 1, 3]
    assert np.isnan(median[0]) and np.isnan(median[1])
    assert median[2] == 100.0 and median[3] == 100.0  # median of {100, 999, 5}


def test_a_leg_finishing_at_the_query_instant_counts_facts_before_queries():
    frame = legs([
        (0, 30, "A>B", "A", "B", "FTL", 10, 7.0),
        (30, 40, "A>B", "A", "B", "FTL", 10, 1.0),
    ])
    count, median = bb.level_statistics(frame, CUTS)["corridor"]
    assert count.tolist() == [0, 1] and median[1] == 7.0


def test_a_leg_is_never_its_own_history():
    frame = legs([(0, 10, "A>B", "A", "B", "FTL", 10, 50.0)])
    assert bb.level_statistics(frame, CUTS)["network"][0].tolist() == [0]


def test_an_even_count_takes_the_mean_of_the_two_middle_values():
    frame = legs([
        (0, 1, "A>B", "A", "B", "FTL", 10, 10.0),
        (0, 2, "A>B", "A", "B", "FTL", 10, 30.0),
        (100, 101, "A>B", "A", "B", "FTL", 10, 0.0),
    ])
    assert bb.level_statistics(frame, CUTS)["corridor"][1][2] == 20.0


def test_hard_backoff_walks_corridor_then_hubs_then_band_then_network():
    frame = legs([
        (0, 10, "A>B", "A", "B", "FTL", 10, 100.0),     # corridor A>B history for later legs
        (0, 11, "A>C", "A", "C", "FTL", 90, 40.0),      # same origin hub A, other corridor, long band
        (0, 12, "D>B", "D", "B", "Carting", 10, 20.0),  # same destination hub B
        (0, 13, "E>F", "E", "F", "FTL", 10, 4.0),       # same route type x band as leg "G>H"? (short FTL)
        (0, 14, "Z>Y", "Z", "Y", "Carting", 90, 60.0),
        (100, 101, "A>B", "A", "B", "FTL", 10, 0.0),    # corridor level: 100
        (100, 102, "A>X", "A", "X", "FTL", 10, 0.0),    # corridor empty -> origin hub A: {100, 40} -> 70
        (100, 103, "Q>B", "Q", "B", "Carting", 10, 0.0),# corridor+origin empty -> dest hub B: {100, 20} -> 60
        (100, 104, "R>S", "R", "S", "FTL", 10, 0.0),    # hubs empty -> short FTL: {100, 4} -> 52
        (100, 105, "T>U", "T", "U", "Carting", 70, 0.0),# nothing shared except the network (long/Carting differs)
    ])
    late = bb.hard_backoff(bb.level_statistics(frame, CUTS)).iloc[5:].reset_index(drop=True)
    assert late["backoff_level"].tolist() == [1, 2, 3, 4, 4]
    assert late["backoff_gap"].tolist() == pytest.approx([100.0, 70.0, 60.0, 52.0, 60.0])
    # the last leg shares nothing with anyone but its band: a long Carting leg meets Z>Y (60)


def test_a_leg_with_no_history_anywhere_gets_zero_and_is_flagged():
    frame = legs([(0, 10, "A>B", "A", "B", "FTL", 10, 99.0)])
    out = bb.hard_backoff(bb.level_statistics(frame, CUTS))
    assert out["backoff_gap"].iloc[0] == 0.0 and bool(out["backoff_no_history"].iloc[0])


def test_shrinkage_with_no_prior_legs_reproduces_the_parent_estimate():
    frame = legs([
        (0, 10, "A>B", "A", "B", "FTL", 10, 40.0),
        (100, 101, "C>D", "C", "D", "FTL", 10, 0.0),   # only the network and the band have history
    ])
    stats = bb.level_statistics(frame, CUTS)
    hard = bb.hard_backoff(stats)
    assert bb.shrunken_backoff(stats, k=5)[1] == pytest.approx(hard["backoff_gap"].iloc[1]) == pytest.approx(40.0)


def test_shrinkage_weights_follow_n_over_n_plus_k():
    # The query leg's corridor, both hubs and its band each hold the same two legs (gap 10); the network
    # also holds four far-away legs (gap 90), so the network median is 90 and every other level's is 10.
    rows = [(0, 1, "A>B", "A", "B", "FTL", 10, 10.0), (0, 2, "A>B", "A", "B", "FTL", 10, 10.0)]
    rows += [(0, 3 + i, f"X{i}>Y{i}", f"X{i}", f"Y{i}", "Carting", 90, 90.0) for i in range(4)]
    rows += [(100, 101, "A>B", "A", "B", "FTL", 10, 0.0)]
    stats = bb.level_statistics(legs(rows), CUTS)
    assert stats["network"][1][-1] == 90.0 and stats["corridor"][1][-1] == 10.0
    # k = 2, n = 2 at four levels: weight 1/2 each, from the network (90) upward: 50, 30, 20, then 15.
    assert bb.shrunken_backoff(stats, 2.0)[-1] == pytest.approx(15.0)
    # k = 0 is the hard rule (own median); a huge k collapses to the network median.
    assert bb.shrunken_backoff(stats, 1e-12)[-1] == pytest.approx(10.0)
    assert bb.shrunken_backoff(stats, 1e12)[-1] == pytest.approx(90.0)


def test_judge_refuses_a_level_one_median_that_disagrees_with_the_feature_table():
    frame = legs([
        (0, 10, "A>B", "A", "B", "FTL", 10, 100.0),
        (20, 30, "A>B", "A", "B", "FTL", 10, 5.0),
    ])
    stats = bb.level_statistics(frame, CUTS)
    frame["corr_n_prior"] = [0, 1]
    frame["corr_median_gap_min"] = [np.nan, 100.0]
    assert bb.judge_level_one(frame, stats)["count_agrees"] is True
    frame["corr_median_gap_min"] = [np.nan, 99.0]
    with pytest.raises(ValueError, match="does not reproduce"):
        bb.judge_level_one(frame, stats)


def test_distance_bands_are_cut_at_the_two_given_points():
    bands = bb.distance_bands(pd.Series([5.0, 30.0, 45.0, 60.0, 500.0]), CUTS)
    assert bands.tolist() == ["short", "medium", "medium", "long", "long"]


def test_the_old_median_is_zero_on_a_cold_corridor_and_the_median_otherwise():
    frame = pd.DataFrame({"corr_n_prior": [0, 3], "corr_median_gap_min": [np.nan, 12.5]})
    assert bb.old_median(frame).tolist() == [0.0, 12.5]


def test_k_is_chosen_on_validation_with_the_smaller_k_winning_a_tie():
    frame = legs([
        (0, 10, "A>B", "A", "B", "FTL", 10, 10.0),
        (20, 30, "A>B", "A", "B", "FTL", 10, 10.0),
        (40, 50, "A>B", "A", "B", "FTL", 10, 10.0),
    ])
    stats = bb.level_statistics(frame, CUTS)
    k, scores = bb.choose_k(frame.iloc[2:], stats, np.array([2]))
    assert k == min(bb.K_GRID) and set(scores) == {str(v) for v in bb.K_GRID}
