"""Empirical-Bayes ranking with a heavy-tailed (Student t) prior on corridor effects (D-102, upgrade B10).

    python -m src.ml.eb_t

D-081 models corridor effects as normal. Here `theta_c ~ mu + tau * t_nu`, with the marginal likelihood of each corridor mean computed by
numerical integration over a grid of `theta`, `mu` and `tau` fitted by maximum likelihood for each `nu`, and the best `nu` kept. The ranking
by `P(theta_c > t)` is compared across the support floors of D-081 with the normal-prior and raw rankings. Writes `b10_eb_t.json`.
"""

from __future__ import annotations

import argparse
import itertools
import json
from datetime import UTC, datetime

import numpy as np
from scipy import optimize, stats

from src.common import config
from src.common.logging_setup import get_logger
from src.ml import audit_data, eb_ranking

log = get_logger("ml.eb_t")

RAW = config.BENCHMARKS_RAW_DIR
OUT = RAW / "b10_eb_t.json"
FLOORS = eb_ranking.FLOORS
NUS = (2.0, 3.0, 5.0, 10.0, 30.0, 1000.0)
GRID_POINTS = 3000


class Fit:
    """Marginal likelihood and posterior of one floor's corridors under a t prior."""

    def __init__(self, y: np.ndarray, v: np.ndarray):
        self.y, self.v = y, v
        self.theta = np.linspace(y.min() - 1.0, y.max() + 1.0, GRID_POINTS)
        self.dtheta = float(self.theta[1] - self.theta[0])
        sd = np.sqrt(v)[:, None]
        self.noise = stats.norm.pdf((y[:, None] - self.theta[None, :]) / sd) / sd

    def prior(self, mu: float, tau: float, nu: float) -> np.ndarray:
        return stats.t.pdf((self.theta - mu) / tau, df=nu) / tau

    def loglik(self, mu: float, tau: float, nu: float) -> float:
        integrand = self.noise * self.prior(mu, tau, nu)[None, :]
        marginal = integrand.sum(axis=1) * self.dtheta
        return float(np.log(np.maximum(marginal, 1e-300)).sum())

    def maximise(self, nu: float) -> tuple[float, float, float]:
        start = [float(np.average(self.y, weights=1 / self.v)), float(np.log(max(np.std(self.y) * 0.8, 0.05)))]
        res = optimize.minimize(lambda p: -self.loglik(p[0], float(np.exp(p[1])), nu), start, method="Nelder-Mead",
                                options={"xatol": 1e-4, "fatol": 1e-4, "maxiter": 200})
        return float(res.x[0]), float(np.exp(res.x[1])), float(-res.fun)

    def posterior(self, mu: float, tau: float, nu: float, threshold: float) -> dict:
        weights = self.noise * self.prior(mu, tau, nu)[None, :]
        weights /= weights.sum(axis=1, keepdims=True)
        mean = weights @ self.theta
        exceed = weights[:, self.theta > threshold].sum(axis=1)
        return {"mean": mean, "z": exceed}


def run() -> dict:
    legs = audit_data.load_legs()
    tab = eb_ranking.corridor_sums(legs)
    base = audit_data.network_totals(legs["r"].to_numpy())
    threshold = float(json.loads((RAW / "b4_eb_ranking.json").read_text(encoding="utf-8"))["threshold_log"])
    results: dict[int, dict] = {}
    fits: dict[str, dict] = {}
    for floor in FLOORS:
        res = eb_ranking.floor_rankings(tab, base, floor, threshold)
        y, v, ids = res["y"], res["v"], res["ids"]
        fit = Fit(y, v)
        by_nu = {}
        for nu in NUS:
            mu, tau, ll = fit.maximise(nu)
            by_nu[nu] = {"mu": mu, "tau": tau, "loglik": ll}
            log.info("floor %d nu %g: mu %.3f tau %.3f loglik %.2f", floor, nu, mu, tau, ll)
        best = max(by_nu, key=lambda k: by_nu[k]["loglik"])
        gain = by_nu[best]["loglik"] - by_nu[1000.0]["loglik"]
        post = fit.posterior(by_nu[best]["mu"], by_nu[best]["tau"], best, threshold)
        order = ids[np.lexsort((-post["mean"], -post["z"]))]
        top_decile = y >= np.percentile(y, 90)
        shrink = (post["mean"] - by_nu[best]["mu"]) / np.where(np.abs(y - by_nu[best]["mu"]) > 1e-9, y - by_nu[best]["mu"], np.nan)
        normal_shrink = (res["post"]["mean"] - by_nu[1000.0]["mu"]) / np.where(np.abs(y - by_nu[1000.0]["mu"]) > 1e-9, y - by_nu[1000.0]["mu"], np.nan)
        results[floor] = {"orders": {**res["orders"], "eb_t": (order, len(ids))}, "ids": ids}
        fits[str(floor)] = {
            "corridors": int(len(ids)), "best_nu": best, "tau_best": by_nu[best]["tau"], "mu_best": by_nu[best]["mu"],
            "loglik_gain_over_normal": float(gain),
            "lr_statistic_vs_normal": float(2 * gain),
            "median_retained_share_top_decile_t": float(np.nanmedian(shrink[top_decile])),
            "median_retained_share_top_decile_normal": float(np.nanmedian(normal_shrink[top_decile])),
            "loglik_by_nu": {str(k): v["loglik"] for k, v in by_nu.items()},
        }

    def mean_pairwise(ranking: str) -> float:
        return float(np.nanmean([
            eb_ranking.jaccard(eb_ranking.top_list(*results[a]["orders"][ranking]),
                               eb_ranking.top_list(*results[b]["orders"][ranking]))
            for a, b in itertools.combinations(sorted(results), 2)]))

    summary = {name: mean_pairwise(name) for name in ("raw_published", "raw_mean", "eb_prob", "eb_t")}
    raw_top = {f: set(eb_ranking.top_list(*results[f]["orders"]["raw_mean"])) for f in results}
    kept = {str(f): len(raw_top[f] & set(eb_ranking.top_list(*results[f]["orders"]["eb_t"]))) for f in results}
    margin = summary["eb_t"] - summary["raw_published"]
    report = {
        "generated_at": datetime.now(UTC).isoformat(), "decision": "D-102", "threshold_log": threshold,
        "grid_points": GRID_POINTS, "nus": list(NUS), "floors": fits,
        "mean_pairwise_top20_jaccard": summary, "t_minus_raw_published": margin,
        "raw_top20_kept_by_t_ranking": kept,
        "decision_rule": "t prior helps materially only if t_minus_raw_published > 0.10",
        "t_prior_helps_materially": bool(margin > 0.10),
    }
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    report = run()
    print(json.dumps({k: report[k] for k in ("mean_pairwise_top20_jaccard", "t_minus_raw_published", "t_prior_helps_materially")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
