"""Tests for the Week 3 baseline stage — the parts that never touch Spark.

    pytest tests/test_baselines.py -q

`time_split` and `prepare_model_features` are pure pandas and are exactly the two
things Week 4 depends on getting right: the split Week 4 must reuse verbatim (D-020),
and the cold-start fill Week 4's own feature prep has to match if it wants comparable
numbers. Both are asserted here on small, hand-built frames rather than the real
26,369-row table, so a future change to Stage 4's column names breaks a fast test
instead of a 30-second Spark job.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.ml.baselines import (
    FEATURES,
    corridor_mean_predictions,
    osrm_predictions,
    prepare_model_features,
    time_split,
)


def _toy_frame(n: int = 10) -> pd.DataFrame:
    """Ten legs, evenly spaced in time, half of them a corridor's first sighting."""
    return pd.DataFrame(
        {
            "trip_creation_time": pd.date_range("2018-09-01", periods=n, freq="D"),
            "route_type": ["FTL", "Carting"] * (n // 2),
            "planned_min": np.linspace(10, 100, n),
            "planned_km": np.linspace(5, 50, n),
            "created_hour": list(range(n)),
            "created_dayofweek": [((i % 7) + 1) for i in range(n)],
            "created_is_weekend": [i % 7 in (0, 6) for i in range(n)],
            "gap_min": np.linspace(0, 90, n),
            "corr_n_prior": [0, 1, 2, 0, 3, 0, 4, 5, 0, 6],
            "corr_mean_log_ratio": [None, 0.1, 0.2, None, 0.3, None, 0.4, 0.5, None, 0.6],
            "corr_std_log_ratio": [None, None, 0.05, None, 0.05, None, 0.05, 0.05, None, 0.05],
            "corr_mean_gap_min": [None, 5.0, 10.0, None, 15.0, None, 20.0, 25.0, None, 30.0],
            "corr_last_log_ratio": [None, 0.1, 0.2, None, 0.3, None, 0.4, 0.5, None, 0.6],
            "corr_hours_since_last": [None, 24.0, 24.0, None, 24.0, None, 24.0, 24.0, None, 24.0],
            "src_n_prior": [1] * n,
            "src_mean_log_ratio": [0.1] * n,
            "src_std_log_ratio": [0.05] * n,
            "src_mean_gap_min": [5.0] * n,
            "src_last_log_ratio": [0.1] * n,
            "src_hours_since_last": [12.0] * n,
            "dst_n_prior": [1] * n,
            "dst_mean_log_ratio": [0.1] * n,
            "dst_std_log_ratio": [0.05] * n,
            "dst_mean_gap_min": [5.0] * n,
            "dst_last_log_ratio": [0.1] * n,
            "dst_hours_since_last": [12.0] * n,
        }
    )


def test_time_split_is_chronological_and_respects_the_fraction():
    pdf = _toy_frame(10)
    train, test, cutoff = time_split(pdf, frac=0.8)

    assert len(train) == 8
    assert len(test) == 2
    # Nothing in train may be later than anything in test — the whole point of a
    # chronological split over a random one.
    assert train["trip_creation_time"].max() <= cutoff
    assert test["trip_creation_time"].min() > cutoff


def test_cold_start_legs_get_a_flag_and_a_zero_fill_not_a_dropped_row():
    pdf = _toy_frame(10)
    prepared = prepare_model_features(pdf)

    cold = pdf["corr_n_prior"] == 0
    assert cold.sum() > 0, "the toy frame should contain cold-start legs"
    assert (prepared.loc[cold, "corr_is_cold"] == 1).all()
    assert (prepared.loc[~cold, "corr_is_cold"] == 0).all()
    # Filled, never dropped: same row count, no leftover nulls on the columns a
    # cold leg would otherwise carry into the linear model.
    assert len(prepared) == len(pdf)
    assert not prepared["corr_mean_log_ratio"].isna().any()
    assert (prepared.loc[cold, "corr_mean_log_ratio"] == 0.0).all()
    # Every column the linear model reads must exist and be fully non-null.
    assert not prepared[FEATURES].isna().any().any()


def test_corridor_mean_baseline_falls_back_to_the_osrm_prediction_when_cold():
    pdf = _toy_frame(10)
    corr_pred = corridor_mean_predictions(pdf)
    osrm_pred = osrm_predictions(pdf)

    cold = (pdf["corr_n_prior"] == 0).to_numpy()
    assert np.array_equal(corr_pred[cold], osrm_pred[cold])
    # Where there is history, the corridor mean must actually use it rather than
    # silently falling back too.
    warm = ~cold
    assert np.array_equal(corr_pred[warm], pdf.loc[warm, "corr_mean_gap_min"].to_numpy())
