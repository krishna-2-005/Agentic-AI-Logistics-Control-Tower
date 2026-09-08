# W5 · Mounika — trip-replay producer, streaming job, throughput harness

Week 5 is my hard week (execution plan §1). D1-D2 is the producer — the stream's
left-hand end; the Structured Streaming job (D3-D4) and the throughput/latency
harness (D5) land in later sections of this same file, per GIT_RULES §2.

## What I built (D1-D2)

**`src/streaming/producer.py`.** Reads the frozen `features_v1` cache, turns every
leg into the query + fact event pair the Week 4 schema already defines (D-031), and
replays them **time-compressed** — the dataset's real ~26-day window emitted over N
wall-clock seconds.

```bash
python -m src.streaming.producer --duration 60                   # whole window in 60s
python -m src.streaming.producer --limit 300 --duration 6 --validate --clean
python -m src.streaming.producer --sink kafka                    # when a broker exists
```

Writes JSON-lines batches to `data/stream/trips/` (gitignored, like every generated
artefact under `data/`). The committed evidence is the five-leg sample Week 4 already
put in `demo/sample_events/`, not the replay output.

## Nothing here re-invents the event

`src.streaming.schema` owns `query_event` / `fact_event` / `validate_event`, and this
module calls them. That was the whole point of writing the schema in Week 4 D5 before
a producer existed to consume it — D-031 argued the streaming layer should answer to
the same fact/query contract Stage 4's batch join already proved leak-free (D-020),
and the way to keep that true is one shared source, not two that agree today.

`--validate` runs every event through the JSON Schema before any of them are emitted.
On the smoke run below, all 600 validated.

## D1-D2 · No Docker, so the file sink is what actually runs

`docker --version` is not a command on this machine, so there is no broker. The
execution plan wrote its own escape hatch for exactly this — *"3-day rule: if Kafka
fights the environment, switch to file-streaming fallback"* — and `README.md`'s
prerequisite table has listed Docker as Week-5-**optional** since Week 1.

Both sinks are written behind one `emit()`:

| Sink | What it does | Run here? |
|---|---|---|
| `file` | one JSON-lines file per tick into `STREAM_TRIPS_DIR`, for Spark's file source | **yes** |
| `kafka` | real `KafkaProducer` onto `KAFKA_TOPIC_TRIPS`, keyed by `corridor_id` | written, import-checked, **never run against a live broker here** |

Switching is `--sink kafka` or `STREAM_SOURCE` in `.env` — one flag, not a rewrite.
D-035 has the full reasoning, including why the Kafka path is worth shipping
unexercised rather than leaving unwritten, and why it keys on `corridor_id`.

**The file sink writes then renames.** Spark's file source lists a directory and will
happily read a file that is still being written; a half-written final line surfaces at
the consumer as a malformed record, a long way from its cause. Every batch goes to
`.tick_NNNNNN.jsonl.tmp` and is renamed into place, so a file the job can see is a
file that is already complete. Verified on the smoke run: zero `.tmp` files left
behind.

## D1-D2 · Time compression is proportional, not uniform

Each event's real `event_time` maps linearly onto the replay window, so a quiet night
in the data stays a quiet stretch and a busy morning still bursts. Spreading events
evenly across the window would have produced a smoother — and better-looking —
throughput number than the data actually supports. Same instinct D-003 applies to
reporting a majority-class baseline beside an accuracy, applied to a rate.

Events are flushed in **ticks** (default 0.5s) rather than slept over one at a time:
the full window is ~880 events/sec, and a `time.sleep()` per event would spend more
time in timer overhead than in the replay. One file per tick is also exactly what a
file source wants.

## First real run

300 legs → 600 events, replayed over 6 seconds:

| | |
|---|---|
| Events | 600 (300 query + 300 fact), all schema-validated |
| Real span replayed | 61.9 hours |
| Wall clock | 5.5s across 10 ticks |
| Sustained rate | **109 events/sec** |
| Time compression | **~40,000×** |
| Files written | 10 `.jsonl`, 0 `.tmp` left behind |

These are smoke-run numbers on a deliberately small slice, not the headline. The real
sustained-throughput and event-to-alert latency figures are D5's harness, measured
against the full 52,738-event replay with the streaming job actually consuming — this
table only says the producer works.

**One real bug, caught by running it** (P-38): the first run died parsing its own
event timestamps. A query event carries microseconds; a fact event lands on a whole
second whenever the leg's duration is a whole number of minutes, which on this data it
usually is. `pd.to_datetime` inferred one format from the first element and threw on
the other. **This is P-09 from Week 1 arriving by a different route** — that time from
the publisher's file, this time from our own two event builders — and the carry from
P-09 ("one explicit format, never an inferred one") had only ever been applied to the
Spark reader. Now stated as a rule that covers both halves of the codebase: anywhere a
timestamp is parsed from a collection, name the format.

## What is not in this file yet

- **Structured Streaming job (D3-D4)** — read the source, join broadcast corridor and
  hub features, apply the champion `PipelineModel`, write a delay-flagged alert sink.
- **Throughput / latency harness (D5)** — sustained events/sec and event-to-alert
  milliseconds, on the full replay.
