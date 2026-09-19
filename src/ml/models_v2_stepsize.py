"""D-049's step-size fix for the v2 GBT, chosen on validation and scored once on test.

    python -m src.ml.models_v2_stepsize

D-049 read the saved v2 GBT and found MLlib's absolute-loss trees can move a prediction at
most `stepSize * (maxIter - 1)` minutes after the first tree: 9.95 minutes at 0.05. This
module runs exactly the procedure D-049 fixed before it was run:

1. Cut the training split chronologically again at the same fraction (`time_split`).
2. Fit GBT (`lossType="absolute"`, `maxIter=200`, `maxDepth=6`) at each `stepSize` in
   `STEP_SIZES` on the earlier part; score MAE on the later part.
3. Refit the winner on the full training split, score it once on test, and apply the
   adoption rule unchanged. The winner replaces the candidate whatever its test score.

The test split is not touched until step 3, and only for one model.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from pyspark.ml import PipelineModel
from pyspark.ml.regression import GBTRegressor

from src.common import config
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark
from src.ml.baselines import TARGET, time_split
from src.ml.models_v2 import (
    FEATURES_V2,
    MODELS_DIR,
    adoption_outcome,
    fit_residual,
    load_v2,
    predict,
    prepare,
    slice_table,
)

log = get_logger("ml.models_v2_stepsize")

#: Fixed by D-049. Nothing else varies.
STEP_SIZES = (0.05, 0.3, 1.0)
MAX_ITER, MAX_DEPTH = 200, 6

METRICS_CSV = config.BENCHMARKS_RAW_DIR / "w7_model_metrics_v2_stepsize.csv"
REPORT_JSON = config.BENCHMARKS_RAW_DIR / "w7_model_v2_stepsize_report.json"
MODEL_PATH = MODELS_DIR / "v2_gbt_residual_stepsize"


def gbt(step_size: float) -> GBTRegressor:
    return GBTRegressor(featuresCol="features_vec", labelCol="residual", lossType="absolute",
                        maxIter=MAX_ITER, maxDepth=MAX_DEPTH, stepSize=step_size, seed=42,
                        checkpointInterval=10)


def correction_cap(step_size: float) -> float:
    """The most MLlib's sign-fitted trees after the first can move one prediction, in minutes."""
    return round(step_size * (MAX_ITER - 1), 2)


def choose(validation_mae: dict[float, float]) -> float:
    """Lowest validation MAE; on an exact tie the smaller step, which is the more conservative."""
    return min(validation_mae, key=lambda step: (validation_mae[step], step))


def run(metrics_csv: Path = METRICS_CSV, report_json: Path = REPORT_JSON) -> dict:
    frame = load_v2()
    train_raw, test_raw, cutoff = time_split(frame)
    inner_raw, valid_raw, inner_cutoff = time_split(train_raw)
    train, test = prepare(train_raw), prepare(test_raw)
    inner, valid = prepare(inner_raw), prepare(valid_raw)
    log.info("validation: %s legs fit, %s legs scored (cut %s); test untouched", f"{len(inner):,}",
             f"{len(valid):,}", inner_cutoff)

    spark = get_spark("models-v2-stepsize")
    checkpoint_dir = config.SPARK_LOCAL_DIR / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    spark.sparkContext.setCheckpointDir(str(checkpoint_dir))
    validation_mae: dict[float, float] = {}
    try:
        y_valid = valid[TARGET].to_numpy()
        validation_mae[-1.0] = float(np.mean(np.abs(y_valid - valid["baseline_median"].to_numpy())))
        log.info("validation: corridor median MAE %.2f", validation_mae[-1.0])
        for step in STEP_SIZES:
            model = fit_residual(spark, inner, gbt(step))
            pred = valid["baseline_median"].to_numpy() + predict(spark, model, valid, FEATURES_V2)
            validation_mae[step] = float(np.mean(np.abs(y_valid - pred)))
            log.info("validation: stepSize %.2f -> MAE %.2f (correction cap %.2f min)", step,
                     validation_mae[step], correction_cap(step))
        median_valid = validation_mae.pop(-1.0)
        chosen = choose(validation_mae)
        log.info("chosen on validation: stepSize %.2f", chosen)

        final = fit_residual(spark, train, gbt(chosen))
        final.write().overwrite().save(str(MODEL_PATH))
        candidate = f"v2_gbt_residual_absolute_step{chosen:g}"
        predictions = {
            "corridor_median": test["baseline_median"].to_numpy(),
            "v2_gbt_residual_absolute": test["baseline_median"].to_numpy()
            + predict(spark, PipelineModel.load(str(MODELS_DIR / "v2_gbt_residual")), test, FEATURES_V2),
            candidate: test["baseline_median"].to_numpy() + predict(spark, final, test, FEATURES_V2),
        }
    finally:
        stop_spark(spark)

    table = slice_table(test, train, predictions)
    metrics_csv.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(metrics_csv, index=False)
    decision = adoption_outcome(table, candidate)
    overall = table[table["dimension"] == "overall"].set_index("model")["mae_min"].to_dict()
    support = table[(table["dimension"] == "corridor_support_in_train") & (table["model"] == candidate)]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": "D-049",
        "grid": {"stepSize": list(STEP_SIZES), "maxIter": MAX_ITER, "maxDepth": MAX_DEPTH, "lossType": "absolute"},
        "validation": {
            "n_fit": len(inner), "n_scored": len(valid), "cutoff": str(inner_cutoff),
            "corridor_median_mae_min": round(median_valid, 2),
            "mae_min_by_step_size": {f"{k:g}": round(v, 2) for k, v in validation_mae.items()},
            "correction_cap_min_by_step_size": {f"{k:g}": correction_cap(k) for k in STEP_SIZES},
            "chosen_step_size": chosen,
        },
        "test": {
            "n": len(test), "cutoff": str(cutoff), "overall_mae_min": overall,
            "candidate_delta_vs_median_by_support": support.set_index("slice")["delta_vs_median_min"].to_dict(),
        },
        "adoption": decision,
        "model_saved": str(MODEL_PATH.relative_to(config.REPO_ROOT)).replace("\\", "/"),
    }
    report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("test overall MAE: %s", overall)
    log.info("D-049 rule on the validation-chosen model: outcome %d -- %s", decision["outcome"], decision["action"])
    return report


if __name__ == "__main__":
    print(json.dumps(run()["adoption"], indent=2))
