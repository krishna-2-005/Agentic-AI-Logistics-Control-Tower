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
Lahari's entry point locally hit a shared-file coupling (`docs/problems.md` P-30) —
resolved without re-running the ~40-minute training, by promoting from the
already-written `w4_model_report.json` directly.

## What is not in this section yet

- **Pipeline hardening / one-command batch run (D3-D4)** — retries on a transient
  stage failure, and a documented single entry point a fresh clone can run start to
  finish.
- **Stream event JSON schema (D5)**, agreed with Krishna and Lahari for Week 5's Kafka
  producer.
