"""Tests for the Tracking & Exception Agent (execution plan W6 D1-D2).

    pytest tests/test_exception_agent.py -q

No LLM, no TMS, no Spark. The agent's decisions are deterministic by design (only the
customer-facing wording is generated), which is exactly what makes them testable -- so
this file pins the decisions, not the prose.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.agents import exception_agent as ea
from src.agents.tms_client import TMSError


def _investigation(**overrides) -> ea.Investigation:
    base = {
        "corridor_id": "INDA>INDB",
        "audit_n_legs": 40,
        "audit_excess_ratio": 1.4,
        "audit_is_significant": True,
        "audit_direction": "worse",
        "audit_bottleneck_rank": 12,
    }
    base.update(overrides)
    return ea.Investigation(**base)


def _alert(**overrides) -> pd.Series:
    base = {
        "alert_id": "query-trip-1|x|INDA>INDB",
        "leg_id": "trip-1|x|INDA>INDB",
        "corridor_id": "INDA>INDB",
        "source_center": "INDA",
        "destination_center": "INDB",
        "planned_min": 100.0,
        "predicted_gap_min": 250.0,
        "threshold_gap_min": 100.0,
        "predicted_total_min": 350.0,
        "alert_time": pd.Timestamp("2026-09-13T10:00:00+05:30"),
        "corr_is_cold": 0, "src_is_cold": 0, "dst_is_cold": 0,
    }
    base.update(overrides)
    return pd.Series(base)


# ── the audit's vocabulary, which this agent once guessed wrong (P-48) ───────
def test_a_corridor_is_only_confirmed_slow_when_significant_and_worse():
    assert _investigation().confirmed_slow
    assert not _investigation(audit_direction="better").confirmed_slow
    assert not _investigation(audit_is_significant=False).confirmed_slow
    assert not _investigation(audit_n_legs=None, audit_is_significant=False).confirmed_slow


def test_the_audit_vocabulary_is_the_one_audit_py_writes():
    # src/ml/audit.py: np.where(excess_ratio >= 1, "worse", "better")
    assert ea.SLOWER_THAN_NETWORK == "worse"
    assert ea.AUDIT_DIRECTIONS == {"worse", "better"}


def test_an_unknown_direction_value_fails_loudly(tmp_path):
    # A renamed value would otherwise disable the escalation silently, which is what
    # P-48 actually was.
    csv = tmp_path / "audit.csv"
    csv.write_text(
        "corridor_id,n_legs,excess_ratio,is_significant,direction,bottleneck_rank\n"
        "INDA>INDB,40,1.4,True,slower,12\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="direction values"):
        ea.load_audit(csv)


def test_a_missing_audit_file_is_survivable(tmp_path):
    assert ea.load_audit(tmp_path / "nope.csv").empty


# ── severity is arithmetic ──────────────────────────────────────────────────
@pytest.mark.parametrize(("ratio", "expected"), [
    (1.0, "low"), (1.29, "low"), (1.3, "medium"), (1.99, "medium"),
    (2.0, "high"), (2.99, "high"), (3.0, "critical"), (12.0, "critical"),
])
def test_severity_cut_points_on_an_ordinary_corridor(ratio, expected):
    ordinary = _investigation(audit_is_significant=False)
    assert ea.severity_for(ratio, ordinary) == expected


def test_a_confirmed_slow_corridor_escalates_one_step():
    assert ea.severity_for(2.1, _investigation()) == "critical"
    assert ea.severity_for(1.5, _investigation()) == "high"
    assert ea.severity_for(1.0, _investigation()) == "medium"


def test_a_confirmed_fast_corridor_does_not_escalate():
    # The bug: "significant" was read as "slow", so a corridor confirmed *faster* than
    # the network escalated the ticket and was described as a known slow route.
    faster = _investigation(audit_direction="better")
    assert ea.severity_for(2.1, faster) == "high"
    assert ea.severity_for(1.0, faster) == "low"


def test_escalation_cannot_exceed_critical():
    assert ea.severity_for(9.0, _investigation()) == "critical"


# ── evidence and wording ────────────────────────────────────────────────────
def test_evidence_names_the_direction_in_words():
    assert "SLOWER" in " ".join(_investigation().evidence_lines())
    assert "FASTER" in " ".join(_investigation(audit_direction="better").evidence_lines())


def test_evidence_says_when_the_corridor_was_never_audited():
    lines = " ".join(_investigation(audit_n_legs=None).evidence_lines())
    assert "not in the Week 2 audit" in lines


def test_evidence_says_when_there_is_no_shipment():
    assert "no shipment on this corridor" in " ".join(_investigation().evidence_lines())


def test_the_template_claims_a_slow_route_only_when_the_audit_confirms_one():
    slow = ea.template_notification(_alert(), _investigation(), "high")
    fast = ea.template_notification(_alert(), _investigation(audit_direction="better"), "high")
    assert "confirmed slow route" in slow
    assert "confirmed slow route" not in fast


def test_the_template_names_the_shipment_and_the_delay():
    text = ea.template_notification(_alert(), _investigation(shipment_ref="SHP-000002"), "high")
    assert "SHP-000002" in text and "INDA>INDB" in text


def test_a_failed_draft_falls_back_to_the_template(monkeypatch):
    class Boom:
        def invoke(self, _):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(ea, "get_llm", lambda: Boom())
    prompt = ea.load_prompt("exception_triage")
    text, source = ea.draft_notification(_alert(), _investigation(), "high", prompt)
    assert source == "template" and text


def test_no_prompt_means_no_call_at_all(monkeypatch):
    monkeypatch.setattr(ea, "get_llm", lambda: pytest.fail("--no-draft must not call the model"))
    _, source = ea.draft_notification(_alert(), _investigation(), "high", None)
    assert source == "template"


# ── processing one alert ────────────────────────────────────────────────────
def test_a_dry_run_files_nothing_and_posts_nothing():
    outcome = ea.process_alert(_alert(), pd.DataFrame(), {}, None, None, None, dry_run=True)
    assert outcome.skipped_reason == "dry run"
    assert not outcome.filed and not outcome.notified


def test_without_a_shipment_the_agent_says_so_rather_than_filing():
    outcome = ea.process_alert(_alert(), pd.DataFrame(), {}, None, None, None)
    assert outcome.skipped_reason == "no shipment on this corridor in the TMS"
    assert not outcome.filed


def test_the_excess_ratio_is_over_the_legs_own_threshold():
    outcome = ea.process_alert(_alert(), pd.DataFrame(), {}, None, None, None, dry_run=True)
    assert outcome.excess_ratio == pytest.approx(2.5)
    assert outcome.excess_min == pytest.approx(150.0)


def test_state_round_trips(tmp_path):
    path = tmp_path / "state.json"
    ea.save_state({"a1": "EXC-000001"}, path)
    assert ea.load_state(path) == {"a1": "EXC-000001"}
    assert not list(tmp_path.glob("*.tmp"))


def test_a_corrupt_state_file_does_not_stop_the_agent(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{broken", encoding="utf-8")
    assert ea.load_state(path) == {}


# ── the TMS client's errors ─────────────────────────────────────────────────
def test_a_tms_error_carries_the_servers_own_explanation():
    error = TMSError(409, "ORD-000001 already has shipment SHP-000001.", "/shipments")
    assert error.status_code == 409
    assert "already has shipment" in str(error) and "/shipments" in str(error)
