"""Tests for the MCP stdio client and the transport-error fix it forced (v3.1 G-06, P-54).

    pytest tests/test_mcp_stdio.py -q

One test spawns the real server as a subprocess and speaks MCP to it over stdio -- the
only way to test the handshake, tool discovery and result encoding rather than the
Python functions behind them. It takes a few seconds and is worth them.
"""

from __future__ import annotations

import asyncio
import json

from src.agents import mcp_server
from src.agents import mcp_stdio_client as client
from src.agents.tms_client import TMSClient, TMSError

DEAD_PORT = "http://127.0.0.1:8999"


# ── P-54: a TMS that is down must be handled, not crash the caller ──────────
def test_a_refused_connection_becomes_a_tms_error():
    try:
        TMSClient(base_url=DEAD_PORT, timeout=2.0).health()
    except TMSError as exc:
        assert exc.status_code == 0 and "transport failure" in str(exc)
    else:
        raise AssertionError("a dead port must raise TMSError")


def test_is_up_is_false_rather_than_raising_on_a_dead_port():
    assert TMSClient(base_url=DEAD_PORT, timeout=2.0).is_up() is False


def test_tms_health_tool_reports_down_instead_of_crashing(monkeypatch):
    # The bug: the tool whose whole purpose is reporting a down TMS crashed when it was.
    monkeypatch.setattr(mcp_server, "_tms", lambda: TMSClient(base_url=DEAD_PORT, timeout=2.0))
    assert json.loads(mcp_server.tms_health())["status"] == "down"


# ── the client's planned calls ──────────────────────────────────────────────
def test_planned_calls_exercise_real_paths():
    calls = client.planned_calls()
    names = [name for name, _ in calls]
    assert "tms_health" in names and "search_knowledge" in names
    # Both the audited and the "not audited" branch of corridor_stats are driven.
    corridor_args = [args["corridor_id"] for name, args in calls if name == "corridor_stats"]
    assert "INDZZZZZZAAA>INDZZZZZZAAB" in corridor_args


def test_every_planned_tool_is_one_the_server_advertises():
    for name, _ in client.planned_calls():
        assert name in mcp_server.TOOL_NAMES


# ── the real protocol, over stdio ───────────────────────────────────────────
def test_the_server_answers_a_real_mcp_client_over_stdio(tmp_path, monkeypatch):
    # Keep the TMS-dependent call out: this test must not need a running TMS, and the
    # down path is pinned above. What is under test is the protocol itself.
    monkeypatch.setattr(client, "planned_calls", lambda: [("hub_friction", {"centre_code": "INDZZZZZZAAA"}),
                                                          ("corridor_stats", {"corridor_id": "X>Y"})])
    transcript = asyncio.run(client.drive(tmp_path / "t.json"))
    assert transcript["summary"]["tools_discovered"] == len(mcp_server.TOOL_NAMES)
    assert transcript["summary"]["errors"] == 0
    assert transcript["summary"]["results_parseable_json"] == 2
    assert json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))["transport"] == "stdio"
