"""Shared test fixtures.

Every agent writes a trace per call (`src.agents.tracing`). Tests exercise those agents,
so without this every test run would append fake calls to the real trace log the Agent
console reads.
"""

from __future__ import annotations

import pytest

from src.agents import tracing


@pytest.fixture(autouse=True)
def _isolated_trace_log(monkeypatch, tmp_path):
    monkeypatch.setattr(tracing, "TRACE_PATH", tmp_path / "agent_calls.jsonl")
