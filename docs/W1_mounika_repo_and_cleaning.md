# W1 · Mounika — repository, environment, and the Stage 1 cleaning pipeline

## What I built

**Repository skeleton** exactly as GIT_RULES §1 specifies — `src/{pipeline,ml,streaming,tms,agents,dashboard,automation,common}`,
`docs/`, `demo/`, `benchmarks/`, `notebooks/`, `data/` — plus the root files the whole
team depends on: `.gitignore`, `.env.example`, `requirements.txt` (pinned),
`README.md`, `GIT_RULES.md`, and `.github/pull_request_template.md`.

**`data/README.md`** — download instructions for the primary Kaggle source and both
mirrors, the expected SHA-256, and the rule that `raw/` is immutable while
`processed/` is disposable and rebuildable with one command.

**Shared layer `src/common/`**, so no script hardcodes a path or builds its own Spark
session:
- `config.py` — every path, the pinned dataset facts, and the domain constants
  (`DELAY_THRESHOLD`, `MIN_CORRIDOR_SUPPORT`) that Lahari's decisions live in.
- `spark.py` — one `get_spark()` for batch, streaming, and ML. Shuffle partitions set
  to 8 (Spark's default of 200 makes hundreds of near-empty tasks on 145K rows),
  `PYSPARK_PYTHON` pinned to `sys.executable` because the driver's interpreter lookup
  is unreliable on Windows and inside venvs, and Parquet datetime rebase set to
  `CORRECTED` so the pre-Gregorian timestamps in this file are handled explicitly
  instead of throwing.
- `logging_setup.py` — console plus a per-run file in `logs/`.
- `check_env.py` — **the Gate 1 check**, below.

**Stage 1 cleaning pipeline** — `src/pipeline/clean.py` with the pinned schema in
`src/pipeline/schema.py`.

## How to run

```bash
python -m src.common.check_env          # every member, day 1
python -m src.pipeline.clean            # builds data/processed/clean_v1
```

`check_env` prints a pass/fail table across Python, JAVA_HOME/Spark, the raw dataset
(presence, size, SHA-256), the LLM provider, git identity, and the optional Week 4-6
extras. **Gate 1 is not passed until the required rows are green on all three
machines.** It exits non-zero on failure, so it can gate CI later.

## What Stage 1 does

Reads with an explicit schema (one pass, and a loud failure if a mirror ships
different columns), then:

1. **Types** — timestamps parsed with their two distinct formats; `cutoff_timestamp`
   is the only column without sub-second precision and needs its own. Cast failures
   are counted into the quality report rather than silently nulled.
2. **Centre codes standardised** (upper, trimmed) and `corridor_id` built. Case or
   whitespace drift here would silently split one corridor into two in the audit.
3. **Facility names backfilled** — 293 `source_name` and 261 `destination_name` nulls
   recovered from a code→name map built from the dataset itself. Every affected code
   appears with a name on other rows, so no external lookup is needed. Ties resolve to
   the most frequent spelling, deterministically.
4. **Locations parsed** — `Anand_VUNagar_DC (Gujarat)` → city `Anand`, state
   `Gujarat`. Non-matching rows get null rather than a wrong guess.
5. **Quality flags** — `is_negative_segment`, `is_zero_osrm_segment`, `is_suspect`
   (D-006). `segment_factor` recomputed with a zero guard because the raw column
   carries a `-1` sentinel on the zero-OSRM rows. `od_duration_min` derived.
6. **Drops, each with a named reason and a count** — null trip/centre, unparseable or
   inverted OD window, non-positive `osrm_time` or `actual_time`. Exact duplicates
   removed (the published file has none; this guards a re-download).
7. **Writes** partitioned Parquet plus `_quality_report.json` accounting for every row
   in, every row out, every drop reason, every flag, and the distinct-key counts.

Nothing is dropped silently. A row is either kept, or dropped under a reason that
appears in the report with a count.

## Numbers

`_quality_report.json` is produced by the run, so the authoritative numbers land when
Stage 1 first executes. Expected input, confirmed independently in
`benchmarks/raw/w1_column_profile.csv`:

| Property | Value |
|---|---|
| Raw rows | 144,867 |
| Columns | 24 |
| Trips | 14,817 |
| OD legs | 26,369 |
| Corridors | 2,783 |
| Exact duplicates | 0 |
| Nulls to backfill | 554 |
| Rows flagged suspect | ~4,320 (2.98%) |

## ⚠ Blocked — this is the Gate 1 blocker

**Stage 1 has not been executed.** There is no JDK on this machine: `JAVA_HOME` points
at `C:\Program Files\Java\jdk-17.0.8`, which does not exist, and no `java` is on PATH.
PySpark cannot start a driver without one, so `clean.py` is written and reviewed but
unrun, and `data/processed/clean_v1` does not yet exist.

**Fix (each member, once):**

```powershell
winget install EclipseAdoptium.Temurin.17.JDK
# then set JAVA_HOME to the install path and reopen the shell
python -m src.common.check_env      # must show Spark rows green
python -m src.pipeline.clean
```

Everything that does not need Spark was built and run instead — the profile, the EDA,
the corridor tables, the dashboard skeleton — so Week 1's analytical results exist and
are reproducible today. Only the Parquet cache waits on the JDK.

## Next (Week 2)

- Trip/corridor reconstruction with Spark window functions (segments → legs), which
  must reproduce `benchmarks/raw/w1_leg_summary.csv` row for row — that file is the
  test oracle.
- Hub dwell-time computation. Week 1 already established that
  `start_scan_to_end_scan − actual_time` **is** dwell (median 49 min/leg), so this
  needs no new columns.
- Parquet schema frozen and versioned.
- Mock TMS skeleton: FastAPI + SQLite, orders and shipments endpoints.
