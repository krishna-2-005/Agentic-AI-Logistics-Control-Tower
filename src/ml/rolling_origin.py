"""Rolling-origin evaluation: four chronological folds instead of one split (D-076, upgrade B2).

    python -m src.ml.rolling_origin

The headline split is one cut of the 22 days. A single cut can be lucky, and validation and test
disagreed about the first residual model once (D-049). Here the same configurations are refit and
scored on four later windows, with the hyperparameters **frozen** (no retuning in any fold):

    fold 1: train on days  1-10, test on days 11-13        fold 3: train 1-16, test 17-19
    fold 2: train on days  1-13, test on days 14-16        fold 4: train 1-19, test 20-22

Day 1 is 2018-09-12 (calendar day in India time of the leg's creation). The folds are fixed in D-076
before any fold was run. A fold's training legs are those *created* before its test window, the same
convention as the headline split; a leg created just before a window may finish inside it, so its label
is not strictly known at the cut, which the paper states as a limit. In each fold the baselines are
recomputed (the distance-band cut points come from that fold's training legs), and two Spark
configurations are refit: **v2** (over the old median, step size 1.0) and **v3** (over the back-off
baseline, the step size D-075 chose). Per-fold MAE, the difference to the bar, and their mean and
standard deviation over folds are written to `b2_rolling_origin.csv` and `b2_rolling_origin.json`.
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
from src.ml import models_v3
from src.ml.baselines import TARGET
from src.ml.models_v2 import FEATURES_V2, predict
from src.ml.models_v2 import fit_residual as fit_v2
from src.ml.models_v2 import prepare as prepare_v2
from src.ml.models_v2_stepsize import gbt
from src.ml.significance import IST_OFFSET

log = get_logger("ml.rolling_origin")

RAW = config.BENCHMARKS_RAW_DIR
OUT_CSV = RAW / "b2_rolling_origin.csv"
OUT_JSON = RAW / "b2_rolling_origin.json"
FIRST_DAY = pd.Timestamp("2018-09-12")
#: (train through day, test days first..last), inclusive. Fixed in D-076.
FOLDS = ((10, 11, 13), (13, 14, 16), (16, 17, 19), (19, 20, 22))


def day_numbers(creation: pd.Series) -> np.ndarray:
    """1-based day of leg creation, India time, with day 1 = 2018-09-12."""
    local = (pd.to_datetime(creation) + IST_OFFSET).dt.normalize()
    return ((local - FIRST_DAY).dt.days + 1).to_numpy()


def run_fold(spark, frame: pd.DataFrame, day: np.ndarray, fold: tuple[int, int, int], step_v3: float, base_name: str) -> dict:
    train_end, test_start, test_end = fold
    train_rows = np.flatnonzero(day <= train_end)
    test_rows = np.flatnonzero((day >= test_start) & (day <= test_end))
    train_raw, test_raw = frame.iloc[train_rows], frame.iloc[test_rows]
    cuts = (float(np.quantile(train_raw["planned_km"], 1 / 3)), float(np.quantile(train_raw["planned_km"], 2 / 3)))
    stats = bb.level_statistics(frame, cuts)
    hard = bb.hard_backoff(stats)
    old = bb.old_median(frame)
    y = test_raw[TARGET].to_numpy()

    columns = models_v3.baseline_columns(frame, base_name, stats, hard, 1.0)

    def part_v3(rows: np.ndarray) -> pd.DataFrame:
        return models_v3.prepare_v3(frame.iloc[rows], columns.iloc[rows].reset_index(drop=True))

    train_v3, test_v3 = part_v3(train_rows), part_v3(test_rows)
    train_v2, test_v2 = prepare_v2(train_raw), prepare_v2(test_raw)

    model_v3 = models_v3.fit(spark, train_v3, step_v3)
    pred_v3 = test_v3["baseline_gap"].to_numpy() + predict(spark, model_v3, test_v3, models_v3.FEATURES_V3)
    model_v2 = fit_v2(spark, train_v2, gbt(1.0))
    pred_v2 = test_v2["baseline_median"].to_numpy() + predict(spark, model_v2, test_v2, FEATURES_V2)

    preds = {"old_median": old[test_rows], "backoff": hard["backoff_gap"].to_numpy()[test_rows], "v2_gbt": pred_v2, "v3_gbt": pred_v3}
    maes = {k: float(np.mean(np.abs(y - p))) for k, p in preds.items()}
    cold = (test_raw["corr_n_prior"] == 0).to_numpy()
    row = {"fold": None, "train_days": f"1-{train_end}", "test_days": f"{test_start}-{test_end}",
           "n_train": len(train_rows), "n_test": len(test_rows), "n_cold_test": int(cold.sum()),
           **{f"mae_{k}": round(v, 4) for k, v in maes.items()},
           "delta_v2_vs_backoff": round(maes["v2_gbt"] - maes["backoff"], 4),
           "delta_v3_vs_backoff": round(maes["v3_gbt"] - maes["backoff"], 4),
           "delta_backoff_vs_old_median": round(maes["backoff"] - maes["old_median"], 4)}
    if cold.any():
        row["mae_cold_backoff"] = round(float(np.mean(np.abs(y[cold] - preds["backoff"][cold]))), 4)
        row["mae_cold_v2_gbt"] = round(float(np.mean(np.abs(y[cold] - pred_v2[cold]))), 4)
        row["mae_cold_v3_gbt"] = round(float(np.mean(np.abs(y[cold] - pred_v3[cold]))), 4)
    return row


def summarise(table: pd.DataFrame) -> dict:
    out: dict = {}
    for column in [c for c in table.columns if c.startswith(("mae_", "delta_"))]:
        values = table[column].dropna().to_numpy(dtype=float)
        out[column] = {"mean": round(float(values.mean()), 4), "sd": round(float(values.std(ddof=1)), 4) if len(values) > 1 else None,
                       "folds": int(len(values))}
    for model in ("v2_gbt", "v3_gbt"):
        column = f"delta_{model.split('_')[0]}_vs_backoff"
        out[f"{model}_beats_backoff_in_folds"] = int((table[column] < 0).sum())
    return out


def run() -> dict:
    rule = json.loads((RAW / "b1_backoff_baseline.json").read_text(encoding="utf-8"))
    v3 = json.loads((RAW / "b1_model_v3.json").read_text(encoding="utf-8"))
    step_v3, base_name = float(v3["step_size_chosen"]), v3["baseline_under_residual"]
    frame = bb.load_legs()
    day = day_numbers(frame["trip_creation_time"])
    if day.min() != 1 or day.max() != 22:
        raise ValueError(f"expected 22 calendar days numbered 1..22, got {day.min()}..{day.max()}")
    spark = get_spark("rolling-origin")
    checkpoint = config.SPARK_LOCAL_DIR / "checkpoints"
    checkpoint.mkdir(parents=True, exist_ok=True)
    spark.sparkContext.setCheckpointDir(str(checkpoint))
    rows = []
    try:
        for number, fold in enumerate(FOLDS, start=1):
            row = run_fold(spark, frame, day, fold, step_v3, base_name)
            row["fold"] = number
            rows.append(row)
            log.info("fold %d: bar %.3f | v2 %.3f | v3 %.3f", number, row["mae_backoff"], row["mae_v2_gbt"], row["mae_v3_gbt"])
    finally:
        stop_spark(spark)
    table = pd.DataFrame(rows)
    table.to_csv(OUT_CSV, index=False)
    report = {"generated_at": datetime.now(UTC).isoformat(), "decision": "D-076", "folds": [list(f) for f in FOLDS],
              "v3_step_size_frozen": step_v3, "v2_step_size_frozen": 1.0, "bar": rule["bar"]["name"],
              "summary": summarise(table)}
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    for name in ("b1_backoff_baseline.json", "b1_model_v3.json"):
        if not (RAW / name).exists():
            log.error("Missing %s -- run the B1 stages first.", name)
            return 1
    report = run()
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
