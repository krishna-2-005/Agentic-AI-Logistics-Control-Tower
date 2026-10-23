"""B8: the exception-precision statistics (D-085)."""

import math

import pytest

from src.ml import exception_stats as es


def test_cochran_armitage_matches_hand_computation():
    # x = [1, 2, 3], n = [10, 10, 10], scores 1..3: pbar = 0.2
    # T = 1*(1-2) + 2*(2-2) + 3*(3-2) = 2 ; sum n s^2 = 140 ; (sum n s)^2 / N = 3600/30 = 120
    # Var = 0.2*0.8*(140-120) = 3.2 ; z = 2 / sqrt(3.2)
    out = es.cochran_armitage([1, 2, 3], [10, 10, 10])
    assert out["z"] == pytest.approx(2 / math.sqrt(3.2), abs=1e-4)
    assert out["direction"] == "increasing"


def test_cochran_armitage_flat_and_decreasing():
    assert es.cochran_armitage([5, 5, 5], [10, 10, 10])["z"] == 0
    assert es.cochran_armitage([8, 5, 2], [10, 10, 10])["direction"] == "decreasing"
    with pytest.raises(ValueError):
        es.cochran_armitage([1], [2])


def test_two_prop_z_symmetry_and_null():
    assert es.two_prop_z(30, 100, 30, 100)["z"] == 0
    a = es.two_prop_z(60, 100, 40, 100)["z"]
    assert a == pytest.approx(-es.two_prop_z(40, 100, 60, 100)["z"])
    assert a > 0


def test_gain_identity_and_bootstrap_is_deterministic():
    tp, alerted, delayed, legs = 1007, 1720, 1082, 2000
    w = alerted / legs
    p_a, p_n = tp / alerted, (delayed - tp) / (legs - alerted)
    assert (1 - w) * (p_a - p_n) == pytest.approx(p_a - delayed / legs)
    assert es.bootstrap_gain(tp, alerted, delayed, legs, 500) == es.bootstrap_gain(tp, alerted, delayed, legs, 500)


def test_no_gain_is_not_significant():
    out = es.policy_vs_trivial("null", 50, 100, 100, 200)  # alerted 50% == base 50%
    assert not out["significant_at_5pct"]
    assert "not better" in out["write_up"]


def test_small_gain_gets_directional_wording():
    out = es.policy_vs_trivial("small", 11, 20, 19, 40)
    assert not out["significant_at_5pct"]
    assert out["write_up"].startswith("directionally better")


def test_inconsistent_counts_rejected():
    with pytest.raises(ValueError):
        es.bootstrap_gain(10, 5, 8, 20)
