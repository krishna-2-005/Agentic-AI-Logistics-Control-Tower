"""The residual GBT over the hierarchical back-off baseline (D-075, rules 2 and 3).

    python -m src.ml.models_v3                    # select on validation, refit, score once on test

Same learner as v2 (`src.ml.models_v2_stepsize.gbt`: MLlib, absolute loss, 200 trees, depth 6), same
chronological split, same selection protocol (D-049): the step size is chosen on the validation cut
inside the training split, the chosen model is refit on the full training split and scored **once**
on test. What changes is the thing the model corrects. v2 corrected the corridor median, which is
0.0 on a corridor with no history; v3 corrects the baseline D-075 rule 2 names (read from
`b1_backoff_baseline.json`, never typed here), and gets two more inputs, as-of descriptors of that
baseline: the level it fell back to (1 corridor ... 5 network) and its prior-leg count.

Rule 3 is applied at the end and written to the results file: of v2 and v3, the lower **validation**
MAE is "the reported model", whatever the test numbers say.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark
from src.ml import backoff_baseline as bb
from src.ml.baselines import TARGET, time_split
from src.ml.models_v2 import FEATURES_V2, predict, prepare_serving
from src.ml.models_v2_stepsize import STEP_SIZES, choose, gbt

log = get_logger("ml.models_v3")

RAW = config.BENCHMARKS_RAW_DIR
MODEL_PATH = config.MODELS_DIR / "v3_gbt_residual_backoff"
OUT_JSON = RAW / "b1_model_v3.json"
OUT_TEST = RAW / "b1_v3_test_predictions.csv"
OUT_VALIDATION = RAW / "b1_v3_validation_predictions.csv"
EXTRA_FEATURES = ["baseline_level", "baseline_n"]
FEATURES_V3 = FEATURES_V2 + EXTRA_FEATURES
V2_REPORT = RAW / "w7_model_v2_stepsize_report.json"


def baseline_columns(frame: pd.DataFrame, name: str, stats, hard: pd.DataFrame, k: float) -> pd.DataFrame:
    """`baseline_gap`, `baseline_level`, `baseline_n` for the baseline D-075 rule 2 chose."""
    if name == "backoff":
        return pd.DataFrame({"baseline_gap": hard["backoff_gap"].to_numpy(), "baseline_level": hard["backoff_level"].to_numpy(),
                             "baseline_n": hard["backoff_n"].to_numpy()})
    if name == "shrunk_backoff":
        return pd.DataFrame({"baseline_gap": bb.shrunken_backoff(stats, k), "baseline_level": hard["backoff_level"].to_numpy(),
                             "baseline_n": hard["backoff_n"].to_numpy()})
    old = bb.old_median(frame)
    return pd.DataFrame({"baseline_gap": old, "baseline_level": np.where(frame["corr_n_prior"] == 0, 0, 1),
                         "baseline_n": frame["corr_n_prior"].to_numpy()})


def prepare_v3(frame: pd.DataFrame, columns: pd.DataFrame) -> pd.DataFrame:
    out = prepare_serving(frame).reset_index(drop=True)
    for column in ("baseline_gap", *EXTRA_FEATURES):
        out[column] = columns[column].to_numpy()
    out["residual"] = out[TARGET] - out["baseline_gap"]
    return out


def fit(spark, train: pd.DataFrame, step: float):
    from pyspark.ml import Pipeline
    from pyspark.ml.feature import VectorAssembler

    pipeline = Pipeline(stages=[VectorAssembler(inputCols=FEATURES_V3, outputCol="features_vec"), gbt(step)])
    return pipeline.fit(spark.createDataFrame(train[FEATURES_V3 + ["residual"]]))


def run() -> dict:
    rule = json.loads((RAW / "b1_backoff_baseline.json").read_text(encoding="utf-8"))
    base_name, k_star = rule["v3_baseline"]["name"], rule["k_chosen"]
    frame = bb.load_legs()
    train_raw, test_raw, cutoff = time_split(frame)
    inner_raw, valid_raw, _ = time_split(train_raw)
    cuts = tuple(rule["distance_band_cuts_km"])
    stats = bb.level_statistics(frame, (cuts[0], cuts[1]))
    columns = baseline_columns(frame, base_name, stats, bb.hard_backoff(stats), k_star)
    position = {leg: i for i, leg in enumerate(frame["leg_id"])}

    def part(raw: pd.DataFrame) -> pd.DataFrame:
        rows = np.array([position[leg] for leg in raw["leg_id"]])
        return prepare_v3(raw, columns.iloc[rows].reset_index(drop=True))

    train, inner, valid, test = part(train_raw), part(inner_raw), part(valid_raw), part(test_raw)
    log.info("baseline under the residual: %s | fit %s, validate %s, train %s, test %s", base_name,
             f"{len(inner):,}", f"{len(valid):,}", f"{len(train):,}", f"{len(test):,}")

    spark = get_spark("models-v3")
    checkpoint_dir = config.SPARK_LOCAL_DIR / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    spark.sparkContext.setCheckpointDir(str(checkpoint_dir))
    validation_mae: dict[float, float] = {}
    try:
        y_valid = valid[TARGET].to_numpy()
        for step in STEP_SIZES:
            model = fit(spark, inner, step)
            pred = valid["baseline_gap"].to_numpy() + predict(spark, model, valid, FEATURES_V3)
            validation_mae[step] = float(np.mean(np.abs(y_valid - pred)))
            log.info("validation: stepSize %.2f -> MAE %.4f", step, validation_mae[step])
        chosen = choose(validation_mae)
        valid_pred = valid["baseline_gap"].to_numpy() + predict(spark, fit(spark, inner, chosen), valid, FEATURES_V3)
        final = fit(spark, train, chosen)
        final.write().overwrite().save(str(MODEL_PATH))
        test_pred = test["baseline_gap"].to_numpy() + predict(spark, final, test, FEATURES_V3)
    finally:
        stop_spark(spark)

    y_test = test[TARGET].to_numpy()
    v2 = json.loads(V2_REPORT.read_text(encoding="utf-8"))
    v2_validation = float(v2["validation"]["mae_min_by_step_size"]["1"])
    v3_validation = validation_mae[chosen]
    reported = "v3" if v3_validation < v2_validation else "v2"
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "decision": "D-075",
        "baseline_under_residual": base_name,
        "features": {"v2": len(FEATURES_V2), "v3": len(FEATURES_V3), "extra": EXTRA_FEATURES},
        "step_sizes": list(STEP_SIZES),
        "validation_mae_by_step_size": {str(k): round(v, 4) for k, v in validation_mae.items()},
        "step_size_chosen": chosen,
        "validation_mae": {"baseline": round(float(np.mean(np.abs(y_valid - valid["baseline_gap"].to_numpy()))), 4),
                           "v2_gbt_step1": v2_validation, "v3_gbt": round(v3_validation, 4)},
        "test_mae": {"baseline": round(float(np.mean(np.abs(y_test - test["baseline_gap"].to_numpy()))), 4),
                     "v3_gbt": round(float(np.mean(np.abs(y_test - test_pred))), 4)},
        "test_cutoff": str(cutoff),
        "reported_model": reported,
        "reported_rule": "lower validation MAE of v2 and v3, whatever the test numbers say (D-075 rule 3)",
        "model_saved": "data/models/v3_gbt_residual_backoff",
    }
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    pd.DataFrame({"leg_id": test["leg_id"], "pred_v3_gbt": test_pred}).to_csv(OUT_TEST, index=False)
    pd.DataFrame({"leg_id": valid["leg_id"], "pred_v3_gbt": valid_pred}).to_csv(OUT_VALIDATION, index=False)
    log.info("v3: validation %.4f (v2 %.2f), test %.4f -> reported model: %s",
             v3_validation, v2_validation, report["test_mae"]["v3_gbt"], reported)
    return report


def main() -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    if not (RAW / "b1_backoff_baseline.json").exists():
        log.error("Run `python -m src.ml.backoff_baseline` first: it names the baseline this model corrects.")
        return 1
    report = run()
    print(json.dumps({k: report[k] for k in ("step_size_chosen", "validation_mae", "test_mae", "reported_model")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
