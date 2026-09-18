"""Drive the MCP tool server from a real MCP client over stdio (execution plan v3.1, G-06).

    python -m src.agents.mcp_stdio_client
    python -m src.agents.mcp_stdio_client --out benchmarks/raw/w7_mcp_stdio_transcript.json

Week 6 exposed twelve tools and called them as Python functions. That proves the tools
work; it does not prove the *server* does -- the JSON-RPC handshake, the tool schemas an
MCP client discovers, argument marshalling, and the result encoding are all untested
until something speaks the protocol to it. This does: it launches
`python -m src.agents.mcp_server` as a subprocess, talks to it only through stdin and
stdout exactly as MCP Inspector or a desktop client would, and records every exchange.

The transcript is evidence, not a log
-------------------------------------
Each call records the tool, the arguments sent, the wall-clock time, whether the server
flagged an error, and the result text as the client received it. Arguments are chosen
from the project's own data -- the audit's worst bottleneck, the most congested hub, a
corridor the stream actually alerted on -- so every call exercises a real code path
rather than an empty one. A call that returns an error is recorded, not retried: the
transcript's job is to say what the server did.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("agents.mcp_stdio_client")

OUT_JSON = config.BENCHMARKS_RAW_DIR / "w7_mcp_stdio_transcript.json"
MAX_RESULT_CHARS = 2000


def planned_calls() -> list[tuple[str, dict]]:
    """Tool calls whose arguments come from the project's own data."""
    raw = config.BENCHMARKS_RAW_DIR
    calls: list[tuple[str, dict]] = [("tms_health", {}), ("alert_summary", {})]

    top = raw / "w2_top20_bottlenecks.csv"
    if top.exists():
        corridor = pd.read_csv(top).iloc[0]["corridor_id"]
        calls.append(("corridor_stats", {"corridor_id": corridor}))
    calls.append(("corridor_stats", {"corridor_id": "INDZZZZZZAAA>INDZZZZZZAAB"}))  # the "not audited" path

    friction = raw / "w2_hub_friction_top20.csv"
    if friction.exists():
        calls.append(("hub_friction", {"centre_code": pd.read_csv(friction).iloc[0]["centre_code"]}))

    calls.append(("worst_corridors", {"limit": 3}))
    try:
        from src.dashboard.alerts import load_alerts

        feed = load_alerts()
        if not feed.empty:
            calls.append(("alerts_for_corridor", {"corridor_id": feed.alerts.iloc[0]["corridor_id"], "limit": 2}))
    except (ValueError, OSError):
        pass
    calls.append(("search_knowledge", {"query": "why was the delay threshold set to 2x", "k": 2, "kind": "doc"}))
    return calls


def _result_text(result) -> str:
    parts = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        parts.append(text if text is not None else str(block))
    return "".join(parts)


async def drive(out_path: Path = OUT_JSON) -> dict:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.agents.mcp_server"],
        cwd=str(config.REPO_ROOT),
    )
    transcript: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "transport": "stdio",
        "server_command": f"{Path(sys.executable).name} -m src.agents.mcp_server",
        "calls": [],
    }
    started = time.perf_counter()
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        transcript["handshake_ms"] = round((time.perf_counter() - started) * 1000, 1)
        transcript["protocol_version"] = str(getattr(init, "protocol_version", getattr(init, "protocolVersion", "")))
        server_info = getattr(init, "server_info", None) or getattr(init, "serverInfo", None)
        transcript["server_name"] = getattr(server_info, "name", None)

        listed = await session.list_tools()
        transcript["tools_discovered"] = [
            {"name": tool.name, "description": (tool.description or "").strip().splitlines()[0][:160],
             "input_schema_keys": sorted((getattr(tool, "input_schema", None)
                                          or getattr(tool, "inputSchema", None) or {}).get("properties", {}))}
            for tool in listed.tools
        ]
        log.info("handshake %.0f ms, %d tools discovered", transcript["handshake_ms"], len(listed.tools))

        for name, arguments in planned_calls():
            call_started = time.perf_counter()
            result = await session.call_tool(name, arguments)
            elapsed = round((time.perf_counter() - call_started) * 1000, 1)
            text = _result_text(result)
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            is_error = bool(getattr(result, "is_error", getattr(result, "isError", False)))
            transcript["calls"].append({
                "tool": name,
                "arguments": arguments,
                "duration_ms": elapsed,
                "is_error": is_error,
                "result_is_json": parsed is not None,
                "result": text[:MAX_RESULT_CHARS],
                "result_truncated": len(text) > MAX_RESULT_CHARS,
            })
            log.info("%-20s %6.0f ms  %s", name, elapsed, "ERROR" if is_error else "ok")

    calls = transcript["calls"]
    transcript["summary"] = {
        "tools_discovered": len(transcript["tools_discovered"]),
        "calls": len(calls),
        "errors": sum(1 for c in calls if c["is_error"]),
        "results_parseable_json": sum(1 for c in calls if c["result_is_json"]),
        "distinct_tools_called": len({c["tool"] for c in calls}),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
    log.info("transcript -> %s", out_path)
    return transcript


def main() -> int:
    parser = argparse.ArgumentParser(description="Drive the MCP server over stdio and record the transcript")
    parser.add_argument("--out", type=Path, default=OUT_JSON)
    args = parser.parse_args()
    transcript = asyncio.run(drive(args.out))
    print(json.dumps(transcript["summary"], indent=2))
    return 0 if transcript["summary"]["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
