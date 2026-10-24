"""The LightGBM forest and the served-model switch (D-101). No data files.

    pytest tests/test_lgbm_serving.py -q
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

lightgbm = pytest.importorskip("lightgbm")

from src.ml import gbt_local, lgbm_export  # noqa: E402


@pytest.fixture(scope="module")
def booster_and_data():
    rng = np.random.default_rng(0)
    x = pd.DataFrame(rng.normal(size=(400, 5)), columns=list("abcde"))
    y = 3 * x["a"] - 2 * (x["b"] > 0) + rng.normal(scale=0.3, size=400) + 50
    model = lightgbm.LGBMRegressor(objective="l1", n_estimators=30, max_depth=4, num_leaves=15, learning_rate=0.1,
                                   random_state=1, verbose=-1)
    model.fit(x, y)
    return model.booster_, x


def test_the_flattened_forest_reproduces_the_booster_exactly(booster_and_data):
    booster, x = booster_and_data
    forest = lgbm_export.flatten(booster)
    assert forest.summation == "sequential" and len(forest.roots) == 30
    assert np.array_equal(gbt_local.predict(forest, x), booster.predict(x))


def test_the_forest_survives_a_round_trip_through_the_json_file(booster_and_data, tmp_path):
    booster, x = booster_and_data
    forest = lgbm_export.flatten(booster)
    gbt_local.to_json(forest, tmp_path / "f.json.gz")
    back = gbt_local.from_json(tmp_path / "f.json.gz")
    assert back.summation == "sequential"
    assert np.array_equal(gbt_local.predict(back, x), booster.predict(x))


def test_a_spark_forest_file_without_a_summation_key_still_loads_as_lanes4(tmp_path):
    forest = gbt_local.Forest(["a"], np.ones(1), np.array([-1]), np.array([0.0]), np.array([-1]), np.array([-1]),
                              np.array([2.0]), np.array([0]))
    gbt_local.to_json(forest, tmp_path / "g.json.gz")
    import gzip
    import json

    with gzip.open(tmp_path / "g.json.gz", "rt", encoding="utf-8") as handle:
        raw = json.load(handle)
    raw.pop("summation")
    with gzip.open(tmp_path / "g.json.gz", "wt", encoding="utf-8") as handle:
        json.dump(raw, handle)
    assert gbt_local.from_json(tmp_path / "g.json.gz").summation == "lanes4"


def test_a_model_with_a_categorical_split_is_refused():
    node = {"split_feature": 0, "threshold": "1||2", "decision_type": "==", "left_child": {"leaf_value": 1.0},
            "right_child": {"leaf_value": 2.0}}

    class Fake:
        def dump_model(self):
            return {"feature_names": ["a"], "tree_info": [{"tree_structure": node}]}

    with pytest.raises(ValueError, match="continuous splits only"):
        lgbm_export.flatten(Fake())
