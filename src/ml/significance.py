"""Uncertainty for every model comparison (D-076, upgrade B2).

    python -m src.ml.significance          # reads the per-leg test predictions, writes b2_significance.json

Every comparison is a model against the bar on the *same* test legs, so the quantity is the paired
per-leg difference `d_i = |y_i - f_i| - |y_i - b_i|` (negative favours the model); its mean is the MAE
difference. Four ways of putting an interval or a p-value on it, all pre-registered:

* **Paired bootstrap over legs.** Reported, but legs share trips, vehicles and days, so the interval is
  too narrow. It is the *optimistic* row and the module says so in the output.
* **Block bootstrap by calendar day (the paper's interval).** Whole days are resampled with
  replacement, which keeps the within-day dependence inside each draw. The test split covers about six
  days, so this interval rests on few blocks; a **six-hour-block** version is reported beside it.
* **Wilcoxon signed-rank.** Distribution-free, but it assumes independent pairs, so its p-value is
  optimistic for the same reason the paired bootstrap is.
* **Diebold-Mariano** on the loss differential in time order, with a Bartlett-kernel (Newey-West)
  long-run variance whose bandwidth is the median number of legs per day (day-level dependence), and
  the conventional floor(n^(1/3)) bandwidth as a second row.

Holm's correction is applied across the 13 non-overall slices, separately for each test.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps
from statsmodels.stats.multitest import multipletests

from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("ml.significance")

RAW = config.BENCHMARKS_RAW_DIR
OUT_JSON = RAW / "b2_significance.json"
SEED = 20261021
N_BOOT = 10_000
IST_OFFSET = pd.Timedelta(hours=5, minutes=30)
CHUNK = 500


# ── blocks ──────────────────────────────────────────────────────────────────
def day_blocks(creation_times: pd.Series) -> np.ndarray:
    """Calendar day (IST) of leg creation, as a dense 0..D-1 block id."""
    days = (pd.to_datetime(creation_times) + IST_OFFSET).dt.normalize()
    return pd.factorize(days, sort=True)[0]


def hour_blocks(creation_times: pd.Series, hours: int = 6) -> np.ndarray:
    """Blocks of `hours` hours (IST), as a dense block id; the sensitivity check for few-day splits."""
    local = pd.to_datetime(creation_times) + IST_OFFSET
    start = local.min().normalize()
    return pd.factorize(((local - start) // pd.Timedelta(hours=hours)).to_numpy(), sort=True)[0]


# ── resampling ──────────────────────────────────────────────────────────────
def paired_bootstrap(d: np.ndarray, n_boot: int = N_BOOT, seed: int = SEED) -> np.ndarray:
    """Bootstrap distribution of mean(d), resampling legs."""
    rng = np.random.default_rng(seed)
    out = np.empty(n_boot)
    for start in range(0, n_boot, CHUNK):
        size = min(CHUNK, n_boot - start)
        out[start:start + size] = d[rng.integers(0, len(d), size=(size, len(d)))].mean(axis=1)
    return out


def block_bootstrap(d: np.ndarray, blocks: np.ndarray, n_boot: int = N_BOOT, seed: int = SEED) -> np.ndarray:
    """Bootstrap distribution of mean(d), resampling whole blocks with replacement.

    The statistic is the ratio of resampled sums to resampled counts, because blocks differ in size.
    Blocks with no legs in the slice are kept in the draw (they contribute nothing), exactly as a
    resample of the full calendar would; a draw that lands only on empty blocks is dropped.
    """
    n_blocks = int(blocks.max()) + 1
    sums = np.bincount(blocks, weights=d, minlength=n_blocks)
    counts = np.bincount(blocks, minlength=n_blocks).astype(float)
    rng = np.random.default_rng(seed)
    out = np.empty(n_boot)
    for start in range(0, n_boot, CHUNK):
        size = min(CHUNK, n_boot - start)
        draw = rng.integers(0, n_blocks, size=(size, n_blocks))
        total = counts[draw].sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[start:start + size] = sums[draw].sum(axis=1) / total
    return out[~np.isnan(out)]


def interval(distribution: np.ndarray, level: float = 0.95) -> tuple[float, float]:
    tail = (1.0 - level) / 2.0
    lo, hi = np.quantile(distribution, [tail, 1.0 - tail])
    return float(lo), float(hi)


def bootstrap_p(distribution: np.ndarray) -> float:
    """Two-sided p-value for 'the mean difference is zero' from a bootstrap distribution, never exactly 0."""
    b = len(distribution)
    below = (np.sum(distribution <= 0) + 1) / (b + 1)
    above = (np.sum(distribution >= 0) + 1) / (b + 1)
    return float(min(1.0, 2.0 * min(below, above)))


# ── tests ───────────────────────────────────────────────────────────────────
def wilcoxon_p(d: np.ndarray) -> float:
    nonzero = d[d != 0]
    if len(nonzero) < 10:
        return float("nan")
    return float(sps.wilcoxon(nonzero, alternative="two-sided").pvalue)


def long_run_variance(x: np.ndarray, bandwidth: int) -> float:
    """Newey-West: gamma_0 + 2 * sum_{l=1..L} (1 - l/(L+1)) gamma_l of the demeaned series."""
    n = len(x)
    centred = x - x.mean()
    bandwidth = max(0, min(bandwidth, n - 1))
    total = float(np.dot(centred, centred)) / n
    for lag in range(1, bandwidth + 1):
        gamma = float(np.dot(centred[lag:], centred[:-lag])) / n
        total += 2.0 * (1.0 - lag / (bandwidth + 1.0)) * gamma
    return total


def diebold_mariano(d: np.ndarray, bandwidth: int) -> tuple[float, float]:
    """(statistic, two-sided p) for mean(d) = 0, normal reference, HAC variance with `bandwidth` lags."""
    n = len(d)
    if n < 10:
        return float("nan"), float("nan")
    variance = long_run_variance(d, bandwidth)
    if variance <= 0:
        return float("nan"), float("nan")
    statistic = float(d.mean() / math.sqrt(variance / n))
    return statistic, float(2.0 * sps.norm.sf(abs(statistic)))


def holm(pvalues: list[float]) -> list[float]:
    clean = np.array([1.0 if math.isnan(p) else p for p in pvalues])
    return [float(p) for p in multipletests(clean, method="holm")[1]]


# ── one comparison ──────────────────────────────────────────────────────────
def compare(y: np.ndarray, model: np.ndarray, bar: np.ndarray, mask: np.ndarray, days: np.ndarray,
            quarter_days: np.ndarray, legs_per_day: int, seed: int = SEED, n_boot: int = N_BOOT) -> dict:
    d = (np.abs(y - model) - np.abs(y - bar))[mask]
    paired = paired_bootstrap(d, n_boot, seed)
    by_day = block_bootstrap(d, days[mask], n_boot, seed)
    by_six_hours = block_bootstrap(d, quarter_days[mask], n_boot, seed)
    dm_day = diebold_mariano(d, legs_per_day)
    dm_cuberoot = diebold_mariano(d, int(np.floor(len(d) ** (1 / 3))))
    block_lo, block_hi = interval(by_day)
    return {
        "n": int(mask.sum()),
        "mae_model": round(float(np.mean(np.abs(y[mask] - model[mask]))), 4),
        "mae_bar": round(float(np.mean(np.abs(y[mask] - bar[mask]))), 4),
        "delta_mae": round(float(d.mean()), 4),
        "ci_block_day": [round(block_lo, 4), round(block_hi, 4)],
        "ci_block_6h": [round(v, 4) for v in interval(by_six_hours)],
        "ci_paired_legs_optimistic": [round(v, 4) for v in interval(paired)],
        "blocks_day": int(len(np.unique(days[mask]))),
        "blocks_6h": int(len(np.unique(quarter_days[mask]))),
        "excludes_zero_block_day": bool(block_hi < 0 or block_lo > 0),
        "wins_block_day": bool(block_hi < 0),
        "p_block_day": round(bootstrap_p(by_day), 6),
        "p_block_6h": round(bootstrap_p(by_six_hours), 6),
        "p_wilcoxon_optimistic": None if math.isnan(wilcoxon_p(d)) else round(wilcoxon_p(d), 6),
        "dm_day_bandwidth": {"statistic": None if math.isnan(dm_day[0]) else round(dm_day[0], 4),
                             "p": None if math.isnan(dm_day[1]) else round(dm_day[1], 6), "bandwidth": legs_per_day},
        "dm_cuberoot_bandwidth": {"statistic": None if math.isnan(dm_cuberoot[0]) else round(dm_cuberoot[0], 4),
                                  "p": None if math.isnan(dm_cuberoot[1]) else round(dm_cuberoot[1], 6),
                                  "bandwidth": int(np.floor(len(d) ** (1 / 3)))},
    }


def model_mae_interval(y: np.ndarray, pred: np.ndarray, days: np.ndarray, seed: int = SEED, n_boot: int = N_BOOT) -> dict:
    error = np.abs(y - pred)
    lo, hi = interval(block_bootstrap(error, days, n_boot, seed))
    return {"mae": round(float(error.mean()), 4), "ci_block_day": [round(lo, 4), round(hi, 4)]}


# ── driver ──────────────────────────────────────────────────────────────────
def load_predictions() -> pd.DataFrame:
    """One row per test leg with every `pred_*` column the study files provide, merged on leg_id."""
    frame = pd.read_csv(RAW / "b1_test_predictions.csv", parse_dates=["trip_creation_time"])
    for name in ("b1_v3_test_predictions.csv", "b6_test_predictions.csv"):
        path = RAW / name
        if path.exists():
            frame = frame.merge(pd.read_csv(path), on="leg_id", how="left", validate="one_to_one")
    return frame


def run(n_boot: int = N_BOOT) -> dict:
    from src.ml import backoff_baseline as bb
    from src.ml.baselines import time_split
    from src.ml.models_v2 import slice_masks

    predictions = load_predictions()
    rule = json.loads((RAW / "b1_backoff_baseline.json").read_text(encoding="utf-8"))
    bar_name = rule["bar"]["name"]
    bar = predictions[f"pred_{bar_name}"].to_numpy()
    y = predictions["gap_min"].to_numpy()

    frame = bb.load_legs()
    train_raw, test_raw, _ = time_split(frame)
    test_view = test_raw.reset_index(drop=True)
    if not (test_view["leg_id"].to_numpy() == predictions["leg_id"].to_numpy()).all():
        raise ValueError("the prediction file and the test split disagree on leg order")

    masks: dict[str, np.ndarray] = {}
    for name, mask in bb.regimes(test_view, train_raw).items():
        masks[name] = mask
    slice_names: list[str] = []
    for dimension, slices in slice_masks(test_view, train_raw).items():
        for name, mask in slices.items():
            key = "overall" if dimension == "overall" else f"{dimension}: {name}"
            masks.setdefault(key, mask)
            if dimension != "overall":
                slice_names.append(key)

    days = day_blocks(predictions["trip_creation_time"])
    quarter_days = hour_blocks(predictions["trip_creation_time"], hours=6)
    legs_per_day = int(np.median(np.bincount(days)))
    models = [c.removeprefix("pred_") for c in predictions.columns if c.startswith("pred_")]
    log.info("%d test legs, %d days, %d six-hour blocks, %d legs/day, bar %s, models %s", len(y),
             int(days.max()) + 1, int(quarter_days.max()) + 1, legs_per_day, bar_name, models)

    results: dict[str, dict] = {}
    for m_index, model in enumerate(models):
        pred = predictions[f"pred_{model}"].to_numpy()
        entry: dict = {"own_mae": model_mae_interval(y, pred, days, SEED + m_index, n_boot), "vs_bar": {}}
        if model != bar_name:
            for c_index, (name, mask) in enumerate(masks.items()):
                entry["vs_bar"][name] = compare(y, pred, bar, mask, days, quarter_days, legs_per_day,
                                                SEED + 1000 * (m_index + 1) + c_index, n_boot)
            # Holm across the 13 non-overall slices, separately for each test.
            for field, getter in (("holm_p_block_day", lambda c: c["p_block_day"]),
                                  ("holm_p_dm_day", lambda c: c["dm_day_bandwidth"]["p"] if c["dm_day_bandwidth"]["p"] is not None else float("nan")),
                                  ("holm_p_wilcoxon", lambda c: c["p_wilcoxon_optimistic"] if c["p_wilcoxon_optimistic"] is not None else float("nan"))):
                adjusted = holm([getter(entry["vs_bar"][s]) for s in slice_names])
                for s, p_adj in zip(slice_names, adjusted, strict=True):
                    entry["vs_bar"][s][field] = round(p_adj, 6)
            slice_rows = [entry["vs_bar"][s] for s in slice_names]
            overall = entry["vs_bar"]["overall"]
            entry["summary"] = {
                "slices_total_including_overall": len(slice_rows) + 1,
                "wins_block_ci_below_zero": int(sum(c["wins_block_day"] for c in slice_rows) + overall["wins_block_day"]),
                "wins_after_holm_block": int(sum(c["holm_p_block_day"] < 0.05 and c["delta_mae"] < 0 for c in slice_rows)
                                             + (overall["p_block_day"] < 0.05 and overall["delta_mae"] < 0)),
                "slices_point_estimate_below_zero": int(sum(c["delta_mae"] < 0 for c in slice_rows) + (overall["delta_mae"] < 0)),
                "overall_wins_block_ci_below_zero": bool(overall["wins_block_day"]),
            }
        results[model] = entry

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "decision": "D-076",
        "seed": SEED, "n_bootstrap": n_boot,
        "bar": bar_name,
        "test_legs": len(y), "calendar_days": int(days.max()) + 1, "six_hour_blocks": int(quarter_days.max()) + 1,
        "legs_per_day_median": legs_per_day,
        "interval_used_in_paper": "ci_block_day",
        "caution": "the day-block interval rests on about six blocks; the paired-leg interval ignores dependence and "
                   "is optimistic; Wilcoxon assumes independent pairs and is optimistic for the same reason",
        "models": results,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--boot", type=int, default=N_BOOT)
    args = parser.parse_args()
    for name in ("b1_backoff_baseline.json", "b1_test_predictions.csv"):
        if not (RAW / name).exists():
            log.error("Missing %s -- run `python -m src.ml.backoff_baseline` first.", Path(RAW / name))
            return 1
    report = run(args.boot)
    for model, entry in report["models"].items():
        summary = entry.get("summary")
        overall = entry["vs_bar"].get("overall")
        line = f"{model:18s} MAE {entry['own_mae']['mae']:.3f} {entry['own_mae']['ci_block_day']}"
        if overall:
            line += f" | vs bar {overall['delta_mae']:+.3f} block {overall['ci_block_day']} | wins {summary['wins_block_ci_below_zero']}/{summary['slices_total_including_overall']}"
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
