"""Structured Streaming scoring job (execution plan W5 D3-D4) -- the stream's right-hand end.

    python -m src.streaming.job --once              # drain whatever the producer left
    python -m src.streaming.job --duration 90       # run alongside a live replay
    python -m src.streaming.job --once --clean      # fresh checkpoint and alert dir

Reads the trip-replay event stream, joins each query event to a **broadcast snapshot**
of the as-of history the champion model was trained on, applies that `PipelineModel`,
and writes the rows it flags as predicted delays to `STREAM_ALERTS_DIR` in the shape
`docs/schemas/alert.schema.json` fixes -- Krishna's live alerts panel (D3-D4) and
alert bot (D5) read that directory and nothing else of this module.

Source: a file source, not Kafka
--------------------------------
There is no broker on this machine (no Docker), so this reads the JSON-lines tick
files `producer.py`'s `FileSink` writes -- the execution plan's own 3-day-rule
fallback, taken at D1-D2 and still in force here. D-035 says which path has actually
been run rather than letting the code imply both have. Switching to Kafka is a
different `readStream` format and the same everything-else, because the event shape
on either side of that swap is the one schema D-031 already fixed.

Why `foreachBatch` rather than a pure streaming DataFrame
---------------------------------------------------------
Each micro-batch is handed to ordinary batch code: the same broadcast join, the same
`PipelineModel.transform`, the same D-003 threshold comparison a batch script would
run. That is not a workaround for something streaming cannot do -- it is what makes
Lahari's stream-equals-batch guarantee (D1-D2) mean anything past the event encoding.
If the streaming path re-implemented scoring in streaming-native operators, "identical
rows produce identical predictions" would be a claim about two code paths that merely
look alike. Here it is a claim about one.

What this job deliberately does not do
--------------------------------------
**Fact events are counted and dropped.** The history joined here is a static snapshot
taken once at start-up, so a leg finishing mid-replay does not update the history the
next query is scored against. That is exactly what the plan asks for at this stage
("join broadcast features"), and it is the same simplification `src.ml.predict` already
documents for the what-if page -- but it is a simplification, and a streaming layer
that silently let facts vanish without saying so would be misrepresenting itself. The
count appears in the log and in the run summary. Making history live means stateful
aggregation with as-of semantics, which is a Week 6+ piece of work, not a flag.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pyspark.ml import PipelineModel
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

from src.common import config
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark
from src.ml.baselines import (
    FEATURES,
    HISTORY_PREFIXES,
    HISTORY_STATS,
    prepare_model_features,
)

log = get_logger("streaming.job")

#: A streaming file source cannot infer a schema -- it would have to read the whole
#: directory to guess one, which is the opposite of streaming. Spelled out here from
#: `docs/schemas/stream_event.schema.json`, the only place the event shape is decided.
EVENT_SCHEMA = StructType([
    StructField("event_id", StringType()),
    StructField("kind", StringType()),
    StructField("event_time", StringType()),
    StructField("corridor_id", StringType()),
    StructField("source_center", StringType()),
    StructField("destination_center", StringType()),
    StructField("trip_uuid", StringType()),
    StructField("leg_id", StringType()),
    # query-only
    StructField("route_type", StringType()),
    StructField("planned_min", DoubleType()),
    StructField("planned_km", DoubleType()),
    StructField("created_hour", IntegerType()),
    StructField("created_dayofweek", IntegerType()),
    StructField("created_is_weekend", IntegerType()),
    # fact-only
    StructField("gap_min", DoubleType()),
    StructField("log_gap_ratio", DoubleType()),
    StructField("is_delayed", IntegerType()),
])

#: Which `features_v1` column each history prefix's snapshot keys on. Same mapping
#: `src.ml.predict.KEY_COLUMN` uses -- one lookup rule, two callers.
KEY_COLUMN = {"corr": "corridor_id", "src": "source_center", "dst": "destination_center"}

ALERT_COLUMNS = [
    "alert_id", "leg_id", "trip_uuid", "corridor_id", "source_center", "destination_center",
    "event_time", "route_type", "planned_min", "planned_km",
    "predicted_gap_min", "predicted_total_min", "threshold_gap_min", "delay_threshold",
    "corr_is_cold", "src_is_cold", "dst_is_cold",
    "emit_time", "alert_time", "latency_ms", "batch_id",
]

#: Event columns carried through scoring so they can ride onto the alert. Kept apart
#: from FEATURES because the model must never see them: `leg_id` and `event_time` would
#: be leakage dressed as identifiers.
CARRIED = [
    "event_id", "leg_id", "trip_uuid", "corridor_id", "source_center", "destination_center",
    "event_time", "route_type",
    "corr_is_cold", "src_is_cold", "dst_is_cold", "emit_epoch_ms",
]

#: What the scoring frame actually selects. `planned_min` and `planned_km` are both a
#: model feature and an alert field, so the two lists overlap; deduplicated here (the
#: same `dict.fromkeys` idiom `src.ml.models.SPARK_COLUMNS` uses) because selecting a
#: name twice is not a duplicate column to Spark, it is an ambiguous one.
SCORING_COLUMNS = list(dict.fromkeys(FEATURES + CARRIED))


@dataclass
class JobStats:
    """What a run actually scored. Returned rather than only logged, so the D5
    throughput harness asserts on numbers instead of scraping log lines."""

    batches: int = 0
    events: int = 0
    queries: int = 0
    facts_dropped: int = 0
    alerts: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    #: Seconds spent inside `process_batch` per micro-batch. Wall time includes the
    #: stream sitting idle waiting for files, which says more about the producer's
    #: pacing than the job's capacity; this is the time the job was actually working.
    batch_seconds: list[float] = field(default_factory=list)
    #: Seconds per named stage inside `process_batch`, summed over every batch. A
    #: single 14-second batch figure says the pipeline is slow without saying which
    #: part is, and the pandas round trip in particular is a deliberate cost that
    #: deserves to be measured rather than assumed small.
    stage_seconds: dict[str, float] = field(default_factory=dict)
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def wall_seconds(self) -> float:
        return self.finished_at - self.started_at

    @property
    def events_per_second(self) -> float:
        return self.events / self.wall_seconds if self.wall_seconds > 0 else 0.0

    @property
    def scoring_seconds(self) -> float:
        return sum(self.batch_seconds)

    @property
    def scoring_rate_eps(self) -> float:
        """Events per second of time actually spent scoring -- the saturated rate.

        The number to quote as capacity. `events_per_second` divides by wall clock,
        which includes every second the stream waited for the next tick file, so at a
        gentle offered rate it reports the producer's pacing wearing the job's name.
        """
        return self.events / self.scoring_seconds if self.scoring_seconds > 0 else 0.0

    def latency_percentile(self, pct: float) -> float | None:
        """Nearest-rank percentile of event-to-alert latency, or None if no alerts.

        Nearest-rank rather than an interpolated quantile: with a few hundred samples
        the interpolation invents a value between two real measurements, and a latency
        figure that no request actually experienced is a worse number to publish than
        one that did.
        """
        if not self.latencies_ms:
            return None
        ordered = sorted(self.latencies_ms)
        rank = max(1, min(len(ordered), round(pct / 100.0 * len(ordered))))
        return ordered[rank - 1]

    def stage_breakdown(self) -> dict[str, float]:
        return {name: round(seconds, 2) for name, seconds in sorted(self.stage_seconds.items())}

    def summary(self) -> dict:
        return {
            "batches": self.batches,
            "events": self.events,
            "queries": self.queries,
            "facts_dropped": self.facts_dropped,
            "alerts": self.alerts,
            "wall_seconds": round(self.wall_seconds, 2),
            "events_per_second": round(self.events_per_second, 1),
            "scoring_seconds": round(self.scoring_seconds, 2),
            "scoring_rate_eps": round(self.scoring_rate_eps, 1),
            "latency_p50_ms": self.latency_percentile(50),
            "latency_p95_ms": self.latency_percentile(95),
            "latency_max_ms": max(self.latencies_ms) if self.latencies_ms else None,
            "stage_seconds": self.stage_breakdown(),
        }


def latest_history(spark: SparkSession, prefix: str) -> DataFrame:
    """The most recent as-of history snapshot per key, one row per key.

    `features_v1` carries, on every leg, the `{prefix}_*` history **as of that leg**
    (D-020). The newest leg for a key therefore already holds that key's latest known
    snapshot -- so this is a window function over the frozen cache, not a second
    recomputation of Stage 4's history. `src.ml.predict._latest_history` does the same
    lookup one key at a time for a single form submission; this does it for every key
    at once because a stream cannot afford a Spark query per event.
    """
    key = KEY_COLUMN[prefix]
    # `{prefix}_is_cold` is deliberately not read here: it is not a `features_v1`
    # column at all. D-023's indicator is derived from `{prefix}_n_prior` by
    # `prepare_model_features`, and deriving it a second time in Spark would be two
    # implementations of one policy -- exactly the trap P-23 already sprang once.
    cols = [f"{prefix}_{stat}" for stat in HISTORY_STATS]
    window = Window.partitionBy(key).orderBy(F.col("trip_creation_time").desc())
    return (
        spark.read.parquet(str(config.FEATURES_V1))
        .select(key, "trip_creation_time", *cols)
        .withColumn("_rank", F.row_number().over(window))
        .filter(F.col("_rank") == 1)
        .drop("_rank", "trip_creation_time")
    )


def load_history(spark: SparkSession) -> dict[str, DataFrame]:
    """One cached snapshot per prefix, materialised before the stream starts.

    Cached deliberately: a broadcast join re-reads the small side for every micro-batch
    otherwise, and re-reading three parquet windows fifty times over a sixty-second
    replay is latency the measurement at D5 would then report as if it were the model's.
    """
    snapshots = {}
    for prefix in HISTORY_PREFIXES:
        snapshot = latest_history(spark, prefix).cache()
        rows = snapshot.count()  # forces the cache before the first micro-batch
        log.info("%s history snapshot: %s keys", prefix, f"{rows:,}")
        snapshots[prefix] = snapshot
    return snapshots


def enrich(queries: DataFrame, history: dict[str, DataFrame]) -> DataFrame:
    """Broadcast-join a batch of query events to the history snapshot and build FEATURES.

    Cold keys -- a corridor the snapshot has never seen -- come out of the left join as
    nulls and are filled with zeros and `is_cold = 1`, which is the same answer
    `src.ml.predict` produces for the same situation and the same rule D-023 fixed for
    the batch features. A prediction made off zeroed history is still a prediction; the
    `is_cold` flag travels onto the alert so a consumer can say the history was empty
    rather than implying the corridor is reliably on time.
    """
    enriched = queries
    for prefix in HISTORY_PREFIXES:
        enriched = enriched.join(F.broadcast(history[prefix]), on=KEY_COLUMN[prefix], how="left")

    # The only fill this function performs, and the only one it is entitled to: a key
    # the snapshot has never seen produces a null `n_prior` from the left join, and a
    # key with no rows has had, precisely, zero prior legs. Every other null belongs to
    # D-023's cold-start policy, which `prepare_model_features` owns -- including the
    # assertion that no null appears outside the cases that policy documents. Filling
    # them here would silence that assertion on the streaming path only.
    return enriched.fillna({f"{p}_n_prior": 0 for p in HISTORY_PREFIXES})


def flag_alerts(scored: DataFrame, batch_id: int) -> DataFrame:
    """Keep only the legs the model calls delayed, in the alert schema's shape.

    The rule is D-003's, taken from `config.DELAY_THRESHOLD` rather than restated:
    `predicted_gap_min > (DELAY_THRESHOLD - 1) * planned_min`, identical to what
    `src.ml.predict.build_result` computes for the what-if page. Both the threshold in
    force and the gap it implies ride along on the row, so an alert read a week later
    still says what it was measured against.
    """
    threshold = F.lit(config.DELAY_THRESHOLD - 1.0) * F.col("planned_min")
    return (
        scored
        .withColumn("predicted_gap_min", F.round(F.col("prediction"), 1))
        .withColumn("threshold_gap_min", F.round(threshold, 1))
        .filter(F.col("prediction") > threshold)
        .withColumn("predicted_total_min", F.round(F.col("planned_min") + F.col("prediction"), 1))
        .withColumn("delay_threshold", F.lit(float(config.DELAY_THRESHOLD)))
        .withColumn("alert_id", F.col("event_id"))
        .withColumn("batch_id", F.lit(int(batch_id)))
    )


class AlertWriter:
    """One JSON-lines file per micro-batch, written atomically and idempotently.

    Named by `batch_id`, so a batch replayed after a driver restart overwrites its own
    file instead of appending a second copy of every alert -- the at-least-once
    delivery `foreachBatch` gives you, turned into effectively-once output by making
    the write idempotent, which is the documented way to do it rather than a trick.
    Staged under a dot-prefixed temporary name and renamed, for the same reason the
    producer's `FileSink` does: a reader that lists this directory must never catch a
    half-written file (and Krishna's panel polls exactly this directory).
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.written: list[Path] = []

    def write(self, rows: list[dict], batch_id: int) -> Path | None:
        if not rows:
            return None
        final = self.directory / f"alerts_{batch_id:06d}.jsonl"
        staging = self.directory / f".alerts_{batch_id:06d}.jsonl.tmp"
        payload = "\n".join(json.dumps(row) for row in rows) + "\n"
        staging.write_text(payload, encoding="utf-8")
        staging.replace(final)
        self.written.append(final)
        return final


def _to_iso(epoch_ms: float | None) -> str | None:
    """Epoch milliseconds to a timezone-aware ISO string in this machine's zone."""
    if epoch_ms is None:
        return None
    return datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc).astimezone().isoformat()


def process_batch(
    batch_df: DataFrame,
    batch_id: int,
    model: PipelineModel,
    history: dict[str, DataFrame],
    writer: AlertWriter,
    stats: JobStats,
) -> None:
    """Score one micro-batch and write whatever it flags. Ordinary batch code."""
    started = time.monotonic()
    # One pass for both counts. Two separate `.count()` calls are two extra Spark jobs
    # over the same batch, and this function is the thing the D5 harness times.
    with _stage(stats, "count"):
        by_kind = {row["kind"]: row["count"] for row in batch_df.groupBy("kind").count().collect()}
    rows = sum(by_kind.values())
    if rows == 0:
        return
    n_queries = by_kind.get("query", 0)

    if n_queries == 0:
        log.info("batch %d: %d event(s), all facts -- nothing to score", batch_id, rows)
        _record(stats, started, rows, 0, 0)
        return

    queries = batch_df.filter(F.col("kind") == "query")

    # Through pandas and back, so the streaming path calls the *same*
    # `prepare_model_features` the batch path does rather than a Spark translation of
    # it. `is_ftl` and the three `is_cold` indicators are D-023 and D-019 policy, not
    # arithmetic, and a second implementation of a policy is a second thing to keep in
    # step. That round trip is a deliberate cost, so it is timed rather than waved at.
    with _stage(stats, "join_and_collect"):
        joined = enrich(queries, history).toPandas()
    with _stage(stats, "prepare_features"):
        prepared = prepare_model_features(joined)
    with _stage(stats, "score"):
        scored = model.transform(
            batch_df.sparkSession.createDataFrame(prepared[SCORING_COLUMNS])
        )
        alerts = flag_alerts(scored, batch_id)
        carried = [c for c in ALERT_COLUMNS if c not in ("emit_time", "alert_time", "latency_ms")]
        collected = alerts.select(*carried, "emit_epoch_ms").collect()

    # Both ends of the latency measurement are epoch milliseconds, so the arithmetic
    # never depends on the Spark session's timezone agreeing with the machine's. They
    # do agree here (both Asia/Kolkata), which is exactly why a subtraction of two
    # local wall-clock timestamps would have looked correct while silently carrying a
    # whole-hours error anywhere they did not.
    alert_epoch_ms = time.time() * 1000.0
    payload = []
    for row in collected:
        record = row.asDict()
        emit_epoch_ms = record.pop("emit_epoch_ms", None)
        record["emit_time"] = _to_iso(emit_epoch_ms)
        record["alert_time"] = _to_iso(alert_epoch_ms)
        latency_ms = alert_epoch_ms - emit_epoch_ms if emit_epoch_ms is not None else None
        record["latency_ms"] = round(latency_ms, 1) if latency_ms is not None else None
        if latency_ms is not None:
            stats.latencies_ms.append(latency_ms)
        payload.append({key: record.get(key) for key in ALERT_COLUMNS})

    with _stage(stats, "write"):
        writer.write(payload, batch_id)
    _record(stats, started, rows, n_queries, len(payload))
    log.info(
        "batch %d: %d event(s) -> %d query, %d fact dropped -> %d alert(s) in %.1fs",
        batch_id, rows, n_queries, rows - n_queries, len(payload), stats.batch_seconds[-1],
    )


@contextmanager
def _stage(stats: JobStats, name: str):
    """Time one named stage of a micro-batch into `stats.stage_seconds`."""
    started = time.monotonic()
    try:
        yield
    finally:
        stats.stage_seconds[name] = stats.stage_seconds.get(name, 0.0) + (time.monotonic() - started)


def _record(stats: JobStats, started: float, rows: int, queries: int, alerts: int) -> None:
    """Book a batch's work -- only once it is finished.

    Counting at the *start* of `process_batch` is the obvious place and is wrong: a
    micro-batch still in flight when the stream is stopped would then contribute its
    full event count while its alerts were never written. The throughput harness reads
    `events` to decide whether the job kept up, so that arrangement quietly reports a
    run that did not finish as a run that did -- which is exactly how it presented
    itself the first time this was measured (P-43).
    """
    stats.batches += 1
    stats.events += rows
    stats.queries += queries
    stats.facts_dropped += rows - queries
    stats.alerts += alerts
    stats.batch_seconds.append(time.monotonic() - started)


def read_stream(spark: SparkSession, source_dir: Path, max_files_per_trigger: int | None):
    """The file source, plus the file's modification time as the event's emit time.

    `_metadata.file_modification_time` is when the producer released the tick file that
    carried this event -- the earliest instant a consumer could possibly have seen it.
    Measuring event-to-alert latency from the producer's *scheduled* offset instead
    would credit the pipeline for the replay's own compression, which would be a
    flattering number about nothing.
    """
    reader = (
        spark.readStream.schema(EVENT_SCHEMA)
        .option("maxFilesPerTrigger", max_files_per_trigger or 1000)
        .json(str(source_dir))
    )
    return reader.select(
        "*",
        (F.col("_metadata.file_modification_time").cast("double") * 1000).alias("emit_epoch_ms"),
    )


def run(
    source_dir: Path = config.STREAM_TRIPS_DIR,
    alerts_dir: Path = config.STREAM_ALERTS_DIR,
    checkpoint_dir: Path = config.STREAM_CHECKPOINT_DIR,
    once: bool = True,
    duration_seconds: float = 60.0,
    max_files_per_trigger: int | None = None,
    spark: SparkSession | None = None,
) -> JobStats:
    """Run the scoring stream and return what it did."""
    champion_path = config.MODELS_DIR / "champion"
    if not champion_path.exists():
        raise FileNotFoundError(
            f"No champion model at {champion_path} -- run `python -m src.automation.retrain` first."
        )
    source_dir.mkdir(parents=True, exist_ok=True)

    owns_spark = spark is None
    spark = spark or get_spark("stream-job")
    stats = JobStats()
    try:
        model = PipelineModel.load(str(champion_path))
        history = load_history(spark)
        writer = AlertWriter(alerts_dir)

        stream = read_stream(spark, source_dir, max_files_per_trigger)
        writer_builder = (
            stream.writeStream
            .foreachBatch(lambda df, bid: process_batch(df, bid, model, history, writer, stats))
            .option("checkpointLocation", str(checkpoint_dir))
        )
        # The clock starts here, not at the top of the function: loading a
        # PipelineModel and materialising three history snapshots is start-up, and
        # charging ~25s of it to an events/sec figure would understate the pipeline by
        # a factor that grows as the measurement gets shorter.
        stats.started_at = time.monotonic()
        # `availableNow` drains what is already on disk and stops, which is what a
        # reproducible measurement wants; `processingTime` keeps polling, which is what
        # running beside a live producer wants. Same pipeline, different trigger.
        if once:
            query = writer_builder.trigger(availableNow=True).start()
            query.awaitTermination()
        else:
            query = writer_builder.trigger(processingTime="2 seconds").start()
            query.awaitTermination(timeout=duration_seconds)
            query.stop()
    finally:
        stats.finished_at = time.monotonic()
        if owns_spark:
            stop_spark(spark)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Score the trip-replay stream and emit delay alerts")
    parser.add_argument("--once", action="store_true",
                        help="process everything already in the source directory, then stop")
    parser.add_argument("--duration", type=float, default=60.0,
                        help="wall-clock seconds to keep the stream running (ignored with --once)")
    parser.add_argument("--source", type=Path, default=config.STREAM_TRIPS_DIR)
    parser.add_argument("--alerts", type=Path, default=config.STREAM_ALERTS_DIR)
    parser.add_argument("--checkpoint", type=Path, default=config.STREAM_CHECKPOINT_DIR)
    parser.add_argument("--max-files-per-trigger", type=int, default=None,
                        help="cap the files in one micro-batch; smaller means more, smaller batches")
    parser.add_argument("--clean", action="store_true",
                        help="delete the checkpoint and existing alerts before starting")
    args = parser.parse_args()

    if args.clean:
        for path in (args.checkpoint, args.alerts):
            if path.exists():
                shutil.rmtree(path)
                log.info("removed %s", path)

    if not config.FEATURES_V1.exists():
        log.error("Missing %s -- run `python -m src.pipeline.features` first.", config.FEATURES_V1)
        return 1

    stats = run(
        source_dir=args.source,
        alerts_dir=args.alerts,
        checkpoint_dir=args.checkpoint,
        once=args.once,
        duration_seconds=args.duration,
        max_files_per_trigger=args.max_files_per_trigger,
    )
    summary = stats.summary()
    log.info(
        "%d batch(es), %s event(s) -> %s query, %s fact dropped -> %s alert(s) in %.1fs",
        summary["batches"], f"{summary['events']:,}", f"{summary['queries']:,}",
        f"{summary['facts_dropped']:,}", f"{summary['alerts']:,}", summary["wall_seconds"],
    )
    if summary["latency_p50_ms"] is not None:
        log.info(
            "event-to-alert latency: p50 %.0f ms, p95 %.0f ms, max %.0f ms",
            summary["latency_p50_ms"], summary["latency_p95_ms"], summary["latency_max_ms"],
        )
    else:
        log.info("no alerts, so no event-to-alert latency to report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
