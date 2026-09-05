"""Tests for the Spark-free part of the what-if predictor (execution plan W4 D5).

    pytest tests/test_predict.py -q

`predict_delay` itself needs a SparkSession and a real champion `PipelineModel` on
disk (gitignored, machine-local) and is exercised interactively instead (D-029) --
these tests cover `build_result`, the pure post-prediction logic split out of it for
exactly this reason.
"""

from __future__ import annotations

from src.ml.predict import build_result


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
