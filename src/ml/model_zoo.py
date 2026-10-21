"""Stronger single-node baselines, the reporting rule, and a feature-group ablation (D-077, upgrade B6).

    python -m src.ml.model_zoo               # fits the zoo, applies the reporting rule, runs the ablation

Why. A single-node `HistGradientBoostingRegressor` (29.52 on test) beats the reported MLlib model (30.90)
and the paper called it "not a candidate" without a reason; there was no LightGBM or XGBoost either.
Here every boosted model gets the **same budget** (200 trees, depth 6, three learning rates chosen on the
validation cut only) on the **same split, residual target and inputs** as the Spark v3 model, and the
**reporting rule** of D-077 is applied: the reported model is the one with the lowest *validation* MAE
regardless of library. Nothing is labelled "not a candidate"; every model is in the results with its
validation and test MAE.

Two settings are run so the 29.52 question is settled on equal footing:

* **primary**  the 40 inputs of v3 over the back-off baseline D-075 chose;
* **secondary** the 38 inputs of v2 over the old median (0.0 on a cold corridor), exactly v2's setting.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger
from src.ml import backoff_baseline as bb
from src.ml import significance as sig
from src.ml.baselines import TARGET, time_split
from src.ml.models_v2 import FEATURES_V2
from src.ml.models_v3 import EXTRA_FEATURES, FEATURES_V3, baseline_columns, prepare_v3

log = get_logger("ml.model_zoo")

RAW = config.BENCHMARKS_RAW_DIR
OUT_JSON = RAW / "b6_model_zoo.json"
OUT_TEST = RAW / "b6_test_predictions.csv"
OUT_ABLATION = RAW / "b6_feature_ablation.json"
LEARNING_RATES = (0.03, 0.1, 0.3)
N_TREES, DEPTH, SEED = 200, 6, 42

#: Feature groups for the ablation (D-077). The v1 inputs are named by prefix in `src.ml.baselines`.
GROUPS: dict[str, list[str]] = {
    "plan_and_route": ["planned_min", "is_ftl"],
    "distance": ["planned_km"],
    "time": ["created_hour", "created_dayofweek", "created_is_weekend"],
    "corridor_history": [c for c in FEATURES_V2 if c.startswith("corr_") and c not in
                         ("corr_median_gap_min", "corr_p90_gap_min", "corr_iqr_gap_min", "corr_std_gap_min",
                          "corr_mean_gap_7d", "corr_n_prior_7d", "corr_7d_is_cold")],
    "hub_history": [c for c in FEATURES_V2 if c.startswith(("src_", "dst_")) and "dwell" not in c],
    "v2_dispersion_and_dwell": ["corr_median_gap_min", "corr_p90_gap_min", "corr_iqr_gap_min", "corr_std_gap_min",
                                "corr_mean_gap_7d", "corr_n_prior_7d", "src_dwell_by_hour_min", "dst_dwell_by_hour_min",
                                "corr_7d_is_cold", "src_dwell_is_cold", "dst_dwell_is_cold"],
    "baseline_descriptors": list(EXTRA_FEATURES),
}


def build(name: str, rate: float, huber_delta: float) -> Callable[[], object]:
    """A fresh, unfitted model for `name` at learning rate `rate`."""
    def make() -> object:
        if name == "lightgbm_l1":
            import lightgbm as lgb

            return lgb.LGBMRegressor(objective="l1", n_estimators=N_TREES, max_depth=DEPTH, num_leaves=2 ** DEPTH,
                                     learning_rate=rate, random_state=SEED, verbose=-1, n_jobs=8)
        if name == "lightgbm_huber":
            import lightgbm as lgb

            return lgb.LGBMRegressor(objective="huber", alpha=huber_delta, n_estimators=N_TREES, max_depth=DEPTH,
                                     num_leaves=2 ** DEPTH, learning_rate=rate, random_state=SEED, verbose=-1, n_jobs=8)
        if name == "xgboost_l1":
            import xgboost as xgb

            return xgb.XGBRegressor(objective="reg:absoluteerror", n_estimators=N_TREES, max_depth=DEPTH,
                                    learning_rate=rate, tree_method="hist", random_state=SEED, n_jobs=8)
        if name == "histgbr_l1":
            from sklearn.ensemble import HistGradientBoostingRegressor

            return HistGradientBoostingRegressor(loss="absolute_error", max_iter=N_TREES, max_depth=DEPTH,
                                                 learning_rate=rate, random_state=SEED)
        raise ValueError(name)
    return make


BOOSTED = ("lightgbm_l1", "lightgbm_huber", "xgboost_l1", "histgbr_l1")


def fit_predict_linear(train: pd.DataFrame, others: list[pd.DataFrame], features: list[str]) -> list[np.ndarray]:
    """Linear median regression on standardised inputs; no hyperparameter, so no validation search."""
    from sklearn.linear_model import QuantileRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    model = make_pipeline(StandardScaler(), QuantileRegressor(quantile=0.5, alpha=0.0, solver="highs"))
    model.fit(train[features], train["residual"])
    return [model.predict(frame[features]) for frame in others]


def fit_boosted(name: str, rate: float, huber_delta: float, train: pd.DataFrame, others: list[pd.DataFrame],
                features: list[str]) -> list[np.ndarray]:
    model = build(name, rate, huber_delta)()
    model.fit(train[features], train["residual"])  # type: ignore[attr-defined]
    return [np.asarray(model.predict(frame[features])) for frame in others]  # type: ignore[attr-defined]


def select_and_score(name: str, features: list[str], inner: pd.DataFrame, valid: pd.DataFrame,
                     train: pd.DataFrame, test: pd.DataFrame) -> dict:
    """D-049's protocol for one model: pick the rate on validation, refit on train, score test once."""
    y_valid, y_test = valid[TARGET].to_numpy(), test[TARGET].to_numpy()
    started = time.monotonic()
    if name == "quantile_linear":
        (valid_res,) = fit_predict_linear(inner, [valid], features)
        (test_res,) = fit_predict_linear(train, [test], features)
        choice: float | None = None
        grid: dict[float, float] = {}
        valid_pred = valid["baseline_gap"].to_numpy() + valid_res
    else:
        delta = float(np.median(np.abs(inner["residual"] - inner["residual"].median())))
        grid = {}
        for rate in LEARNING_RATES:
            (res,) = fit_boosted(name, rate, delta, inner, [valid], features)
            grid[rate] = float(np.mean(np.abs(y_valid - (valid["baseline_gap"].to_numpy() + res))))
        choice = min(LEARNING_RATES, key=lambda r: (grid[r], r))
        (valid_res,) = fit_boosted(name, choice, delta, inner, [valid], features)
        valid_pred = valid["baseline_gap"].to_numpy() + valid_res
        (test_res,) = fit_boosted(name, choice, float(np.median(np.abs(train["residual"] - train["residual"].median()))),
                                  train, [test], features)
    test_pred = test["baseline_gap"].to_numpy() + test_res
    return {
        "validation_mae_by_learning_rate": {str(k): round(v, 4) for k, v in grid.items()},
        "learning_rate_chosen": choice,
        "validation_mae": round(float(np.mean(np.abs(y_valid - valid_pred))), 4),
        "test_mae": round(float(np.mean(np.abs(y_test - test_pred))), 4),
        "seconds": round(time.monotonic() - started, 1),
        "_valid_pred": valid_pred, "_test_pred": test_pred,
    }


def frames(setting: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    """(inner, valid, train, test, features) with `baseline_gap` and `residual` for one setting."""
    rule = json.loads((RAW / "b1_backoff_baseline.json").read_text(encoding="utf-8"))
    frame = bb.load_legs()
    train_raw, test_raw, _ = time_split(frame)
    inner_raw, valid_raw, _ = time_split(train_raw)
    cuts = tuple(rule["distance_band_cuts_km"])
    stats = bb.level_statistics(frame, (cuts[0], cuts[1]))
    hard = bb.hard_backoff(stats)
    name = rule["v3_baseline"]["name"] if setting == "primary" else "old_median"
    columns = baseline_columns(frame, name, stats, hard, rule["k_chosen"])
    position = {leg: i for i, leg in enumerate(frame["leg_id"])}

    def part(raw: pd.DataFrame) -> pd.DataFrame:
        rows = np.array([position[leg] for leg in raw["leg_id"]])
        return prepare_v3(raw, columns.iloc[rows].reset_index(drop=True))

    features = list(FEATURES_V3) if setting == "primary" else list(FEATURES_V2)
    return part(inner_raw), part(valid_raw), part(train_raw), part(test_raw), features


def run_setting(setting: str) -> dict:
    inner, valid, train, test, features = frames(setting)
    results = {}
    for name in (*BOOSTED, "quantile_linear"):
        results[name] = select_and_score(name, features, inner, valid, train, test)
        log.info("[%s] %-16s validation %.4f test %.4f (%.0fs) rate %s", setting, name,
                 results[name]["validation_mae"], results[name]["test_mae"], results[name]["seconds"],
                 results[name]["learning_rate_chosen"])
    return {"results": results, "test": test, "valid": valid, "train": train, "inner": inner, "features": features}


def reporting_rule(primary: dict, secondary: dict) -> dict:
    """D-077: the reported model is the lowest validation MAE regardless of library."""
    v2 = json.loads((RAW / "w7_model_v2_stepsize_report.json").read_text(encoding="utf-8"))
    v3 = json.loads((RAW / "b1_model_v3.json").read_text(encoding="utf-8"))
    candidates: dict[str, dict] = {
        "spark_v2_gbt (old median, step 1.0)": {"validation_mae": float(v2["validation"]["mae_min_by_step_size"]["1"]),
                                                "test_mae": float(v2["test"]["overall_mae_min"]["v2_gbt_residual_absolute_step1"]),
                                                "library": "spark-mllib", "setting": "v2"},
        "spark_v3_gbt (back-off baseline)": {"validation_mae": float(v3["validation_mae"]["v3_gbt"]),
                                             "test_mae": float(v3["test_mae"]["v3_gbt"]), "library": "spark-mllib",
                                             "setting": "primary"},
    }
    for setting, block in (("primary", primary), ("secondary_old_median", secondary)):
        for name, r in block["results"].items():
            candidates[f"{name} ({setting})"] = {"validation_mae": r["validation_mae"], "test_mae": r["test_mae"],
                                                 "library": "single-node", "setting": setting}
    reported = min(candidates, key=lambda k: candidates[k]["validation_mae"])
    best_spark = min((k for k in candidates if candidates[k]["library"] == "spark-mllib"),
                     key=lambda k: candidates[k]["validation_mae"])
    return {"candidates": candidates, "reported_model": reported, "reported_library": candidates[reported]["library"],
            "best_spark_model_served_candidate": best_spark,
            "rule": "lowest validation MAE regardless of library (D-077); test MAE is reported whatever it is"}


def ablation(primary: dict, reported_choice: str) -> dict:
    """Drop one feature group at a time from the best single-node boosted model of the primary setting."""
    block = primary["results"]
    best = min(BOOSTED, key=lambda m: block[m]["validation_mae"])
    rate = block[best]["learning_rate_chosen"]
    train, test, features = primary["train"], primary["test"], primary["features"]
    delta = float(np.median(np.abs(train["residual"] - train["residual"].median())))
    y = test[TARGET].to_numpy()
    full = block[best]["_test_pred"]
    days = sig.day_blocks(test["trip_creation_time"])
    out = {"model": best, "learning_rate": rate, "test_mae_full": block[best]["test_mae"], "groups": {}}
    for group, columns in GROUPS.items():
        kept = [f for f in features if f not in columns]
        (res,) = fit_boosted(best, rate, delta, train, [test], kept)
        pred = test["baseline_gap"].to_numpy() + res
        d = np.abs(y - pred) - np.abs(y - full)
        lo, hi = sig.interval(sig.block_bootstrap(d, days, sig.N_BOOT, sig.SEED))
        out["groups"][group] = {"features_removed": [c for c in columns if c in features], "test_mae_without": round(float(np.mean(np.abs(y - pred))), 4),
                                "delta_mae": round(float(d.mean()), 4), "ci_block_day": [round(lo, 4), round(hi, 4)],
                                "interval_excludes_zero": bool(hi < 0 or lo > 0)}
        log.info("ablation %-24s ΔMAE %+.3f [%.3f, %.3f]", group, d.mean(), lo, hi)
    out["reported_model_for_context"] = reported_choice
    return out


def run() -> dict:
    primary = run_setting("primary")
    secondary = run_setting("secondary")
    rule = reporting_rule(primary, secondary)

    def clean(block: dict) -> dict:
        return {name: {k: v for k, v in r.items() if not k.startswith("_")} for name, r in block["results"].items()}

    predictions = pd.DataFrame({"leg_id": primary["test"]["leg_id"]})
    for name, r in primary["results"].items():
        predictions[f"pred_{name}"] = r["_test_pred"]
    for name, r in secondary["results"].items():
        predictions[f"pred_{name}_oldbase"] = r["_test_pred"]
    predictions.to_csv(OUT_TEST, index=False)

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "decision": "D-077",
        "budget": {"trees": N_TREES, "depth": DEPTH, "learning_rates": list(LEARNING_RATES), "seed": SEED},
        "primary_setting": "40 inputs (v3) over the back-off baseline",
        "secondary_setting": "38 inputs (v2) over the old median, 0.0 on a cold corridor",
        "primary": clean(primary), "secondary": clean(secondary),
        "reporting": rule,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    OUT_ABLATION.write_text(json.dumps(ablation(primary, rule["reported_model"]), indent=2), encoding="utf-8")
    log.info("reported model by the D-077 rule: %s", rule["reported_model"])
    return report


def main() -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    for name in ("b1_backoff_baseline.json", "b1_model_v3.json"):
        if not (RAW / name).exists():
            log.error("Missing %s -- run the B1 stages first (backoff_baseline, models_v3).", name)
            return 1
    report = run()
    print(json.dumps(report["reporting"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
