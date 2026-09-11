"""Tests for the shared delay label and the threshold sweep (execution plan W5 D3-D4).

    pytest tests/test_threshold_sensitivity.py -q

No Spark: the sweep is exercised on a small synthetic frame with the real FEATURES
columns, and the champion's predictions are passed in as an array, which is exactly the
seam `sweep()` was written around.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.common import config
from src.ml import threshold_sensitivity as ts
from src.ml.baselines import (
    CLASSIFIER_TARGET,
    FEATURES,
    HISTORY_PREFIXES,
    TARGET,
    add_delay_label,
    delay_label,
    threshold_to_label,
)


# ── the one delay label every caller now uses (P-42) ─────────────────────────
def test_the_label_is_gap_over_t_minus_one_times_plan():
    # T = 2.00: delayed when the gap alone exceeds the plan.
    assert int(delay_label(101.0, 100.0, 2.0)) == 1
    assert int(delay_label(99.0, 100.0, 2.0)) == 0


def test_the_boundary_itself_is_not_delayed():
    # D-003 says "more than T x planned"; exactly T x is on time.
    assert int(delay_label(100.0, 100.0, 2.0)) == 0
    assert int(delay_label(25.0, 100.0, 1.25)) == 0


def test_the_default_threshold_is_the_decided_one():
    gap = np.array([10.0, 60.0, 120.0])
    plan = np.array([50.0, 50.0, 50.0])
    assert list(delay_label(gap, plan)) == list(delay_label(gap, plan, config.DELAY_THRESHOLD))


def test_scalar_array_and_series_all_work():
    assert int(delay_label(150.0, 100.0)) == 1
    assert list(delay_label(np.array([150.0, 50.0]), np.array([100.0, 100.0]))) == [1, 0]
    assert list(delay_label(pd.Series([150.0, 50.0]), pd.Series([100.0, 100.0]))) == [1, 0]


def test_a_lower_threshold_never_labels_fewer_legs_delayed():
    rng = np.random.default_rng(0)
    gap, plan = rng.uniform(0, 300, 500), rng.uniform(20, 200, 500)
    counts = [delay_label(gap, plan, t).sum() for t in ts.THRESHOLDS]
    assert counts == sorted(counts, reverse=True)


def test_every_caller_agrees_with_the_helper():
    frame = pd.DataFrame({TARGET: [10.0, 60.0, 120.0], "planned_min": [50.0, 50.0, 50.0]})
    expected = list(delay_label(frame[TARGET], frame["planned_min"], 1.5))
    assert list(add_delay_label(frame, 1.5)[CLASSIFIER_TARGET]) == expected
    assert list(threshold_to_label(frame[TARGET].to_numpy(), frame["planned_min"].to_numpy(), 1.5)) == expected


def test_the_stream_fact_event_uses_the_same_label():
    from src.streaming.schema import fact_event

    row = pd.Series({
        "leg_id": "trip-a|20180912000209|INDA>INDB", "trip_uuid": "trip-a",
        "corridor_id": "INDA>INDB", "source_center": "INDA", "destination_center": "INDB",
        "gap_min": 60.0, "planned_min": 50.0, "log_gap_ratio": 0.8,
    })
    assert fact_event(row)["is_delayed"] == int(delay_label(60.0, 50.0))


# ── the extra metrics ────────────────────────────────────────────────────────
def test_a_constant_prediction_has_zero_mcc_whatever_the_base_rate():
    y = np.array([1] * 96 + [0] * 4)  # T = 1.15's base rate
    metrics = ts.extra_metrics(y, np.ones_like(y))
    assert metrics["mcc"] == 0.0
    assert metrics["balanced_accuracy"] == pytest.approx(0.5)
    assert metrics["alert_rate"] == 1.0


def test_a_perfect_prediction_has_mcc_one():
    y = np.array([0, 1, 1, 0, 1])
    assert ts.extra_metrics(y, y.copy())["mcc"] == pytest.approx(1.0)


# ── the sweep itself, on a synthetic frame ───────────────────────────────────
def _synthetic(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({feature: rng.uniform(0, 1, n) for feature in FEATURES})
    frame["planned_min"] = rng.uniform(30, 300, n)
    frame["planned_km"] = frame["planned_min"] * 1.2
    frame["is_ftl"] = rng.integers(0, 2, n)
    for prefix in HISTORY_PREFIXES:
        frame[f"{prefix}_n_prior"] = rng.integers(0, 20, n)
        frame[f"{prefix}_is_cold"] = (frame[f"{prefix}_n_prior"] == 0).astype(int)
    frame["corr_mean_gap_min"] = frame["planned_min"] * rng.uniform(0.2, 1.8, n)
    frame[TARGET] = frame["planned_min"] * rng.uniform(0.0, 2.5, n)
    return frame


@pytest.fixture(scope="module")
def results() -> pd.DataFrame:
    train, test = _synthetic(400, 1), _synthetic(150, 2)
    champion_gap = test[TARGET].to_numpy() * 0.9
    return ts.sweep(train, test, champion_gap)


def test_every_model_is_scored_at_every_threshold(results):
    assert len(results) == len(ts.THRESHOLDS) * len(ts.MODEL_ORDER)
    assert set(results["model"]) == set(ts.MODEL_ORDER)


def test_the_base_rate_falls_as_the_threshold_rises(results):
    rates = results.drop_duplicates("threshold").sort_values("threshold")["pct_delayed_test"].tolist()
    assert rates == sorted(rates, reverse=True)


def test_the_majority_class_never_scores_any_mcc(results):
    assert (results[results["model"] == "majority_class"]["mcc"] == 0.0).all()


def test_osrm_never_calls_a_leg_delayed(results):
    # OSRM predicts zero gap, which is on time at every threshold above 1.0.
    assert (results[results["model"] == "OSRM_threshold"]["alert_rate"] == 0.0).all()


def test_every_row_carries_the_majority_class_rate(results):
    # D-003 rule 3: reported beside every classifier metric, permanently.
    assert results["majority_class_rate"].notna().all()


def test_the_rendered_section_reports_every_threshold_and_d003s_figures(results):
    rates = {t: 50.0 for t in ts.THRESHOLDS}
    text = ts.render_doc(results, rates, 400, 150, "2018-10-01")
    for t in ts.THRESHOLDS:
        assert f"| {t:.2f}" in text
        assert f"{ts.D003_PCT_DELAYED[t]:.1f}%" in text
    assert "MCC" in text and "(decided)" in text
