"""Power of the cell-permutation corridor audit, by simulation (D-099, upgrade B9).

    python -m src.ml.audit_power

A zero ("0 of 273 confirmed", D-080) is ambiguous: no effect, or a test too weak to see one. This module plants
known corridor effects into the placebo world of D-080 (real cell structure, cell means shuffled within size strata,
so no corridor effect exists and cells stay internally correlated) and measures how often each of the four audit
variants finds them. Permutation p-values are empirical against a null bank built once from the real cell means (20,000 full draws plus
the 1,000 largest values per corridor out of 10^6 further draws), so they are exact down to 10^-6; the bank is
checked first against the real 10^6-permutation run and the check is written to the result file. Writes `b9_power.json`.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

from src.common import config
from src.common.logging_setup import get_logger
from src.ml import audit_data
from src.ml.audit import welch_against_network
from src.ml.audit_robust import ALPHA, CellModel

log = get_logger("ml.audit_power")

RAW = config.BENCHMARKS_RAW_DIR
OUT = RAW / "b9_power.json"
SEED = 20260901
DELTAS = (0.0, 0.10, 0.20, 0.30, 0.50, 0.75, 1.00)
DATASETS = 30
PLANTED_PER_BIN = 10
NULL_PERMUTATIONS = 20_000
BINS = (("10-14", 10, 14), ("15-24", 15, 24), ("25+", 25, 10**9))
TAIL_PERMUTATIONS = 1_000_000
TAIL_KEEP = 1000


class NullBank:
    """Per-corridor permutation null of the difference statistic, from the real cell means.

    Two parts, so that p-values are exact (empirical) all the way down to 1/(R_tail+1) without storing 10^6 x K values:
    the full null of `permutations` draws (accurate for p above about 10^-3), and the largest `TAIL_KEEP` values per
    corridor out of `tail_permutations` further draws (exact below that). A first version used a normal tail instead
    and failed its own calibration check (D-099 outcome); this replaces it.
    """

    def __init__(self, model: CellModel, permutations: int, tail_permutations: int, seed: int, chunk: int = 500):
        rng = np.random.default_rng(seed)
        k = model.incidence.shape[1]
        absd = np.empty((permutations, k), dtype=np.float32)
        done = 0
        while done < permutations:
            reps = min(chunk, permutations - done)
            s_p, tot_p = model.corridor_sums(model.permuted_means(rng, reps))
            absd[done:done + reps] = np.abs(model.difference(s_p, tot_p))
            done += reps
        self.absd = np.sort(absd, axis=0)
        self.permutations = permutations
        self.tail_permutations = tail_permutations
        top = np.full((TAIL_KEEP, k), -1.0, dtype=np.float32)
        rng_tail = np.random.default_rng(seed + 7)
        done = 0
        while done < tail_permutations:
            reps = min(chunk, tail_permutations - done)
            s_p, tot_p = model.corridor_sums(model.permuted_means(rng_tail, reps))
            block = np.abs(model.difference(s_p, tot_p)).astype(np.float32)
            merged = np.concatenate([top, block], axis=0)
            top = np.partition(merged, merged.shape[0] - TAIL_KEEP, axis=0)[merged.shape[0] - TAIL_KEEP:]
            done += reps
        self.tail = np.sort(top, axis=0)  # ascending; the smallest kept value is the TAIL_KEEP-th largest

    def pvalues(self, d_obs: np.ndarray) -> np.ndarray:
        """Two-sided empirical p-values for the observed statistics `d_obs` (one per corridor)."""
        a = np.abs(d_obs)
        p = np.empty_like(a, dtype=float)
        for c in range(len(a)):
            exceed_tail = TAIL_KEEP - int(np.searchsorted(self.tail[:, c], a[c] - 1e-12, side="left"))
            if exceed_tail < TAIL_KEEP:
                p[c] = (1.0 + exceed_tail) / (self.tail_permutations + 1.0)
            else:
                exceed = self.permutations - int(np.searchsorted(self.absd[:, c], a[c] - 1e-12, side="left"))
                p[c] = (1.0 + exceed) / (self.permutations + 1.0)
        return p


def calibration(model: CellModel, bank: NullBank) -> dict:
    """Bank p-values for the real statistics against the 10^6-permutation run of D-084."""
    s_obs, tot_obs = model.corridor_sums(model.ybar[None, :])
    d_obs = model.difference(s_obs, tot_obs)[0]
    hybrid = bank.pvalues(d_obs)
    ref = pd.read_csv(RAW / "b3_audit_robust_1e6_corridors.csv")
    legs = audit_data.load_legs()
    ids = audit_data.welch_audit(legs).sort_values("corridor_id")["corridor_id"].to_numpy()
    ref = ref.set_index("corridor_id").loc[ids]
    exact = ref["p_perm"].to_numpy()
    out: dict[str, float | int | None] = {"corridors": int(len(ids)), "reference_permutations": 1_000_000}
    for method in ("fdr_bh", "fdr_by"):
        rej_h = multipletests(hybrid, alpha=ALPHA, method=method)[0]
        rej_x = multipletests(exact, alpha=ALPHA, method=method)[0]
        out[f"disagreements_{method}"] = int((rej_h != rej_x).sum())
    small = exact < 1e-3
    out["corridors_with_reference_p_below_1e-3"] = int(small.sum())
    if small.sum() > 2:
        out["spearman_log10p_below_1e-3"] = float(
            pd.Series(np.log10(hybrid[small])).corr(pd.Series(np.log10(exact[small])), method="spearman"))
    out["median_abs_log10_ratio_below_1e-3"] = (
        float(np.median(np.abs(np.log10(hybrid[small]) - np.log10(exact[small])))) if small.any() else None)
    return out


def plant(model: CellModel, rng: np.random.Generator, delta: float, corridors: np.ndarray):
    """Shuffled-world cell means with `delta` added to every cell of the planted corridors."""
    ybar = model.permuted_means(rng, 1)[0].copy()
    if delta:
        mask = np.zeros(model.incidence.shape[1], dtype=float)
        mask[corridors] = 1.0
        ybar += delta * np.asarray(model.incidence @ mask).ravel()
    return ybar


def run_dataset(model: CellModel, bank: NullBank, ybar: np.ndarray) -> dict[str, np.ndarray]:
    w = (ybar * model.m)[None, :]
    s_c = np.asarray(w @ model.incidence)[0]
    tot = float(w.sum())
    d_obs = model.difference(s_c[None, :], np.array([tot]))[0]
    ss_cell = ybar**2 * model.m + model.ss_dev
    ss_c = np.asarray(ss_cell[None, :] @ model.incidence)[0]
    table = pd.DataFrame({"n_legs": model.n_c, "sum_log": s_c, "sumsq_log": ss_c})
    welch = welch_against_network(table, {"n": model.n_legs, "sum": tot, "sumsq": float(ss_cell.sum())})
    p_welch = welch["p_value"].to_numpy()
    p_perm = bank.pvalues(d_obs)
    rises = d_obs > 0
    out = {"rises": rises}
    for name, p in (("welch", p_welch), ("perm", p_perm)):
        for short, method in (("bh", "fdr_bh"), ("by", "fdr_by")):
            out[f"{short}_{name}"] = multipletests(p, alpha=ALPHA, method=method)[0]
    return out


def choose(model: CellModel, rng: np.random.Generator) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    n_c = model.n_c
    chosen, by_bin = [], {}
    for label, lo, hi in BINS:
        pool = np.flatnonzero((n_c >= lo) & (n_c <= hi))
        pick = rng.choice(pool, size=min(PLANTED_PER_BIN, len(pool)), replace=False)
        chosen.extend(pick.tolist())
        by_bin[label] = pick
    return np.array(chosen), by_bin


def run(datasets: int = DATASETS, null_permutations: int = NULL_PERMUTATIONS, tail_permutations: int = TAIL_PERMUTATIONS) -> dict:
    t0 = time.time()
    legs = audit_data.load_legs()
    audited = audit_data.welch_audit(legs).sort_values("corridor_id").reset_index(drop=True)
    model = CellModel(legs, audited["corridor_id"].to_numpy())
    bank = NullBank(model, null_permutations, tail_permutations, SEED)
    calib = calibration(model, bank)
    log.info("calibration: %s", calib)
    variants = ("bh_welch", "by_welch", "bh_perm", "by_perm")
    results = []
    for di, delta in enumerate(DELTAS):
        found: dict[str, list[float]] = {v: [] for v in variants}
        found_bin: dict[str, dict[str, list[float]]] = {v: {b[0]: [] for b in BINS} for v in variants}
        false_disc: dict[str, list[float]] = {v: [] for v in variants}
        for rep in range(datasets):
            rng = np.random.default_rng(SEED + 1000 * di + rep)
            planted, by_bin = choose(model, rng)
            ybar = plant(model, rng, delta, planted)
            out = run_dataset(model, bank, ybar)
            is_planted = np.zeros(len(model.n_c), dtype=bool)
            is_planted[planted] = True
            for v in variants:
                hit = out[v] & out["rises"]
                found[v].append(float(hit[planted].mean()))
                for label, idx in by_bin.items():
                    found_bin[v][label].append(float(hit[idx].mean()))
                rejected = out[v]
                wrong = rejected & ~(is_planted & out["rises"]) if delta else rejected  # no true effect at delta 0
                false_disc[v].append(float(wrong.sum() / max(rejected.sum(), 1)))
        results.append({
            "delta": delta, "datasets": datasets,
            "power": {v: round(float(np.mean(found[v])), 4) for v in variants},
            "power_by_leg_count": {v: {b: round(float(np.mean(x)), 4) for b, x in found_bin[v].items()} for v in variants},
            "false_discovery_proportion": {v: round(float(np.mean(false_disc[v])), 4) for v in variants},
        })
        log.info("delta %.2f: power %s", delta, results[-1]["power"])
    report = {"generated_at": datetime.now(UTC).isoformat(), "decision": "D-099", "seed": SEED,
              "null_permutations": null_permutations, "tail_permutations": tail_permutations, "tail_kept_per_corridor": TAIL_KEEP, "planted_per_bin": PLANTED_PER_BIN, "bins": [b[0] for b in BINS],
              "calibration": calib, "results": results, "seconds": round(time.time() - t0, 1)}
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datasets", type=int, default=DATASETS)
    ap.add_argument("--null-permutations", type=int, default=NULL_PERMUTATIONS)
    ap.add_argument("--tail-permutations", type=int, default=TAIL_PERMUTATIONS)
    args = ap.parse_args()
    run(args.datasets, args.null_permutations, args.tail_permutations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
