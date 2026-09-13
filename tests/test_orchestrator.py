"""Tests for the lifecycle orchestrator and the MCP tool server (W6 D3-D4).

    pytest tests/test_orchestrator.py -q

No LLM, no TMS, no Spark. The graph's value is that the *route* changes with what the
agents decide, so the routing functions are what this file pins hardest: an ambiguous
email must never reach the TMS, and a shipment nobody flagged must never become an
exception.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.agents import mcp_server as mcp
from src.agents import orchestrator as orch
from src.agents.order_corpus import OrderEmail


def _case(**overrides) -> OrderEmail:
    base = {
        "seq": 9001, "variant": "test", "subject": "Booking", "body": "...",
        "expected_action": "file", "expected_missing": None,
        "expected_fields": {
            "customer_name": "Test Exports", "origin_centre": "IND306401AAB",
            "dest_centre": "IND302014AAA", "route_type": "FTL",
            "pieces": 4, "weight_kg": 1200.0,
        },
    }
    base.update(overrides)
    return OrderEmail(**base)


# ── routing: the reason this is a graph ─────────────────────────────────────
def test_a_filed_order_routes_to_booking():
    assert orch.route_after_intake({"action": "file", "order": {"a": 1}}) == "book"


def test_an_ambiguous_email_never_reaches_the_tms():
    assert orch.route_after_intake({"action": "clarify", "order": None}) == "clarify"
    assert orch.route_after_intake({"action": "clarify", "order": {"a": 1}}) == "clarify"


def test_a_file_decision_with_no_order_still_stops():
    # "file" with nothing extracted is a contradiction; booking it would post an empty
    # order rather than ask the question the contradiction implies.
    assert orch.route_after_intake({"action": "file", "order": None}) == "clarify"
    assert orch.route_after_intake({}) == "clarify"


def test_an_unflagged_shipment_never_becomes_an_exception():
    assert orch.route_after_monitor({"alert": None}) == "done"
    assert orch.route_after_monitor({}) == "done"


def test_a_flagged_shipment_is_triaged():
    assert orch.route_after_monitor({"alert": {"alert_id": "a1"}}) == "triage"


# ── intake in demonstration mode ────────────────────────────────────────────
def test_complete_ground_truth_files():
    state = orch.intake({"case_seq": 1, "expected_fields": _case().expected_fields, "use_llm": False, "steps": []})
    assert state["action"] == "file"
    assert state["steps"] == ["intake"]


def test_missing_ground_truth_clarifies_and_names_the_field():
    fields = dict(_case().expected_fields)
    del fields["weight_kg"]
    state = orch.intake({"case_seq": 1, "expected_fields": fields, "use_llm": False, "steps": []})
    assert state["action"] == "clarify"
    assert state["missing_field"] == "weight_kg"


def test_demonstration_mode_calls_no_model(monkeypatch):
    monkeypatch.setattr(orch, "process_email", lambda *a, **k: pytest.fail("--no-llm must not call the model"))
    orch.intake({"case_seq": 1, "expected_fields": _case().expected_fields, "use_llm": False, "steps": []})


# ── the graph, and a dry run through it ─────────────────────────────────────
def test_the_graph_compiles_with_every_node():
    graph = orch.build_graph()
    assert {"intake", "clarify", "book", "monitor", "triage", "done"} <= set(graph.get_graph().nodes)


def test_a_dry_run_books_nothing(monkeypatch):
    monkeypatch.setattr(orch, "_client", lambda: pytest.fail("a dry run must not touch the TMS"))
    state = orch.book({"case_seq": 1, "order": _case().expected_fields, "dry_run": True, "steps": []})
    assert state["corridor_id"] == "IND306401AAB>IND302014AAA"
    assert state.get("order_ref") is None


def test_an_ambiguous_case_stops_before_booking(monkeypatch):
    monkeypatch.setattr(orch, "_client", lambda: pytest.fail("clarify must not touch the TMS"))
    fields = dict(_case().expected_fields)
    del fields["pieces"]
    result = orch.run_case(_case(seq=9002, expected_fields=fields), use_llm=False, dry_run=True)
    assert result["steps"] == ["intake", "clarify"]
    assert result.get("shipment_ref") is None


def test_the_external_ref_is_deterministic_in_the_case(monkeypatch):
    captured = {}

    class FakeClient:
        def create_order(self, payload):
            captured.update(payload)
            return {"order_ref": "ORD-000099", "corridor_id": "INDA>INDB"}

        def create_shipment(self, order_ref):
            return {"shipment_ref": "SHP-000099"}

    monkeypatch.setattr(orch, "_client", lambda: FakeClient())
    state = orch.book({"case_seq": 42, "order": _case().expected_fields, "dry_run": False, "steps": []})
    assert captured["external_ref"] == "W6-ORCH-0042"
    assert captured["source"] == "agent"
    assert state["shipment_ref"] == "SHP-000099"


def test_a_replayed_order_reuses_its_existing_shipment():
    from src.agents.tms_client import TMSError

    class Conflicting:
        def create_shipment(self, order_ref):
            raise TMSError(409, "already has shipment SHP-000007.", "/shipments")

        def list_shipments(self, limit=200):
            return [{"order_ref": "ORD-000007", "shipment_ref": "SHP-000007"}]

    assert orch._book_shipment(Conflicting(), "ORD-000007") == "SHP-000007"


def test_monitor_finds_no_alert_when_the_corridor_is_quiet(monkeypatch):
    from src.dashboard.alerts import AlertFeed

    monkeypatch.setattr(orch, "load_alerts", lambda: AlertFeed(pd.DataFrame(), 0, pd.Timestamp.now()))
    state = orch.monitor({"corridor_id": "INDA>INDB", "steps": []})
    assert state["alert"] is None
    assert orch.route_after_monitor(state) == "done"


# ── the MCP tool server ─────────────────────────────────────────────────────
def test_every_advertised_tool_exists_and_is_callable():
    for name in mcp.TOOL_NAMES:
        assert callable(getattr(mcp, name)), name


def test_tools_return_parseable_json():
    # A dict rendered with str() is not JSON, and the failure lands at the client.
    assert json.loads(mcp._ok({"a": 1, "when": pd.Timestamp("2026-09-13")}))["a"] == 1


def test_an_unaudited_corridor_says_so_rather_than_inventing_a_verdict():
    result = json.loads(mcp.corridor_stats("INDZZZZZZAAA>INDZZZZZZAAB"))
    assert result["found"] is False and "D-018" in result["reason"]


def test_a_centre_outside_the_top_20_reports_no_rank():
    result = json.loads(mcp.hub_friction("INDZZZZZZAAA"))
    assert result["friction_rank"] is None and result["in_top_20"] is False


def test_the_server_advertises_the_documented_tools():
    assert mcp.server.name == "control-tower"
    assert len(mcp.TOOL_NAMES) == len(set(mcp.TOOL_NAMES))
