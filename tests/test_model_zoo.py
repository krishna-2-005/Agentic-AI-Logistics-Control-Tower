"""The model zoo (D-077) on small synthetic frames, and the study files it reads. No Spark.

    pytest tests/test_model_zoo.py -q
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("xgboost")

from src.common import config  # noqa: E402
from src.ml import model_zoo, significance  # noqa: E402

FEATURES = ["a", "b", "c"]


def _frame(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x = pd.DataFrame(rng.normal(size=(n, 3)), columns=FEATURES)
    baseline = rng.normal(30, 5, n)
    residual = 4 * x["a"] - 2 * (x["b"] > 0) + rng.normal(scale=0.5, size=n)
    return x.assign(baseline_gap=baseline, residual=residual, gap_min=baseline + residual)


@pytest.mark.parametrize("name", model_zoo.BOOSTED)
def test_each_boosted_model_fits_and_beats_the_baseline_on_a_learnable_target(name):
    train, test = _frame(300, 1), _frame(150, 2)
    (res,) = model_zoo.fit_boosted(name, 0.1, 1.0, train, [test], FEATURES)
    assert np.isfinite(res).all()
    assert np.mean(np.abs(test["residual"] - res)) < np.mean(np.abs(test["residual"]))


def test_the_linear_median_regression_runs_and_has_no_hyperparameter():
    train, test = _frame(120, 3), _frame(60, 4)
    (res,) = model_zoo.fit_predict_linear(train, [test], FEATURES)
    assert res.shape == (60,) and np.isfinite(res).all()


def test_select_and_score_picks_the_rate_on_validation_and_scores_test_once():
    inner, valid, train, test = _frame(200, 5), _frame(80, 6), _frame(280, 7), _frame(100, 8)
    out = model_zoo.select_and_score("lightgbm_l1", FEATURES, inner, valid, train, test)
    assert out["learning_rate_chosen"] in model_zoo.LEARNING_RATES
    assert out["learning_rate_chosen"] == min(model_zoo.LEARNING_RATES, key=lambda r: out["validation_mae_by_learning_rate"][str(r)])
    assert len(out["_test_pred"]) == 100 and out["test_mae"] > 0


def test_an_unknown_model_name_is_refused():
    with pytest.raises(ValueError):
        model_zoo.build("not_a_model", 0.1, 1.0)()


def test_the_reporting_rule_on_the_committed_results_picks_the_lowest_validation_mae():
    import json

    zoo = json.loads((config.BENCHMARKS_RAW_DIR / "b6_model_zoo.json").read_text(encoding="utf-8"))
    rule = zoo["reporting"]
    candidates = rule["candidates"]
    best = min(candidates, key=lambda k: candidates[k]["validation_mae"])
    assert rule["reported_model"] == best
    spark = {k: v for k, v in candidates.items() if v["library"] == "spark-mllib"}
    assert rule["best_spark_model_served_candidate"] == min(spark, key=lambda k: spark[k]["validation_mae"])


def test_the_study_prediction_files_merge_one_to_one_on_every_test_leg():
    frame = significance.load_predictions()
    assert len(frame) == 5274 and frame["leg_id"].is_unique
    for column in ("pred_backoff", "pred_v2_gbt", "pred_v3_gbt", "pred_lightgbm_l1_oldbase"):
        assert column in frame and frame[column].notna().all()


def test_the_interval_of_a_models_own_mae_contains_its_mae():
    rng = np.random.default_rng(9)
    y = rng.normal(0, 30, 600)
    pred = y + rng.normal(0, 20, 600)
    days = np.repeat(np.arange(6), 100)
    out = significance.model_mae_interval(y, pred, days, n_boot=400)
    assert out["ci_block_day"][0] <= out["mae"] <= out["ci_block_day"][1]
