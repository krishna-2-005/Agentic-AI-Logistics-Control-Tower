# ruff: noqa: DTZ001 -- a what-if departure is a bare local time, as the form gives it.
"""Tests for the Spark-free part of the what-if predictor (execution plan W4 D5).

    pytest tests/test_predict.py -q

`predict_delay` itself needs a SparkSession and a real champion `PipelineModel` on
disk (gitignored, machine-local) and is exercised interactively instead (D-029) --
these tests cover `build_result`, the pure post-prediction logic split out of it for
exactly this reason.
"""

from __future__ import annotations

from datetime import datetime

from src.ml.predict import base_row, build_result


def test_not_delayed_below_the_d003_threshold():
    result = build_result(predicted_gap_min=50.0, planned_min=200.0, cold_flags={})
    # threshold is (2.00 - 1) * 200 = 200
    assert result["threshold_gap_min"] == 200.0
    assert result["is_delayed_predicted"] is False
    assert result["predicted_total_min"] == 250.0


def test_delayed_above_the_d003_threshold():
    result = build_result(predicted_gap_min=250.0, planned_min=200.0, cold_flags={})
    assert result["is_delayed_predicted"] is True
    assert result["predicted_total_min"] == 450.0


def test_exactly_at_threshold_is_not_delayed():
    # D-003's rule is a strict ">", matching add_delay_label / threshold_to_label
    result = build_result(predicted_gap_min=200.0, planned_min=200.0, cold_flags={})
    assert result["is_delayed_predicted"] is False


def test_cold_flags_pass_through_unchanged():
    flags = {"corr": True, "src": False, "dst": True}
    result = build_result(predicted_gap_min=10.0, planned_min=100.0, cold_flags=flags)
    assert result["cold_flags"] == flags


# ── P-46: the what-if row speaks Spark's day-of-week ─────────────────────────
def test_a_wednesday_is_four_as_the_model_learned_it():
    # datetime.weekday() says 2 for a Wednesday; the champion was trained on Spark's 4.
    row = base_row("FTL", 100.0, 120.0, datetime(2018, 9, 12, 14, 30))
    assert row["created_dayofweek"] == 4
    assert (row["created_hour"], row["created_is_weekend"], row["is_ftl"]) == (14, 0, 1)


def test_saturday_is_seven_and_sunday_is_one():
    assert base_row("Carting", 1.0, 1.0, datetime(2018, 9, 15))["created_dayofweek"] == 7
    sunday = base_row("Carting", 1.0, 1.0, datetime(2018, 9, 16))
    assert (sunday["created_dayofweek"], sunday["created_is_weekend"], sunday["is_ftl"]) == (1, 1, 0)
