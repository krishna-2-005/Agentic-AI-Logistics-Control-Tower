"""Empirical-Bayes model: estimators, shrinkage, coverage and the stability helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.ml import eb_ranking as eb


def _simulate(seed: int, k: int = 400, mu: float = 0.8, tau: float = 0.4):
    rng = np.random.default_rng(seed)
    n = rng.integers(5, 60, k).astype(float)
    sigma2 = 0.09
    theta = rng.normal(mu, tau, k)
    v = np.full(k, sigma2) / n
    y = rng.normal(theta, np.sqrt(v))
    return theta, y, v, n


def test_estimators_recover_the_between_variance():
    ests = {"reml": [], "ml": [], "dl": []}
    for seed in range(15):
        _, y, v, _ = _simulate(seed)
        ests["reml"].append(eb.tau2_likelihood(y, v, True))
        ests["ml"].append(eb.tau2_likelihood(y, v, False))
        ests["dl"].append(eb.tau2_dl(y, v))
    for name, vals in ests.items():
        assert abs(np.mean(vals) - 0.16) < 0.03, name


def test_zero_between_variance_is_found():
    rng = np.random.default_rng(0)
    v = np.full(200, 0.01)
    y = rng.normal(1.0, 0.1, 200)
    assert eb.tau2_likelihood(y, v, True) < 0.003


def test_small_corridors_are_shrunk_more_than_large_ones():
    _, y, v, n = _simulate(3)
    tau2 = eb.tau2_likelihood(y, v, True)
    post = eb.posterior(y, v, tau2, threshold=1.0)
    small, large = n <= 10, n >= 50
    assert post["shrink"][small].mean() > 3 * post["shrink"][large].mean()
    # shrinkage moves a corridor toward mu, and never past it
    moved = np.abs(post["mean"] - post["mu"]) <= np.abs(y - post["mu"]) + 1e-12
    assert moved.all()


def test_ninety_percent_interval_covers_about_ninety_percent():
    covered, total = 0, 0
    for seed in range(10):
        theta, y, v, _ = _simulate(100 + seed)
        post = eb.posterior(y, v, eb.tau2_likelihood(y, v, True), threshold=1.0)
        covered += int(((theta >= post["lo90"]) & (theta <= post["hi90"])).sum())
        total += len(theta)
    assert 0.86 < covered / total < 0.94


def test_probability_ranking_prefers_precise_corridors_over_noisy_extremes():
    y = np.array([2.0, 1.6])
    v = np.array([1.0, 0.0004])
    post = eb.posterior(y, v, 0.04, threshold=1.2)
    assert post["p_exceed"][1] > post["p_exceed"][0]
    assert post["mean"][0] < y[0]  # the noisy extreme is pulled in


def test_design_effect_grows_with_cell_size():
    de = eb.design_effect(np.array([10.0, 40.0]), np.array([1.0, 2.0]), icc=0.1)
    assert de[0] == 1.9 and de[1] > de[0] - 1e-9
    assert eb.design_effect(np.array([5.0]), np.array([5.0]), 0.1)[0] == 1.0


def test_top_list_and_jaccard():
    order = np.array(["a", "b", "c", "d", "e"], dtype=object)
    assert eb.top_list(order, 5, k=2) == ["a", "b"]
    assert eb.top_list(order, 3, k=5) == ["a", "b", "c"]
    assert eb.top_list(order, 5, restrict={"b", "d", "e"}, k=2) == ["b", "d"]
    assert eb.jaccard(["a", "b"], ["b", "c"]) == 1 / 3


def test_floor_rankings_use_one_corridor_set_and_shrink_noisy_tops():
    rng = np.random.default_rng(4)
    rows = []
    for c in range(60):
        n = int(rng.integers(5, 40))
        rows.append(pd.DataFrame({"corridor_id": f"c{c}", "r": rng.normal(0.8 + 0.3 * (c % 5), 0.3, n)}))
    legs = pd.concat(rows, ignore_index=True)
    tab = eb.corridor_sums(legs)
    base = {"n": len(legs), "sum": legs["r"].sum(), "sumsq": (legs["r"] ** 2).sum()}
    res = eb.floor_rankings(tab, base, 10, threshold=1.2)
    ids = set(res["ids"])
    assert ids == set(tab.loc[tab["n_legs"] >= 10, "corridor_id"])
    for name in ("raw_mean", "eb_prob", "eb_postmean"):
        assert set(res["orders"][name][0]) == ids
