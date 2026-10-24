"""Temporal stability of the corridor audit (B5, pre-registered in D-082).

    python -m src.ml.stability

The 23 creation dates are split into halves and thirds; the audit (published Welch with
Benjamini-Hochberg, Benjamini-Yekutieli, the cell-permutation test of D-080) and the
empirical-Bayes ranking of D-081 are run on each part independently, and the parts are
compared: overlap of the significantly-slower sets, Spearman correlation of corridor
effects, and the share of an earlier part's flagged corridors still slower later.

Writes `benchmarks/raw/b5_stability.json` and `b5_stability_corridors.csv`.
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps
from statsmodels.stats.multitest import multipletests

from src.common import config
from src.ml import audit_data, audit_robust, eb_ranking
from src.ml.audit import ALPHA
from src.ml.stats import wilson

SEED = 20260803
BOOT = 2000
PERMS = audit_robust.PERMUTATIONS
TOP_N = 20
OUT_JSON = config.BENCHMARKS_RAW_DIR / "b5_stability.json"
OUT_CSV = config.BENCHMARKS_RAW_DIR / "b5_stability_corridors.csv"
RULES = ("bh_welch", "by_welch", "by_perm")
#: Proportional floors (D-082): the 10-leg floor scaled to the share of the window.
FLOORS = {"proportional": {2: 5, 3: 4}, "strict": {2: 10, 3: 10}}


def assign_parts(legs: pd.DataFrame, k: int) -> pd.Series:
    """Part index 0..k-1 of each leg: contiguous groups of creation dates, in date order."""
    dates = np.sort(legs["day"].unique())
    groups = np.array_split(np.arange(len(dates)), k)
    which = {d: i for i, g in enumerate(groups) for d in dates[g]}
    return legs["day"].map(which).astype(int)


def audit_part(part: pd.DataFrame, floor: int, threshold: float, perms: int, seed: int) -> pd.DataFrame:
    """One part audited on its own; one row per corridor with at least `floor` legs."""
    tab = eb_ranking.corridor_sums(part)
    base = audit_data.network_totals(part["r"].to_numpy())
    res = eb_ranking.floor_rankings(tab, base, floor, threshold)
    a = res["audited"]
    ids = res["ids"]
    out = pd.DataFrame(
        {
            "n_legs": a["n_legs"].to_numpy(),
            "mean_log": a["mean_log"].to_numpy(),
            "rest_mean_log": a["rest_mean_log"].to_numpy(),
            "excess_ratio": a["excess_ratio"].to_numpy(),
            "p_welch": a["p_value"].to_numpy(),
            "eb_mean": res["post"]["mean"],
            "eb_z": res["post"]["z"],
        },
        index=pd.Index(ids, name="corridor_id"),
    )
    slower = out["excess_ratio"] >= 1.0
    out["sig_bh_welch_slower"] = (a["is_significant"] & (a["direction"] == "worse")).to_numpy()
    rej, _, _, _ = multipletests(out["p_welch"].to_numpy(), alpha=ALPHA, method="fdr_by")
    out["sig_by_welch_slower"] = rej & slower.to_numpy()
    if perms:
        model = audit_robust.CellModel(part, ids)
        _, p_perm = audit_robust.permutation_pvalues(model, perms, seed)
        rej_p, _, _, _ = multipletests(p_perm, alpha=ALPHA, method="fdr_by")
        out["p_perm"] = p_perm
        out["sig_by_perm_slower"] = rej_p & slower.to_numpy()
    else:
        out["p_perm"] = np.nan
        out["sig_by_perm_slower"] = False
    order_eb, n_eb = res["orders"]["eb_prob"]
    order_raw, n_raw = res["orders"]["raw_published"]
    out["eb_top20"] = out.index.isin(eb_ranking.top_list(order_eb, n_eb))
    out["raw_top20"] = out.index.isin(eb_ranking.top_list(order_raw, n_raw))
    out["tau2_reml"] = res["fit"]["reml"]
    return out


def jaccard_flags(a: np.ndarray, b: np.ndarray) -> float:
    union = (a | b).sum()
    return float((a & b).sum() / union) if union else float("nan")


def set_overlap(a: np.ndarray, b: np.ndarray, rng: np.random.Generator, boot: int) -> dict:
    """Overlap of two boolean flag vectors over the same universe, with chance reference."""
    n, ka, kb, both = len(a), int(a.sum()), int(b.sum()), int((a & b).sum())
    expected = ka * kb / n if n else float("nan")
    p = float(sps.hypergeom.sf(both - 1, n, ka, kb)) if ka and kb else float("nan")
    cis = None
    if ka and kb and boot:
        idx = rng.integers(0, n, (boot, n))
        j = np.array([jaccard_flags(a[i], b[i]) for i in idx])
        cis = [float(np.nanpercentile(j, 2.5)), float(np.nanpercentile(j, 97.5))]
    return {
        "universe": n,
        "size_earlier": ka,
        "size_later": kb,
        "intersection": both,
        "jaccard": jaccard_flags(a, b),
        "jaccard_ci95_corridor_bootstrap": cis,
        "expected_intersection_by_chance": expected,
        "hypergeometric_p_one_sided": p,
        "above_chance": bool(p < 0.05) if p == p else False,
    }


def spearman(x: np.ndarray, y: np.ndarray, rng: np.random.Generator, boot: int) -> dict:
    rho = float(sps.spearmanr(x, y).statistic)
    n = len(x)
    ci = None
    if boot and n > 3:
        idx = rng.integers(0, n, (boot, n))
        vals = np.array([sps.spearmanr(x[i], y[i]).statistic for i in idx])
        ci = [float(np.nanpercentile(vals, 2.5)), float(np.nanpercentile(vals, 97.5))]
    label = "low" if rho < 0.3 else ("moderate" if rho < 0.6 else "substantial")
    return {"rho": rho, "n": n, "ci95_corridor_bootstrap": ci, "reading": label}


def persistence(flag: np.ndarray, later_slower: np.ndarray, later_sig: np.ndarray) -> dict:
    """Share of an earlier part's flagged corridors still slower (or significant) later."""
    k = int(flag.sum())
    return {
        "flagged": k,
        "still_slower": wilson(int((flag & later_slower).sum()), k).as_dict() if k else None,
        "still_significantly_slower": wilson(int((flag & later_sig).sum()), k).as_dict() if k else None,
    }


def compare_pair(early: pd.DataFrame, late: pd.DataFrame, rng: np.random.Generator, boot: int) -> dict:
    """All D-082 statistics for an earlier and a later part."""
    uni = early.index.intersection(late.index)
    e, l_ = early.loc[uni], late.loc[uni]
    later_slower = (l_["excess_ratio"] >= 1.0).to_numpy()
    later_sig = l_["sig_bh_welch_slower"].to_numpy()
    out: dict[str, Any] = {
        "universe": int(len(uni)),
        "base_rate_slower_in_later": float(later_slower.mean()) if len(uni) else None,
        "overlap": {
            r: set_overlap(e[f"sig_{r}_slower"].to_numpy(), l_[f"sig_{r}_slower"].to_numpy(), rng, boot)
            for r in RULES
        },
        "spearman_raw_mean": spearman(e["mean_log"].to_numpy(), l_["mean_log"].to_numpy(), rng, boot),
        "spearman_eb_posterior_mean": spearman(e["eb_mean"].to_numpy(), l_["eb_mean"].to_numpy(), rng, boot),
        "persistence": {
            "raw_bh_welch_slower_set": persistence(e["sig_bh_welch_slower"].to_numpy(), later_slower, later_sig),
            "raw_top20": persistence(e["raw_top20"].to_numpy(), later_slower, later_sig),
            "eb_top20": persistence(e["eb_top20"].to_numpy(), later_slower, later_sig),
        },
    }
    top_raw = out["persistence"]["raw_top20"]["still_slower"]
    top_eb = out["persistence"]["eb_top20"]["still_slower"]
    if top_raw and top_eb:
        overlap = top_raw["ci_low"] <= top_eb["ci_high"] and top_eb["ci_low"] <= top_raw["ci_high"]
        out["eb_vs_raw_top20_persistence_reading"] = (
            "no_detectable_difference" if overlap
            else ("eb_higher" if top_eb["rate"] > top_raw["rate"] else "raw_higher")
        )
    return out


def run(perms: int = PERMS, boot: int = BOOT, seed: int = SEED) -> dict:
    t0 = time.time()
    legs = audit_data.load_legs()
    net = audit_data.network_totals(legs["r"].to_numpy())
    thr = net["sum"] / net["n"] + float(np.log(eb_ranking.THRESHOLD_FACTOR))
    rng = np.random.default_rng(seed)
    result: dict = {
        "generated_at": datetime.now(UTC).isoformat(),
        "decision": "D-082",
        "threshold_log": thr,
        "permutations": perms,
        "bootstrap_reps": boot,
        "seed": seed,
        "settings": {},
    }
    csv_tab = None
    for setting, floors in FLOORS.items():
        result["settings"][setting] = {}
        for k in (2, 3):
            part_id = assign_parts(legs, k)
            audits, info = [], []
            for i in range(k):
                part = legs[part_id == i]
                aud = audit_part(part, floors[k], thr, perms, seed + 17 * i)
                audits.append(aud)
                dates = np.sort(part["day"].unique())
                info.append(
                    {
                        "first_date": str(pd.Timestamp(dates[0]).date()),
                        "last_date": str(pd.Timestamp(dates[-1]).date()),
                        "dates": int(len(dates)),
                        "legs": int(len(part)),
                        "floor": floors[k],
                        "corridors_tested": int(len(aud)),
                        "significant_slower": {r: int(aud[f"sig_{r}_slower"].sum()) for r in RULES},
                        "tau2_reml": float(aud["tau2_reml"].iloc[0]),
                    }
                )
            pairs = {}
            for a, b in itertools.combinations(range(k), 2):
                pairs[f"T{a + 1}->T{b + 1}" if k == 3 else "H1->H2"] = compare_pair(
                    audits[a], audits[b], rng, boot
                )
            result["settings"][setting]["halves" if k == 2 else "thirds"] = {
                "parts": info,
                "pairs": pairs,
            }
            if setting == "proportional" and k == 2:
                e, l_ = audits
                uni = e.index.intersection(l_.index)
                cols = ["n_legs", "mean_log", "excess_ratio", "eb_mean", "eb_z",
                        "sig_bh_welch_slower", "sig_by_welch_slower", "sig_by_perm_slower",
                        "raw_top20", "eb_top20"]
                csv_tab = e.loc[uni, cols].add_suffix("_h1").join(l_.loc[uni, cols].add_suffix("_h2"))
    h = result["settings"]["proportional"]["halves"]["pairs"]["H1->H2"]
    result["headline"] = {
        "universe_corridors_both_halves": h["universe"],
        "bh_welch_slower_jaccard": h["overlap"]["bh_welch"]["jaccard"],
        "bh_welch_slower_hypergeometric_p": h["overlap"]["bh_welch"]["hypergeometric_p_one_sided"],
        "spearman_raw_mean": h["spearman_raw_mean"]["rho"],
        "spearman_eb_posterior_mean": h["spearman_eb_posterior_mean"]["rho"],
        "raw_slower_set_still_slower_rate": (h["persistence"]["raw_bh_welch_slower_set"]["still_slower"] or {}).get("rate"),
        "raw_top20_still_slower_rate": (h["persistence"]["raw_top20"]["still_slower"] or {}).get("rate"),
        "eb_top20_still_slower_rate": (h["persistence"]["eb_top20"]["still_slower"] or {}).get("rate"),
        "base_rate_slower_in_later": h["base_rate_slower_in_later"],
    }
    result["seconds"] = round(time.time() - t0, 1)
    assert csv_tab is not None
    csv_tab.reset_index().to_csv(OUT_CSV, index=False)
    OUT_JSON.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--permutations", type=int, default=PERMS)
    ap.add_argument("--bootstrap", type=int, default=BOOT)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()
    res = run(args.permutations, args.bootstrap, args.seed)
    print(json.dumps(res["headline"], indent=2))


if __name__ == "__main__":
    main()
