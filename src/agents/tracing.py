"""Agent call tracing (execution plan v3.1 W7 D3-D4) -- every agent call, inputs and outputs.

    from src.agents.tracing import traced

    with traced("analytics_assistant", inputs={"question": q}) as span:
        ...
        span.outputs = {"answer": text, "route": route}

One JSON line per call in `data/traces/agent_calls.jsonl`: agent, start time, duration,
inputs, outputs, and the error if it raised. The dashboard's Agent console reads the same
file. A trace is written even when the call fails -- a log that only records successes
cannot answer the question a trace exists for, which is "what happened to that request".

Inputs and outputs are truncated to a fixed size per field, not dropped: a trace too big
to open is as useless as no trace, and a trace that silently omits the argument that
caused the failure is worse.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.common import config

TRACE_PATH = config.DATA_DIR / "traces" / "agent_calls.jsonl"
MAX_FIELD_CHARS = 2000


@dataclass
class Span:
    agent: str
    inputs: dict[str, Any]
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    outputs: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat(timespec="milliseconds"))


def _clip(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= MAX_FIELD_CHARS else value[:MAX_FIELD_CHARS] + f"... [+{len(value) - MAX_FIELD_CHARS} chars]"
    if isinstance(value, dict):
        return {k: _clip(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clip(v) for v in value[:50]]
    return value


@contextmanager
def traced(agent: str, inputs: dict[str, Any], path: Path | None = None) -> Iterator[Span]:
    path = path or TRACE_PATH
    span = Span(agent=agent, inputs=inputs)
    started = time.perf_counter()
    error = None
    try:
        yield span
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        record = {
            "trace_id": span.trace_id,
            "agent": span.agent,
            "started_at": span.started_at,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "inputs": _clip(span.inputs),
            "outputs": _clip(span.outputs),
            "error": error,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")


def read_traces(path: Path | None = None, agent: str | None = None, limit: int = 200) -> list[dict]:
    """Newest first. Unreadable lines are skipped -- one bad line must not cost the console."""
    path = path or TRACE_PATH
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if agent is None or record.get("agent") == agent:
            rows.append(record)
    return list(reversed(rows))[:limit]
