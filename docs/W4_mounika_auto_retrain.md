# W4 · Mounika — auto-retraining loop, champion/challenger promotion

## What I built

**`src/automation/retrain.py`.** One command that runs the whole batch chain end to
end and ends with a decision, not just a number: clean → reconstruct → hubs →
features → train (Lahari's `src.ml.models.run()`, Random Forest + GBT) → evaluate →
champion/challenger swap.

```bash
python -m src.automation.retrain                # skip stages already cached
python -m src.automation.retrain --force-rebuild # rebuild every stage from raw
```

Writes `data/models/champion` (an MLlib `PipelineModel` directory — a straight copy of
whichever model won, not a pointer), `data/models/champion_metrics.json` (what is
champion and why), and appends one line per run to
`benchmarks/raw/w4_retrain_history.jsonl` — the committed evidence that the loop has
actually run, promoted or not, not just that the code exists.

## D1–D2 · Why a stage can be skipped, and why that is not laziness

Every cached Parquet stage (`clean_v1`, `trips_v1`, `hubs_v1`, `features_v1`) is
versioned under D-016 precisely so a schema change adds `_v2` rather than silently
repointing a version teammates' in-flight work already reads. An "auto-retraining"
script that rebuilt all four from the 145K-row raw CSV on every invocation would
quietly undo that discipline — every scheduled retrain would also be a full batch
reprocessing job, at Stage 1-4's cost, on a day nothing upstream actually changed.
`ensure_batch_pipeline()` checks each stage's output path first and only runs what is
missing; `--force-rebuild` is the explicit, named way to say the raw data changed and
Stage 1 should run again.

## D1–D2 · One subprocess per stage, not one shared Spark session

Each pipeline stage module owns and stops its own `SparkSession`
(`src.common.spark.get_spark()` / `stop_spark()`). `get_spark()` is a `getOrCreate()`
singleton per process, so importing four stage modules into one Python process and
calling their `main()`s back to back would mean reasoning about whether the second
stage's `get_spark()` call reuses the first stage's still-open session, conflicts with
its config (`app_name`, `shuffle_partitions`), or leaks it. `subprocess.run([sys.
executable, "-m", module])` per stage sidesteps the question entirely: every stage
gets the same clean JVM and clean shutdown it already gets when a person runs it by
hand from the command line, and this script differs from a person typing four commands
only in also checking whether each one is necessary first.

## D1–D2 · Champion swap is a strict MAE win, and a decline is logged the same as a win

The challenger is whichever of Random Forest/GBT `src.ml.models.run()` already named
its own winner on test MAE (D-024) — I call that entry point rather than
reimplementing Stage 6's fit/evaluate logic a second time here. Promotion requires
`challenger_mae < champion_mae` exactly: no champion on record promotes automatically
(there is nothing yet to lose to), otherwise the number has to be strictly better, not
a tie and not "close enough." A softer bar — a percentage margin, a human sign-off
step — is not what an *auto*-retraining loop is for; the risk it trades away is a slow
ratchet toward a worse model across several technically-passing swaps, which a strict
inequality cannot do.

Both outcomes write the same shape of line to `w4_retrain_history.jsonl` — a decline is
not a silent no-op, it is "the loop ran, compared honestly, and correctly did nothing,"
which is exactly the kind of negative result this project's `docs/problems.md`
convention already insists on keeping visible rather than only recording the wins.

## First real run

The loop's first run trained both models via Lahari's `run()` (3-fold CV, the same
grid `docs/W4_lahari_beat_osrm.md` reports), named **Random Forest** the challenger at
**36.89 min test MAE** (against GBT's 38.28), and promoted it — there was no champion
on record yet, so nothing had to be beaten. `data/models/champion` now holds that
`PipelineModel`; `data/models/champion_metrics.json` and
`benchmarks/raw/w4_retrain_history.jsonl` both carry the same number, so a second run
that trains a worse model has something concrete to fail to beat.

One real snag surfaced validating this before either branch had merged: replaying
Lahari's entry point locally hit a shared-file coupling (`docs/problems.md` P-32) —
resolved without re-running the ~40-minute training, by promoting from the
already-written `w4_model_report.json` directly.

## D3–D4 · A preflight check, a bounded retry, and a real test suite

Two hardening gaps D1-D2 left: a failing stage raised immediately with no retry, and
nothing checked the environment *before* handing four Spark jobs to a JVM that might
not even start.

**`preflight()` runs before the first subprocess, not after it fails.** It checks the
one thing every one of the four stages needs and none of them checks for itself:
`JAVA_HOME` set to a real JDK. Testing this against a deliberately broken value found
a real bug rather than a hypothetical one — this machine's own `.env` still carried
`JAVA_HOME=C:\Users\HP\jdks\...`, the *other* machine's path from Week 1-2, masked
only because the correct value already sits in the User-scope environment variable
and `load_dotenv()` never overrides a variable that already exists. Fixed on this
machine's `.env` as a direct result of writing this check, not before.

**Each stage gets `MAX_STAGE_ATTEMPTS = 2` with a short backoff, not an unbounded
retry.** The one transient failure this project has actually hit is Lahari's P-30 —
driver-heap exhaustion that a retry after memory frees up can plausibly survive. A
genuinely broken stage fails the same way twice and raises exactly as before; nothing
here turns a real failure into a silent hang.

**`tests/test_retrain.py` — nine tests, none of which touch Spark or train a model.**
Retrying the real ~40-minute batch chain to test a two-line retry loop would cost 80
minutes checking behaviour that has nothing to do with Spark. Instead: `preflight()`
against a missing / empty / valid `JAVA_HOME`; `ensure_batch_pipeline` skipping an
existing output without invoking anything, and retrying a deliberately-nonexistent
module exactly twice before raising; and `promote_challenger` promoting with no
champion on record, declining a worse challenger without touching the champion
directory, and promoting a better one — all against throwaway `tmp_path` directories,
never `data/models/champion` itself. D-030 has the full account.

## D5 · The stream event schema is D-020's fact/query design, replayed as JSON

The execution plan's D5 line asks for a schema, agreed with Krishna and Lahari, for
Week 5's Kafka producer. Rather than invent field names from scratch, one topic
carries two event kinds that are already this project's own design:

- **`query`** fires at a leg's `trip_creation_time`, carrying exactly what the
  champion model predicts on (`planned_min`, `planned_km`, `route_type`,
  `created_hour`/`created_dayofweek`/`created_is_weekend`).
- **`fact`** fires at `od_end_time`, carrying exactly the outcome columns D-020's
  `BANNED_FEATURES` boundary already forbids a query from seeing (`gap_min`,
  `log_gap_ratio`, `is_delayed`).

This is the same split `src/pipeline/features.py`'s `as_of_history` already uses for
the batch feature pipeline — Week 5's streaming join reads as the live version of a
join Stage 4 already proved leak-free, rather than a second event shape someone has
to reason about being equivalent to the first.

`docs/schemas/stream_event.schema.json` is the formal JSON Schema.
`src/streaming/schema.py --examples 5` reads real rows from `features_v1`, derives
each fact's `event_time` as `od_start_time + actual_time` (not approximated —
`actual_time = gap_min + planned_min`, `src.ml.baselines`'s own definition), and
validates every event against the schema before writing
`demo/sample_events/trip_replay_sample.json`. Hand-checked one event end to end:
`planned_min=46.0`, `gap_min=101.0` → `actual_time=147` min →
`00:02:09 + 147 min = 02:29:09`, exactly what the module produced.

**Status: proposed, not yet confirmed** (D-031) — there is no Week 5 producer or
streaming job built against it yet for a real cross-check to be about. Carried into
Week 5 as the schema both Krishna's producer-adjacent work and Lahari's declared
stream-equals-batch correctness test need to agree on before either is built.

## What is not in this section yet

Nothing — D1-D2, D3-D4, and D5 are all in this file now.
