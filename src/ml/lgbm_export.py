"""Serve the reported LightGBM model through the numpy tree reader (D-101, upgrade B12).

    python -m src.ml.lgbm_export            # refit, export, verify on every leg, write the evidence file
    python -m src.ml.lgbm_export --check    # exit 1 unless the committed evidence says every leg is identical

The reported model (D-077) is LightGBM with L1 loss over the old median, on the same 38 inputs the served Spark v2 model
reads, so the serving features and the history state do not change; only the trees do. This refits it with the settings
D-077 chose, flattens the booster's trees into the `gbt_local.Forest` arrays (all weights 1, leaf values as LightGBM stores
them, summed left to right in float64 as LightGBM sums), and requires the reader to reproduce `booster.predict` **exactly** on
all 26,369 legs of `features_v2`. Writes `data/serving/lgbm_forest.json.gz` (the file the API and the stream read) and
`benchmarks/raw/b13_lgbm_serving_equivalence.json`.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger
from src.ml import gbt_local, model_zoo, serving
from src.ml.baselines import TARGET
from src.ml.models_v2 import FEATURES_V2

log = get_logger("ml.lgbm_export")

RAW = config.BENCHMARKS_RAW_DIR
EVIDENCE = RAW / "b13_lgbm_serving_equivalence.json"
FOREST_FILE = config.DATA_DIR / "serving" / "lgbm_forest.json.gz"
MODEL = "lightgbm_l1"
LEARNING_RATE = 0.03
SERVED_ID = "lightgbm_l1_residual_old_median"
EXPECTED_TEST_MAE = 29.6578


def flatten(booster) -> gbt_local.Forest:
    """The booster's trees as flat node arrays, children as global indices, leaves marked with feature -1."""
    info = booster.dump_model()
    names = list(info["feature_names"])
    feature: list[int] = []
    threshold: list[float] = []
    left: list[int] = []
    right: list[int] = []
    value: list[float] = []
    roots: list[int] = []

    def add(node: dict) -> int:
        index = len(feature)
        feature.append(-1)
        threshold.append(0.0)
        left.append(-1)
        right.append(-1)
        value.append(0.0)
        if "leaf_value" in node:
            value[index] = float(node["leaf_value"])
            return index
        if node["decision_type"] != "<=":
            raise ValueError(f"unsupported decision type {node['decision_type']!r}: this reader walks continuous splits only")
        if node.get("missing_type", "None") not in ("None",):
            raise ValueError("the model learned a missing-value rule; the served inputs have no missing values")
        feature[index] = int(node["split_feature"])
        threshold[index] = float(node["threshold"])
        left[index] = add(node["left_child"])
        right[index] = add(node["right_child"])
        return index

    for tree in info["tree_info"]:
        roots.append(add(tree["tree_structure"]))
    return gbt_local.Forest(
        names, np.ones(len(roots)), np.array(feature), np.array(threshold), np.array(left), np.array(right),
        np.array(value), np.array(roots), summation="sequential")


def refit():
    inner, valid, train, test, features = model_zoo.frames("secondary")
    if list(features) != list(FEATURES_V2):
        raise AssertionError("the zoo's secondary setting no longer uses the 38 v2 inputs")
    delta = float(np.median(np.abs(train["residual"] - train["residual"].median())))
    model = model_zoo.build(MODEL, LEARNING_RATE, delta)()
    model.fit(train[features], train["residual"])  # type: ignore[attr-defined]
    prediction = test["baseline_gap"].to_numpy() + np.asarray(model.predict(test[features]))  # type: ignore[attr-defined]
    mae = float(np.mean(np.abs(test[TARGET].to_numpy() - prediction)))
    if round(mae, 4) != EXPECTED_TEST_MAE:
        raise AssertionError(f"refit test MAE {mae:.4f} does not reproduce the zoo's {EXPECTED_TEST_MAE}")
    return model.booster_, mae


def run() -> dict:
    booster, test_mae = refit()
    forest = flatten(booster)
    gbt_local.to_json(forest, FOREST_FILE)
    forest = gbt_local.from_json(FOREST_FILE)  # verified through the file the host reads, not the in-memory original
    frame = pd.read_parquet(config.FEATURES_V2)
    prepared = serving.prepare(frame)
    x = prepared[FEATURES_V2]
    reference = np.asarray(booster.predict(x))
    local = gbt_local.predict(forest, prepared)
    diff = np.abs(local - reference)
    report = {
        "generated_at": datetime.now(UTC).isoformat(), "decision": "D-101", "model": SERVED_ID,
        "settings": {"objective": "l1", "trees": len(forest.roots), "learning_rate": LEARNING_RATE},
        "nodes": int(len(forest.value)), "legs": int(len(frame)),
        "refit_test_mae": round(test_mae, 4), "summation": forest.summation,
        "identical_predictions": int((diff == 0).sum()), "max_abs_difference_min": float(diff.max()),
        "verified_through": "data/serving/lgbm_forest.json.gz (the file the API and the stream read)",
    }
    EVIDENCE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        d = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        return 0 if d["identical_predictions"] == d["legs"] else 1
    report = run()
    print(json.dumps(report, indent=2))
    return 0 if report["identical_predictions"] == report["legs"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
