"""
Unit tests for the exporter's logic, run on fixtures rather than on the committed JSON.

These cover the behaviour that depends on files which may or may not exist yet
(the B3/B4 corridor columns, the B7 ablation, a newer freeze, the hierarchical
back-off bar), plus the rule that a missing number raises instead of falling back.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.report import export_web as ew


def _freeze_doc() -> dict:
    return {"frozen_at": "2026-01-01T00:00:00+00:00", "values": []}


def test_latest_freeze_is_picked_numerically(tmp_path: Path) -> None:
    for n in (3, 4, 10, 9):
        (tmp_path / f"results_freeze_v{n}.json").write_text(json.dumps(_freeze_doc()))
    (tmp_path / "results_freeze_v11.json.bak").write_text("{}")
    assert ew.latest_freeze_path(tmp_path).name == "results_freeze_v10.json"


def test_latest_freeze_raises_when_none_exist(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ew.latest_freeze_path(tmp_path)


def test_export_follows_the_newest_freeze_in_the_repo() -> None:
    assert ew.latest_freeze_path() == ew.FREEZE_PATH
    assert "v" + ew.FREEZE_PATH.stem.rsplit("_v", 1)[1] == ew.FREEZE_VERSION


def test_missing_freeze_key_raises_instead_of_falling_back() -> None:
    freeze = {"legs_total": {"id": "legs_total", "value": 5}}
    assert ew._need(freeze, "legs_total") == 5
    with pytest.raises(KeyError, match="assistant_route_accuracy"):
        ew._need(freeze, "assistant_route_accuracy")


def test_strict_nested_lookup_names_the_missing_path() -> None:
    with pytest.raises(KeyError, match="a.b.c"):
        ew._req({"a": {"b": {}}}, "a", "b", "c")


def test_no_silent_numeric_default_remains_in_the_exporter() -> None:
    source = Path(ew.__file__).read_text(encoding="utf-8")
    assert "def g(" not in source
    assert '.get("value", ' not in source
    assert "freeze.get(" not in source


def test_agent_card_rejects_counts_that_disagree_with_the_freeze() -> None:
    with pytest.raises(ValueError, match="freeze holds"):
        ew._agree(0.90, 0.85, "x")
    ew._agree(0.8999, 0.9, "x")


def test_wilson_interval_is_computed_from_counts() -> None:
    p = ew._prop(180, 200)
    assert (p["ci_low"], p["ci_high"]) == (0.8506, 0.9343)
    assert ew._prop(20, 20)["ci_low"] < 0.9


# ── optional B3 / B4 columns ─────────────────────────────────────────────────

def test_corridor_extras_absent_files_add_nothing(tmp_path: Path) -> None:
    assert ew.load_corridor_extras(tmp_path) == {}


def test_corridor_extras_read_robust_and_eb_rank(tmp_path: Path) -> None:
    pd.DataFrame({"corridor_id": ["A>B", "C>D"], "robust": [True, False]}).to_csv(
        tmp_path / ew.ROBUST_CSV, index=False)
    pd.DataFrame({"corridor_id": ["A>B", "C>D"], "eb_rank": [3, 7]}).to_csv(
        tmp_path / ew.EB_CSV, index=False)
    extras = ew.load_corridor_extras(tmp_path)
    assert extras["A>B"] == {"robust": True, "eb_rank": 3}
    assert extras["C>D"] == {"robust": False, "eb_rank": 7}


def test_corridor_extras_ignore_a_file_with_unknown_columns(tmp_path: Path) -> None:
    pd.DataFrame({"corridor_id": ["A>B"], "something_else": [1]}).to_csv(
        tmp_path / ew.EB_CSV, index=False)
    assert ew.load_corridor_extras(tmp_path) == {}


# ── optional B7 ablation ─────────────────────────────────────────────────────

def test_ablation_absent_returns_none(tmp_path: Path) -> None:
    assert ew.ablation_panel(tmp_path) is None


def test_ablation_reads_list_of_arms(tmp_path: Path) -> None:
    doc = {"arms": [
        {"name": "code decides",
         "accuracy": {"rate": 0.96, "ci_low": 0.9, "ci_high": 0.99, "total": 100},
         "unanimity": 1.0, "cost_usd": 0.0},
        {"name": "LLM decides", "successes": 80, "total": 100,
         "unanimity": 0.7, "cost_usd": 1.5},
    ]}
    (tmp_path / "b7_agent_ablation.json").write_text(json.dumps(doc))
    panel = ew.ablation_panel(tmp_path)
    assert panel is not None
    a, b = panel["arms"]
    assert a["accuracy"] == 0.96 and a["n"] == 100 and a["unanimity"] == 1.0
    assert b["accuracy"] == 0.8 and b["ci_low"] is not None and b["cost"] == 1.5


def test_ablation_reads_mapping_of_arms_and_leaves_missing_keys_out(tmp_path: Path) -> None:
    doc = {"arms": {"rules": {"accuracy": 0.9, "n": 50}, "llm": {"accuracy": 0.8, "n": 50}}}
    (tmp_path / "b7_agent_ablation.json").write_text(json.dumps(doc))
    panel = ew.ablation_panel(tmp_path)
    assert panel is not None
    assert [a["name"] for a in panel["arms"]] == ["rules", "llm"]
    assert panel["arms"][0]["unanimity"] is None and panel["arms"][0]["cost"] is None


def test_ablation_with_an_unrecognised_layout_is_omitted(tmp_path: Path) -> None:
    (tmp_path / "b7_agent_ablation.json").write_text(json.dumps({"something": 1}))
    assert ew.ablation_panel(tmp_path) is None


# ── paper page data ──────────────────────────────────────────────────────────

CFF = """cff-version: 1.2.0
title: >-
  A Title
  Over Two Lines
authors:
  - family-names: Doe
    given-names: Jane
  - family-names: Roe
    given-names: Richard
repository-code: https://example.org/repo
date-released: '2026-09-19'
version: 1.0.0
"""


def test_bibtex_is_built_from_citation_cff() -> None:
    bib = ew.bibtex_from_citation(ew.parse_citation(CFF))
    assert "title   = {A Title Over Two Lines}" in bib
    assert "Doe, Jane and Roe, Richard" in bib
    assert "year    = {2026}" in bib and "https://example.org/repo" in bib


def test_figure_captions_parse_from_the_readme_table() -> None:
    text = "| [`fig1_x`](fig1_x.png) | A caption. Source: a.csv |\n| header | x |\n"
    assert ew.figure_captions(text) == {"fig1_x": "A caption. Source: a.csv"}


# ── hierarchical back-off hook ───────────────────────────────────────────────

def _headline(out: Path) -> dict:
    return json.loads((out / "model.json").read_text(encoding="utf-8"))["data"]["headline"]


def test_the_backoff_bar_and_the_reported_model_come_from_the_freeze(tmp_path: Path) -> None:
    freeze = ew._load_freeze()
    ew.export_model(tmp_path / "a", freeze)
    head = _headline(tmp_path / "a")
    assert head["backoff_mae_min"] == round(freeze["bar_backoff_mae"]["value"], 2)
    assert head["reported_mae_min"] == round(freeze["reported_mae"]["value"], 2)
    assert head["rolling_folds_reported"] == freeze["ro_zoo_beats_bar_folds"]["value"]

    moved = dict(freeze, bar_backoff_mae=dict(freeze["bar_backoff_mae"], value=31.5))
    ew.export_model(tmp_path / "b", moved)
    assert _headline(tmp_path / "b")["backoff_mae_min"] == 31.5


def test_the_export_refuses_a_freeze_without_the_bar(tmp_path: Path) -> None:
    freeze = {k: v for k, v in ew._load_freeze().items() if k != "bar_backoff_mae"}
    with pytest.raises(KeyError, match="bar_backoff_mae"):
        ew.export_model(tmp_path / "c", freeze)


def test_q_values_keep_significant_figures() -> None:
    assert ew._sig(1.234e-12) == 1.23e-12
    assert ew._sig(float("nan")) is None


def test_route_label_never_prints_nan() -> None:
    src = {"city": None, "facility": None, "code": "IND1"}
    dst = {"city": "Pune", "facility": "X", "code": "IND2"}
    assert ew._route_label(src, dst) == "IND1 → Pune"
