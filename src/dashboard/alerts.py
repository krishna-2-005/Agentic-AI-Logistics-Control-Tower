"""Reading the streaming job's alert sink (execution plan W5 D3-D4).

The Live alerts page and the alert bot (D5) both need to answer the same questions of
`STREAM_ALERTS_DIR` -- what is in it, how fresh is it, which corridors keep appearing --
so the answers live here rather than twice: once inline in a Streamlit page and once
inside the bot. Neither Streamlit nor Spark is imported, which is what makes any of this
testable and is also why the page stays inside D-009 (the what-if predictor is the only
page allowed a SparkSession, D-034).

Nothing here decides what an alert *is*. `docs/schemas/alert.schema.json` fixes the
shape and `src/streaming/job.py` produces it; this module reads that contract and does
not widen it.

Two clocks, and why the panel shows both
----------------------------------------
`event_time` is the real historical creation time of the leg being scored -- 2018, on
this dataset. `alert_time` is the wall-clock instant the micro-batch flagged it. A
replay compresses ~26 days into a minute, so these are deliberately different and a
panel that shows one where it means the other reads as a system with a broken clock.
The alert schema says so in its own description of the field; this module keeps them
apart, and `freshness` is always measured on `alert_time`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.common import config

#: Columns the page and the bot rely on. A file missing any of them is a file written by
#: something other than the current job, and saying so beats rendering a table with a
#: hole in it.
REQUIRED_COLUMNS = (
    "alert_id", "leg_id", "corridor_id", "source_center", "destination_center",
    "event_time", "route_type", "planned_min", "predicted_gap_min",
    "predicted_total_min", "threshold_gap_min", "alert_time",
)


@dataclass
class AlertFeed:
    """Everything the alert sink currently holds, plus how it was read."""

    alerts: pd.DataFrame
    files: int
    read_at: datetime

    @property
    def empty(self) -> bool:
        return self.alerts.empty

    @property
    def latest_alert_time(self) -> datetime | None:
        if self.empty:
            return None
        return self.alerts["alert_time"].max().to_pydatetime()

    @property
    def seconds_since_last_alert(self) -> float | None:
        """Age of the newest alert, in seconds, or None if there are none.

        Measured against `alert_time` (wall clock), never `event_time` (2018). Returns a
        number even when it is large: a panel that hides staleness is worse than one
        that shows a big number, because the failure it hides is "the stream stopped".
        """
        latest = self.latest_alert_time
        if latest is None:
            return None
        return (self.read_at - latest).total_seconds()


def load_alerts(directory: Path | None = None) -> AlertFeed:
    """Read every `alerts_*.jsonl` file in the sink into one frame, newest first.

    The job writes one file per micro-batch and never appends to a file it has already
    renamed into place, so reading the whole directory is reading the whole stream.
    Files that are unreadable or malformed are skipped rather than raising: this is
    called from a dashboard page, and one bad file should cost that file, not the panel.
    """
    directory = directory or config.STREAM_ALERTS_DIR
    read_at = datetime.now().astimezone()
    if not directory.exists():
        return AlertFeed(pd.DataFrame(), 0, read_at)

    rows: list[dict] = []
    files = 0
    for path in sorted(directory.glob("alerts_*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        files += 1
        for line in lines:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not rows:
        return AlertFeed(pd.DataFrame(), files, read_at)

    frame = pd.DataFrame(rows)
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(
            f"{directory} holds alerts missing {missing} -- written by a different "
            "version of src/streaming/job.py than docs/schemas/alert.schema.json describes."
        )

    # The two clocks are parsed differently because they *are* different, and treating
    # them alike is the bug this comment exists to prevent.
    #
    # `event_time` is a bare local timestamp copied out of the 2018 dataset -- no offset,
    # and none implied. Reading it as UTC and converting would shift every historical
    # time by the local offset, silently rewriting the data. It stays naive.
    #
    # `alert_time` and `emit_time` are offset-aware instants this machine produced, so
    # they are read as such and shown in this machine's zone.
    #
    # `format="ISO8601"` on all of them, never an inferred one: the columns carry mixed
    # precision (a 2018 event_time keeps microseconds; a whole-second timestamp does
    # not), and pandas infers a format from the first element and then throws on the
    # rest. That is P-09 in Week 1 and P-38 in the producer; there is no reason to meet
    # it a third time.
    local_tz = datetime.now().astimezone().tzinfo
    if "event_time" in frame.columns:
        frame["event_time"] = pd.to_datetime(frame["event_time"], format="ISO8601", errors="coerce")
    for column in ("alert_time", "emit_time"):
        if column in frame.columns:
            frame[column] = pd.to_datetime(
                frame[column], format="ISO8601", errors="coerce", utc=True
            ).dt.tz_convert(local_tz)

    # One row per alert_id. The job's own contract says a replayed micro-batch re-emits
    # the same alert_id, so this is where that promise is cashed rather than trusted.
    frame = frame.drop_duplicates(subset="alert_id", keep="last")
    return AlertFeed(frame.sort_values("alert_time", ascending=False).reset_index(drop=True), files, read_at)


def excess_min(alerts: pd.DataFrame) -> pd.Series:
    """How far past the delay threshold each prediction sits, in minutes.

    The severity ordering the panel and the bot both use. `predicted_gap_min` alone
    ranks a 400-minute haul above a 40-minute one whatever either was planned to take;
    what makes an alert worth a human's attention is how far past *its own* threshold it
    is, which is the same quantity D-003's rule tests.
    """
    return alerts["predicted_gap_min"] - alerts["threshold_gap_min"]


def corridor_rollup(alerts: pd.DataFrame, top: int = 15) -> pd.DataFrame:
    """Alerts per corridor, worst first -- the view an operations desk actually acts on.

    A flat list of 17,000 alerts is a log. The question a dispatcher asks is which
    corridors keep producing them, because that is what a person can do something about.
    """
    if alerts.empty:
        return pd.DataFrame(columns=["corridor_id", "alerts", "median_excess_min", "worst_excess_min"])
    working = alerts.assign(excess_min=excess_min(alerts))
    rollup = (
        working.groupby("corridor_id")
        .agg(
            alerts=("alert_id", "count"),
            median_excess_min=("excess_min", "median"),
            worst_excess_min=("excess_min", "max"),
        )
        .reset_index()
        .sort_values(["alerts", "worst_excess_min"], ascending=False)
    )
    return rollup.head(top).reset_index(drop=True)


def summary(feed: AlertFeed) -> dict:
    """The numbers the panel puts at the top, computed once."""
    if feed.empty:
        return {
            "alerts": 0, "files": feed.files, "corridors": 0,
            "cold_alerts": 0, "median_excess_min": None, "worst_excess_min": None,
            "median_latency_ms": None, "seconds_since_last_alert": None,
        }
    alerts = feed.alerts
    excess = excess_min(alerts)
    cold_columns = [c for c in ("corr_is_cold", "src_is_cold", "dst_is_cold") if c in alerts.columns]
    cold = int(alerts[cold_columns].max(axis=1).sum()) if cold_columns else 0
    return {
        "alerts": len(alerts),
        "files": feed.files,
        "corridors": int(alerts["corridor_id"].nunique()),
        "cold_alerts": cold,
        "median_excess_min": float(excess.median()),
        "worst_excess_min": float(excess.max()),
        "median_latency_ms": (
            float(alerts["latency_ms"].median()) if "latency_ms" in alerts.columns
            and alerts["latency_ms"].notna().any() else None
        ),
        "seconds_since_last_alert": feed.seconds_since_last_alert,
    }
