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


# ── marking, in one place ────────────────────────────────────────────────────
# Marked here rather than with a decorator in each file so that adding a
# Spark-dependent test to an already-marked module does not silently land in the
# fast suite and time a pull request out waiting for a JVM that is not there.

SPARK_MODULES = {
    "test_features",
    "test_predict",
    "test_producer",
    "test_stream_job",
}


def pytest_collection_modifyitems(items):
    for item in items:
        if item.module.__name__.rsplit(".", 1)[-1] in SPARK_MODULES:
            item.add_marker(pytest.mark.spark)
