"""Today's history, as aggregates only -- what the public predictor serves from (WP-04, D-073).

The data licence (`DATA_LICENSE.md`) is that the Delhivery records are never redistributed:
`data/` is gitignored and every public artefact is an aggregate or a model output. The
predictor's history is a fold over every leg's *outcome*, so shipping the facts it folds
would be shipping the dataset in another shape.

It does not need them. The public predictor only asks about **today**, years after the
data window, and for a query that late every history feature is a function of per-key
aggregates and nothing else:

* the all-history statistics (count, means, the sample std, median, p90, IQR, last
  value) are the final state of each key's fold, the same for every later query;
* `hours_since_last` is the query time minus the key's last fact, so only that last
  time is stored;
* the trailing 7-day window is empty for any query more than seven days after the last
  fact, so it reads as cold.

So the snapshot stores, per `(key type, key)`, exactly what `KeyState.read` would return,
with `hours_since_last` replaced by the last fact's time. That is the per-corridor and
per-hub level the committed audit tables already publish. `read` refuses a query earlier
than `valid_from`, the one condition under which the snapshot would not be exact, and
`verify` checks it against the full fold on every leg's keys.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from src.streaming.state import (
    KEY_TYPES,
    TRAILING_SECONDS,
    HistoryBook,
    KeyState,
    epoch_us,
    floor_seconds,
    keys_for,
)

SINCE = "hours_since_last"


def build(facts: list[dict]) -> dict:
    """Fold every fact and keep, per key, what a late query would read."""
    book = HistoryBook()
    for fact in facts:
        book.apply_fact(fact)
    last_s = floor_seconds(epoch_us(facts[-1]["event_time"]))
    # One second past the 7-day frame's reach: from here on every trailing window is empty.
    valid_from_s = last_s + TRAILING_SECONDS + 1
    probe = {"event_time": _iso(valid_from_s)}
    keys: dict[str, dict[str, dict[str, Any]]] = {kt: {} for kt in KEY_TYPES}
    for (key_type, key), state in book.states.items():
        row = state.read(probe)
        prefix = key_type if not key_type.endswith("_dwell") else None
        if prefix:
            row.pop(f"{prefix}_{SINCE}", None)
            running = state.running
            row["last_known_s"] = running.last_known_s if running else None
            row.pop("corr_mean_gap_7d", None)
            row.pop("corr_n_prior_7d", None)
        keys[key_type][key] = row
    return {"valid_from_s": valid_from_s, "valid_from": _iso(valid_from_s),
            "facts_folded": len(facts), "keys": keys}


def _iso(seconds: int) -> str:
    from datetime import datetime, timedelta

    return (datetime(1970, 1, 1) + timedelta(seconds=seconds)).isoformat()


def read(snapshot: dict, query: dict) -> dict:
    """The 26 history features for `query`, from aggregates alone. Exact for any query at
    or after `valid_from`; refuses an earlier one rather than answering it wrong."""
    query_s = floor_seconds(epoch_us(query["event_time"]))
    if query_s < snapshot["valid_from_s"]:
        raise ValueError(f"the snapshot serves departures from {snapshot['valid_from']} on")
    out: dict[str, Any] = {}
    for key_type, key in keys_for(query):
        stored = snapshot["keys"][key_type].get(key)
        if stored is None:
            out.update(KeyState.new(key_type).read(query))
            continue
        row = dict(stored)
        if not key_type.endswith("_dwell"):
            last = row.pop("last_known_s")
            row[f"{key_type}_{SINCE}"] = None if last is None else (query_s - last) / 3600.0
            if key_type == "corr":
                row["corr_mean_gap_7d"], row["corr_n_prior_7d"] = None, 0
        out.update(row)
    return out


def write(snapshot: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(snapshot, handle)


def load(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def verify(facts: list[dict], snapshot: dict, query_times: list[str]) -> dict:
    """Compare snapshot reads with full-fold reads for every leg's own keys, at each time."""
    book = HistoryBook()
    for fact in facts:
        book.apply_fact(fact)
    compared = differing = 0
    for when in query_times:
        for fact in facts:
            query = {**fact, "kind": "query", "event_time": when}
            full, snap = book.read(query), read(snapshot, query)
            compared += 1
            differing += full != snap
    return {"queries": compared, "differing": differing, "query_times": query_times}
