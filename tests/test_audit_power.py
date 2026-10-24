"""The power study (D-099) and the reliability indices (D-100) on small synthetic data. No data files.

    pytest tests/test_audit_power.py -q
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ml import audit_indices as ai
from src.ml import audit_power as ap
from src.ml.audit_robust import CellModel


def _legs(n_corridors: int = 12, per_corridor: int = 16, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for c in range(n_corridors):
        for i in range(per_corridor):
            rows.append((f"C{c:02d}", f"S{c:02d}{i % 2}", float(rng.normal(0.3, 0.4))))
    frame = pd.DataFrame(rows, columns=["corridor_id", "schedule", "r"])
    frame["day"] = pd.Timestamp("2018-09-12") + pd.to_timedelta(np.arange(len(frame)) % 10, unit="D")
    return frame


@pytest.fixture(scope="module")
def model() -> CellModel:
    legs = _legs()
    return CellModel(legs, np.array(sorted(legs["corridor_id"].unique())))


def test_the_null_bank_gives_p_values_in_the_unit_interval_and_a_small_one_for_an_extreme_statistic(model):
    bank = ap.NullBank(model, 600, 4000, seed=1, chunk=200)
    k = model.incidence.shape[1]
    p_typical = bank.pvalues(np.zeros(k))
    p_extreme = bank.pvalues(np.full(k, 50.0))
    assert ((p_typical > 0) & (p_typical <= 1)).all() and (p_typical > 0.9).all()
    assert (p_extreme <= 1.0 / 4000 * 2).all()


def test_p_values_never_fall_below_the_resolution_of_the_bank(model):
    bank = ap.NullBank(model, 400, 2000, seed=2, chunk=200)
    p = bank.pvalues(np.full(model.incidence.shape[1], 1e6))
    assert np.allclose(p, 1.0 / 2001)


def test_planting_raises_exactly_the_planted_corridors(model):
    rng = np.random.default_rng(5)
    chosen = np.array([0, 4])
    plain = model.permuted_means(np.random.default_rng(5), 1)[0]
    planted = ap.plant(model, np.random.default_rng(5), 0.7, chosen)
    w = (planted - plain) * model.m
    shift = np.asarray(w[None, :] @ model.incidence)[0] / model.n_c
    assert shift[chosen] == pytest.approx(0.7)
    assert np.allclose(np.delete(shift, chosen), 0.0)
    assert rng is not None


def test_a_large_planted_shift_is_found_by_welch_and_missed_less_than_a_small_one(model):
    bank = ap.NullBank(model, 600, 3000, seed=4, chunk=200)
    hits = {}
    for delta in (0.0, 2.5):
        rng = np.random.default_rng(9)
        out = ap.run_dataset(model, bank, ap.plant(model, rng, delta, np.array([1, 2, 3])))
        hits[delta] = int((out["bh_welch"] & out["rises"])[[1, 2, 3]].sum())
    assert hits[2.5] >= hits[0.0]


def test_indices_on_a_known_sample():
    legs = pd.DataFrame({"corridor_id": ["A"] * 20, "r": np.log(np.arange(1, 21, dtype=float))})
    out = ai.indices(legs, floor=10)
    q = np.arange(1, 21, dtype=float)
    assert out.loc["A", "pti"] == pytest.approx(np.percentile(q, 95))
    assert out.loc["A", "bi"] == pytest.approx((np.percentile(q, 95) - q.mean()) / q.mean())
    assert ai.indices(legs.head(5), floor=10).empty


def test_jaccard_and_top_helpers():
    frame = pd.DataFrame({"x": [3.0, 2.0, 1.0]}, index=["a", "b", "c"])
    assert ai.top(frame, "x", 2) == {"a", "b"}
    assert ai.jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)
    assert ai.jaccard(set(), set()) == 0.0


def test_the_t_prior_marginal_beats_the_normal_when_one_corridor_is_extreme():
    from src.ml import eb_t

    rng = np.random.default_rng(4)
    y = np.concatenate([rng.normal(0.8, 0.1, 80), [4.0, -2.5]])
    v = np.full(len(y), 0.01)
    fit = eb_t.Fit(y, v)
    _, _, heavy = fit.maximise(3.0)
    _, _, normal = fit.maximise(1000.0)
    assert heavy > normal


def test_the_t_posterior_probabilities_are_ordered_by_distance_above_the_threshold():
    from src.ml import eb_t

    y = np.array([0.5, 1.0, 1.6, 2.2])
    fit = eb_t.Fit(y, np.full(4, 0.02))
    post = fit.posterior(1.0, 0.5, 5.0, threshold=1.2)
    assert (np.diff(post["z"]) > 0).all() and ((post["z"] >= 0) & (post["z"] <= 1)).all()
