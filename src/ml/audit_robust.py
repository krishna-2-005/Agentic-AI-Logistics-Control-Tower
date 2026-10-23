"""Dependence-aware corridor audit (B3, pre-registered in D-080 on the evidence of D-083).

    python -m src.ml.audit_robust                  # 100,000 permutations
    python -m src.ml.audit_robust --permutations 20000

The published audit tests each corridor against the rest of the network with Welch's
t-test, which treats legs as independent. D-083 found legs of one corridor and one
recurring service (`route_schedule_uuid`) are correlated. This module re-runs the audit
four ways and applies the headline rule fixed in D-080 before anything was run:

* `bh_welch`  the published audit, Benjamini-Hochberg on Welch p-values
* `by_welch`  the same p-values, Benjamini-Yekutieli (valid under any dependence)
* `bh_perm`   cell-permutation p-values, Benjamini-Hochberg
* `by_perm`   cell-permutation p-values, Benjamini-Yekutieli

The permutation unit is the (corridor, route schedule) cell. One permutation shuffles the
cell mean log-ratios among cells of the same size stratum, each position keeping its size
and its corridor; the corridor statistic is its mean minus the mean of the rest.

Writes `benchmarks/raw/b3_audit_robust.json` and `b3_audit_robust_corridors.csv`.
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from scipy import sparse
from statsmodels.stats.multitest import multipletests

from src.common import config
from src.ml import audit_data
from src.ml.audit import ALPHA, welch_against_network

SEED = 20260801
PERMUTATIONS = 100_000
PLACEBO_REPS = 200
TOP_N = 20
OUT_JSON = config.BENCHMARKS_RAW_DIR / "b3_audit_robust.json"
OUT_CSV = config.BENCHMARKS_RAW_DIR / "b3_audit_robust_corridors.csv"

#: Cells of 1..8 legs are their own stratum; larger ones are binned (D-080).
STRATUM_EDGES = (9, 12, 16, 23)
VARIANTS = ("bh_welch", "by_welch", "bh_perm", "by_perm")
#: Final tie-break of the headline rule (D-080 amendment): more conservative first.
TIE_ORDER = ("by_perm", "bh_perm", "by_welch", "bh_welch")


def size_stratum(m: np.ndarray) -> np.ndarray:
    """Stratum index of each cell size: 0..7 exact for sizes 1..8, then four bins."""
    m = np.asarray(m)
    return np.where(m <= 8, m - 1, 8 + np.searchsorted(STRATUM_EDGES, m, side="right") - 1)


class CellModel:
    """Cells over all legs, and the incidence of tested corridors on them."""

    def __init__(self, legs: pd.DataFrame, tested_ids: np.ndarray):
        key = legs["corridor_id"] + "|" + legs["schedule"]
        cell_code, cell_index = pd.factorize(key)
        r = legs["r"].to_numpy(dtype=float)
        n_cells = len(cell_index)
        m = np.bincount(cell_code, minlength=n_cells).astype(float)
        s = np.bincount(cell_code, weights=r, minlength=n_cells)
        ybar = s / m
        dev = r - ybar[cell_code]
        ss_dev = np.bincount(cell_code, weights=dev * dev, minlength=n_cells)
        cell_corridor = (
            legs.groupby(cell_code)["corridor_id"].first().to_numpy()
        )
        pos = {c: i for i, c in enumerate(tested_ids)}
        corr_idx = np.array([pos.get(c, -1) for c in cell_corridor])
        order = np.argsort(size_stratum(m), kind="stable")
        self.m = m[order]
        self.ybar = ybar[order]
        self.ss_dev = ss_dev[order]
        self.stratum = size_stratum(m)[order].astype(float)
        corr_sorted = corr_idx[order]
        k = len(tested_ids)
        use = corr_sorted >= 0
        self.incidence = sparse.csr_matrix(
            (np.ones(use.sum()), (np.flatnonzero(use), corr_sorted[use])), shape=(n_cells, k)
        )
        self.n_cells = n_cells
        self.n_corr_cells = np.asarray(self.incidence.sum(axis=0)).ravel().astype(int)
        self.n_legs = int(m.sum())
        self.n_c = np.asarray(self.incidence.T @ self.m).ravel()

    def permuted_means(self, rng: np.random.Generator, reps: int) -> np.ndarray:
        """`reps` x cells matrix of cell means shuffled within size strata."""
        key = self.stratum[None, :] + rng.random((reps, self.n_cells))
        perm = np.argsort(key, axis=1)
        return self.ybar[perm]

    def corridor_sums(self, ybar_mat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Per-corridor leg sums (reps x K) and the network total per rep."""
        w = ybar_mat * self.m[None, :]
        return np.asarray(w @ self.incidence), w.sum(axis=1)

    def difference(self, s_c: np.ndarray, tot: np.ndarray) -> np.ndarray:
        """Corridor mean minus the mean of the rest, from leg sums."""
        n_c = self.n_c[None, :]
        return s_c / n_c - (tot[:, None] - s_c) / (self.n_legs - n_c)


def permutation_pvalues(model: CellModel, permutations: int, seed: int, chunk: int = 500):
    """Two-sided cell-permutation p-values for the observed corridor differences."""
    s_obs, tot_obs = model.corridor_sums(model.ybar[None, :])
    d_obs = model.difference(s_obs, tot_obs)[0]
    rng = np.random.default_rng(seed)
    exceed = np.zeros(len(d_obs), dtype=np.int64)
    done = 0
    while done < permutations:
        reps = min(chunk, permutations - done)
        s_p, tot_p = model.corridor_sums(model.permuted_means(rng, reps))
        d_p = model.difference(s_p, tot_p)
        exceed += (np.abs(d_p) >= np.abs(d_obs)[None, :] - 1e-12).sum(axis=0)
        done += reps
    return d_obs, (1.0 + exceed) / (permutations + 1.0)


def placebo_size(model: CellModel, reps: int, seed: int, alpha: float = ALPHA) -> dict:
    """Welch's behaviour when no corridor effect exists but the cell structure does.

    Cell means are shuffled within strata and each leg keeps its deviation from its own
    cell mean, so cells stay internally correlated while corridor membership carries no
    information. Welch p-values are computed per placebo dataset with the audit's own
    `welch_against_network`.
    """
    rng = np.random.default_rng(seed + 1)
    ybar_mat = model.permuted_means(rng, reps)
    s_c, tot = model.corridor_sums(ybar_mat)
    ss_cell = ybar_mat**2 * model.m[None, :] + model.ss_dev[None, :]
    ss_c = np.asarray(ss_cell @ model.incidence)
    ss_tot = ss_cell.sum(axis=1)
    reject, discoveries = [], []
    for i in range(reps):
        tab = pd.DataFrame(
            {"n_legs": model.n_c, "sum_log": s_c[i], "sumsq_log": ss_c[i]}
        )
        out = welch_against_network(
            tab, {"n": model.n_legs, "sum": float(tot[i]), "sumsq": float(ss_tot[i])}
        )
        p = out["p_value"].to_numpy()
        reject.append(float((p < alpha).mean()))
        discoveries.append(int(multipletests(p, alpha=alpha, method="fdr_bh")[0].sum()))
    return {
        "placebo_datasets": reps,
        "welch_uncorrected_rejection_rate_at_0.05": float(np.mean(reject)),
        "welch_uncorrected_rejection_rate_max": float(np.max(reject)),
        "bh_welch_mean_discoveries": float(np.mean(discoveries)),
        "bh_welch_max_discoveries": int(np.max(discoveries)),
        "bh_welch_datasets_with_any_discovery": int(np.sum(np.array(discoveries) > 0)),
    }


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a | b) else float("nan")


def headline_variant(slower: dict[str, int], faster: dict[str, int]) -> str:
    """D-080: fewest significantly slower corridors; ties go to fewest faster, then `TIE_ORDER`."""
    return min(VARIANTS, key=lambda v: (slower[v], faster[v], TIE_ORDER.index(v)))


def classify_corridors(tab: pd.DataFrame, headline: str) -> pd.Series:
    """`robust` = significant under the headline and `bh_welch`; `fragile` = original only."""
    sig_h, sig_o = tab[f"sig_{headline}"], tab["sig_bh_welch"]
    status = np.select(
        [sig_h & sig_o, sig_o & ~sig_h, sig_h & ~sig_o],
        ["robust", "fragile", "headline_only"],
        default="not_significant",
    )
    return pd.Series(status, index=tab.index)


def run(permutations: int = PERMUTATIONS, seed: int = SEED, placebo: int = PLACEBO_REPS) -> dict:
    t0 = time.time()
    legs = audit_data.load_legs()
    audited = audit_data.welch_audit(legs).sort_values("corridor_id").reset_index(drop=True)
    pub = pd.read_csv(audit_data.PUBLISHED_AUDIT).set_index("corridor_id")
    ref = pub.loc[audited["corridor_id"]]
    repro_err = float(np.abs(audited["p_value"].to_numpy() - ref["p_value"].to_numpy()).max())
    s0, f0 = audit_data.significant_sets(audited)
    if (len(s0), len(f0)) != (273, 512):
        raise AssertionError(f"published headline not reproduced: {len(s0)} / {len(f0)}")

    model = CellModel(legs, audited["corridor_id"].to_numpy())
    d_obs, p_perm = permutation_pvalues(model, permutations, seed)
    p_welch = audited["p_value"].to_numpy()

    tab = audited[["corridor_id", "n_legs", "n_trips", "mean_log", "rest_mean_log", "excess_ratio"]].copy()
    tab["n_cells"] = model.n_corr_cells
    tab["diff_mean_log"] = d_obs
    tab["p_welch"], tab["p_perm"] = p_welch, p_perm
    for name, p in (("welch", p_welch), ("perm", p_perm)):
        for short, method in (("bh", "fdr_bh"), ("by", "fdr_by")):
            rej, q, _, _ = multipletests(p, alpha=ALPHA, method=method)
            tab[f"q_{short}_{name}"] = q
            tab[f"sig_{short}_{name}"] = rej
    tab["direction"] = np.where(tab["excess_ratio"] >= 1, "worse", "better")
    names = pub.loc[tab["corridor_id"], ["source_city", "dest_city", "source_state", "dest_state"]]
    for col in names.columns:
        tab[col] = names[col].to_numpy()

    slower = {v: int((tab[f"sig_{v}"] & (tab["direction"] == "worse")).sum()) for v in VARIANTS}
    faster = {v: int((tab[f"sig_{v}"] & (tab["direction"] == "better")).sum()) for v in VARIANTS}
    head = headline_variant(slower, faster)
    tab["status"] = classify_corridors(tab, head)
    tab["headline_variant"] = head

    is_slow0 = tab["sig_bh_welch"] & (tab["direction"] == "worse")
    is_fast0 = tab["sig_bh_welch"] & (tab["direction"] == "better")
    survive = {
        v: {
            "slower_of_273": int((is_slow0 & tab[f"sig_{v}"]).sum()),
            "faster_of_512": int((is_fast0 & tab[f"sig_{v}"]).sum()),
            "significant_slower": slower[v],
            "significant_faster": faster[v],
        }
        for v in VARIANTS
    }
    top = {}
    for v in VARIANTS:
        sel = tab[tab[f"sig_{v}"] & (tab["direction"] == "worse")]
        top[v] = list(sel.sort_values("excess_ratio", ascending=False)["corridor_id"].head(TOP_N))
    jac = {f"{a}|{b}": jaccard(set(top[a]), set(top[b])) for a, b in itertools.combinations(VARIANTS, 2)}
    slow_rows = tab[tab["direction"] == "worse"]
    by_perm_p = list(slow_rows.sort_values(["p_perm", "excess_ratio"], ascending=[True, False])["corridor_id"].head(TOP_N))
    status_counts = tab.loc[tab["status"] != "not_significant"].groupby(["status", "direction"]).size()

    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "decision": "D-080 (cluster unit D-083)",
        "corridors_tested": int(len(tab)),
        "alpha": ALPHA,
        "permutations": permutations,
        "seed": seed,
        "permutation_p_floor": 1.0 / (permutations + 1.0),
        "reproduction_max_abs_p_error_vs_published": repro_err,
        "published_slower": len(s0),
        "published_faster": len(f0),
        "cells_total": model.n_cells,
        "cells_in_tested_corridors": int(model.n_corr_cells.sum()),
        "variants": survive,
        "headline_variant": head,
        "headline_slower": slower[head],
        "headline_faster": faster[head],
        "headline_dropped_vs_published": bool(head != "bh_welch"),
        "robust_slower": int(((tab["status"] == "robust") & (tab["direction"] == "worse")).sum()),
        "robust_faster": int(((tab["status"] == "robust") & (tab["direction"] == "better")).sum()),
        "fragile_slower": int(((tab["status"] == "fragile") & (tab["direction"] == "worse")).sum()),
        "fragile_faster": int(((tab["status"] == "fragile") & (tab["direction"] == "better")).sum()),
        "headline_only_corridors": int((tab["status"] == "headline_only").sum()),
        "status_counts": {f"{a}_{b}": int(n) for (a, b), n in status_counts.items()},
        "top20_slower": top,
        "top20_slower_by_permutation_p": by_perm_p,
        "top20_jaccard_welch_list_vs_permutation_p_list": jaccard(set(top["bh_welch"]), set(by_perm_p)),
        "perm_p_below_0.05": int((tab["p_perm"] < 0.05).sum()),
        "perm_p_below_0.01": int((tab["p_perm"] < 0.01).sum()),
        "welch_p_below_0.05": int((tab["p_welch"] < 0.05).sum()),
        "perm_p_min": float(tab["p_perm"].min()),
        "median_cells_per_corridor": float(np.median(model.n_corr_cells)),
        "corridors_with_one_cell": int((model.n_corr_cells == 1).sum()),
        "top20_jaccard": jac,
        "top20_jaccard_min": float(min(jac.values())),
        "spearman_log10_p_welch_vs_perm": float(
            pd.Series(np.log10(p_welch)).corr(pd.Series(np.log10(p_perm)), method="spearman")
        ),
        "placebo": placebo_size(model, placebo, seed) if placebo else None,
        "seconds": round(time.time() - t0, 1),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    tab.to_csv(OUT_CSV, index=False)
    OUT_JSON.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--permutations", type=int, default=PERMUTATIONS)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--placebo", type=int, default=PLACEBO_REPS)
    ap.add_argument("--suffix", default="", help="write b3_audit_robust<suffix>.* instead (a sensitivity run, D-084)")
    args = ap.parse_args()
    global OUT_JSON, OUT_CSV
    if args.suffix:
        OUT_JSON = OUT_JSON.with_name(f"b3_audit_robust{args.suffix}.json")
        OUT_CSV = OUT_CSV.with_name(f"b3_audit_robust{args.suffix}_corridors.csv")
    res = run(args.permutations, args.seed, args.placebo)
    print(json.dumps({k: v for k, v in res.items() if k != "top20_slower"}, indent=2))


if __name__ == "__main__":
    main()
