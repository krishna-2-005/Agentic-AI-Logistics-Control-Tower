"""The two read-only feeds the API serves: stream alerts and agent traces (WP-04).

Alerts: a replay, served live, and labelled as one
-------------------------------------------------
The public container runs no producer, no broker and no streaming job -- a free CPU
Space is not where a Spark stream belongs. What it serves instead is the alert output of
a **real run of the v2 stream** (`src.streaming.job`, the full replay WP-11 validated),
recorded at deploy time and released in event-time order as wall-clock time passes, so
the page sees the feed move the way the stream produced it. Every response says
`mode: "replay"` and when the run was recorded; the page shows that label. A feed that
moved without saying it was a recording would be claiming a running pipeline the
container does not have.

Severity is the exception agent's own (`severity_for` on `predicted / threshold`,
escalated one step on a corridor the Week 2 audit confirmed slow), computed with the
agent's own `investigate` against the audit -- the same word means the same thing on the
Alerts page and in an agent's ticket.

Traces: the agents' own log
---------------------------
`src.agents.tracing` writes one JSON line per agent call. The API returns the newest
rows, trimmed to what the console shows; inputs and outputs are not returned, because a
public endpoint has no business echoing whatever a visitor typed into the assistant
back to the next visitor.
"""

from __future__ import annotations

import gzip
import json
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from src.common import config

SERVING_DIR = config.DATA_DIR / "serving"
ALERT_FEED = SERVING_DIR / "alert_feed.jsonl.gz"
ALERT_FEED_META = SERVING_DIR / "alert_feed_meta.json"

#: One recorded alert released every this many wall-clock seconds. The page polls every
#: 5 s, so a few new rows arrive per poll -- visibly moving, never a flood.
RELEASE_EVERY_S = 2.0
#: Released before the first visitor arrives, so the page is never empty on a cold start.
INITIAL_RELEASED = 40


def build_alert_feed(alerts_dir: Path, out: Path = ALERT_FEED, meta_out: Path = ALERT_FEED_META,
                     recorded_from: str = "") -> dict:
    """Turn a stream alert sink into the feed file, oldest event first. Deploy-time only."""
    import pandas as pd

    from src.agents.exception_agent import investigate, load_audit, load_friction, severity_for
    from src.dashboard.alerts import load_alerts

    feed = load_alerts(alerts_dir)
    if feed.empty:
        raise RuntimeError(f"no alerts in {alerts_dir} -- run the stream first")
    alerts = feed.alerts.sort_values(["event_time", "alert_id"]).reset_index(drop=True)
    audit, friction = load_audit(), load_friction()
    rows = []
    for _, alert in alerts.iterrows():
        threshold = float(alert["threshold_gap_min"])
        ratio = float(alert["predicted_gap_min"]) / threshold if threshold > 0 else float("inf")
        found = investigate(alert, audit, friction, client=None)
        corridor = alert["corridor_id"]
        route = corridor
        if corridor in audit.index:
            a = audit.loc[corridor]
            if pd.notna(a.get("source_city")) and pd.notna(a.get("dest_city")):
                route = f"{a['source_city']} → {a['dest_city']}"
        rows.append({
            "corridor_id": corridor,
            "route": route,
            "predicted_gap_min": round(float(alert["predicted_gap_min"]), 1),
            "excess_ratio": round(ratio, 2) if ratio != float("inf") else None,
            "severity": severity_for(ratio, found),
            "n_legs": found.audit_n_legs or 0,
            "event_time": alert["event_time"].isoformat(),
            "model_id": alert.get("model_id") if isinstance(alert.get("model_id"), str) else None,
        })
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    meta = {
        "alerts": len(rows),
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "recorded_from": recorded_from,
        "by_severity": {s: sum(1 for r in rows if r["severity"] == s) for s in ("low", "medium", "high", "critical")},
    }
    meta_out.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


class AlertReplay:
    """Releases the recorded feed in order as time passes, looping at the end."""

    def __init__(self, path: Path = ALERT_FEED, meta_path: Path = ALERT_FEED_META,
                 every_s: float = RELEASE_EVERY_S, initial: int = INITIAL_RELEASED,
                 clock=time.monotonic) -> None:
        self.rows: list[dict] = []
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                self.rows = [json.loads(line) for line in handle if line.strip()]
        self.meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        self.every_s, self.initial, self.clock = every_s, initial, clock
        self.started = clock()

    def released(self) -> int:
        """How many rows have been released so far, counting repeats after a loop."""
        return self.initial + int((self.clock() - self.started) / self.every_s)

    def window(self, since: int = 0, limit: int = 50) -> list[dict]:
        """The newest released rows with `seq > since`, newest first. `seq` keeps rising
        across loops, so a client polling with `since` never sees a row twice."""
        if not self.rows:
            return []
        latest = self.released()
        first = max(since + 1, latest - limit + 1, 1)
        out = []
        for seq in range(latest, first - 1, -1):
            out.append({"seq": seq, **self.rows[(seq - 1) % len(self.rows)]})
        return out

    def rollup(self, rows: list[dict], top: int = 10) -> list[dict]:
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["corridor_id"]] = counts.get(row["corridor_id"], 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
        return [{"corridor_id": c, "n": n} for c, n in ranked]


def read_traces(path: Path, agent: str | None = None, limit: int = 50) -> list[dict]:
    """The newest `limit` agent calls, newest first, trimmed to what the console shows."""
    if not path.exists():
        return []
    keep: deque[dict] = deque(maxlen=limit)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if agent and record.get("agent") != agent:
                continue
            keep.append(record)
    rows = []
    for record in reversed(keep):
        outputs = record.get("outputs") or {}
        event = outputs.get("route") or outputs.get("decision") or outputs.get("verdict") or "call"
        rows.append({
            "ts": record.get("started_at"),
            "agent": record.get("agent"),
            "event": str(event)[:60],
            "ok": record.get("error") is None,
            "duration_ms": record.get("duration_ms"),
        })
    return rows
