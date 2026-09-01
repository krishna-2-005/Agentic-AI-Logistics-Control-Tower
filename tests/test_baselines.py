"""Tests for the Week 3 baseline stage — the parts that never touch Spark.

    pytest tests/test_baselines.py -q

`time_split` and `prepare_model_features` are pure pandas and are exactly the two
things Week 4 depends on getting right: the split Week 4 must reuse verbatim (D-022),
and the cold-start fill Week 4's own feature prep has to match if it wants comparable
numbers. `add_delay_label`, `threshold_to_label`, `majority_class_predictions` and
`evaluate_classifier` are the same kind of dependency for D-003's label — Week 4's
Random Forest and GBT owe the same classifier table (D-025), scored the same way. All
are asserted here on small, hand-built frames rather than the real 26,369-row table,
so a future change to Stage 4's column names breaks a fast test instead of a
30-second Spark job.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.common import config
from src.ml.baselines import (
    CLASSIFIER_TARGET,
    FEATURES,
    add_delay_label,
    corridor_mean_predictions,
    evaluate_classifier,
    majority_class_predictions,
    osrm_predictions,
    prepare_model_features,
    threshold_to_label,
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


def test_add_delay_label_matches_d003_threshold():
    pdf = _toy_frame(10)
    labelled = add_delay_label(pdf)

    expected = (pdf["gap_min"] > (config.DELAY_THRESHOLD - 1) * pdf["planned_min"]).astype(int)
    assert (labelled[CLASSIFIER_TARGET] == expected).all()
    # A copy's new column, not a mutation of the frame the caller still holds.
    assert CLASSIFIER_TARGET not in pdf.columns


def test_threshold_to_label_reproduces_the_true_label_from_the_true_gap():
    labelled = add_delay_label(_toy_frame(10))

    # Thresholding gap_min itself must reproduce is_delayed exactly — the whole point
    # of building both from the same rule (D-003), rather than the label and a
    # model's classification score disagreeing on what "delayed" means.
    implied = threshold_to_label(labelled["gap_min"].to_numpy(), labelled["planned_min"].to_numpy())
    assert np.array_equal(implied, labelled[CLASSIFIER_TARGET].to_numpy())


def test_majority_class_predictions_is_fit_on_train_and_broadcast_to_any_length():
    majority_positive = pd.Series([1, 1, 1, 0, 0])  # 60% positive
    pred = majority_class_predictions(majority_positive, n=7)
    assert len(pred) == 7
    assert (pred == 1).all()

    majority_negative = pd.Series([1, 0, 0, 0])  # 25% positive
    pred_neg = majority_class_predictions(majority_negative, n=3)
    assert len(pred_neg) == 3
    assert (pred_neg == 0).all()


def test_evaluate_classifier_reports_majority_rate_from_y_true_not_y_pred():
    y_true = np.array([1, 1, 1, 0, 0])  # 60% positive -> majority rate 0.6
    y_pred = np.array([0, 0, 0, 0, 0])  # a degenerate model, e.g. OSRM_threshold

    metrics = evaluate_classifier(y_true, y_pred)

    assert metrics["n"] == 5
    assert metrics["majority_class_rate"] == 0.6
    # Never predicting the positive class: precision, recall and F1 on it are all
    # exactly zero rather than raising — the harness must be able to score a model
    # this degenerate, not just a well-behaved one.
    assert metrics["precision"] == 0.0
    assert metrics["recall"] == 0.0
    assert metrics["f1"] == 0.0
