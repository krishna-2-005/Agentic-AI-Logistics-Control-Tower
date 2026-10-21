"""The Spark-free audit rebuild must reproduce the published corridor audit."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ml import audit_data

needs_data = pytest.mark.skipif(
    not (audit_data.LEGS_PATH.exists() and audit_data.PUBLISHED_AUDIT.exists()),
    reason="legs table or published audit not present",
)


def _toy_legs() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    n = 400
    return pd.DataFrame(
        {
            "leg_id": np.arange(n),
            "trip_uuid": [f"t{i // 2}" for i in range(n)],
            "schedule": [f"s{i % 9}" for i in range(n)],
            "corridor_id": [f"c{i % 8}" for i in range(n)],
            "r": rng.normal(0.8, 0.5, n),
            "day": pd.to_datetime("2018-09-12") + pd.to_timedelta(np.arange(n) % 5, unit="D"),
        }
    )


def test_corridor_table_applies_support_floor():
    legs = _toy_legs()
    tab = audit_data.corridor_table(legs, min_support=60)
    assert tab.empty
    tab = audit_data.corridor_table(legs, min_support=10)
    assert len(tab) == 8
    assert tab["n_legs"].sum() == 400
    assert np.isclose(tab["sum_log"].sum(), legs["r"].sum())


def test_welch_audit_matches_scipy_on_toy_data():
    from scipy import stats

    legs = _toy_legs()
    out = audit_data.welch_audit(legs, min_support=10).set_index("corridor_id")
    for cid, row in out.iterrows():
        inside = legs.loc[legs["corridor_id"] == cid, "r"]
        rest = legs.loc[legs["corridor_id"] != cid, "r"]
        ref = stats.ttest_ind(inside, rest, equal_var=False)
        assert np.isclose(row["t_stat"], ref.statistic, atol=1e-9)
        assert np.isclose(row["p_value"], ref.pvalue, atol=1e-9)


def test_anova_icc_detects_clusters():
    rng = np.random.default_rng(1)
    groups = np.repeat(np.arange(200), 10)
    clustered = rng.normal(0, 1, 200)[groups] + rng.normal(0, 1, groups.size)
    assert 0.4 < audit_data.anova_icc(clustered, groups)["rho"] < 0.6
    flat = rng.normal(0, 1, groups.size)
    assert abs(audit_data.anova_icc(flat, groups)["rho"]) < 0.05


@needs_data
def test_reproduces_published_audit_to_1e9():
    legs = audit_data.load_legs()
    out = audit_data.welch_audit(legs, min_support=10).set_index("corridor_id")
    pub = pd.read_csv(audit_data.PUBLISHED_AUDIT).set_index("corridor_id")
    assert len(out) == len(pub) == 1130
    out = out.loc[pub.index]
    for col in ["mean_log", "t_stat", "dof", "p_value", "q_value", "excess_ratio"]:
        assert np.abs(out[col] - pub[col]).max() < 1e-9, col
    slower, faster = audit_data.significant_sets(out.reset_index())
    assert (len(slower), len(faster)) == (273, 512)
