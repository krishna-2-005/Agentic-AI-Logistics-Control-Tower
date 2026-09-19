"""Trip-replay producer (execution plan W5 D1-D2) -- the stream's left-hand end.

    python -m src.streaming.producer --duration 60           # whole window in 60s
    python -m src.streaming.producer --limit 2000 --duration 20
    python -m src.streaming.producer --sink kafka            # when a broker exists

Reads the frozen `features_v1` cache, turns every leg into the **query + fact event
pair** `docs/schemas/stream_event.schema.json` already defines (D-031), orders them
by `event_time`, and emits them **time-compressed**: the dataset's real ~26-day
observation window replayed over N wall-clock seconds.

Nothing about the event shape is invented here. `src.streaming.schema` owns
`query_event` / `fact_event` / `validate_event`, and this module calls them -- the
same "one shared source, not two that can drift" reasoning D-031 gives for reusing
D-020's fact/query split in the first place, applied one level down.

Two sinks behind one interface
------------------------------
* ``kafka`` -- a real `KafkaProducer` onto `KAFKA_TOPIC_TRIPS`. Imported lazily, so a
  machine with no broker can still run the file path.
* ``file``  -- one JSON-lines file per tick into `STREAM_TRIPS_DIR`, which Spark
  Structured Streaming reads as a **file source**. This is the fallback the execution
  plan's own 3-day rule calls for ("if Kafka fights the environment, switch to
  file-streaming") and `README.md` already advertises.

**Which one this machine actually runs, stated plainly:** the file sink. There is no
Docker here and therefore no broker, so the Kafka path is written and import-checked
but has never been run against a live broker on this machine -- see D-035 and
`docs/W5_mounika_kafka_streaming.md`. The choice is one flag, not one rewrite, which
is the point of putting both behind the same `emit()`.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark
from src.streaming.schema import (
    EXAMPLE_COLUMNS,
    fact_event,
    load_schema,
    query_event,
    require_od_end_time,
    validate_event,
    with_od_end_time,
)

log = get_logger("streaming.producer")

#: Wall-clock seconds between flushes. Events are bucketed into ticks rather than
#: slept over one at a time: replaying 52,738 events across 60s is ~880 events/sec,
#: and a `time.sleep()` per event would spend more time in timer overhead than in the
#: replay itself. One file per tick is also exactly what a Spark file source wants --
#: it picks up whole files, not partial writes.
TICK_SECONDS = 0.5

#: Ordering rule, reused rather than restated: at equal `event_time` a fact sorts
#: before a query, so a leg that finishes at the same instant another is created is
#: already history to it (D-020's as_of_history, D-031's schema note).
KIND_ORDER = {"fact": 0, "query": 1}


@dataclass
class ReplayStats:
    """What a run actually did -- returned rather than only logged, so the D5
    throughput harness can assert on it instead of scraping a log line."""

    events: int = 0
    ticks: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0
    sink: str = ""
    files_written: list[Path] = field(default_factory=list)

    @property
    def wall_seconds(self) -> float:
        return self.finished_at - self.started_at

    @property
    def events_per_second(self) -> float:
        return self.events / self.wall_seconds if self.wall_seconds > 0 else 0.0


class FileSink:
    """One JSON-lines file per tick into a directory a Spark file source watches.

    Each file is written under a temporary name and then renamed, because Spark's
    file source lists the directory and will happily pick up a file that is still
    being written -- a half-written last line is a parse failure at the consumer end,
    which is a genuinely nasty bug to chase back to its cause. An atomic rename means
    a file the streaming job can see is a file that is already complete.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.written: list[Path] = []

    def emit(self, batch: list[dict], tick: int) -> None:
        if not batch:
            return
        final = self.directory / f"tick_{tick:06d}.jsonl"
        staging = self.directory / f".tick_{tick:06d}.jsonl.tmp"
        payload = "\n".join(json.dumps(event) for event in batch) + "\n"
        staging.write_text(payload, encoding="utf-8")
        staging.replace(final)
        self.written.append(final)

    def close(self) -> None:
        return None


class KafkaSink:
    """A real `KafkaProducer` onto `KAFKA_TOPIC_TRIPS`, keyed by `corridor_id`.

    Keying on the corridor is deliberate: it puts every event for one corridor on the
    same partition, so a stateful consumer sees that corridor's facts and queries in
    the order they were produced. Never exercised against a live broker on this
    machine (no Docker) -- D-035 says so rather than letting the code imply otherwise.
    """

    def __init__(self, servers: str, topic: str) -> None:
        from kafka import KafkaProducer  # lazy: the file path must not need this

        self.topic = topic
        self.producer = KafkaProducer(
            bootstrap_servers=servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8"),
            linger_ms=50,
        )

    def emit(self, batch: list[dict], tick: int) -> None:  # tick is a file-sink concept, unused here
        for event in batch:
            self.producer.send(self.topic, key=event["corridor_id"], value=event)
        self.producer.flush()

    def close(self) -> None:
        self.producer.close()


def load_legs(limit: int | None = None) -> pd.DataFrame:
    """The frozen Stage 4 cache, oldest legs first. Spark is used for the read only."""
    spark = get_spark("stream-producer")
    try:
        sdf = spark.read.parquet(str(config.FEATURES_V1)).select(*EXAMPLE_COLUMNS)
        pdf = require_od_end_time(with_od_end_time(spark, sdf).toPandas())
    finally:
        stop_spark(spark)
    pdf = pdf.sort_values("trip_creation_time").reset_index(drop=True)
    return pdf.head(limit) if limit else pdf


def build_events(pdf: pd.DataFrame) -> list[dict]:
    """Two events per leg, ordered the way a replay has to emit them."""
    events: list[dict] = []
    for _, row in pdf.iterrows():
        events.append(query_event(row))
        events.append(fact_event(row))
    events.sort(key=lambda e: (e["event_time"], KIND_ORDER[e["kind"]]))
    return events


def compress_schedule(events: list[dict], duration_seconds: float) -> list[tuple[float, dict]]:
    """Map each event's real `event_time` onto a wall-clock offset in [0, duration].

    Linear, not evenly spaced: the gaps between events stay proportional to the real
    gaps, so a quiet night in the data stays a quiet stretch of the replay and a busy
    morning still bursts. Spreading events evenly would produce a smoother, more
    flattering throughput number than the data actually justifies.
    """
    if not events:
        return []
    # `format="ISO8601"` rather than letting pandas infer one format from the first
    # element: a query event carries microseconds (`...T00:02:09.740725`) while a fact
    # event lands on a whole second whenever the leg's duration does
    # (`...T00:23:34`), and inference picks one shape then throws on the other. Exactly
    # P-09's mixed-precision trap from Week 1, arriving in a second place -- logged
    # again as P-38 rather than fixed quietly.
    times = pd.to_datetime([e["event_time"] for e in events], format="ISO8601")
    start, end = times[0], times[-1]
    span = (end - start).total_seconds()
    if span <= 0:
        return [(0.0, event) for event in events]
    return [
        ((t - start).total_seconds() / span * duration_seconds, event)
        for t, event in zip(times, events, strict=True)
    ]


def make_sink(sink_name: str) -> FileSink | KafkaSink:
    if sink_name == "kafka":
        return KafkaSink(config.KAFKA_BOOTSTRAP_SERVERS, config.KAFKA_TOPIC_TRIPS)
    return FileSink(config.STREAM_TRIPS_DIR)


def replay(
    schedule: list[tuple[float, dict]],
    sink: FileSink | KafkaSink,
    sink_name: str,
    tick_seconds: float = TICK_SECONDS,
) -> ReplayStats:
    """Emit the scheduled events, bucketed into ticks, sleeping to keep real time.

    If a tick's work overruns its slot the next flush goes out immediately rather
    than sleeping a negative amount -- the replay then runs slower than the requested
    duration, and the returned `wall_seconds` says so, instead of the run quietly
    claiming a compression ratio it never achieved.
    """
    stats = ReplayStats(sink=sink_name, started_at=time.monotonic())
    batch: list[dict] = []
    tick = 0
    next_flush = tick_seconds

    for offset, event in schedule:
        while offset > next_flush:
            _flush(sink, batch, tick, stats)
            batch = []
            tick += 1
            _sleep_until(stats.started_at + next_flush)
            next_flush += tick_seconds
        batch.append(event)

    _flush(sink, batch, tick, stats)
    stats.finished_at = time.monotonic()
    if isinstance(sink, FileSink):
        stats.files_written = sink.written
    sink.close()
    return stats


def _flush(sink: FileSink | KafkaSink, batch: list[dict], tick: int, stats: ReplayStats) -> None:
    if not batch:
        return
    sink.emit(batch, tick)
    stats.events += len(batch)
    stats.ticks += 1


def _sleep_until(deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay cleaned trips as a time-compressed event stream")
    parser.add_argument("--sink", choices=["file", "kafka"], default=None,
                        help=f"default: STREAM_SOURCE in .env (currently {config.STREAM_SOURCE!r})")
    parser.add_argument("--duration", type=float, default=60.0, help="wall-clock seconds to replay the window over")
    parser.add_argument("--limit", type=int, default=None, help="only the first N legs (2 events each)")
    parser.add_argument("--tick", type=float, default=TICK_SECONDS, help="seconds between flushes")
    parser.add_argument("--validate", action="store_true", help="validate every event against the JSON Schema first")
    parser.add_argument("--clean", action="store_true", help="empty the file sink's directory before replaying")
    args = parser.parse_args()

    if not config.FEATURES_V1.exists():
        log.error("Missing %s -- run `python -m src.pipeline.features` first.", config.FEATURES_V1)
        return 1

    sink_name = args.sink or ("kafka" if config.STREAM_SOURCE == "kafka" else "file")
    pdf = load_legs(args.limit)
    events = build_events(pdf)
    log.info(
        "%s legs -> %s events (%s ... %s)",
        f"{len(pdf):,}", f"{len(events):,}", events[0]["event_time"], events[-1]["event_time"],
    )

    if args.validate:
        schema = load_schema()
        for event in events:
            validate_event(event, schema)
        log.info("all %s events validate against stream_event.schema.json", f"{len(events):,}")

    if args.clean and sink_name == "file" and config.STREAM_TRIPS_DIR.exists():
        removed = 0
        for path in config.STREAM_TRIPS_DIR.glob("*.jsonl"):
            path.unlink()
            removed += 1
        log.info("cleaned %d file(s) from %s", removed, config.STREAM_TRIPS_DIR)

    schedule = compress_schedule(events, args.duration)
    real_span_s = (
        pd.to_datetime(events[-1]["event_time"]) - pd.to_datetime(events[0]["event_time"])
    ).total_seconds()

    try:
        sink = make_sink(sink_name)
    except Exception as exc:  # noqa: BLE001 -- a missing broker must say so, not traceback
        log.error("could not open the %s sink: %s", sink_name, exc)
        return 1

    log.info("replaying %.1f real hours over %.0fs into the %s sink...", real_span_s / 3600, args.duration, sink_name)
    stats = replay(schedule, sink, sink_name, args.tick)

    log.info(
        "%s events in %.1fs over %d ticks = %.0f events/sec sustained (%.0fx time compression)",
        f"{stats.events:,}", stats.wall_seconds, stats.ticks, stats.events_per_second,
        real_span_s / stats.wall_seconds if stats.wall_seconds else 0,
    )
    if stats.files_written:
        log.info("%d file(s) -> %s", len(stats.files_written), config.STREAM_TRIPS_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
