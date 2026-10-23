"""Cell-permutation audit: size, power, correction ordering and the headline rule."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats
from statsmodels.stats.multitest import multipletests

pytest.importorskip("pyspark")  # the fast job runs without PySpark: skip, do not error

from src.ml import audit_robust as ar


def _clustered_legs(seed: int, corridors: int = 80, effect: dict | None = None) -> pd.DataFrame:
    """Legs whose log-ratio shares a cell (corridor x schedule) effect; no corridor effect."""
    rng = np.random.default_rng(seed)
    rows = []
    sched = 0
    for c in range(corridors):
        for _ in range(rng.integers(1, 3)):
            sched += 1
            m = int(rng.integers(6, 14))
            cell = rng.normal(0.0, 0.5)
            shift = (effect or {}).get(c, 0.0)
            for r in cell + shift + rng.normal(0.0, 0.2, m):
                rows.append((f"c{c}", f"s{sched}", r))
    legs = pd.DataFrame(rows, columns=["corridor_id", "schedule", "r"])
    legs["r"] += 0.8
    return legs


def _tested_ids(legs: pd.DataFrame) -> np.ndarray:
    n = legs.groupby("corridor_id").size()
    return np.sort(n[n >= 10].index.to_numpy())


def test_size_stratum_bins():
    m = np.array([1, 2, 8, 9, 11, 12, 15, 16, 22, 23, 80])
    assert ar.size_stratum(m).tolist() == [0, 1, 7, 8, 8, 9, 9, 10, 10, 11, 11]


def test_permutation_has_correct_size_under_cell_null_and_welch_does_not():
    ps_perm, ps_welch = [], []
    for seed in range(6):
        legs = _clustered_legs(seed)
        ids = _tested_ids(legs)
        model = ar.CellModel(legs, ids)
        _, p = ar.permutation_pvalues(model, 600, seed=seed, chunk=300)
        ps_perm.append(p)
        tot = legs["r"].to_numpy()
        for cid in ids:
            inside = legs.loc[legs["corridor_id"] == cid, "r"]
            rest = legs.loc[legs["corridor_id"] != cid, "r"]
            ps_welch.append(stats.ttest_ind(inside, rest, equal_var=False).pvalue)
        assert tot.size == model.n_legs
    rate_perm = float((np.concatenate(ps_perm) < 0.05).mean())
    rate_welch = float((np.array(ps_welch) < 0.05).mean())
    assert rate_perm < 0.10
    assert rate_welch > 0.25


def test_permutation_detects_a_large_shift():
    base = _clustered_legs(11)
    ids = _tested_ids(base)
    target = str(ids[3])
    legs = _clustered_legs(11, effect={int(target[1:]): 3.0})
    ids = _tested_ids(legs)
    model = ar.CellModel(legs, ids)
    d, p = ar.permutation_pvalues(model, 2000, seed=5)
    i = list(ids).index(target)
    assert d[i] > 1.0
    assert p[i] < 0.01


def test_difference_matches_direct_computation():
    legs = _clustered_legs(2)
    ids = _tested_ids(legs)
    model = ar.CellModel(legs, ids)
    s, tot = model.corridor_sums(model.ybar[None, :])
    d = model.difference(s, tot)[0]
    for j in (0, 5, 17):
        inside = legs.loc[legs["corridor_id"] == ids[j], "r"].mean()
        rest = legs.loc[legs["corridor_id"] != ids[j], "r"].mean()
        assert np.isclose(d[j], inside - rest)


def test_by_is_never_less_conservative_than_bh():
    rng = np.random.default_rng(0)
    for _ in range(20):
        p = np.concatenate([rng.uniform(0, 1e-3, 30), rng.uniform(0, 1, 300)])
        bh = multipletests(p, alpha=0.05, method="fdr_bh")[0]
        by = multipletests(p, alpha=0.05, method="fdr_by")[0]
        assert by.sum() <= bh.sum()
        assert not (by & ~bh).any()


def test_headline_rule_and_tie_break():
    slower = {"bh_welch": 273, "by_welch": 218, "bh_perm": 40, "by_perm": 12}
    faster = {"bh_welch": 512, "by_welch": 452, "bh_perm": 90, "by_perm": 30}
    assert ar.headline_variant(slower, faster) == "by_perm"
    slower["bh_perm"], faster["bh_perm"] = 12, 10
    assert ar.headline_variant(slower, faster) == "bh_perm"
    zero = dict.fromkeys(ar.VARIANTS, 0)
    assert ar.headline_variant(zero, zero) == "by_perm"


def test_classify_corridors_robust_vs_fragile():
    tab = pd.DataFrame(
        {
            "sig_bh_welch": [True, True, False, False],
            "sig_by_perm": [True, False, True, False],
        }
    )
    got = ar.classify_corridors(tab, "by_perm").tolist()
    assert got == ["robust", "fragile", "headline_only", "not_significant"]


def test_jaccard():
    assert ar.jaccard({1, 2}, {2, 3}) == 1 / 3
    assert np.isnan(ar.jaccard(set(), set()))
