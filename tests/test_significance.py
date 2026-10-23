"""The significance module (D-076) on simulated data where the right answer is known. No data files.

    pytest tests/test_significance.py -q
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ml import significance as sig


def test_days_roll_over_at_midnight_india_time_not_utc():
    times = pd.Series(pd.to_datetime(["2018-09-12 18:29:00", "2018-09-12 18:31:00", "2018-09-13 18:31:00"]))
    # 18:30 UTC is midnight IST: the first leg is still the 12th, the second is already the 13th.
    assert sig.day_blocks(times).tolist() == [0, 1, 2]


def test_six_hour_blocks_are_cut_on_india_time():
    # 00:00 and 00:20 UTC are 05:30 and 05:50 IST (block 0); 00:40 UTC is 06:10 IST (block 1); 06:45 UTC is 12:15 IST (block 2).
    times = pd.Series(pd.to_datetime(["2018-09-12 00:00", "2018-09-12 00:20", "2018-09-12 00:40", "2018-09-12 06:45"]))
    assert sig.hour_blocks(times, hours=6).tolist() == [0, 0, 1, 2]


def test_the_paired_bootstrap_is_centred_on_the_sample_mean():
    d = np.random.default_rng(1).normal(-2.0, 10.0, size=800)
    dist = sig.paired_bootstrap(d, n_boot=2000, seed=3)
    assert dist.mean() == pytest.approx(d.mean(), abs=0.1)
    lo, hi = sig.interval(dist)
    assert lo < d.mean() < hi


def test_a_block_bootstrap_is_wider_than_a_paired_one_when_blocks_differ():
    rng = np.random.default_rng(5)
    blocks = np.repeat(np.arange(6), 300)
    block_effect = rng.normal(0, 3.0, size=6)[blocks]  # whole days drift together
    d = block_effect + rng.normal(0, 5.0, size=len(blocks))
    paired = sig.interval(sig.paired_bootstrap(d, 3000, 1))
    blocky = sig.interval(sig.block_bootstrap(d, blocks, 3000, 1))
    assert (blocky[1] - blocky[0]) > 1.5 * (paired[1] - paired[0])


def test_the_paired_bootstrap_interval_covers_the_true_mean_about_95_percent_of_the_time():
    rng = np.random.default_rng(11)
    hits = 0
    runs = 150
    for i in range(runs):
        d = rng.normal(-1.0, 8.0, size=400)
        lo, hi = sig.interval(sig.paired_bootstrap(d, 400, i))
        hits += lo <= -1.0 <= hi
    assert 0.88 <= hits / runs <= 1.0


def test_block_bootstrap_ratio_handles_unequal_blocks_and_empty_ones():
    d = np.array([1.0, 1.0, 1.0, 9.0])
    blocks = np.array([0, 0, 0, 2])  # block 1 is empty in this slice
    dist = sig.block_bootstrap(d, blocks, 500, 2)
    assert np.isfinite(dist).all() and dist.min() >= 1.0 and dist.max() <= 9.0


def test_bootstrap_p_is_never_exactly_zero_and_is_two_sided():
    assert sig.bootstrap_p(np.full(1000, -1.0)) > 0.0
    assert sig.bootstrap_p(np.concatenate([np.full(500, -1.0), np.full(500, 1.0)])) == pytest.approx(1.0, abs=0.01)


def test_long_run_variance_of_noise_is_its_variance_and_of_ar1_is_larger():
    rng = np.random.default_rng(2)
    noise = rng.normal(0, 2.0, size=20000)
    assert sig.long_run_variance(noise, 20) == pytest.approx(4.0, rel=0.1)
    ar = np.zeros(20000)
    for t in range(1, len(ar)):
        ar[t] = 0.7 * ar[t - 1] + rng.normal()
    assert sig.long_run_variance(ar, 50) > 3.0 * float(ar.var())


def test_diebold_mariano_has_roughly_the_right_size_and_detects_a_real_difference():
    rng = np.random.default_rng(7)
    rejections = sum(sig.diebold_mariano(rng.normal(0, 1, 600), 8)[1] < 0.05 for _ in range(400))
    assert 0.02 <= rejections / 400 <= 0.09
    assert sig.diebold_mariano(rng.normal(-0.5, 1, 600), 8)[1] < 0.001


def test_holm_never_lowers_a_p_value_and_keeps_the_order():
    raw = [0.001, 0.02, 0.04, 0.3]
    adjusted = sig.holm(raw)
    assert all(a >= r for a, r in zip(adjusted, raw, strict=True))
    assert adjusted == sorted(adjusted)


def test_compare_finds_a_real_improvement_and_its_interval_excludes_zero():
    rng = np.random.default_rng(13)
    n = 3000
    days = np.repeat(np.arange(6), n // 6)
    y = rng.normal(0, 30, n)
    bar = y + rng.normal(0, 25, n)
    model = y + rng.normal(0, 15, n)  # clearly better
    result = sig.compare(y, model, bar, np.ones(n, dtype=bool), days, days, n // 6, seed=1, n_boot=1500)
    assert result["delta_mae"] < -3 and result["wins_block_day"] and result["ci_block_day"][1] < 0
    assert result["p_wilcoxon_optimistic"] < 1e-6 and result["dm_day_bandwidth"]["p"] < 0.01


def test_compare_does_not_find_a_difference_between_a_model_and_itself():
    rng = np.random.default_rng(17)
    y = rng.normal(0, 30, 1200)
    same = y + rng.normal(0, 20, 1200)
    days = np.repeat(np.arange(4), 300)
    result = sig.compare(y, same, same, np.ones(1200, dtype=bool), days, days, 300, seed=2, n_boot=500)
    assert result["delta_mae"] == 0.0 and not result["wins_block_day"] and result["ci_block_day"] == [0.0, 0.0]


def test_a_slice_with_too_few_legs_gets_no_wilcoxon_or_dm_rather_than_a_made_up_number():
    rng = np.random.default_rng(19)
    y = rng.normal(0, 10, 50)
    mask = np.zeros(50, dtype=bool)
    mask[:6] = True
    days = np.repeat(np.arange(5), 10)
    result = sig.compare(y, y + 1, y + 2, mask, days, days, 10, seed=3, n_boot=300)
    assert result["p_wilcoxon_optimistic"] is None and result["dm_day_bandwidth"]["p"] is None
