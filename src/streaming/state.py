"""Event-time history, one key at a time -- what the stream needs to serve the v2 model.

The batch feature tables compute every history feature as a window function over a
fact/query union (`src.pipeline.features.as_of_history`, `src.pipeline.features_v2`).
A stream cannot run a window over data it has not seen yet, so it keeps the same
statistics as **running state per key** instead: each fact event updates the state of
the keys it belongs to, and each query event reads that state at its own event time.
This module is that state and nothing else -- plain Python, no Spark -- so the
streaming job, the what-if predictor and the tests all fold events through one
implementation rather than three that merely agree today (D-053, WP-11).

Five key types, one per group of features:

======== ================================ =============================================
key type  key                              features it produces
======== ================================ =============================================
corr      corridor_id                      v1 corridor history + median/p90/IQR/std + 7-day
src       source_center                    v1 source-hub history
dst       destination_center               v1 destination-hub history
src_dwell source_center | hour bucket      `src_dwell_by_hour_min`
dst_dwell destination_center | hour bucket `dst_dwell_by_hour_min`
======== ================================ =============================================

Matching Spark bit for bit, not approximately
---------------------------------------------
Stream-equals-batch is judged on identical predictions, and a GBT turns a feature that
differs in its last bit into a different prediction whenever the value sits on a split.
So every statistic here repeats the arithmetic Spark performs, in the order it performs
it, rather than a mathematically equal formula:

* running sums and means add values one at a time in event order, as a ROWS frame
  from UNBOUNDED PRECEDING does;
* the sample standard deviation uses Spark's `CentralMomentAgg` update (a Welford
  recurrence), not `statistics.stdev`;
* percentiles use Spark's exact `percentile` interpolation between the two nearest
  ranks, not numpy's;
* the 7-day window is a RANGE frame over epoch *seconds* -- `cast("long")` truncates
  the microseconds -- and is summed from scratch for each query, as Spark's sliding
  frame does.

Where the batch definition has an edge a stream cannot reproduce, it is counted rather
than papered over: the 7-day frame compares whole seconds, so a fact finishing in the
same second as a query but a fraction of a second *after* it is inside the batch frame
and has not yet happened on the stream.
"""

from __future__ import annotations

import bisect
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

#: Mirrors `src.pipeline.features_v2`. Restated rather than imported so this module
#: stays importable without Spark; `tests/test_stream_state.py` asserts the two agree.
TRAILING_DAYS = 7
TRAILING_SECONDS = TRAILING_DAYS * 86_400
HOUR_BUCKETS = {"night": (0, 5), "morning": (6, 11), "afternoon": (12, 17), "evening": (18, 23)}

#: v1's six per-prefix history statistics, in `src.ml.baselines.HISTORY_STATS` order.
V1_STATS = ("n_prior", "mean_log_ratio", "std_log_ratio", "mean_gap_min", "last_log_ratio", "hours_since_last")

CORRIDOR_V2 = (
    "corr_median_gap_min", "corr_p90_gap_min", "corr_iqr_gap_min", "corr_std_gap_min",
    "corr_mean_gap_7d", "corr_n_prior_7d",
)

#: key type -> (event field holding the key, whether the hour bucket is part of the key)
KEY_TYPES: dict[str, tuple[str, bool]] = {
    "corr": ("corridor_id", False),
    "src": ("source_center", False),
    "dst": ("destination_center", False),
    "src_dwell": ("source_center", True),
    "dst_dwell": ("destination_center", True),
}

#: Every feature column the state can emit, in a fixed order -- the stream's output schema.
FEATURE_COLUMNS: list[str] = (
    [f"{p}_{s}" for p in ("corr", "src", "dst") for s in V1_STATS]
    + list(CORRIDOR_V2)
    + ["src_dwell_by_hour_min", "dst_dwell_by_hour_min"]
)
INT_COLUMNS = {"corr_n_prior", "src_n_prior", "dst_n_prior", "corr_n_prior_7d"}

_EPOCH = datetime(1970, 1, 1)


def hour_bucket(hour: int) -> str:
    for name, (low, high) in HOUR_BUCKETS.items():
        if low <= hour <= high:
            return name
    raise ValueError(f"hour {hour} is outside every bucket")


def epoch_us(when: datetime | str) -> int:
    """Microseconds since the epoch for a **naive** timestamp, read as wall-clock time.

    The zone does not matter: every quantity here is a difference of two timestamps,
    and Asia/Kolkata has no daylight saving, so a constant offset cancels.
    """
    if isinstance(when, str):
        when = datetime.fromisoformat(when)
    if when.tzinfo is not None:
        raise ValueError(f"expected a naive timestamp (D-013), got {when.isoformat()}")
    return (when - _EPOCH) // timedelta(microseconds=1)


def floor_seconds(us: int) -> int:
    """`cast(timestamp as long)`: floor division, as Spark's `Math.floorDiv`."""
    return us // 1_000_000


def spark_percentile(ordered: list[float], p: float) -> float:
    """Spark's exact `percentile`: linear interpolation between the two nearest ranks."""
    position = (len(ordered) - 1) * p
    lower, higher = math.floor(position), math.ceil(position)
    lower_value = ordered[lower]
    if higher == lower:
        return lower_value
    higher_value = ordered[higher]
    if higher_value == lower_value:
        return lower_value
    return (higher - position) * lower_value + (position - lower) * higher_value


def keys_for(event: dict) -> list[tuple[str, str]]:
    """The `(key type, key)` pairs an event belongs to. Facts and queries alike: a fact
    updates exactly the keys a query would read, which is what makes it history."""
    bucket = hour_bucket(int(event["created_hour"]))
    out = []
    for key_type, (column, bucketed) in KEY_TYPES.items():
        key = event[column]
        out.append((key_type, f"{key}|{bucket}" if bucketed else key))
    return out


def sort_key(event: dict) -> tuple[int, int, str]:
    """D-020's order: event time, then facts before queries at an identical instant.
    The leg id only makes ties reproducible; Spark leaves their order unspecified."""
    return (epoch_us(event["event_time"]), 0 if event["kind"] == "fact" else 1, event["leg_id"])


@dataclass
class RunningHistory:
    """v1's as-of history for one key (`as_of_history`): running sums over prior legs."""

    n: int = 0
    sum_stat: float = 0.0
    sumsq_stat: float = 0.0
    sum_gap: float = 0.0
    last_stat: float | None = None
    last_known_s: int | None = None

    def add(self, when_us: int, log_gap_ratio: float, gap_min: float) -> None:
        self.n += 1
        self.sum_stat += log_gap_ratio
        self.sumsq_stat += log_gap_ratio * log_gap_ratio
        self.sum_gap += gap_min
        self.last_stat = log_gap_ratio
        self.last_known_s = floor_seconds(when_us)

    def read(self, when_us: int, prefix: str) -> dict[str, Any]:
        n = self.n
        mean = self.sum_stat / n if n else None
        std = None
        if n > 1 and mean is not None:
            std = math.sqrt(max(self.sumsq_stat / n - mean * mean, 0.0))
        since = None
        if self.last_known_s is not None:
            since = (floor_seconds(when_us) - self.last_known_s) / 3600.0
        return {
            f"{prefix}_n_prior": n,
            f"{prefix}_mean_log_ratio": mean,
            f"{prefix}_std_log_ratio": std,
            f"{prefix}_mean_gap_min": self.sum_gap / n if n else None,
            f"{prefix}_last_log_ratio": self.last_stat,
            f"{prefix}_hours_since_last": since,
        }


@dataclass
class CorridorDispersion:
    """features_v2's corridor dispersion and trailing 7-day mean for one corridor."""

    ordered: list[float] = field(default_factory=list)
    # Spark's CentralMomentAgg buffer, for stddev_samp.
    m_n: float = 0.0
    m_avg: float = 0.0
    m_m2: float = 0.0
    # (epoch seconds, gap) in arrival order, pruned once older than any query can reach.
    recent: list[list[float]] = field(default_factory=list)

    def add(self, when_us: int, gap_min: float) -> None:
        bisect.insort(self.ordered, gap_min)
        new_n = self.m_n + 1.0
        delta = gap_min - self.m_avg
        delta_n = delta / new_n
        self.m_avg = self.m_avg + delta_n
        self.m_m2 = self.m_m2 + delta * (delta - delta_n)
        self.m_n = new_n
        self.recent.append([floor_seconds(when_us), gap_min])

    def prune(self, watermark_s: int) -> int:
        """Drop 7-day entries no query at or after the watermark can still reach."""
        cutoff = watermark_s - TRAILING_SECONDS
        keep = [entry for entry in self.recent if entry[0] >= cutoff]
        dropped = len(self.recent) - len(keep)
        self.recent = keep
        return dropped

    def read(self, when_us: int) -> dict[str, Any]:
        n = len(self.ordered)
        q = floor_seconds(when_us)
        total, count = 0.0, 0
        for seconds, gap in self.recent:
            if q - TRAILING_SECONDS <= seconds <= q:
                total += gap
                count += 1
        out: dict[str, Any] = dict.fromkeys(CORRIDOR_V2)
        if n:
            out["corr_median_gap_min"] = spark_percentile(self.ordered, 0.5)
            out["corr_p90_gap_min"] = spark_percentile(self.ordered, 0.9)
            out["corr_iqr_gap_min"] = spark_percentile(self.ordered, 0.75) - spark_percentile(self.ordered, 0.25)
        if n > 1:
            out["corr_std_gap_min"] = math.sqrt(self.m_m2 / (self.m_n - 1.0))
        out["corr_mean_gap_7d"] = total / count if count else None
        out["corr_n_prior_7d"] = count
        return out


@dataclass
class DwellHistory:
    """Mean dwell of prior legs at one hub in one part of the day (`dwell_by_hour`)."""

    n: int = 0
    total: float = 0.0

    def add(self, dwell_min: float | None) -> None:
        if dwell_min is None:
            return
        self.n += 1
        self.total += dwell_min

    def read(self, prefix: str) -> dict[str, Any]:
        return {f"{prefix}_dwell_by_hour_min": self.total / self.n if self.n else None}


@dataclass
class KeyState:
    """All the state one `(key type, key)` group keeps, serialisable for the state store."""

    key_type: str
    running: RunningHistory | None = None
    dispersion: CorridorDispersion | None = None
    dwell: DwellHistory | None = None
    last_event_us: int | None = None
    facts: int = 0
    out_of_order: int = 0

    @classmethod
    def new(cls, key_type: str) -> KeyState:
        if key_type not in KEY_TYPES:
            raise ValueError(f"unknown key type {key_type!r}")
        state = cls(key_type=key_type)
        if key_type.endswith("_dwell"):
            state.dwell = DwellHistory()
        else:
            state.running = RunningHistory()
        if key_type == "corr":
            state.dispersion = CorridorDispersion()
        return state

    def _observe(self, when_us: int) -> None:
        if self.last_event_us is not None and when_us < self.last_event_us:
            self.out_of_order += 1
        else:
            self.last_event_us = when_us

    def apply_fact(self, event: dict) -> None:
        when = epoch_us(event["event_time"])
        self._observe(when)
        self.facts += 1
        if self.running is not None:
            self.running.add(when, float(event["log_gap_ratio"]), float(event["gap_min"]))
        if self.dispersion is not None:
            self.dispersion.add(when, float(event["gap_min"]))
        if self.dwell is not None:
            # A pandas row carries NaN, not None, for a field the event did not have.
            dwell = event.get("dwell_min")
            self.dwell.add(None if dwell is None or dwell != dwell else float(dwell))

    def read(self, event: dict) -> dict[str, Any]:
        """The features this key contributes to a query, as of the query's event time."""
        when = epoch_us(event["event_time"])
        self._observe(when)
        if self.dwell is not None:
            return self.dwell.read(self.key_type.removesuffix("_dwell"))
        assert self.running is not None
        out = self.running.read(when, self.key_type)
        if self.dispersion is not None:
            out.update(self.dispersion.read(when))
        return out

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, payload: str) -> KeyState:
        raw = json.loads(payload)
        return cls(
            key_type=raw["key_type"],
            running=RunningHistory(**raw["running"]) if raw["running"] else None,
            dispersion=CorridorDispersion(**raw["dispersion"]) if raw["dispersion"] else None,
            dwell=DwellHistory(**raw["dwell"]) if raw["dwell"] else None,
            last_event_us=raw["last_event_us"],
            facts=raw["facts"],
            out_of_order=raw["out_of_order"],
        )


class HistoryBook:
    """Every key's state in one process -- for the predictor and for tests.

    Folds events in D-020 order and returns, for each query, the full feature row the
    stream would have assembled from its five groups. The streaming job does the same
    work spread across Spark's state store, one group per key; this is the reference
    it is held to.
    """

    def __init__(self) -> None:
        self.states: dict[tuple[str, str], KeyState] = {}

    def _state(self, key_type: str, key: str) -> KeyState:
        state = self.states.get((key_type, key))
        if state is None:
            state = self.states[(key_type, key)] = KeyState.new(key_type)
        return state

    def apply_fact(self, event: dict) -> None:
        for key_type, key in keys_for(event):
            self._state(key_type, key).apply_fact(event)

    def read(self, event: dict) -> dict[str, Any]:
        row: dict[str, Any] = {}
        for key_type, key in keys_for(event):
            row.update(self._state(key_type, key).read(event))
        return row

    def fold(self, events: list[dict]) -> dict[str, dict[str, Any]]:
        """Apply `events` in order; return each query's features keyed by `leg_id`."""
        out = {}
        for event in sorted(events, key=sort_key):
            if event["kind"] == "fact":
                self.apply_fact(event)
            else:
                out[event["leg_id"]] = self.read(event)
        return out
