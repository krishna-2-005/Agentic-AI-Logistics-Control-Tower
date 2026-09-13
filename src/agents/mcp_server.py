"""MCP tool server (execution plan W6 D3-D4) -- the project's data as callable tools.

    python -m src.agents.mcp_server                 # stdio, for an MCP client
    python -m src.agents.mcp_server --list          # what it exposes, no server

Exposes three families of tool over the Model Context Protocol:

* **corridor stats** -- the Week 2 audit and the hub-friction table, per corridor and
  per centre;
* **predictions** -- what the streaming job has already flagged, and (on demand) a
  fresh what-if score from the champion model;
* **TMS operations** -- orders, shipments, exception tickets and invoices, through the
  one client `src.agents.tms_client` already owns.

Nothing here computes anything new. Every tool is a thin wrapper over a module that
already exists and is already tested, which is the point: an MCP tool is an *interface*
to a capability, and a tool that quietly reimplements the capability behind it is two
implementations of one thing waiting to disagree (the trap P-23, P-42 and P-48 each
sprang in their own way).

A note on `what_if_delay`
------------------------
It is the only expensive tool here: it starts a SparkSession and loads the champion
`PipelineModel`, which takes tens of seconds (D-034 records why that page is the one
exception to D-009). It is exposed because "predictions" is what the plan asks for, and
its docstring says the cost out loud so a client can prefer `alerts_for_corridor`,
which reads what the stream already decided and answers instantly.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any

import pandas as pd
from mcp.server import MCPServer

from src.agents.exception_agent import load_audit, load_friction
from src.agents.tms_client import TMSClient, TMSError
from src.common import config
from src.common.logging_setup import get_logger
from src.dashboard.alerts import corridor_rollup, excess_min, load_alerts, summary

log = get_logger("agents.mcp_server")

server = MCPServer(
    name="control-tower",
    instructions=(
        "Corridor statistics, delay predictions and mock-TMS operations for an Indian "
        "logistics network. Corridor ids are 'IND######AAA>IND######AAB'. Every number "
        "comes from the project's own audited tables; nothing is estimated here."
    ),
)


def _ok(payload: Any) -> str:
    """Tools return JSON text: an MCP client reads strings, and a dict rendered by
    `str()` is not JSON (single quotes), which is a silent parse failure at the far end."""
    return json.dumps(payload, indent=2, default=str)


# ── corridor statistics ──────────────────────────────────────────────────────
@server.tool()
def corridor_stats(corridor_id: str) -> str:
    """Week 2's audit verdict for one corridor: how far over plan it runs, whether that
    is statistically significant, and its bottleneck rank if it has one.

    Returns `found: false` for a corridor the audit never tested -- below D-018's
    10-leg floor there is no verdict to give, and inventing one is worse than saying so.
    """
    audit = load_audit()
    if audit.empty or corridor_id not in audit.index:
        return _ok({"corridor_id": corridor_id, "found": False,
                    "reason": "not in the Week 2 audit (fewer legs than D-018's floor)"})
    row = audit.loc[corridor_id]
    rank = row.get("bottleneck_rank")
    return _ok({
        "corridor_id": corridor_id,
        "found": True,
        "n_legs": int(row["n_legs"]),
        "mean_osrm_time_min": round(float(row["mean_osrm_time"]), 1),
        "mean_actual_time_min": round(float(row["mean_actual_time"]), 1),
        "median_gap_ratio": round(float(row["median_gap_ratio"]), 3),
        "excess_ratio": round(float(row["excess_ratio"]), 3),
        "direction": str(row["direction"]),
        "is_significant": bool(row["is_significant"]),
        "q_value": float(row["q_value"]),
        # pandas gives NaN for a corridor with no rank; NaN is not JSON, and json.dumps
        # would emit a bare NaN token that a strict client refuses to parse.
        "bottleneck_rank": None if pd.isna(rank) else int(rank),
    })


@server.tool()
def hub_friction(centre_code: str) -> str:
    """Where a centre sits in the network's hub-friction ranking, if it is in the top 20."""
    friction = load_friction()
    rank = friction.get(centre_code)
    return _ok({"centre_code": centre_code, "friction_rank": rank,
                "in_top_20": rank is not None})


@server.tool()
def worst_corridors(limit: int = 10) -> str:
    """The corridors currently producing the most delay alerts, worst first."""
    feed = load_alerts()
    if feed.empty:
        return _ok({"alerts": 0, "corridors": []})
    rollup = corridor_rollup(feed.alerts, top=limit)
    return _ok({"alerts": len(feed.alerts), "corridors": rollup.to_dict(orient="records")})


# ── predictions ──────────────────────────────────────────────────────────────
@server.tool()
def alerts_for_corridor(corridor_id: str, limit: int = 5) -> str:
    """Delay alerts the streaming job has already raised for one corridor, worst first.

    Instant: it reads the alert sink the Week 5 job writes. Prefer this over
    `what_if_delay` whenever the question is about a leg the stream has already scored.
    """
    feed = load_alerts()
    if feed.empty:
        return _ok({"corridor_id": corridor_id, "alerts": []})
    rows = feed.alerts[feed.alerts["corridor_id"] == corridor_id]
    if rows.empty:
        return _ok({"corridor_id": corridor_id, "alerts": []})
    rows = rows.assign(excess_min=excess_min(rows)).sort_values("excess_min", ascending=False).head(limit)
    keep = ["alert_id", "leg_id", "route_type", "planned_min", "predicted_total_min",
            "predicted_gap_min", "threshold_gap_min", "excess_min", "alert_time"]
    return _ok({"corridor_id": corridor_id, "alerts": rows[keep].to_dict(orient="records")})


@server.tool()
def alert_summary() -> str:
    """How many alerts are in the sink, over how many corridors, and how fresh they are."""
    return _ok(summary(load_alerts()))


@server.tool()
def what_if_delay(corridor_id: str, source_center: str, destination_center: str,
                  route_type: str, planned_min: float, planned_km: float,
                  departure: str) -> str:
    """Score a hypothetical leg with the champion model. **Slow: starts Spark.**

    Tens of seconds per call, because it loads a real MLlib `PipelineModel` (D-034).
    `departure` is ISO-8601, e.g. `2018-09-20T14:30`. For a leg the stream has already
    scored, `alerts_for_corridor` answers the same question instantly.
    """
    from src.ml.predict import predict_delay

    result = predict_delay(
        corridor_id=corridor_id, source_center=source_center,
        destination_center=destination_center, route_type=route_type,
        planned_min=planned_min, planned_km=planned_km,
        departure=datetime.fromisoformat(departure),
    )
    return _ok({"corridor_id": corridor_id, **result})


# ── TMS operations ───────────────────────────────────────────────────────────
def _tms() -> TMSClient:
    return TMSClient()


@server.tool()
def tms_health() -> str:
    """Whether the mock TMS is up, and what it holds."""
    try:
        return _ok(_tms().health())
    except (TMSError, OSError) as exc:
        return _ok({"status": "down", "error": str(exc), "base_url": config.TMS_BASE_URL})


@server.tool()
def list_orders(limit: int = 20) -> str:
    """Recent orders in the TMS."""
    return _ok(_tms().list_orders(limit=limit))


@server.tool()
def list_shipments(limit: int = 20) -> str:
    """Recent shipments, with their corridor and status."""
    return _ok(_tms().list_shipments(limit=limit))


@server.tool()
def list_exceptions(limit: int = 20) -> str:
    """Exception tickets, newest first."""
    return _ok(_tms().list_exceptions(limit=limit))


@server.tool()
def file_exception(shipment_ref: str, severity: str, reason: str, notes: str = "") -> str:
    """File an exception ticket against a shipment.

    `severity` is one of low, medium, high, critical. This **writes**: it also flags the
    shipment `exception`, which is the TMS's own behaviour, not this tool's.
    """
    return _ok(_tms().create_exception(shipment_ref, severity, reason, notes or None))


@server.tool()
def list_invoices(limit: int = 20) -> str:
    """Invoices submitted against shipments, with their audit status."""
    return _ok(_tms().list_invoices(limit=limit))


TOOL_NAMES = [
    "corridor_stats", "hub_friction", "worst_corridors",
    "alerts_for_corridor", "alert_summary", "what_if_delay",
    "tms_health", "list_orders", "list_shipments", "list_exceptions",
    "file_exception", "list_invoices",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="MCP tool server for the control tower")
    parser.add_argument("--list", action="store_true", help="print the tools and exit")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"])
    args = parser.parse_args()

    if args.list:
        for name in TOOL_NAMES:
            print(name)
        return 0

    log.info("serving %d tools over %s", len(TOOL_NAMES), args.transport)
    server.run(transport=args.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
