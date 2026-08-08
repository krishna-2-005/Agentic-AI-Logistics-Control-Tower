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
3. **Textual null sentinels converted** — missing facility names are the literal
   string `nan`, not empty fields. pandas coerces that to NaN on read; **Spark does
   not**, and reads a valid 3-character string. Stage 1 converts it explicitly
   (293 + 261 rows) and counts the conversion. Left alone it would have produced a
   facility in a city called "nan" on the Week 2 India map.
4. **Names recovered where possible, state inferred where not.** The 554 missing names
   belong to 14 centre codes, and none of those codes carries a name anywhere in the
   dataset — verified, so the names are unrecoverable. The *state* is recoverable: the
   centre code embeds an Indian PIN (`IND282002AAD` → 282002 → Agra, Uttar Pradesh),
   which fills the state on 551 rows, flagged `state_from_pin` so an inferred region is
   never mistaken for a parsed one.
5. **Locations parsed** — `Anand_VUNagar_DC (Gujarat)` → city `Anand`, state
   `Gujarat`. Non-matching rows get null rather than a wrong guess.
6. **Quality flags** — `is_negative_segment`, `is_zero_osrm_segment`, `is_suspect`
   (D-006). `segment_factor` recomputed with a zero guard because the raw column
   carries a `-1` sentinel on the zero-OSRM rows. `od_duration_min` derived.
7. **Drops, each with a named reason and a count** — null trip/centre, unparseable or
   inverted OD window, non-positive `osrm_time` or `actual_time`. Exact duplicates
   removed (the published file has none; this guards a re-download).
8. **Writes** partitioned Parquet plus `_quality_report.json` accounting for every row
   in, every row out, every drop reason, every flag, and the distinct-key counts.

Nothing is dropped silently. A row is either kept, or dropped under a reason that
appears in the report with a count.

## Numbers

Produced by the run — `data/processed/clean_v1/_quality_report.json`. Every figure
cross-checks against Lahari's independent pandas profile.

| Property | Value |
|---|---|
| Raw rows in / out | 144,867 / 144,867 (**0 dropped**) |
| Columns in / out | 24 / 35 |
| Trips | 14,817 |
| OD legs | 26,369 |
| Corridors | 2,783 |
| Source / destination centres | 1,508 / 1,481 |
| Timestamp cast failures | 0 across all four columns |
| Textual `nan` sentinels converted | 554 (293 source, 261 destination) |
| Names recovered from codes | 0 — the 14 affected codes are unnamed everywhere |
| States inferred from PIN prefix | 551 |
| Exact duplicates | 0 |
| `is_negative_segment` | 1,973 |
| `is_zero_osrm_segment` | 2,347 |
| `is_suspect` (union) | 2,600 |
| Observation window | 2018-09-12 00:00 → 2018-10-08 03:00 |
| On disk | 55.6 MB CSV → **8.3 MB Parquet**, partitioned by `route_type` |

**Nothing was dropped.** Every drop rule returned 0, which is the honest outcome: this
file is clean on the dimensions that would make a row unusable. The interesting damage
is in the *flags*, not the drops.

## Environment — resolved

Gate 1's Spark blocker is cleared. Three things were needed and none was obvious:

1. **JDK 17.** `winget install EclipseAdoptium.Temurin.17.JDK` hangs forever in a
   non-interactive shell because the MSI needs UAC elevation. The portable Temurin zip
   needs no admin at all — see the README.
2. **PySpark 4.0, not 3.5.** On Python 3.13 the "safe" pins (`pyspark==3.5.1`,
   `numpy==1.26.4`, `pandas==2.2.2`, `pyarrow==15`, `scipy==1.13.1`) have **no cp313
   wheels**; pip silently falls back to building from source and effectively hangs.
   PySpark 4.0 is the first release supporting 3.13. `requirements.txt` now documents
   the check: `pip download <pkg>==<ver> --no-deps --only-binary=:all:`.
3. **winutils.exe + hadoop.dll.** Spark *reads* fine on Windows without them, but
   writing Parquet calls `RawLocalFileSystem.setPermission` → `getWinUtilsPath` and
   fails. Placed in `C:\hadoop\bin` with `HADOOP_HOME` set. Note for the team: this is
   an unsigned third-party binary from the cdarlint/winutils mirror, which is standard
   practice for Spark on Windows but worth knowing.

Verify with `python -m src.common.check_env` — Spark rows must be green.

## Two bugs this week, both found by running the code

Worth recording because both were invisible to inspection and both would have
corrupted results silently:

- **`cutoff_timestamp` has mixed precision.** 141,438 rows are second-level, 3,429
  (2.37%) carry microseconds. A single fixed format throws on the minority under Spark
  4's ANSI mode. Now parsed with an optional fraction, `yyyy-MM-dd HH:mm:ss[.SSSSSS]`.
- **The name backfill was built on a false premise.** It assumed every code with a
  missing name had a name elsewhere. Checking showed none of the 14 do. The step
  stays (it is correct and free for a future mirror) but the docs no longer claim it
  recovers anything, and the PIN-based state recovery does the work that is actually
  possible.

## Next (Week 2)

- Trip/corridor reconstruction with Spark window functions (segments → legs), which
  must reproduce `benchmarks/raw/w1_leg_summary.csv` row for row — that file is the
  test oracle.
- Hub dwell-time computation. Week 1 already established that
  `start_scan_to_end_scan − actual_time` **is** dwell (median 49 min/leg), so this
  needs no new columns.
- Parquet schema frozen and versioned.
- Mock TMS skeleton: FastAPI + SQLite, orders and shipments endpoints.
