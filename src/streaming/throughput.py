"""Throughput and latency harness (execution plan W5 D5).

    python -m src.streaming.throughput --legs 2000 --durations 20,10,5
    python -m src.streaming.throughput --legs 500 --durations 10   # quick check

Answers the two questions the plan asks -- **events/sec sustained** and
**event-to-alert milliseconds** -- by running the real producer and the real streaming
job against each other, in one process, at several offered rates.

Why a ramp rather than one number
---------------------------------
"The pipeline does N events/sec" is only meaningful with the offered load beside it. A
single run at a comfortable rate measures the *producer's* pacing, not the job's
capacity: if the replay offers 100 events/sec and the job processes 100 events/sec,
that is a statement about the replay. So each step replays the **same legs** over a
shorter wall-clock window -- 2,000 legs over 20s, then 10s, then 5s -- and the step
where the job stops draining within the window is where its capacity actually is.
`kept_up` is that judgement, and it is computed from the event counts rather than
asserted.

What is being measured, stated plainly
--------------------------------------
* **Offered rate** is what the producer was asked for; **produced rate** is what it
  achieved. They differ once the requested compression outruns the writer, and the
  producer already reports its own wall clock rather than assuming its schedule held.
* **Event-to-alert latency** is the tick file's modification time (when the producer
  released the event) to the instant the micro-batch wrote the alert. It therefore
  includes the file source's discovery delay and the micro-batch trigger interval,
  because a consumer waiting for an alert waits for those too.
* **Only alerted legs contribute a latency sample.** A query the model does not flag
  produces no alert and no measurement; the figure is *event-to-alert*, not
  event-to-scored.

This measures plumbing, not accuracy. The alert counts here are not a claim about how
well the model detects delays -- see `docs/W5_mounika_kafka_streaming.md` on why the
replay's history snapshot makes that a different question.
"""

from __future__ import annotations

import argparse
import json
import shutil
import threading
import time
from pathlib import Path

from src.common import config
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark
from src.streaming import job as stream_job
from src.streaming import producer as stream_producer

log = get_logger("streaming.throughput")

THROUGHPUT_JSON = config.BENCHMARKS_RAW_DIR / "w5_stream_throughput.json"

#: Extra wall-clock seconds the job is left running after the replay stops, so a
#: pipeline that is merely a little behind gets to finish rather than being recorded
#: as having failed. Generous on purpose: the interesting failure is "cannot keep up
#: at all", not "finished 3 seconds late".
#:
#: Set from a measurement rather than by taste. At 20s the drain was barely longer than
#: one micro-batch (~14s on this machine), so whether a step "kept up" turned on
#: whether the timer happened to fall inside a batch -- the same 4,000 events scored
#: 1,618 in one run and 4,000 in the next at a *lower* offered rate. Four batch times
#: makes the verdict about the pipeline instead of about the clock (P-44).
DRAIN_SECONDS = 60.0

#: Tick files per micro-batch. Left unbounded, Spark's file source takes every file it
#: can see in one trigger, so an entire replay arrives as a single enormous batch and
#: the measured event-to-alert latency becomes "how long one big batch took" -- 30
#: seconds, in the first run of this harness, for events that were emitted 30 seconds
#: apart. Four files a trigger keeps batches small enough that latency measures the
#: pipeline rather than the batching. Raising it trades latency for throughput, which
#: is a real dial and the reason it is exposed rather than hard-coded.
MAX_FILES_PER_TRIGGER = 4


def _clean(*directories: Path) -> None:
    for directory in directories:
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)


def _wait_for_stream(spark, timeout: float = 60.0) -> bool:
    """Block until the streaming query is actually running.

    Without this the producer can write its first ticks before the job has started,
    and those files then sit on disk until the stream comes up -- inflating their
    measured latency by however long Spark took to boot. That is a real number about
    a situation nobody cares about.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if spark.streams.active:
            return True
        time.sleep(0.2)
    return False


def measure_step(
    events: list[dict],
    duration: float,
    spark,
    step: int,
    max_files_per_trigger: int | None = None,
    tick_seconds: float = stream_producer.TICK_SECONDS,
    drain_seconds: float = DRAIN_SECONDS,
) -> dict:
    """One offered rate: replay the same events over `duration` seconds while the job runs."""
    trips_dir = config.STREAM_TRIPS_DIR
    alerts_dir = config.STREAM_ALERTS_DIR
    checkpoint_dir = config.STREAM_CHECKPOINT_DIR / f"step_{step}"
    _clean(trips_dir, alerts_dir)
    if checkpoint_dir.exists():
        shutil.rmtree(checkpoint_dir)

    job_stats: dict[str, stream_job.JobStats] = {}

    def _run_job() -> None:
        job_stats["stats"] = stream_job.run(
            source_dir=trips_dir,
            alerts_dir=alerts_dir,
            checkpoint_dir=checkpoint_dir,
            once=False,
            duration_seconds=duration + drain_seconds,
            max_files_per_trigger=max_files_per_trigger,
            spark=spark,
        )

    thread = threading.Thread(target=_run_job, name=f"stream-job-step-{step}", daemon=True)
    thread.start()
    if not _wait_for_stream(spark):
        raise RuntimeError("the streaming query never became active")

    compressed = stream_producer.compress_schedule(events, duration)
    sink = stream_producer.FileSink(trips_dir)
    replay = stream_producer.replay(compressed, sink, "file", tick_seconds)
    thread.join(timeout=duration + drain_seconds + 60)

    stats = job_stats.get("stats")
    if stats is None:
        raise RuntimeError("the streaming job thread produced no stats")

    return {
        "offered_duration_s": duration,
        "events_offered": len(compressed),
        "offered_rate_eps": round(len(compressed) / duration, 1),
        "produced_rate_eps": round(replay.events_per_second, 1),
        "producer_wall_s": round(replay.wall_seconds, 2),
        "tick_files": len(replay.files_written),
        "events_processed": stats.events,
        "queries_scored": stats.queries,
        "facts_dropped": stats.facts_dropped,
        "alerts": stats.alerts,
        "batches": stats.batches,
        "job_wall_s": round(stats.wall_seconds, 2),
        "processed_rate_eps": round(stats.events_per_second, 1),
        "scoring_seconds": round(stats.scoring_seconds, 2),
        "scoring_rate_eps": round(stats.scoring_rate_eps, 1),
        "slowest_batch_s": round(max(stats.batch_seconds), 2) if stats.batch_seconds else None,
        "stage_seconds": stats.stage_breakdown(),
        # The whole point of the step: did the job drain everything the producer
        # offered, inside the replay plus the drain window? A partial count is not a
        # failure to record politely -- it is the capacity answer.
        "kept_up": stats.events >= replay.events,
        "latency_p50_ms": stats.latency_percentile(50),
        "latency_p95_ms": stats.latency_percentile(95),
        "latency_max_ms": max(stats.latencies_ms) if stats.latencies_ms else None,
        "latency_samples": len(stats.latencies_ms),
    }


def run(
    legs: int | None = 2000,
    durations: tuple[float, ...] = (20.0, 10.0, 5.0),
    max_files_per_trigger: int | None = MAX_FILES_PER_TRIGGER,
    tick_seconds: float = stream_producer.TICK_SECONDS,
    drain_seconds: float = DRAIN_SECONDS,
    out_path: Path = THROUGHPUT_JSON,
) -> dict:
    """Load one set of legs, replay it at each offered rate, and report every step."""
    pdf = stream_producer.load_legs(legs)          # Spark starts and stops in here
    events = stream_producer.build_events(pdf)
    log.info("%s legs -> %s events; offering %d rate(s)", f"{len(pdf):,}", f"{len(events):,}", len(durations))

    spark = get_spark("stream-throughput")
    steps = []
    try:
        for index, duration in enumerate(durations):
            log.info("--- step %d: %s events over %.0fs ---", index, f"{len(events):,}", duration)
            step = measure_step(
                events, duration, spark, index,
                max_files_per_trigger=max_files_per_trigger,
                tick_seconds=tick_seconds,
                drain_seconds=drain_seconds,
            )
            steps.append(step)
            log.info(
                "offered %.0f/s, produced %.0f/s, processed %s of %s event(s) [%s], "
                "%d alert(s), latency p50 %s ms / p95 %s ms",
                step["offered_rate_eps"], step["produced_rate_eps"],
                f"{step['events_processed']:,}", f"{step['events_offered']:,}",
                "kept up" if step["kept_up"] else "FELL BEHIND",
                step["alerts"],
                _fmt(step["latency_p50_ms"]), _fmt(step["latency_p95_ms"]),
            )
    finally:
        stop_spark(spark)

    sustained = [s for s in steps if s["kept_up"]]
    report = {
        "legs": len(pdf),
        "events": len(events),
        "tick_seconds": tick_seconds,
        "max_files_per_trigger": max_files_per_trigger,
        "drain_seconds": drain_seconds,
        "steps": steps,
        # The headline: the highest offered rate the job actually drained. Taken from
        # the produced rate, not the requested one, because the requested rate is an
        # intention and the produced rate is what the job was really handed.
        "sustained_eps": max((s["produced_rate_eps"] for s in sustained), default=None),
        "sustained_latency_p95_ms": next(
            (s["latency_p95_ms"] for s in sorted(sustained, key=lambda s: -s["produced_rate_eps"])),
            None,
        ),
        # The capacity figure that does not depend on how the offered load was paced:
        # events divided by the seconds the job was actually inside `process_batch`.
        "scoring_rate_eps": max((s["scoring_rate_eps"] for s in steps), default=None),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("sustained %s events/sec -> %s", _fmt(report["sustained_eps"]), out_path)
    return report


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legs", type=int, default=2000, help="legs to replay (2 events each)")
    parser.add_argument("--durations", type=str, default="20,10,5",
                        help="comma-separated wall-clock seconds per step; shorter means a higher offered rate")
    parser.add_argument("--tick", type=float, default=stream_producer.TICK_SECONDS)
    parser.add_argument("--max-files-per-trigger", type=int, default=MAX_FILES_PER_TRIGGER,
                        help="tick files per micro-batch; smaller means lower latency, larger means fewer batches")
    parser.add_argument("--drain", type=float, default=DRAIN_SECONDS,
                        help="seconds the job keeps running after the replay stops, to finish its backlog")
    parser.add_argument("--legs-all", action="store_true", help="replay every leg in features_v1")
    parser.add_argument("--out", type=Path, default=THROUGHPUT_JSON)
    args = parser.parse_args()

    if not config.FEATURES_V1.exists():
        log.error("Missing %s -- run `python -m src.pipeline.features` first.", config.FEATURES_V1)
        return 1
    if not (config.MODELS_DIR / "champion").exists():
        log.error("No champion model -- run `python -m src.automation.retrain` first.")
        return 1

    durations = tuple(float(d) for d in args.durations.split(",") if d.strip())
    run(
        legs=None if args.legs_all else args.legs,
        durations=durations,
        max_files_per_trigger=args.max_files_per_trigger,
        tick_seconds=args.tick,
        drain_seconds=args.drain,
        out_path=args.out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
