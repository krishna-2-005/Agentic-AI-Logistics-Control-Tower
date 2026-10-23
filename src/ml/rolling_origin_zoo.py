"""Rolling-origin folds for the reported single-node model (D-098).

    python -m src.ml.rolling_origin_zoo

The four chronological folds of D-076, with the reported model of D-077 (LightGBM, L1 loss, 200 trees, depth 6,
learning rate 0.03 chosen on validation and frozen) over the old median with the 38 v2 inputs. The baselines are
recomputed from each fold's training legs exactly as in `rolling_origin.py`; nothing is retuned. No Spark.
Writes `b2_rolling_origin_zoo.csv` and `b2_rolling_origin_zoo.json`.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger
from src.ml import backoff_baseline as bb
from src.ml import model_zoo
from src.ml.baselines import TARGET
from src.ml.models_v2 import FEATURES_V2
from src.ml.models_v3 import baseline_columns, prepare_v3
from src.ml.rolling_origin import FOLDS, day_numbers

log = get_logger("ml.rolling_origin_zoo")

RAW = config.BENCHMARKS_RAW_DIR
OUT_CSV = RAW / "b2_rolling_origin_zoo.csv"
OUT_JSON = RAW / "b2_rolling_origin_zoo.json"
MODEL = "lightgbm_l1"
LEARNING_RATE = 0.03


def run_fold(frame: pd.DataFrame, day: np.ndarray, fold: tuple[int, int, int]) -> dict:
    train_end, test_start, test_end = fold
    train_rows = np.flatnonzero(day <= train_end)
    test_rows = np.flatnonzero((day >= test_start) & (day <= test_end))
    train_raw, test_raw = frame.iloc[train_rows], frame.iloc[test_rows]
    cuts = (float(np.quantile(train_raw["planned_km"], 1 / 3)), float(np.quantile(train_raw["planned_km"], 2 / 3)))
    stats = bb.level_statistics(frame, cuts)
    hard = bb.hard_backoff(stats)
    old = bb.old_median(frame)
    columns = baseline_columns(frame, "old_median", stats, hard, 1.0)

    def part(rows: np.ndarray) -> pd.DataFrame:
        return prepare_v3(frame.iloc[rows], columns.iloc[rows].reset_index(drop=True))

    train, test = part(train_rows), part(test_rows)
    (residual,) = model_zoo.fit_boosted(MODEL, LEARNING_RATE, 0.0, train, [test], list(FEATURES_V2))
    prediction = test["baseline_gap"].to_numpy() + residual
    y = test_raw[TARGET].to_numpy()
    bar = hard["backoff_gap"].to_numpy()[test_rows]
    mae = {"model": float(np.mean(np.abs(y - prediction))), "backoff": float(np.mean(np.abs(y - bar))),
           "old_median": float(np.mean(np.abs(y - old[test_rows])))}
    return {"train_days": f"1-{train_end}", "test_days": f"{test_start}-{test_end}", "n_train": len(train_rows),
            "n_test": len(test_rows), **{f"mae_{k}": round(v, 4) for k, v in mae.items()},
            "delta_vs_backoff": round(mae["model"] - mae["backoff"], 4)}


def run() -> dict:
    frame = bb.load_legs()
    day = day_numbers(frame["trip_creation_time"])
    rows = []
    for number, fold in enumerate(FOLDS, start=1):
        row = {"fold": number, **run_fold(frame, day, fold)}
        rows.append(row)
        log.info("fold %d: bar %.3f | %s %.3f", number, row["mae_backoff"], MODEL, row["mae_model"])
    table = pd.DataFrame(rows)
    table.to_csv(OUT_CSV, index=False)
    delta = table["delta_vs_backoff"].to_numpy(dtype=float)
    report = {"generated_at": datetime.now(UTC).isoformat(), "decision": "D-098", "model": MODEL,
              "learning_rate_frozen": LEARNING_RATE, "folds": [list(f) for f in FOLDS],
              "summary": {"mae_model": {"mean": round(float(table["mae_model"].mean()), 4),
                                        "sd": round(float(table["mae_model"].std(ddof=1)), 4)},
                          "mae_backoff": {"mean": round(float(table["mae_backoff"].mean()), 4)},
                          "delta_vs_backoff": {"mean": round(float(delta.mean()), 4),
                                               "sd": round(float(delta.std(ddof=1)), 4)},
                          "model_beats_backoff_in_folds": int((delta < 0).sum()), "folds": len(delta)}}
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    for name in ("b1_backoff_baseline.json", "b6_model_zoo.json"):
        if not (RAW / name).exists():
            log.error("Missing %s -- run the B1 and B6 stages first.", name)
            return 1
    print(json.dumps(run()["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
