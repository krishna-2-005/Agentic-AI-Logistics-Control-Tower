"""Empirical-Bayes corridor ranking and its stability across support floors (B4, D-081).

    python -m src.ml.eb_ranking

The audit's top-20 changes with the support floor (D-018). This module fits, at each floor in
{5, 10, 20, 30}, a normal-normal model to the corridor means of `r = log(actual / osrm)`,

    ybar_c ~ N(theta_c, s_c^2 / n_c),     theta_c ~ N(mu, tau^2),

ranks corridors by the posterior probability that `theta_c` exceeds a material threshold, and
compares how much each ranking moves with the floor. Everything is pre-registered in D-081.

Writes `benchmarks/raw/b4_eb_ranking.json` and `b4_eb_corridors.csv`.
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
from scipy import optimize, stats

from src.common import config
from src.ml import audit_data
from src.ml.audit import correct_and_rank, welch_against_network

FLOORS = (5, 10, 20, 30)
TOP_N = 20
Z90 = 1.6448536269514722
THRESHOLD_FACTOR = 1.5
SENSITIVITY_FACTORS = (1.25, 2.0)
SCHEDULE_ICC = 0.0953  # intraclass correlation in b3_dependence_diagnostics.json (D-083)
BOOTSTRAP_REPS = 200
SEED = 20260802
OUT_JSON = config.BENCHMARKS_RAW_DIR / "b4_eb_ranking.json"
OUT_CSV = config.BENCHMARKS_RAW_DIR / "b4_eb_corridors.csv"
RANKINGS = ("raw_published", "raw_mean", "eb_prob", "eb_postmean")


# ── The normal-normal model ────────────────────────────────────────────────────────────


def _wmean(y: np.ndarray, v: np.ndarray, tau2: float) -> tuple[float, float]:
    w = 1.0 / (v + tau2)
    return float((w * y).sum() / w.sum()), float(w.sum())


def tau2_dl(y: np.ndarray, v: np.ndarray) -> float:
    """DerSimonian-Laird method-of-moments between-corridor variance."""
    w = 1.0 / v
    mu = (w * y).sum() / w.sum()
    q = float((w * (y - mu) ** 2).sum())
    denom = w.sum() - (w**2).sum() / w.sum()
    return max(0.0, (q - (len(y) - 1)) / denom)


def _neg_loglik(tau2: float, y: np.ndarray, v: np.ndarray, reml: bool) -> float:
    mu, sw = _wmean(y, v, tau2)
    w = 1.0 / (v + tau2)
    ll = -0.5 * (np.log(v + tau2).sum() + (w * (y - mu) ** 2).sum())
    if reml:
        ll -= 0.5 * np.log(sw)
    return -float(ll)


def tau2_likelihood(y: np.ndarray, v: np.ndarray, reml: bool) -> float:
    """ML or REML between-corridor variance by bounded 1-D search (boundary 0 included)."""
    hi = max(float(np.var(y)) * 4.0, 1e-6)
    res = optimize.minimize_scalar(
        _neg_loglik, bounds=(0.0, hi), args=(y, v, reml), method="bounded",
        options={"xatol": 1e-10},
    )
    at_zero = _neg_loglik(0.0, y, v, reml)
    return 0.0 if at_zero <= res.fun else float(res.x)


def posterior(y: np.ndarray, v: np.ndarray, tau2: float, threshold: float) -> dict:
    """Posterior mean, sd, 90% interval and P(theta > threshold) per corridor.

    The variance includes the uncertainty of `mu_hat` (D-081), `B_c^2 Var(mu_hat)`.
    """
    mu, sw = _wmean(y, v, tau2)
    b = v / (v + tau2)
    mean = (1.0 - b) * y + b * mu
    var = (1.0 - b) * v + b**2 / sw
    sd = np.sqrt(var)
    z = (mean - threshold) / sd
    return {
        "mu": mu,
        "shrink": b,
        "mean": mean,
        "sd": sd,
        "lo90": mean - Z90 * sd,
        "hi90": mean + Z90 * sd,
        "z": z,
        "p_exceed": stats.norm.cdf(z),
    }


# ── Rankings and stability ─────────────────────────────────────────────────────────────


def design_effect(n_legs: np.ndarray, n_cells: np.ndarray, icc: float = SCHEDULE_ICC) -> np.ndarray:
    """D-083 design effect, `1 + (n_c / k_c - 1) * icc`."""
    return 1.0 + (np.maximum(n_legs / n_cells, 1.0) - 1.0) * icc


def floor_rankings(
    tab: pd.DataFrame,
    baseline: dict,
    floor: int,
    threshold: float,
    estimator: str = "reml",
    de: pd.Series | None = None,
) -> dict:
    """All four rankings on the corridors with at least `floor` legs.

    `tab` has `corridor_id`, `n_legs`, `sum_log`, `sumsq_log`. Returns, per ranking, the full
    ordering (best first) and the number of corridors eligible for a top list, plus the fit.
    """
    kept = tab[tab["n_legs"] >= floor].reset_index(drop=True)
    audited = correct_and_rank(welch_against_network(kept, baseline))
    audited = audited.set_index("corridor_id")
    ids = kept["corridor_id"].to_numpy()
    a = audited.loc[ids]
    y = a["mean_log"].to_numpy()
    v = a["var_log"].to_numpy() / a["n_legs"].to_numpy()
    if de is not None:
        v = v * de.loc[ids].to_numpy()
    fit = {
        "reml": tau2_likelihood(y, v, True),
        "ml": tau2_likelihood(y, v, False),
        "dl": tau2_dl(y, v),
    }
    post = posterior(y, v, fit[estimator], threshold)

    sig_worse = (a["is_significant"] & (a["direction"] == "worse")).to_numpy()
    order_pub = np.lexsort((-a["excess_ratio"].to_numpy(), ~sig_worse))
    orders = {
        "raw_published": (ids[order_pub], int(sig_worse.sum())),
        "raw_mean": (ids[np.argsort(-y, kind="stable")], len(ids)),
        "eb_prob": (ids[np.lexsort((-post["mean"], -post["z"]))], len(ids)),
        "eb_postmean": (ids[np.argsort(-post["mean"], kind="stable")], len(ids)),
    }
    return {"orders": orders, "fit": fit, "post": post, "ids": ids, "audited": a, "y": y, "v": v}


def top_list(order: np.ndarray, n_candidates: int, restrict: set | None = None, k: int = TOP_N):
    """First `k` eligible corridors of an ordering, optionally within a corridor set."""
    eligible = order[:n_candidates]
    if restrict is not None:
        eligible = np.array([c for c in eligible if c in restrict], dtype=object)
    return list(eligible[:k])


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if (a | b) else float("nan")


def pair_stability(results: dict[int, dict], ranking: str) -> list[dict]:
    """Jaccard, Spearman and common-set Jaccard for every pair of floors."""
    rows = []
    for fa, fb in itertools.combinations(sorted(results), 2):
        oa, na = results[fa]["orders"][ranking]
        ob, nb = results[fb]["orders"][ranking]
        set_b = set(results[fb]["ids"])
        pos_a = {c: i for i, c in enumerate(oa)}
        pos_b = {c: i for i, c in enumerate(ob)}
        common = [c for c in oa if c in set_b]
        rho = stats.spearmanr([pos_a[c] for c in common], [pos_b[c] for c in common]).statistic
        rows.append(
            {
                "floors": f"{fa}|{fb}",
                "jaccard_top20": jaccard(top_list(oa, na), top_list(ob, nb)),
                "common_set_jaccard_top20": jaccard(top_list(oa, na, set_b), top_list(ob, nb)),
                "spearman_rank_positions": float(rho),
                "corridors_in_both": len(common),
            }
        )
    return rows


def mean_pairwise_jaccard(results: dict[int, dict], ranking: str) -> float:
    vals = []
    for fa, fb in itertools.combinations(sorted(results), 2):
        oa, na = results[fa]["orders"][ranking]
        ob, nb = results[fb]["orders"][ranking]
        vals.append(jaccard(top_list(oa, na), top_list(ob, nb)))
    return float(np.mean(vals))


def corridor_sums(legs: pd.DataFrame) -> pd.DataFrame:
    """`corridor_id`, `n_legs`, `sum_log`, `sumsq_log` for every corridor."""
    g = legs.assign(rr=legs["r"] ** 2).groupby("corridor_id", sort=True)
    return g.agg(n_legs=("r", "size"), sum_log=("r", "sum"), sumsq_log=("rr", "sum")).reset_index()


def bootstrap(legs: pd.DataFrame, threshold: float, reps: int, seed: int) -> dict:
    """Resample legs within each corridor; recompute the mean pairwise Jaccard per ranking."""
    legs = legs.sort_values("corridor_id", kind="stable").reset_index(drop=True)
    r = legs["r"].to_numpy()
    codes, uniq = pd.factorize(legs["corridor_id"])
    n = np.bincount(codes)
    start = np.concatenate([[0], np.cumsum(n)[:-1]])
    rng = np.random.default_rng(seed)
    out: dict[str, list[float]] = {k: [] for k in RANKINGS}
    for _ in range(reps):
        idx = start[codes] + np.floor(rng.random(len(r)) * n[codes]).astype(int)
        rb = r[idx]
        s1 = np.bincount(codes, weights=rb)
        # A resample can repeat one value n times; the identity then rounds a hair below 0.
        s2 = np.maximum(np.bincount(codes, weights=rb * rb), s1**2 / n)
        tab = pd.DataFrame({"corridor_id": uniq, "n_legs": n, "sum_log": s1, "sumsq_log": s2})
        base = audit_data.network_totals(rb)
        res = {f: floor_rankings(tab, base, f, threshold) for f in FLOORS}
        for k in RANKINGS:
            out[k].append(mean_pairwise_jaccard(res, k))
    arr = {k: np.array(v) for k, v in out.items()}

    def ci(x):
        return [float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))]

    return {
        "reps": reps,
        "seed": seed,
        "mean_pairwise_jaccard_ci95": {k: ci(arr[k]) for k in RANKINGS},
        "mean_pairwise_jaccard_boot_mean": {k: float(arr[k].mean()) for k in RANKINGS},
        "diff_eb_prob_minus_raw_published_ci95": ci(arr["eb_prob"] - arr["raw_published"]),
        "diff_eb_prob_minus_raw_mean_ci95": ci(arr["eb_prob"] - arr["raw_mean"]),
    }


def run(reps: int = BOOTSTRAP_REPS, seed: int = SEED) -> dict:
    t0 = time.time()
    legs = audit_data.load_legs()
    base = audit_data.network_totals(legs["r"].to_numpy())
    net_mean = base["sum"] / base["n"]
    thr = net_mean + float(np.log(THRESHOLD_FACTOR))
    tab = corridor_sums(legs)
    cells = (legs["corridor_id"] + "|" + legs["schedule"]).groupby(legs["corridor_id"]).nunique()
    de = pd.Series(design_effect(tab["n_legs"].to_numpy(), cells.loc[tab["corridor_id"]].to_numpy()),
                   index=tab["corridor_id"].to_numpy())

    res = {f: floor_rankings(tab, base, f, thr) for f in FLOORS}
    res_cluster = {f: floor_rankings(tab, base, f, thr, de=de) for f in FLOORS}
    res_dl = {f: floor_rankings(tab, base, f, thr, estimator="dl") for f in FLOORS}
    res_sens = {
        fac: {f: floor_rankings(tab, base, f, net_mean + float(np.log(fac))) for f in FLOORS}
        for fac in SENSITIVITY_FACTORS
    }

    stability = {k: pair_stability(res, k) for k in RANKINGS}
    summary: dict[str, Any] = {}
    for k in RANKINGS:
        rows = stability[k]
        summary[k] = {
            "mean_pairwise_jaccard_top20": float(np.mean([r["jaccard_top20"] for r in rows])),
            "min_pairwise_jaccard_top20": float(np.min([r["jaccard_top20"] for r in rows])),
            "mean_common_set_jaccard_top20": float(np.mean([r["common_set_jaccard_top20"] for r in rows])),
            "mean_spearman_rank_positions": float(np.mean([r["spearman_rank_positions"] for r in rows])),
            "top20_mean_n_legs_by_floor": {
                str(f): float(
                    tab.set_index("corridor_id")
                    .loc[top_list(*res[f]["orders"][k])]["n_legs"].mean()
                )
                for f in FLOORS
            },
            "top20_min_n_legs_by_floor": {
                str(f): int(
                    tab.set_index("corridor_id")
                    .loc[top_list(*res[f]["orders"][k])]["n_legs"].min()
                )
                for f in FLOORS
            },
        }

    boot = bootstrap(legs, thr, reps, seed) if reps else None
    verdict = None
    if boot:
        better_than = []
        for other, key in (("raw_published", "diff_eb_prob_minus_raw_published_ci95"),
                           ("raw_mean", "diff_eb_prob_minus_raw_mean_ci95")):
            point = summary["eb_prob"]["mean_pairwise_jaccard_top20"] - summary[other]["mean_pairwise_jaccard_top20"]
            lo, hi = boot[key]
            better_than.append(point > 0 and lo > 0)
            summary.setdefault("eb_prob_vs", {})[other] = {"difference": point, "ci95": [lo, hi]}
        if all(better_than):
            verdict = "eb_more_stable"
        elif any(summary["eb_prob_vs"][o]["difference"] < 0 and summary["eb_prob_vs"][o]["ci95"][1] < 0
                 for o in ("raw_published", "raw_mean")):
            verdict = "eb_not_more_stable"
        else:
            verdict = "no_detectable_difference"

    f10 = res[10]
    p10, ids10 = f10["post"], f10["ids"]
    n10 = tab.set_index("corridor_id").loc[ids10]["n_legs"].to_numpy()
    bins = {"10-14": (10, 14), "15-24": (15, 24), "25-49": (25, 49), "50+": (50, 10**9)}
    shrink_by_n = {
        name: float(np.median(p10["shrink"][(n10 >= lo) & (n10 <= hi)]))
        for name, (lo, hi) in bins.items() if ((n10 >= lo) & (n10 <= hi)).any()
    }

    estimator_check = {}
    for f in FLOORS:
        fit = res[f]["fit"]
        o_reml, n1 = res[f]["orders"]["eb_prob"]
        o_dl, n2 = res_dl[f]["orders"]["eb_prob"]
        estimator_check[str(f)] = {
            "tau2_reml": fit["reml"], "tau2_ml": fit["ml"], "tau2_dl": fit["dl"],
            "mu_reml": res[f]["post"]["mu"],
            "reml_vs_dl_relative_difference": abs(fit["reml"] - fit["dl"]) / fit["reml"] if fit["reml"] > 0 else None,
            "top20_jaccard_reml_vs_dl": jaccard(top_list(o_reml, n1), top_list(o_dl, n2)),
            "corridors": int(len(res[f]["ids"])),
        }

    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "decision": "D-081",
        "floors": list(FLOORS),
        "network_mean_log": net_mean,
        "threshold_log": thr,
        "threshold_ratio_vs_plan": float(np.exp(thr)),
        "threshold_factor": THRESHOLD_FACTOR,
        "headline_estimator": "reml",
        "estimator_check": estimator_check,
        "summary": summary,
        "verdict_rule_d081": verdict,
        "pair_stability": stability,
        "bootstrap": boot,
        "cluster_adjusted_variance_sensitivity": {
            "design_effect_median": float(de.median()),
            **{
                k: {
                    "mean_pairwise_jaccard_top20": mean_pairwise_jaccard(res_cluster, k),
                    "tau2_reml_by_floor": {str(f): res_cluster[f]["fit"]["reml"] for f in FLOORS},
                }
                for k in ("eb_prob", "eb_postmean")
            },
        },
        "threshold_sensitivity_eb_prob_mean_pairwise_jaccard": {
            str(fac): mean_pairwise_jaccard(r, "eb_prob") for fac, r in res_sens.items()
        },
        "floor10": {
            "corridors": int(len(ids10)),
            "median_shrink_factor_by_n_legs": shrink_by_n,
            "corridors_p_exceed_ge_0.5": int((p10["p_exceed"] >= 0.5).sum()),
            "corridors_p_exceed_ge_0.9": int((p10["p_exceed"] >= 0.9).sum()),
            "corridors_90pct_interval_above_threshold": int((p10["lo90"] > thr).sum()),
            "corridors_raw_mean_above_threshold": int((f10["y"] > thr).sum()),
            "published_slower": int(
                (f10["audited"]["is_significant"] & (f10["audited"]["direction"] == "worse")).sum()
            ),
        },
        "seconds": round(time.time() - t0, 1),
    }

    names = pd.read_csv(audit_data.PUBLISHED_AUDIT).set_index("corridor_id")[
        ["source_city", "dest_city", "source_state", "dest_state"]
    ]
    out = pd.DataFrame({"corridor_id": ids10}).set_index("corridor_id")
    out["n_legs"] = n10
    out["raw_mean_log"] = f10["y"]
    out["raw_excess_ratio"] = f10["audited"]["excess_ratio"].to_numpy()
    out["raw_significant_slower"] = (
        f10["audited"]["is_significant"] & (f10["audited"]["direction"] == "worse")
    ).to_numpy()
    out["eb_post_mean"] = p10["mean"]
    out["eb_lo90"], out["eb_hi90"] = p10["lo90"], p10["hi90"]
    out["eb_p_exceed"] = p10["p_exceed"]
    out["eb_shrink_factor"] = p10["shrink"]
    for f in FLOORS:
        for k in ("raw_published", "eb_prob", "raw_mean"):
            order = res[f]["orders"][k][0]
            out[f"rank_{k}_floor{f}"] = pd.Series(np.arange(1, len(order) + 1), index=order)
    out = out.join(names)
    out.reset_index().to_csv(OUT_CSV, index=False)
    OUT_JSON.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bootstrap", type=int, default=BOOTSTRAP_REPS)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()
    res = run(args.bootstrap, args.seed)
    brief = {k: res[k] for k in ("threshold_log", "headline_estimator", "verdict_rule_d081", "seconds")}
    brief["summary"] = res["summary"]
    print(json.dumps(brief, indent=2))


if __name__ == "__main__":
    main()
