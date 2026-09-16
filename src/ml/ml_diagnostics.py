"""Week 7 ML diagnostics (execution plan v3.1 §2.1 Step 1, G-04) -- before any model change.

    python -m src.ml.ml_diagnostics

The Week 4 Random Forest (36.89 min test MAE) loses to the per-corridor mean baseline
(36.13 min) it has as a feature. v3.1 says diagnose before touching the model, and names
four checks. This module runs the two that need data; the other two are code reads,
recorded in D-048 alongside these numbers.

1. **Categorical-as-numeric** (code read). `src.ml.models.fit_mllib_model` assembles
   `FEATURES` with a bare `VectorAssembler`. There is no `StringIndexer` and no corridor
   key in the vector at all -- corridors enter only through their numeric history -- so
   the suspected "MLlib splits an index alphabetically" bug cannot occur and `maxBins`
   is irrelevant. Checked, not present.
2. **Is the corridor statistic in the vector?** (code read) Yes: `corr_mean_gap_min` is
   one of the 27 `FEATURES`, the same quantity the baseline predicts from. The model has
   the baseline's own answer as an input and still trails it.
3. **Corridor-median baseline** (measured here). MAE is minimised by the median, not the
   mean, so the fair statistical baseline for an MAE table is the per-corridor *median*
   of past gaps. It is computed with the same as-of semantics as Stage 4's history --
   only legs that had *finished* before the query leg was created -- and the as-of
   *mean* computed the same way is checked against `features_v1.corr_mean_gap_min`
   first, so the median is known to sit on exactly the history the features use.
4. **Single-node reference ceiling** (measured here). sklearn
   `HistGradientBoostingRegressor` on the same features and split, twice: squared loss
   (what MLlib's RF optimises) and absolute loss (what the table grades). If absolute
   loss wins and squared does not, the gap is the objective, not the features.

Writes `benchmarks/raw/w7_ml_diagnostics.json`. No model file is written and nothing in
`data/models/` is touched: D-048 reopens the freeze for the correction sprint, and a
diagnostic that changed the champion would be the sprint starting before its own
decision was logged.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from src.common import config
from src.common.logging_setup import get_logger
from src.ml.baselines import (
    FEATURES,
    TARGET,
    corridor_mean_predictions,
    osrm_predictions,
    prepare_model_features,
    time_split,
)

log = get_logger("ml.ml_diagnostics")

OUT_JSON = config.BENCHMARKS_RAW_DIR / "w7_ml_diagnostics.json"
W4_METRICS = config.BENCHMARKS_RAW_DIR / "w4_model_metrics.csv"

#: Stage 4 wrote `leg_id`'s departure stamp in the Spark session's zone; pandas reads the
#: parquet timestamps back as UTC. Mixing the two would shift every fact by 5h30 relative
#: to every query -- silently, and in the direction that leaks. The as-of mean check below
#: is what proves the conversion is right.
SESSION_TZ = "Asia/Kolkata"


def _local(series: pd.Series) -> pd.Series:
    stamps = pd.to_datetime(series)
    if stamps.dt.tz is None:
        stamps = stamps.dt.tz_localize("UTC")
    return stamps.dt.tz_convert(SESSION_TZ).dt.tz_localize(None)


def load_legs(path: Path = config.FEATURES_V1, trips: Path = config.PROCESSED_DIR / "trips_v1") -> pd.DataFrame:
    """Legs with their creation time and their **real** finish time, both local.

    The finish time is joined from `trips_v1.od_end_time`, the column Stage 4's as-of join
    uses. The first version of this module derived it as `od_start + actual_time`, which
    is not the finish: `actual_time` is moving time and excludes dwell
    (`reconstruct.py`: dwell = start_scan_to_end_scan - actual_time), so every fact landed
    early. That counted not-yet-finished legs as known history on 1,128 legs. Joining the
    real finish time brings the reconstruction to 100% agreement with Stage 4's
    `corr_n_prior` and `corr_mean_gap_min`; the median baseline itself moved only from
    33.06 to 33.04 min, so the fix buys a history that is provably identical, not a
    different headline (P-52).
    """
    frame = pd.read_parquet(path)
    frame["created_local"] = _local(frame["trip_creation_time"])

    legs = pd.read_parquet(trips, columns=["trip_uuid", "od_start_time", "od_end_time", "corridor_id"])
    legs["leg_id"] = (
        legs["trip_uuid"] + "|" + _local(legs["od_start_time"]).dt.strftime("%Y%m%d%H%M%S")
        + "|" + legs["corridor_id"]
    )
    legs["od_end_local"] = _local(legs["od_end_time"])
    frame = frame.merge(legs[["leg_id", "od_end_local"]].drop_duplicates("leg_id"), on="leg_id", how="left")
    missing = int(frame["od_end_local"].isna().sum())
    if missing:
        raise ValueError(f"{missing} legs in features_v1 have no od_end_time in trips_v1 -- the join key drifted")
    return frame.sort_values("created_local").reset_index(drop=True)


def as_of_corridor_stats(frame: pd.DataFrame) -> pd.DataFrame:
    """For every leg: count, mean and median of `gap_min` over same-corridor legs that
    had finished at or before this leg's creation (facts before queries on a tie, D-020).
    """
    counts = np.zeros(len(frame), dtype=int)
    means = np.full(len(frame), np.nan)
    medians = np.full(len(frame), np.nan)
    for _, group in frame.groupby("corridor_id", sort=False):
        facts = group.sort_values("od_end_local")
        end_times = facts["od_end_local"].to_numpy()
        gaps = facts["gap_min"].to_numpy()
        prefix_mean = np.cumsum(gaps) / np.arange(1, len(gaps) + 1)
        prefix_median = np.array([np.median(gaps[: k + 1]) for k in range(len(gaps))])
        known = np.searchsorted(end_times, group["created_local"].to_numpy(), side="right")
        rows = group.index.to_numpy()
        counts[rows] = known
        has = known > 0
        means[rows[has]] = prefix_mean[known[has] - 1]
        medians[rows[has]] = prefix_median[known[has] - 1]
    return pd.DataFrame({"n_prior_asof": counts, "mean_asof": means, "median_asof": medians}, index=frame.index)


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return round(float(np.mean(np.abs(y_true - y_pred))), 2)


def run(out_path: Path = OUT_JSON) -> dict:
    legs = load_legs()
    stats = as_of_corridor_stats(legs)
    legs = legs.join(stats)

    # ── check: is our as-of history the history Stage 4 built? ────────────────
    warm = legs["corr_n_prior"] > 0
    count_agree = float((legs.loc[warm, "n_prior_asof"] == legs.loc[warm, "corr_n_prior"]).mean())
    mean_agree = float(np.isclose(legs.loc[warm, "mean_asof"], legs.loc[warm, "corr_mean_gap_min"], atol=1e-6).mean())
    log.info("as-of reconstruction: n_prior agrees on %.1f%%, mean on %.1f%% of warm legs",
             100 * count_agree, 100 * mean_agree)

    train_raw, test_raw, cutoff = time_split(legs)
    train, test = prepare_model_features(train_raw), prepare_model_features(test_raw)
    y_train, y_test = train[TARGET].to_numpy(), test[TARGET].to_numpy()

    cold_test = test["corr_n_prior"].to_numpy() == 0
    median_pred = np.where(cold_test, 0.0, test["median_asof"].fillna(0.0).to_numpy())

    rows = {
        "OSRM": mae(y_test, osrm_predictions(test)),
        "corridor_mean": mae(y_test, corridor_mean_predictions(test)),
        "corridor_median": mae(y_test, median_pred),
    }

    references = {}
    for loss in ("squared_error", "absolute_error"):
        model = HistGradientBoostingRegressor(loss=loss, max_iter=300, learning_rate=0.05, random_state=42)
        model.fit(train[FEATURES], y_train)
        references[loss] = mae(y_test, model.predict(test[FEATURES]))
        rows[f"hist_gbr_{loss}"] = references[loss]
        log.info("HistGradientBoosting (%s): test MAE %.2f", loss, references[loss])

    w4 = pd.read_csv(W4_METRICS)
    w4_test = w4[w4["split"] == "test"].set_index("model")["mae_min"].to_dict()
    for name in ("random_forest", "gbt"):
        if name in w4_test:
            rows[f"mllib_{name}_w4"] = round(float(w4_test[name]), 2)

    best_baseline = min(rows["corridor_mean"], rows["corridor_median"])
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "legs": len(legs),
        "n_train": len(train), "n_test": len(test), "split_cutoff": str(cutoff),
        "test_cold_corridor_share": round(float(cold_test.mean()), 4),
        "asof_reconstruction": {"n_prior_agreement": round(count_agree, 4), "mean_agreement": round(mean_agree, 4)},
        "code_reads": {
            "categorical_as_numeric": "not present: bare VectorAssembler over numeric FEATURES, no StringIndexer, "
                                      "no corridor key in the vector; maxBins does not apply",
            "corridor_statistic_in_vector": "yes: corr_mean_gap_min is one of the 27 FEATURES",
            "training_objective": "MLlib RandomForestRegressor is squared-loss only; the table grades MAE",
        },
        "test_mae_min": rows,
        "best_statistical_baseline": {"name": "corridor_median" if rows["corridor_median"] < rows["corridor_mean"]
                                      else "corridor_mean", "mae": best_baseline},
        "reading": {
            "objective_gap_min": round(references["squared_error"] - references["absolute_error"], 2),
            "absolute_loss_reference_vs_best_baseline_min": round(references["absolute_error"] - best_baseline, 2),
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("diagnostics -> %s", out_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="G-04 diagnostics, before any model change")
    parser.add_argument("--out", type=Path, default=OUT_JSON)
    args = parser.parse_args()
    report = run(args.out)
    print(json.dumps({k: report[k] for k in ("asof_reconstruction", "test_mae_min", "best_statistical_baseline", "reading")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
