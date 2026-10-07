"""Build the files the public API serves from, into `deploy/api/serving/` (WP-04, D-073).

    python scripts/build_api_bundle.py

Run on a machine that has the data (`data/processed`, the model, a v2 stream run). It
writes four files, all committed, because the host builds from the repository:

=========================  ==================================================================
v2_forest.json.gz          the served model's 200 trees, verified identical to Spark on
                           every leg (`src.ml.gbt_local --verify`)
history_snapshot.json.gz   per-corridor and per-hub aggregates for "today" (`src.ml.history_snapshot`),
                           verified identical to the full fold on 52,738 queries
alert_feed.jsonl.gz        the v2 stream's alerts: corridor, predicted gap, severity
agent_calls.jsonl          agent call log, trimmed to agent, time, duration and outcome
=========================  ==================================================================

**Nothing here is a Delhivery record.** `DATA_LICENSE.md` says the dataset is not
redistributed, and the public bundle is held to it: model parameters, aggregates and model
output only. The script refuses to finish if a trip id, a leg id or an event time appears
in any file it wrote.
"""

from __future__ import annotations

import gzip
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.common import config  # noqa: E402 -- the repo root has to be on the path first

BUNDLE = ROOT / "deploy" / "api" / "serving"
SERVING = config.DATA_DIR / "serving"
STREAM_ALERTS = config.STREAM_DIR / "validation_v2" / "alerts"
TRACES = config.DATA_DIR / "traces" / "agent_calls.jsonl"
#: What a raw record would look like if one slipped through.
LEAK = re.compile(r"trip-\d{6,}|\"event_time\"|\"leg_id\"|\"trip_uuid\"")


def trimmed_traces(path: Path) -> list[str]:
    """The call log cut to what `/api/traces` returns. A public file is downloadable, so
    the inputs every agent was given -- including whatever was typed -- stay here."""
    keep = ("route", "decision", "verdict")
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows.append(json.dumps({
            "agent": r.get("agent"), "started_at": r.get("started_at"), "duration_ms": r.get("duration_ms"),
            "error": None if r.get("error") is None else "error",
            "outputs": {k: v for k, v in (r.get("outputs") or {}).items() if k in keep},
        }))
    return rows


def main() -> int:
    from src.api.feeds import build_alert_feed
    from src.ml import gbt_local, serving
    from src.ml.predict import export_snapshot

    BUNDLE.mkdir(parents=True, exist_ok=True)
    gbt_local.to_json(gbt_local.load(serving.MODEL_PATH), BUNDLE / "v2_forest.json.gz")
    snap = export_snapshot(SERVING / "history_snapshot.json.gz")
    shutil.copy2(SERVING / "history_snapshot.json.gz", BUNDLE / "history_snapshot.json.gz")
    feed = build_alert_feed(STREAM_ALERTS, BUNDLE / "alert_feed.jsonl.gz", BUNDLE / "alert_feed_meta.json",
                            recorded_from="src.streaming.validate_v2: the v2 stream over the full replay (WP-11)")
    (BUNDLE / "agent_calls.jsonl").write_text("\n".join(trimmed_traces(TRACES)) + "\n", encoding="utf-8")

    for path in sorted(BUNDLE.iterdir()):
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as handle:
            if LEAK.search(handle.read()):
                path.unlink()
                raise SystemExit(f"{path.name} carries a raw record; removed, bundle not built")
        print(f"  {path.name:28s} {path.stat().st_size / 1024:8.0f} KB")
    print(json.dumps({"snapshot": snap, "alert_feed": feed}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
