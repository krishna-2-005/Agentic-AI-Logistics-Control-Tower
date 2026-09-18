"""ML correction sprint (execution plan v3.1 §2.1 Steps 3-5, G-04) -- residual learning.

    python -m src.ml.models_v2

Changes what the model is asked. Not "how long will this leg take", but "how wrong will
the corridor baseline be": train on `gap_min - baseline` and add the baseline back at
prediction time. A model that learns nothing predicts zero and reproduces the baseline
exactly; anything it does learn is gain on top.

Three things this module holds fixed, because D-048 decided them before any code
----------------------------------------------------------------------------------
* **The baseline is the per-corridor median, not the mean.** D-048 found the median
  scores 33.04 min on the test split against the mean's 36.13, and MAE is minimised by
  the median. Residual learning over the weaker baseline would be choosing the comparison
  after seeing it. Cold corridors fall back to zero gap -- the OSRM plan -- exactly as the
  D-048 baseline did, so the bar here is the bar that was measured.
* **The bar is 33.04, not 36.1.** v3.1 wrote its adoption rule against the mean; the rule
  below is applied against the median.
* **GBT trains on absolute loss.** The single-node reference moved 5.1 minutes between
  squared and absolute loss on the same features; MLlib's Random Forest cannot change its
  objective, so it is trained too and expected to lose.

The judge check
---------------
Before anything trains, v2's `corr_median_gap_min` (Mounika's Spark implementation) is
compared with `src.ml.ml_diagnostics`' pandas median over the same as-of history (itself
verified at 100% against v1). Training refuses unless they agree on every warm leg.

Nothing in `data/models/champion` is replaced. The v2 models are saved beside it; which
becomes the reported model is D-049's decision, made from the slice table this writes.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from pyspark.ml import Pipeline, PipelineModel
from pyspark.ml.feature import VectorAssembler
from pyspark.ml.regression import GBTRegressor, RandomForestRegressor
from sklearn.ensemble import HistGradientBoostingRegressor

from src.common import config
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark
from src.ml.baselines import (
    FEATURES,
    TARGET,
    corridor_mean_predictions,
    osrm_predictions,
    prepare_model_features,
    time_split,
)

log = get_logger("ml.models_v2")

V2_COLUMNS = [
    "corr_median_gap_min", "corr_p90_gap_min", "corr_iqr_gap_min", "corr_std_gap_min",
    "corr_mean_gap_7d", "corr_n_prior_7d", "src_dwell_by_hour_min", "dst_dwell_by_hour_min",
]
#: Indicators for the v2 columns that can be empty on a warm corridor. D-023's rule: a
#: zero fill must say "unknown", never "known and zero".
V2_INDICATORS = {"corr_mean_gap_7d": "corr_7d_is_cold", "src_dwell_by_hour_min": "src_dwell_is_cold",
                 "dst_dwell_by_hour_min": "dst_dwell_is_cold"}
FEATURES_V2 = FEATURES + V2_COLUMNS + list(V2_INDICATORS.values())

METRICS_CSV = config.BENCHMARKS_RAW_DIR / "w7_model_metrics_v2.csv"
REPORT_JSON = config.BENCHMARKS_RAW_DIR / "w7_model_v2_report.json"
MODELS_DIR = config.MODELS_DIR

#: "Tie" for the adoption rule: within 1% of the median baseline's overall MAE. Stated as
#: a number because "ties overall" with no tolerance would be decided after the fact.
TIE_TOLERANCE = 0.01

SUPPORT_SLICES = (("unseen", 0, 0), ("1-9", 1, 9), ("10-29", 10, 29), (">=30", 30, 10**9))
HOUR_SLICES = {"night": (0, 5), "morning": (6, 11), "afternoon": (12, 17), "evening": (18, 23)}


def load_v2(path: Path = config.FEATURES_V2) -> pd.DataFrame:
    return pd.read_parquet(path).sort_values("trip_creation_time").reset_index(drop=True)


def judge_median(frame: pd.DataFrame) -> dict:
    """Mounika's Spark median against Lahari's pandas median, on every warm leg."""
    from src.ml.ml_diagnostics import as_of_corridor_stats
    from src.ml.ml_diagnostics import load_legs as load_diag_legs

    diag = load_diag_legs()
    diag = diag.join(as_of_corridor_stats(diag))[["leg_id", "median_asof"]]
    merged = frame[["leg_id", "corr_n_prior", "corr_median_gap_min"]].merge(diag, on="leg_id", how="inner")
    warm = merged[merged["corr_n_prior"] > 0]
    agree = float(((warm["corr_median_gap_min"] - warm["median_asof"]).abs() <= 1e-6).mean())
    if agree < 1.0:
        raise ValueError(f"v2 corridor median agrees with the independent recomputation on only {agree:.2%} "
                         "of warm legs; refusing to train on a baseline two implementations disagree about.")
    return {"warm_legs_compared": len(warm), "agreement": agree}


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    out = prepare_model_features(frame)
    for column, indicator in V2_INDICATORS.items():
        out[indicator] = out[column].isna().astype(int)
    for column in V2_COLUMNS:
        out[column] = out[column].fillna(0.0)
    cold = out["corr_n_prior"] == 0
    out["baseline_median"] = np.where(cold, 0.0, out["corr_median_gap_min"])
    out["residual"] = out[TARGET] - out["baseline_median"]
    return out


def fit_residual(spark, train: pd.DataFrame, estimator) -> PipelineModel:
    assembler = VectorAssembler(inputCols=FEATURES_V2, outputCol="features_vec")
    pipeline = Pipeline(stages=[assembler, estimator])
    sdf = spark.createDataFrame(train[FEATURES_V2 + ["residual"]])
    return pipeline.fit(sdf)


def predict(spark, model: PipelineModel, frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
    """Predictions in `frame`'s order -- Spark does not promise `toPandas()` keeps it."""
    sdf = spark.createDataFrame(frame[columns].assign(_row=np.arange(len(frame))))
    out = model.transform(sdf).select("_row", "prediction").toPandas().sort_values("_row")
    return out["prediction"].to_numpy()


def slice_masks(test: pd.DataFrame, train: pd.DataFrame) -> dict[str, dict[str, np.ndarray]]:
    support = test["corridor_id"].map(train["corridor_id"].value_counts()).fillna(0).to_numpy()
    km_cuts = np.quantile(train["planned_km"], [1 / 3, 2 / 3])
    km = test["planned_km"].to_numpy()
    hour = test["created_hour"].to_numpy()
    return {
        "overall": {"all": np.ones(len(test), dtype=bool)},
        "corridor_support_in_train": {name: (support >= lo) & (support <= hi) for name, lo, hi in SUPPORT_SLICES},
        "route_type": {rt: (test["route_type"] == rt).to_numpy() for rt in ("FTL", "Carting")},
        "distance_band": {
            f"short (<{km_cuts[0]:.0f} km)": km < km_cuts[0],
            f"medium ({km_cuts[0]:.0f}-{km_cuts[1]:.0f} km)": (km >= km_cuts[0]) & (km < km_cuts[1]),
            f"long (>={km_cuts[1]:.0f} km)": km >= km_cuts[1],
        },
        "departure_hour": {name: (hour >= lo) & (hour <= hi) for name, (lo, hi) in HOUR_SLICES.items()},
    }


def slice_table(test: pd.DataFrame, train: pd.DataFrame, predictions: dict[str, np.ndarray]) -> pd.DataFrame:
    y = test[TARGET].to_numpy()
    rows = []
    for dimension, slices in slice_masks(test, train).items():
        for name, mask in slices.items():
            if not mask.any():
                continue
            baseline = float(np.mean(np.abs(y[mask] - predictions["corridor_median"][mask])))
            for model, pred in predictions.items():
                mae = float(np.mean(np.abs(y[mask] - pred[mask])))
                rows.append({
                    "dimension": dimension, "slice": name, "n": int(mask.sum()), "model": model,
                    "mae_min": round(mae, 2),
                    "median_baseline_mae_min": round(baseline, 2),
                    "delta_vs_median_min": round(mae - baseline, 2),
                })
    return pd.DataFrame(rows)


def adoption_outcome(table: pd.DataFrame, candidate: str) -> dict:
    """v3.1 §2.1 Step 5, applied against the median bar (D-048)."""
    overall = table[(table["dimension"] == "overall") & (table["model"] == candidate)].iloc[0]
    bar = float(overall["median_baseline_mae_min"])
    mae = float(overall["mae_min"])
    support = table[(table["dimension"] == "corridor_support_in_train") & (table["model"] == candidate)]
    sparse = support[support["slice"].isin(["unseen", "1-9"])]
    rich = support[support["slice"] == ">=30"]
    wins_sparse = bool((sparse["delta_vs_median_min"] < 0).any())
    no_loss_rich = bool((rich["delta_vs_median_min"] <= 0).all())

    if mae < bar * (1 - TIE_TOLERANCE):
        outcome, action = 1, "adopt v2: beats the median baseline overall"
    elif abs(mae - bar) <= bar * TIE_TOLERANCE and wins_sparse and no_loss_rich:
        outcome, action = 2, "adopt v2: ties overall, wins where corridor history is thin"
    else:
        outcome, action = 3, "keep v1: v2 does not improve on any slice"
    return {"candidate": candidate, "overall_mae_min": mae, "median_bar_min": bar,
            "tie_tolerance": TIE_TOLERANCE, "wins_sparse_slice": wins_sparse,
            "no_loss_on_well_observed": no_loss_rich, "outcome": outcome, "action": action}


def run(metrics_csv: Path = METRICS_CSV, report_json: Path = REPORT_JSON) -> dict:
    frame = load_v2()
    judge = judge_median(frame)
    log.info("judge check: v2 median agrees on %.1f%% of %s warm legs", 100 * judge["agreement"],
             f"{judge['warm_legs_compared']:,}")

    train_raw, test_raw, cutoff = time_split(frame)
    train, test = prepare(train_raw), prepare(test_raw)
    predictions: dict[str, np.ndarray] = {
        "OSRM": osrm_predictions(test),
        "corridor_mean": corridor_mean_predictions(test),
        "corridor_median": test["baseline_median"].to_numpy(),
    }

    reference = HistGradientBoostingRegressor(loss="absolute_error", max_iter=300, learning_rate=0.05, random_state=42)
    reference.fit(train[FEATURES_V2], train["residual"])
    predictions["histgbr_residual_reference"] = test["baseline_median"].to_numpy() + reference.predict(test[FEATURES_V2])

    spark = get_spark("models-v2")
    # Checkpointing is what lets 200 boosting iterations finish at all. Each iteration
    # extends the RDD lineage, and without a checkpoint the chain is deserialised
    # recursively until the JVM overflows its stack -- the first run of this sprint died
    # with `java.lang.StackOverflowError` at stage 2,046, deep into GBT training, after
    # Week 4's shorter grids had never gone far enough to hit it (P-55). A checkpoint every
    # 10 iterations truncates the lineage; a bigger `-Xss` would only move the cliff.
    checkpoint_dir = config.SPARK_LOCAL_DIR / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    spark.sparkContext.setCheckpointDir(str(checkpoint_dir))
    try:
        champion = PipelineModel.load(str(MODELS_DIR / "champion"))
        predictions["v1_rf_raw_target"] = predict(spark, champion, test, FEATURES)

        gbt = GBTRegressor(featuresCol="features_vec", labelCol="residual", lossType="absolute",
                           maxIter=200, maxDepth=6, stepSize=0.05, seed=42, checkpointInterval=10)
        gbt_model = fit_residual(spark, train, gbt)
        predictions["v2_gbt_residual_absolute"] = test["baseline_median"].to_numpy() + predict(spark, gbt_model, test, FEATURES_V2)
        gbt_model.write().overwrite().save(str(MODELS_DIR / "v2_gbt_residual"))
        log.info("GBT (absolute loss) on residual: fitted and saved")

        # 150 trees at depth 8 is the largest forest Week 4's grid fitted on this 4g driver.
        # 300 ran the executor out of heap while collecting the trees (P-55), and a forest
        # Week 4 could not have trained is not a like-for-like comparison anyway.
        rf = RandomForestRegressor(featuresCol="features_vec", labelCol="residual", numTrees=150, maxDepth=8,
                                   seed=42, checkpointInterval=10)
        rf_model = fit_residual(spark, train, rf)
        predictions["v2_rf_residual_squared"] = test["baseline_median"].to_numpy() + predict(spark, rf_model, test, FEATURES_V2)
        rf_model.write().overwrite().save(str(MODELS_DIR / "v2_rf_residual"))
        log.info("RF (squared loss) on residual: fitted and saved")
    finally:
        stop_spark(spark)

    table = slice_table(test, train, predictions)
    metrics_csv.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(metrics_csv, index=False)

    overall = table[table["dimension"] == "overall"].set_index("model")["mae_min"].to_dict()
    decision = adoption_outcome(table, "v2_gbt_residual_absolute")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "features": {"v1": len(FEATURES), "v2": len(FEATURES_V2)},
        "n_train": len(train), "n_test": len(test), "split_cutoff": str(cutoff),
        "judge_median_check": judge,
        "baseline": "per-corridor as-of median of gap_min; cold corridors fall back to zero gap (the OSRM plan), "
                    "as in D-048",
        "overall_test_mae_min": overall,
        "adoption": decision,
        "models_saved": ["data/models/v2_gbt_residual", "data/models/v2_rf_residual"],
    }
    report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("overall MAE: %s", overall)
    log.info("D-049 rule: outcome %d -- %s", decision["outcome"], decision["action"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Residual-learning sprint over the median baseline (G-04)")
    parser.add_argument("--out", type=Path, default=METRICS_CSV)
    args = parser.parse_args()
    report = run(args.out)
    print(json.dumps({k: report[k] for k in ("judge_median_check", "overall_test_mae_min", "adoption")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
