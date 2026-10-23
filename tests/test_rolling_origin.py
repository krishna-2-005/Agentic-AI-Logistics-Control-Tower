"""Rolling-origin helpers (D-076) and the paper-number macros. No data files, no Spark.

    pytest tests/test_rolling_origin.py -q
"""

from __future__ import annotations

import pandas as pd
import pytest

pytest.importorskip("pyspark")

from src.ml import rolling_origin as ro  # noqa: E402
from src.report import paper_numbers as pn  # noqa: E402


def test_day_one_is_the_twelfth_of_september_in_india_time():
    # 2018-09-11 19:00 UTC is 00:30 IST on the 12th.
    created = pd.Series(pd.to_datetime(["2018-09-11 19:00", "2018-09-12 17:00", "2018-09-12 19:00"]))
    assert ro.day_numbers(created).tolist() == [1, 1, 2]


def test_folds_are_chronological_and_never_overlap_their_training_window():
    for train_end, first, last in ro.FOLDS:
        assert train_end < first <= last <= 22
    assert [f[1] for f in ro.FOLDS] == sorted(f[1] for f in ro.FOLDS)


def test_summary_counts_the_folds_a_model_beats_the_bar():
    table = pd.DataFrame({"mae_backoff": [10.0, 10.0, 10.0, 10.0], "delta_v2_vs_backoff": [-1.0, -2.0, 0.5, -0.5],
                          "delta_v3_vs_backoff": [-1.0, 1.0, 0.5, 0.5]})
    out = ro.summarise(table)
    assert out["v2_gbt_beats_backoff_in_folds"] == 3 and out["v3_gbt_beats_backoff_in_folds"] == 1
    assert out["delta_v2_vs_backoff"]["mean"] == pytest.approx(-0.75)


def test_macro_names_spell_out_digits_and_values_group_thousands():
    assert pn.macro_name("mae_v2") == "fzMaeVTwo"
    assert pn.tex_value(26369) == "26{,}369"
    assert pn.tex_value(0.5) == "0.5" and pn.tex_value(True) == "true"
    assert pn.tex_value("a_b%") == r"a\_b\%"
