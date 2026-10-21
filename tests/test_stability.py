"""Split-by-date stability: part assignment, overlap statistics and a known-answer pair."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.ml import stability as st


def _legs(seed: int, stable: bool, corridors: int = 120, days: int = 20) -> pd.DataFrame:
    """Two periods of legs; corridor effects persist across periods only if `stable`."""
    rng = np.random.default_rng(seed)
    eff1 = rng.normal(0.8, 0.4, corridors)
    eff2 = eff1 if stable else rng.normal(0.8, 0.4, corridors)
    dates = pd.date_range("2018-09-12", periods=days, freq="D")
    rows = []
    for c in range(corridors):
        for d in range(days):
            eff = eff1[c] if d < days // 2 else eff2[c]
            for _ in range(int(rng.integers(0, 3))):
                rows.append((f"c{c}", dates[d],
                             rng.normal(eff, 0.25), f"s{c}"))
    return pd.DataFrame(rows, columns=["corridor_id", "day", "r", "schedule"])


def test_assign_parts_is_contiguous_and_covers_all_dates():
    legs = _legs(0, True)
    for k in (2, 3):
        part = st.assign_parts(legs, k)
        assert set(part) == set(range(k))
        firsts = legs.assign(p=part).groupby("p")["day"].agg(["min", "max"])
        assert (firsts["max"].shift(1).dropna() < firsts["min"].iloc[1:]).all()


def test_set_overlap_known_values_and_chance_reference():
    rng = np.random.default_rng(0)
    a = np.array([True] * 10 + [False] * 90)
    b = np.array([True] * 5 + [False] * 5 + [True] * 5 + [False] * 85)
    out = st.set_overlap(a, b, rng, boot=0)
    assert out["intersection"] == 5
    assert out["jaccard"] == 5 / 15
    assert abs(out["expected_intersection_by_chance"] - 1.0) < 1e-12
    assert out["above_chance"]
    same = st.set_overlap(a, a, rng, boot=0)
    assert same["jaccard"] == 1.0


def test_spearman_reading_labels():
    rng = np.random.default_rng(1)
    x = rng.normal(size=300)
    assert st.spearman(x, x + rng.normal(0, 0.1, 300), rng, 0)["reading"] == "substantial"
    assert st.spearman(x, rng.normal(size=300), rng, 0)["reading"] == "low"


def test_persistence_counts():
    flag = np.array([True, True, True, False])
    slower = np.array([True, True, False, True])
    sig = np.array([True, False, False, False])
    out = st.persistence(flag, slower, sig)
    assert out["flagged"] == 3
    assert out["still_slower"]["successes"] == 2
    assert out["still_significantly_slower"]["successes"] == 1


def test_stable_effects_correlate_and_unstable_effects_do_not():
    rng = np.random.default_rng(3)
    results = {}
    for stable in (True, False):
        legs = _legs(7, stable)
        part = st.assign_parts(legs, 2)
        early = st.audit_part(legs[part == 0], 5, 1.2, 0, 1)
        late = st.audit_part(legs[part == 1], 5, 1.2, 0, 2)
        results[stable] = st.compare_pair(early, late, rng, 0)
    assert results[True]["spearman_raw_mean"]["rho"] > 0.8
    assert abs(results[False]["spearman_raw_mean"]["rho"]) < 0.3
    assert results[True]["overlap"]["bh_welch"]["jaccard"] > results[False]["overlap"]["bh_welch"]["jaccard"]
    assert results[True]["universe"] > 50
