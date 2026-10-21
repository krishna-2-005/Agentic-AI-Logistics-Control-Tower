"""A hierarchical back-off baseline: the fair bar without an unfair cold-start fallback (D-075).

    python -m src.ml.backoff_baseline            # writes benchmarks/raw/b1_*.{json,csv}

Why this exists. The bar the model was judged against, `baseline_median`, predicts a gap of
**0.0 minutes** on a corridor with no history: on those legs the "fair baseline" says the leg
runs exactly on plan, which is OSRM. Most of the model's margin is on exactly those legs
(294 unseen-corridor test legs, 111.2 -> 75.9 min), so a reviewer can fairly say the baseline
has an unfair fallback. Here a leg with no corridor history falls back to the next-most-specific
group that has any, and only a leg with no history *anywhere* (the very first legs of the
stream) gets 0.0.

Levels, in order of preference, each the median of `gap_min` over prior legs in the group:

    L1 corridor   L2 origin hub   L3 destination hub   L4 route type x distance band   L5 network

*Prior* is the repo's as-of rule (D-020): a leg counts only once it has **finished**
(`od_end_time`) before the query leg was **created** (`trip_creation_time`), facts before
queries on a tie. The median is `src.streaming.state.spark_percentile(., 0.5)`, the mean of
the two middle values for an even count, so L1 reproduces `features_v2.corr_median_gap_min`
exactly; that is checked before anything is written (builder-and-judge, D-028).

Two variants, both pre-registered: **hard** back-off uses the first level with at least one
prior leg; **shrunken** back-off shrinks each level toward the next with weight `n / (n + k)`,
`k` chosen on the validation cut only.
"""

from __future__ import annotations

import argparse
import json
from bisect import insort
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger
from src.ml.baselines import TARGET, time_split
from src.streaming.state import spark_percentile

log = get_logger("ml.backoff_baseline")

RAW = config.BENCHMARKS_RAW_DIR
LEVELS = ("corridor", "origin_hub", "destination_hub", "route_distance_band", "network")
#: The shrinkage grid is fixed in D-075; `k` is chosen from it on validation only.
K_GRID = (1, 2, 5, 10, 20, 50, 100)
BAND_NAMES = ("short", "medium", "long")
OUT_JSON = RAW / "b1_backoff_baseline.json"
OUT_SLICES = RAW / "b1_backoff_slices.csv"
OUT_PREDICTIONS = RAW / "b1_test_predictions.csv"
OUT_VALIDATION = RAW / "b1_validation_predictions.csv"


# ── data ────────────────────────────────────────────────────────────────────
def load_legs() -> pd.DataFrame:
    """`features_v2` with each leg's finish time, ordered by creation time.

    The leg id of `features_v2` is built by Spark in the session time zone (IST); the same id is
    rebuilt here from `trips_v1`, whose timestamps pandas reads as UTC, so the departure is
    shifted +5:30 before it is formatted. All 26,369 legs must join or this refuses to continue.
    """
    features = pd.read_parquet(config.FEATURES_V2)
    trips = pd.read_parquet(config.TRIPS_V1, columns=["trip_uuid", "od_start_time", "od_end_time", "corridor_id"])
    start = pd.to_datetime(trips["od_start_time"]) + pd.Timedelta(hours=5, minutes=30)
    trips["leg_id"] = trips["trip_uuid"].astype(str) + "|" + start.dt.strftime("%Y%m%d%H%M%S") + "|" + trips["corridor_id"]
    frame = features.merge(trips[["leg_id", "od_end_time"]], on="leg_id", how="left", validate="one_to_one")
    if frame["od_end_time"].isna().any():
        raise ValueError(f"{int(frame['od_end_time'].isna().sum())} legs lost their finish time in the join")
    return frame.sort_values("trip_creation_time").reset_index(drop=True)


def distance_bands(planned_km: pd.Series, cuts: tuple[float, float]) -> np.ndarray:
    """short / medium / long by two planned-distance cut points (terciles of the training legs)."""
    km = planned_km.to_numpy()
    return np.where(km < cuts[0], BAND_NAMES[0], np.where(km < cuts[1], BAND_NAMES[1], BAND_NAMES[2]))


# ── the as-of engine ────────────────────────────────────────────────────────
def asof_median(keys: np.ndarray, created: np.ndarray, ended: np.ndarray, gap: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For each leg: how many prior legs share its key, and their median `gap`.

    Events are processed in time order with facts before queries on a tie; each group keeps a
    sorted list so the median is read in O(1). Returns (count, median) with NaN where count is 0.
    """
    n = len(keys)
    times = np.concatenate([ended, created]).astype("int64")
    kinds = np.concatenate([np.zeros(n, dtype=np.int8), np.ones(n, dtype=np.int8)])
    index = np.concatenate([np.arange(n), np.arange(n)])
    order = np.lexsort((kinds, times))  # by time, then facts (0) before queries (1)
    store: dict[object, list[float]] = {}
    count = np.zeros(n, dtype=np.int64)
    median = np.full(n, np.nan)
    for position in order:
        i = int(index[position])
        key = keys[i]
        if kinds[position] == 0:
            insort(store.setdefault(key, []), float(gap[i]))
        else:
            history = store.get(key)
            if history:
                count[i] = len(history)
                median[i] = spark_percentile(history, 0.5)
    return count, median


def level_keys(frame: pd.DataFrame, cuts: tuple[float, float]) -> dict[str, np.ndarray]:
    band = distance_bands(frame["planned_km"], cuts)
    return {
        "corridor": frame["corridor_id"].to_numpy(),
        "origin_hub": frame["source_center"].to_numpy(),
        "destination_hub": frame["destination_center"].to_numpy(),
        "route_distance_band": (frame["route_type"].astype(str) + "|" + pd.Series(band)).to_numpy(),
        "network": np.zeros(len(frame), dtype=np.int8),
    }


def level_statistics(frame: pd.DataFrame, cuts: tuple[float, float]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """(count, median) per level for every leg, as-of."""
    created = frame["trip_creation_time"].to_numpy(dtype="datetime64[ns]")
    ended = frame["od_end_time"].to_numpy(dtype="datetime64[ns]")
    gap = frame[TARGET].to_numpy(dtype=float)
    return {name: asof_median(keys, created, ended, gap) for name, keys in level_keys(frame, cuts).items()}


# ── the two baselines ───────────────────────────────────────────────────────
def hard_backoff(stats: dict[str, tuple[np.ndarray, np.ndarray]]) -> pd.DataFrame:
    """First level with at least one prior leg; 0.0 only where there is no history anywhere."""
    n = len(next(iter(stats.values()))[0])
    value, level, support = np.zeros(n), np.zeros(n, dtype=np.int8), np.zeros(n, dtype=np.int64)
    unresolved = np.ones(n, dtype=bool)
    for depth, name in enumerate(LEVELS, start=1):
        count, median = stats[name]
        take = unresolved & (count > 0)
        value[take], level[take], support[take] = median[take], depth, count[take]
        unresolved &= ~take
    return pd.DataFrame({"backoff_gap": value, "backoff_level": level, "backoff_n": support,
                         "backoff_no_history": unresolved})


def shrunken_backoff(stats: dict[str, tuple[np.ndarray, np.ndarray]], k: float) -> np.ndarray:
    """Each level shrunk toward the next with weight n/(n+k), from the network upward."""
    count, median = stats["network"]
    estimate = np.where(count > 0, median, 0.0)
    for name in reversed(LEVELS[:-1]):
        count, median = stats[name]
        weight = count / (count + k)
        estimate = weight * np.nan_to_num(median) + (1.0 - weight) * estimate
    return estimate


# ── checks ──────────────────────────────────────────────────────────────────
def judge_level_one(frame: pd.DataFrame, stats: dict[str, tuple[np.ndarray, np.ndarray]]) -> dict:
    """L1 must reproduce the feature table's own as-of corridor count and median, leg for leg."""
    count, median = stats["corridor"]
    count_ok = bool((count == frame["corr_n_prior"].to_numpy()).all())
    warm = count > 0
    expected = frame["corr_median_gap_min"].to_numpy()
    median_diff = float(np.max(np.abs(median[warm] - expected[warm]))) if warm.any() else 0.0
    report = {"legs": int(len(frame)), "warm_legs": int(warm.sum()), "count_agrees": count_ok,
              "max_abs_median_difference": median_diff}
    if not count_ok or median_diff > 1e-9:
        raise ValueError(f"the L1 median does not reproduce features_v2: {report}; refusing to write results")
    return report


# ── evaluation ──────────────────────────────────────────────────────────────
def mae(y: np.ndarray, pred: np.ndarray, mask: np.ndarray | None = None) -> float:
    if mask is not None:
        y, pred = y[mask], pred[mask]
    return float(np.mean(np.abs(y - pred))) if len(y) else float("nan")


def old_median(frame: pd.DataFrame) -> np.ndarray:
    """The bar as it was: the corridor median, and 0.0 on a corridor with no history."""
    return np.where(frame["corr_n_prior"] == 0, 0.0, frame["corr_median_gap_min"]).astype(float)


def regimes(frame: pd.DataFrame, train: pd.DataFrame) -> dict[str, np.ndarray]:
    unseen = ~frame["corridor_id"].isin(set(train["corridor_id"]))
    cold = (frame["corr_n_prior"] == 0).to_numpy()
    return {"overall": np.ones(len(frame), dtype=bool), "cold_asof": cold, "warm_asof": ~cold,
            "unseen_in_train": unseen.to_numpy()}


def per_regime(y: np.ndarray, predictions: dict[str, np.ndarray], masks: dict[str, np.ndarray]) -> dict:
    return {name: {"n": int(mask.sum()), **{model: round(mae(y, pred, mask), 4) for model, pred in predictions.items()}}
            for name, mask in masks.items()}


def choose_k(validation: pd.DataFrame, stats: dict[str, tuple[np.ndarray, np.ndarray]],
             validation_rows: np.ndarray) -> tuple[float, dict[str, float]]:
    y = validation[TARGET].to_numpy()
    scores = {str(k): mae(y, shrunken_backoff(stats, k)[validation_rows]) for k in K_GRID}
    best = min(K_GRID, key=lambda k: (scores[str(k)], k))
    return float(best), scores


def v2_test_predictions(frame: pd.DataFrame, rows: np.ndarray) -> np.ndarray:
    """The v2 GBT's gap predictions on `frame[rows]`, from the model's own saved trees (numpy, no Spark)."""
    from src.ml import gbt_local, serving
    from src.ml.models_v2 import FEATURES_V2

    prepared = serving.prepare(frame.iloc[rows].reset_index(drop=True))
    forest = gbt_local.load(serving.MODEL_PATH)
    correction = gbt_local.predict(forest, prepared[FEATURES_V2])
    return prepared["baseline_median"].to_numpy() + correction


def run() -> dict:
    frame = load_legs()
    train_raw, test_raw, cutoff = time_split(frame)
    inner_raw, valid_raw, inner_cutoff = time_split(train_raw)
    cuts = (float(np.quantile(train_raw["planned_km"], 1 / 3)), float(np.quantile(train_raw["planned_km"], 2 / 3)))
    stats = level_statistics(frame, cuts)
    judge = judge_level_one(frame, stats)

    position = {leg: i for i, leg in enumerate(frame["leg_id"])}
    test_rows = np.array([position[leg] for leg in test_raw["leg_id"]])
    valid_rows = np.array([position[leg] for leg in valid_raw["leg_id"]])
    k_star, k_scores = choose_k(valid_raw, stats, valid_rows)

    hard = hard_backoff(stats)
    shrunk = shrunken_backoff(stats, k_star)
    old = old_median(frame)

    def split_predictions(rows: np.ndarray) -> dict[str, np.ndarray]:
        return {"old_median": old[rows], "backoff": hard["backoff_gap"].to_numpy()[rows], "shrunk_backoff": shrunk[rows]}

    y_valid, y_test = valid_raw[TARGET].to_numpy(), test_raw[TARGET].to_numpy()
    valid_pred, test_pred = split_predictions(valid_rows), split_predictions(test_rows)
    test_pred["v2_gbt"] = v2_test_predictions(frame, test_rows)

    validation_mae = {name: round(mae(y_valid, pred), 4) for name, pred in valid_pred.items()}
    test_mae = {name: round(mae(y_test, pred), 4) for name, pred in test_pred.items()}

    # D-075 rule 1: the bar is the best of the three baselines on TEST (conservative for the model);
    # rule 2: the baseline under the v3 residual is the best of the three on VALIDATION.
    baselines = ("old_median", "backoff", "shrunk_backoff")
    bar = min(baselines, key=lambda m: (test_mae[m], baselines.index(m)))
    v3_base = min(baselines, key=lambda m: (validation_mae[m], baselines.index(m)))

    masks = regimes(test_raw.reset_index(drop=True), train_raw)
    level_use = hard.iloc[test_rows]["backoff_level"].value_counts().sort_index()
    cold_rows = test_rows[(test_raw["corr_n_prior"] == 0).to_numpy()]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "decision": "D-075",
        "split": {"train": len(train_raw), "validation_fit": len(inner_raw), "validation": len(valid_raw),
                  "test": len(test_raw), "test_cutoff": str(cutoff), "validation_cutoff": str(inner_cutoff)},
        "distance_band_cuts_km": [round(c, 4) for c in cuts],
        "judge_level_one": judge,
        "k_grid_validation_mae": {k: round(v, 4) for k, v in k_scores.items()},
        "k_chosen": k_star,
        "validation_mae": validation_mae,
        "test_mae": test_mae,
        "test_mae_by_regime": per_regime(y_test, test_pred, masks),
        "bar": {"name": bar, "rule": "lowest test MAE of old_median, backoff, shrunk_backoff (D-075 rule 1)",
                "test_mae": test_mae[bar]},
        "v3_baseline": {"name": v3_base, "rule": "lowest validation MAE of the same three (D-075 rule 2)",
                        "validation_mae": validation_mae[v3_base]},
        "backoff_beats_old_median_on_test": bool(min(test_mae["backoff"], test_mae["shrunk_backoff"]) < test_mae["old_median"]),
        "test_legs_by_backoff_level": {LEVELS[int(level) - 1] if level > 0 else "no_history_anywhere": int(n)
                                       for level, n in level_use.items()},
        "test_legs_no_history_anywhere": int(hard.iloc[test_rows]["backoff_no_history"].sum()),
        "all_legs_no_history_anywhere": int(hard["backoff_no_history"].sum()),
        "cold_test_legs": int(len(cold_rows)),
    }

    # Slice table (the 14 slices of the paper), every model against the bar.
    from src.ml.models_v2 import slice_masks

    test_view = test_raw.reset_index(drop=True)
    rows = []
    for dimension, slices in slice_masks(test_view, train_raw).items():
        for name, mask in slices.items():
            if not mask.any():
                continue
            row = {"dimension": dimension, "slice": name, "n": int(mask.sum()), "bar": bar,
                   "bar_mae_min": round(mae(y_test, test_pred[bar], mask), 4)}
            for model, pred in test_pred.items():
                row[f"{model}_mae_min"] = round(mae(y_test, pred, mask), 4)
            rows.append(row)
    pd.DataFrame(rows).to_csv(OUT_SLICES, index=False)

    # Per-leg predictions for the significance study (B2) and the model zoo (B6).
    def predictions_frame(raw: pd.DataFrame, rows_idx: np.ndarray, predictions: dict[str, np.ndarray]) -> pd.DataFrame:
        base = raw[["leg_id", "trip_creation_time", "corridor_id", "corr_n_prior", TARGET]].reset_index(drop=True)
        base["backoff_level"] = hard["backoff_level"].to_numpy()[rows_idx]
        base["backoff_n"] = hard["backoff_n"].to_numpy()[rows_idx]
        return base.assign(**{f"pred_{m}": p for m, p in predictions.items()})

    predictions_frame(test_raw, test_rows, test_pred).to_csv(OUT_PREDICTIONS, index=False)
    predictions_frame(valid_raw, valid_rows, valid_pred).to_csv(OUT_VALIDATION, index=False)

    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("test MAE: %s | bar: %s | v3 baseline: %s | k=%s", test_mae, bar, v3_base, k_star)
    return report


def main() -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    for path in (config.FEATURES_V2, config.TRIPS_V1):
        if not Path(path).exists():
            log.error("Missing %s -- build the pipeline first (see README run order).", path)
            return 1
    report = run()
    print(json.dumps({k: report[k] for k in ("k_chosen", "validation_mae", "test_mae", "bar", "v3_baseline")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
