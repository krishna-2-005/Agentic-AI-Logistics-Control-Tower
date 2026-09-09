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

## D3-D4 · The streaming job, and why it is batch code in a `foreachBatch`

`src/streaming/job.py` reads the tick files as a Spark file source, joins each query
event to a broadcast history snapshot, applies the champion `PipelineModel`, and writes
the rows it flags to `data/stream/alerts/`.

```bash
python -m src.streaming.job --once --clean        # drain what the producer left
python -m src.streaming.job --duration 90         # run beside a live replay
```

Every micro-batch is handed to ordinary batch code — including
`src.ml.baselines.prepare_model_features`, the *same function* Weeks 3 and 4 call, via a
pandas round trip. That is deliberate. Lahari's D1-D2 test proves identical rows produce
identical predictions across the two paths; that guarantee means something only if the
two paths are the same code rather than two implementations that resemble each other.
D-023's cold-start policy and D-019's `is_ftl` encoding are policy, not arithmetic, and
a second copy of a policy is a second thing to keep in step — P-23 already charged this
project once for exactly that.

**The round trip costs 0.08 seconds in a 71-second full-replay run.** 0.1%. I expected
to have to defend it; the harness measured it instead (§D5).

### The history is a snapshot, and fact events are dropped

One window function over `features_v1` per key at start-up — 2,783 corridors, 1,508
source hubs, 1,481 destination hubs — cached and broadcast. A leg *finishing* mid-replay
does not update what the next query is scored against, so **fact events are counted and
discarded**: 26,369 of them in the full run, reported in the log and in the run summary
rather than silently vanishing. The plan asks for "join broadcast features" and this is
that; making history live needs stateful aggregation with as-of semantics, which is Week
6+ work. `src.ml.predict` takes the identical simplification for the what-if page and
says so in the same terms. Full reasoning: D-037.

### Alerts have a written contract

`docs/schemas/alert.schema.json`. Krishna's panel (D3-D4) and bot (D5) read that
directory and nothing else of this module, so the shape is written down for the same
reason D-031 wrote the event shape down. `tests/test_stream_job.py` pins the Python and
the schema to each other in both directions — a contract living in two files drifts, and
a field that drifts silently arrives as a column of nulls rather than as an error.

Each alert carries the prediction, the threshold that produced it, and the three
`is_cold` flags, because "we have never seen this corridor" and "this corridor is
normally on time" are different claims that a zeroed history makes look identical
(D-023). One JSON-lines file per micro-batch, named by `batch_id`, staged and renamed:
`foreachBatch` is at-least-once, so a replayed batch overwrites its own file instead of
appending a second copy of every alert.

## D5 · What the full replay actually did

`src/streaming/throughput.py` runs the real producer and the real job against each
other in one process and reports what happened.

```bash
python -m src.streaming.throughput --legs-all --durations 60 \
    --max-files-per-trigger 1000 --drain 300
```

**The whole dataset, replayed end to end:**

| | |
|---|---|
| Legs replayed | **26,369** (the complete `features_v1`) |
| Events | **52,738** query + fact |
| Producer wall clock | 59.5s → **886 events/sec**, ~38,000× time compression |
| Events processed | **52,738 of 52,738** — nothing dropped |
| Queries scored / facts dropped | 26,369 / 26,369 |
| Alerts written | **17,317** |
| Micro-batches | 4 |
| **Saturated scoring rate** | **740 events/sec** |
| **Event-to-alert latency** | **p50 28.9s, p95 38.0s, max 40.5s** |

### Three numbers, three denominators

"Events per second" is easy to report meaninglessly. Offer 100 events/sec to a pipeline
that can do 740 and you measure 100 — the *producer's* pacing wearing the job's name.
The first version of this harness did exactly that and reported figures between 98 and
179 that moved with the offered load and said nothing about capacity. So each number
here names its denominator: **produced rate** is over the producer's own wall clock,
**saturated scoring rate** is over the seconds actually spent inside `process_batch`,
and **latency** is tick-file modification time to alert write — including file discovery
and the trigger interval, because a consumer waiting for an alert waits for those too.
D-038 has the argument.

### Where the time goes

| stage | seconds | share |
|---|---|---|
| `score` (`createDataFrame` + `transform` + `collect`) | 61.55 | **86%** |
| `join_and_collect` (broadcast join + `toPandas`) | 4.58 | 6% |
| `count` | 4.14 | 6% |
| `write` | 0.30 | 0.4% |
| `prepare_features` (the pandas round trip) | **0.08** | **0.1%** |

This breakdown is why the measurement exists rather than just a headline. "14 seconds
per micro-batch" is a complaint; "13.2 of the 14 are inside the model transform and its
collect, and 0.06 is the round trip I was worried about" is a finding — and it settles
D-037's one open design question with a number instead of an opinion.

### The counter-intuitive result: fewer, larger batches

A micro-batch costs **~14 seconds almost regardless of what is in it** — the same ~14s
whether it holds 1,618 events or 4,000. The cost is fixed, not per-event. So throughput
scales with batch size, and this pipeline gets *faster* with fewer, larger batches,
which is the opposite of the usual latency instinct.

Measured on 2,000 legs (4,000 events), the same replay at two settings of
`max_files_per_trigger`:

| offered | tick files | cap | batches | processed | scoring rate | latency p50 | drained? |
|---|---|---|---|---|---|---|---|
| 200/s | 36 | 4 | 5 | 3,808 / 4,000 | 52/s | 46.8s | **no** |
| 200/s | 36 | none | 2 | 4,000 / 4,000 | 120/s | 32.3s | yes |
| 800/s | 10 | 4 | 4 | 4,000 / 4,000 | 143/s | 28.4s | yes |
| 800/s | 10 | none | 2 | 4,000 / 4,000 | 145/s | 28.2s | yes |
| 2000/s | 4 | 4 | 2 | 4,000 / 4,000 | 287/s | 15.3s | yes |
| 2000/s | 4 | none | 2 | 4,000 / 4,000 | 286/s | 15.1s | yes |

Capping batches at 4 files to chase latency made the *slowest* offered rate the one the
job could not drain: 36 tick files at 4 per batch is 9 batches, ~126 seconds of fixed
cost for a 20-second replay. Both configurations are kept in `benchmarks/raw/` because
the trade-off is the result. It is also why the full run above uses no cap and reaches
740 events/sec against 287 on the small one — same pipeline, bigger batches.

### What the alert stream looks like against the truth

The replay carries its own outcomes, so the alerts can be scored against the fact events
beside them. Over the full 26,369 legs:

| | |
|---|---|
| Actually delayed (D-003, 2.00×) | 13,104 — **49.7%** |
| Alerted | 17,317 — 65.7% |
| Precision / recall | **0.686 / 0.907** |
| Accuracy | 0.748, against a **50.4% majority-class rate** (D-003 rule 3) |
| Alerts on a cold corridor | 552 (3.2%) |

**This is not an accuracy claim and must not be quoted as one.** The broadcast snapshot
holds each key's *latest* known history — from the end of the observation window — and
the replay then scores legs from the beginning of that window against it. In the
intended direction (score what happens next against what is known now) that is correct;
replayed backwards over history it hands the model a snapshot from after the leg it is
scoring. What the table describes is how the alert sink behaves, and it is useful for
that: a panel receiving two alerts for every three legs is a design input for Krishna.
Lahari's Week 4 test-set numbers remain the project's honest accuracy result.

## Four problems, and the one that mattered

- **P-42 — the stream was about to publish a label from the threshold the project
  rejected in Week 2.** Scoring the alerts against the fact events gave precision 0.981,
  and the tell was the base rate beside it: 93.6% of legs "delayed" against D-003's
  49.7%. 93.6% is *exactly* D-003's table entry for the rejected `T = 1.25`.
  `reconstruct.py` writes `is_delayed` using `DELAY_THRESHOLD` as it stood when the cache
  was built; D-003 moved it to 2.00 and the frozen caches were never rebuilt. 11,583 of
  26,369 legs — 43.9% — carry a label contradicting the decided threshold. **It survived
  eight weeks because a downstream correction was working perfectly:**
  `add_delay_label` recomputes before every fit, so every Week 3-4 model is fine and the
  stale column was overwritten on the only path that read it. `fact_event` was the first
  consumer to put it on the wire. Fixed by recomputing, and by dropping the column from
  the loaded set entirely — not loading it beats remembering not to use it. Corrected,
  the same comparison reads precision 0.686, recall 0.907.
- **P-43 — a micro-batch that never finished was counted as finished.** Identical events
  reported 661 alerts in one run and 1,347 in another while both claimed 4,000 events
  processed and both said `kept_up`. The counters were incremented at the top of
  `process_batch`, so a batch cut off mid-flight had already booked its work. Visible
  only because a number that should have been constant was not.
- **P-44 — the drain window was one batch long**, so whether a step "kept up" turned on
  where a 20-second timer fell relative to a 14-second batch. Now 60s, chosen from the
  measured batch duration.
- **P-45 — the event schema declared `created_dayofweek` as 0-6**, Python's convention,
  while Stage 4 emits Spark's 1-7. 3,607 Saturday legs fail validation against the
  contract meant to describe them. D1-D2 missed it because `--limit 300` takes a prefix
  of the chronological order — all 300 legs came from one Wednesday morning, so every
  event validated. **This is P-39's trap in a third place**, and it means P-39's claim
  that the trap was caught "before anything could fall into it" was too strong: this was
  one thing, and `src.ml.predict` on the what-if page is another, still live.

`--limit` taking a prefix is worth its own note even without a bug attached: the first
300 legs are 157 trips created inside 3.9 hours of one night, and 96% of them ran over
2× plan against a 49.7% base rate. A prefix of a replay is the right thing for a
*replay*, and the wrong thing to compute a rate from.

## Tests

`tests/test_stream_job.py` — 19 tests, no Spark and no champion model. The arithmetic
behind every D5 number, the alert writer's idempotency and atomic rename, and, mostly,
that `EVENT_SCHEMA` and the alert records still match the two JSON Schemas in both
directions. `tests/test_stream_schema.py` gained four more, pinning the recomputed delay
label — with a fixture that deliberately carries the stale value, because a fixture
holding the right answer cannot tell "recomputes" from "copies".

## What is still not in this file

- The Kafka sink remains written, import-checked and **never run against a live broker**
  (D-035). Nothing this week changed that; there is still no Docker on this machine.
- History is a static snapshot. Live, fact-driven history is Week 6+ (D-037).
- The stale `is_delayed` column is still in the parquet. Both consumers that matter now
  recompute it, and a rebuild would unfreeze a cache D-016 froze on purpose (P-42).
