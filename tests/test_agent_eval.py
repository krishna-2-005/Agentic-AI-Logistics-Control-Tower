"""Tests for Lahari's Week 6 evaluations and the results freeze (W6 D1-D2, D3-D4, D5).

    pytest tests/test_agent_eval.py -q

Everything here is deterministic by construction: severity is arithmetic and invoice
verdicts are comparisons, which is exactly why they can be evaluated at all (D-041).
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.agents.invoice_auditor import (
    BAND_TOLERANCE,
    audit_invoice,
    freight_band,
    verdict_for,
)
from src.ml import exception_eval as ee
from src.ml import invoice_eval as ie
from src.ml import results_freeze as rf


# ── results freeze ──────────────────────────────────────────────────────────
def test_every_frozen_entry_names_a_source():
    assert rf.ENTRIES
    for entry_id, week, label, _unit, source, _extract in rf.ENTRIES:
        assert entry_id and label and source.endswith((".json", ".csv"))
        assert 1 <= week <= 8


def test_entry_ids_are_unique():
    ids = [entry[0] for entry in rf.ENTRIES]
    assert len(ids) == len(set(ids))


def test_collecting_reads_real_values():
    values, problems = rf.collect()
    assert values, "no Layer 1 values could be read"
    assert not problems, f"unreadable entries: {problems}"
    by_id = {v.id: v for v in values}
    # A couple of anchors that must not move without someone noticing.
    assert by_id["legs_total"].value == 26369
    assert by_id["bottlenecks"].value == 273


def test_a_missing_source_file_is_reported_not_skipped(monkeypatch):
    monkeypatch.setattr(rf, "ENTRIES", [("nope", 1, "Nothing", "", "does_not_exist.json", lambda: 1)])
    values, problems = rf.collect()
    assert values == [] and problems[0]["problem"] == "source missing"


def test_freeze_then_verify_is_clean(tmp_path):
    rf.freeze(tmp_path / "freeze.json")
    report = rf.verify(tmp_path / "freeze.json")
    assert report["clean"] and not report["changed"]


def test_verify_notices_a_value_that_moved(tmp_path):
    path = tmp_path / "freeze.json"
    snapshot = rf.freeze(path)
    snapshot["values"][0]["value"] = "something else entirely"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    report = rf.verify(path)
    assert not report["clean"]
    assert report["changed"][0]["now"] != report["changed"][0]["was"]


def test_verify_notices_a_value_that_vanished(tmp_path):
    path = tmp_path / "freeze.json"
    snapshot = rf.freeze(path)
    snapshot["values"].append({"id": "ghost", "week": 1, "label": "x", "value": 1,
                               "unit": "", "source": "w2_audit_report.json"})
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    assert "ghost" in rf.verify(path)["missing"]


def test_verify_needs_a_freeze_first(tmp_path):
    with pytest.raises(FileNotFoundError):
        rf.verify(tmp_path / "absent.json")


def test_the_summary_groups_by_week_and_links_its_sources(tmp_path):
    text = rf.render_summary(rf.freeze(tmp_path / "freeze.json"))
    assert "# Layer 1 results summary" in text
    assert "## Week 2 — corridor audit" in text
    assert "../benchmarks/raw/w2_audit_report.json" in text
    assert "does not make anything immutable" in text


# ── exception agent evaluation ──────────────────────────────────────────────
def _graded(rows: list[tuple[str, str, int]]) -> pd.DataFrame:
    return pd.DataFrame([
        {"alert_id": f"a{i}", "leg_id": leg, "corridor_id": "INDA>INDB", "severity": severity,
         "excess_ratio": 2.0, "predicted_gap_min": 100.0, "confirmed_slow": False,
         "cold_history": False, "stream_latency_ms": 1500.0, "decide_ms": 0.05}
        for i, (leg, severity, _truth) in enumerate(rows)
    ])


def test_precision_is_over_the_alerts_that_have_truth():
    rows = [("l1", "high", 1), ("l2", "high", 0), ("l3", "low", 1), ("l4", "low", 0)]
    facts = {leg: truth for leg, _s, truth in rows}
    summary = ee.score(_graded(rows), facts)
    assert summary["alerts_scored"] == 4
    assert summary["notification_precision"] == pytest.approx(0.5)


def test_an_alert_with_no_matching_fact_is_counted_separately():
    rows = [("l1", "high", 1), ("missing", "high", 0)]
    summary = ee.score(_graded(rows), {"l1": 1})
    assert summary["alerts_scored"] == 1 and summary["alerts_without_truth"] == 1


def test_precision_is_reported_per_severity():
    rows = [("l1", "critical", 1), ("l2", "critical", 1), ("l3", "low", 0), ("l4", "low", 1)]
    facts = {leg: truth for leg, _s, truth in rows}
    bands = {b["severity"]: b for b in ee.score(_graded(rows), facts)["by_severity"]}
    assert bands["critical"]["precision"] == 1.0
    assert bands["low"]["precision"] == pytest.approx(0.5)


def test_the_policy_table_narrows_as_the_grade_rises():
    rows = [("l1", "critical", 1), ("l2", "high", 1), ("l3", "medium", 0), ("l4", "low", 0)]
    facts = {leg: truth for leg, _s, truth in rows}
    policies = ee.score(_graded(rows), facts)["policies"]
    counts = [p["notified"] for p in policies]
    assert counts == sorted(counts, reverse=True)
    assert policies[0]["notify_at_or_above"] == "low"


def test_recall_is_against_every_delayed_leg_not_just_alerted_ones():
    # The agent only sees what the stream flagged; recall has to say so.
    rows = [("l1", "high", 1)]
    facts = {"l1": 1, "l2": 1, "l3": 1}  # two delayed legs were never alerted
    # score() rounds to four places on the way out; compare at that resolution.
    assert ee.score(_graded(rows), facts)["recall_of_all_delayed"] == pytest.approx(1 / 3, abs=5e-5)


def test_facts_are_read_from_the_replays_own_events(tmp_path):
    (tmp_path / "tick_000000.jsonl").write_text(
        json.dumps({"kind": "query", "leg_id": "l1"}) + "\n"
        + json.dumps({"kind": "fact", "leg_id": "l1", "is_delayed": 1}) + "\n"
        + json.dumps({"kind": "fact", "leg_id": "l2", "is_delayed": 0}) + "\n",
        encoding="utf-8",
    )
    assert ee.load_facts(tmp_path) == {"l1": 1, "l2": 0}


# ── invoice auditor evaluation ──────────────────────────────────────────────
def test_the_authored_set_covers_every_kind():
    cases = ie.build_eval_set(count=len(ie.EXPECTED), seed=ie.EVAL_SEED)
    assert {c.kind for c in cases} == set(ie.EXPECTED)


def test_the_set_is_deterministic():
    a = ie.build_eval_set(20, seed=5)
    b = ie.build_eval_set(20, seed=5)
    assert [(c.case.seq, c.kind, c.case.total_amount) for c in a] == \
           [(c.case.seq, c.kind, c.case.total_amount) for c in b]


def test_it_uses_a_different_seed_from_the_auditors_own_corpus():
    from src.agents import invoice_auditor as ia

    assert ie.EVAL_SEED != 7, "the judge must not reuse the builder's seed (D-028)"
    assert set(ie.EXPECTED) - set(ia.CASE_WEIGHTS), "the judge's kinds must go beyond the builder's"


def test_the_boundary_cases_are_approved():
    # An audit desk that disputes a rounding error, or a charge exactly at the billed
    # ceiling, loses its credibility faster than it saves money.
    for kind in ("rounding_total", "other_at_edge", "clean"):
        assert ie.EXPECTED[kind][0] == "approve"


def test_the_hidden_overcharge_expects_a_dispute():
    # It exists to be missed: the truth says dispute, and the miss is the measurement.
    case = next(c for c in ie.build_eval_set(40, seed=ie.EVAL_SEED) if c.kind == "overcharge_hidden")
    assert case.expected_verdict == "dispute"
    assert case.expected_finding == "rate_above_band"


def test_a_hidden_overcharge_really_does_slip_past_the_auditor():
    from src.agents.invoice_auditor import InvoiceCase

    corridor_km = 100.0
    _low, high = freight_band("FTL", 4000.0, corridor_km)
    hidden = round((high / (1 + BAND_TOLERANCE)) * 1.10, 2)
    case = InvoiceCase(
        seq=1, kind="overcharge_hidden", corridor_id="INDA>INDB", route_type="FTL",
        weight_kg=4000.0, pieces=3, external_invoice_number="LEV-1",
        freight_charge=hidden, other_charges=round(hidden * 0.12, 2),
        total_amount=round(hidden * 1.12, 2),
    )
    assert verdict_for(audit_invoice(case, corridor_km, set())) == "approve"


def test_scoring_reports_false_disputes_separately_from_misses():
    frame, summary = ie.score(ie.build_eval_set(30, seed=ie.EVAL_SEED))
    assert set(frame.columns) >= {"kind", "verdict", "expected_verdict", "verdict_correct"}
    assert summary["false_disputes"] + summary["missed_problems"] == int((~frame["verdict_correct"]).sum())
