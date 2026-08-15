# W2 · Mounika — reconstruction, hub friction, schema freeze, mock TMS

## What I built

**Stage 2 — `src/pipeline/reconstruct.py`.** Collapses the cleaned segment rows into one
row per origin-destination **leg**, the grain every corridor statistic, feature, and
model downstream is computed at (D-002).

`144,867 segment rows → 26,369 OD legs`, across 14,817 trips and 2,783 corridors.

### Why this needs window functions, not `groupBy`

`actual_time`, `osrm_time`, `osrm_distance` and `actual_distance_to_destination` are
**running cumulative totals within a leg** — they grow row by row, and the leg total
sits in the last row. So:

- `groupBy().first()` returns whichever row Spark saw first, which is not stable across
  partitions, and understates every leg.
- `groupBy().sum()` would add cumulative values together, which is meaningless.

The last row per leg is therefore selected with
`row_number() OVER (PARTITION BY trip_uuid, od_start_time, od_end_time ORDER BY source_row_index DESC)`,
and the quantities that genuinely aggregate (`count`, `sum`) are computed separately and
joined back.

### Stage 1 change: `source_row_index`

Stage 2 needs to know which row is *last*, and Parquet does not preserve row order.
Stage 1 now emits `source_row_index` via `monotonically_increasing_id()` on the CSV read
— its high bits encode the partition index, which Spark assigns in file-offset order, so
it is monotonic in file order. **Stage 1 asserts the column is unique** before writing;
a silently non-monotonic index would corrupt every leg total.

This is the substance of D-014 — see below.

## How to run / verify

```bash
python -m src.pipeline.clean                      # rebuild clean_v1 with source_row_index
python -m src.pipeline.reconstruct --validate     # build trips_v1 and diff vs the W1 oracle
```

`--validate` diffs every leg against `benchmarks/raw/w1_leg_summary.csv`, which Lahari
built independently in pandas in Week 1 — a genuine second implementation, not a copy of
this one. It exits non-zero on failure, so it can gate CI.

## Numbers

From `data/processed/trips_v1/_reconstruction_report.json`:

| Property | Value |
|---|---|
| Segments in → legs out | 144,867 → **26,369** |
| Trips | 14,817 |
| Corridors | 2,783 |
| Median gap ratio | **2.00×** |
| Mean gap ratio | 2.56× |
| Median gap | 42 min |
| Mean gap | 110.0 min |
| Median dwell per leg | 49 min |
| Legs over plan | **98.3%** |
| Legs delayed at T=1.25 (D-003, still open) | 93.6% |
| On disk | **3.9 MB** Parquet, partitioned by `route_type` |

Every figure reproduces Lahari's independent Week 1 numbers exactly.

### Validation result

```
all 26,369 leg keys matched
actual_time                     ok   max|diff|=0
osrm_time                       ok   max|diff|=0
osrm_distance                   ok   max|diff|=4.5e-13
actual_distance_to_destination  ok
factor                          ok   max|diff|=7.1e-15
n_segments                      ok   max|diff|=0
gap_min                         ok   max|diff|=0
gap_ratio                       ok   max|diff|=0
dwell_min                       ok   max|diff|=0
1,581 legs differ from the oracle by tie-break only (D-014)
VALIDATION PASSED
```

## The bug validation caught — D-014

The first implementation ordered by `max(actual_time)` and failed on 80 legs. The cause
is worth stating because it is invisible to inspection:

**1,861 legs (7.1%) have a tie on maximum `actual_time`** — their trailing segments add
zero minutes. On all 1,861 the tied rows carry *identical* `actual_time` but *different*
`osrm_time` and `osrm_distance`, so which row you pick changes the leg's OSRM figures
while leaving realised time untouched. `max(actual_time)` does not identify a single row,
and pandas `idxmax()` resolves the tie by taking the *first*, which lands earlier than
the final scan.

Checked against the true last row in file order: it agreed with the last-row rule
**80/80** on the disputed legs and with the oracle's rule **0/80**. Hence
`source_row_index`.

**Impact on any reported number: none.** Median gap ratio 2.0000, mean gap 110.00 min,
98.30% over plan — identical under all three candidate rules. Mean `osrm_distance` moves
by 0.006%.

The validator now classifies these by exact signature (`actual_time` and `n_segments`
identical, some cumulative column different) and reports them without failing the run.
**0 legs differ with a differing `actual_time`** — that would be a real reconstruction
error, and there are none.

---

# D3–D4 · Hub dwell time

**Stage 3 — `src/pipeline/hubs.py`.** `26,369 legs → 1,657 hubs`, of which **121** have
enough traffic to rank. Leaderboard at `benchmarks/raw/w2_hub_dwell.csv` (committed),
full table at `data/processed/hubs_v1`.

```bash
python -m src.pipeline.hubs
```

## I built the obvious metric first and the data said no

Hub dwell "should" be the gap between arriving at a hub on one leg and leaving on the
next. I computed it across all 11,552 in-trip handoffs before aggregating anything:

| Handoff kind | n | Non-zero gap | Median gap |
|---|---|---|---|
| Trip continues from the **same** centre | 9,987 | **1.4%** | **0 min** |
| Next leg starts at a **different** centre | 1,565 | **100%** | 90 min |

The publisher closes one leg's OD window at the instant it opens the next, so on a
continuous handoff there is nothing left in the gap to measure. **Every non-zero gap is
a chain break** — the shipment reappears at a facility it never travelled to on any leg
in the file. That is unobserved movement, not a shipment resting at a hub.

Had I aggregated first and looked later, the leaderboard would have been a ranking of
which hubs happen to sit next to a missing leg, and it would have looked entirely
plausible. This is D-015.

**The chain-break rate is worth keeping in its own right: 13.5% of handoffs.** The
Week 5 replay walks trips leg by leg, so on 13.5% of handoffs the stream will show a
shipment jumping facilities. Better to know that now than to debug it live. It is
emitted as `chain_break_rate` and `median_unobserved_gap_min` — named for what it is.

## What is actually measurable

`dwell_min = start_scan_to_end_scan − actual_time` — the part of a leg's wall clock the
shipment was not moving. Median **49 min**, i.e. **34.6%** of a typical leg. Checked on
all 26,369 legs: `start_scan_to_end_scan` equals the OD window to the minute, and
`dwell_min` is never negative.

**Two metrics, and they disagree.** Raw `dwell_min` correlates **0.54** with the leg's
wall clock, so ranking on it partly ranks hubs by how long their legs are.
`dwell_share = dwell_min / start_scan_to_end_scan` is scale-free. The two rankings
overlap on only **8 of the top 20** (rank correlation 0.49) — so the choice changes the
leaderboard and cannot be implicit. `friction_rank` is assigned on `dwell_share`; raw
minutes stay in the table beside it.

A leg's idle time can't be split between its two ends, so both are credited and
reported separately (`*_out` / `*_in`). Across supported hubs the two correlate only
**0.41** — Kollam_Central_H_1 is 139 min median on departure and 526 on arrival — so
the split carries real information rather than duplicating a column.

### Top 5 by dwell share (of 121 ranked)

| # | Hub | Legs out | Median dwell | Share | Median gap ratio |
|---|---|---|---|---|---|
| 1 | Aluva_Peedika_H (Kerala) | 86 | 350 min | 0.82 | 1.47× |
| 2 | Hubli_Adargchi_IP (Karnataka) | 78 | 373 min | 0.76 | 2.01× |
| 3 | Kollam_Central_H_1 (Kerala) | 32 | 139 min | 0.73 | 1.34× |
| 4 | Bengaluru_Peenya_L (Karnataka) | 36 | 112 min | 0.70 | 1.70× |
| 5 | Warangal_HunterRd_I (Telangana) | 39 | 119 min | 0.69 | 1.62× |

Two checks run inside the stage and fail it rather than warn: outbound and inbound leg
counts must each add back to 26,369 (a fanned-out join is otherwise invisible), and
`friction_rank` must be a dense 1..121. The second exists because the first version
ranked over all 1,657 hubs and produced a leaderboard that started at rank 27 — correct
ordering, no rank 1, easy to miss.

---

# D3–D4 · Parquet schema frozen and versioned

**`src/pipeline/contracts.py`** freezes the column set, per-column type, partition
columns, key and row count of all three caches.

```bash
python -m src.pipeline.contracts --keys
# clean_v1  OK  v1, 36 columns, 144,867 rows
# trips_v1  OK  v1, 32 columns,  26,369 rows
# hubs_v1   OK  v1, 28 columns,   1,657 rows
```

Exits non-zero on any difference, so it can gate CI. A column that was *added* is a
breach too — a contract that quietly tolerates new columns is not a contract.

**Versioning rule (D-016):** add `CLEAN_V2`, add a new `Contract`, move the stage's
`--output`. **Never repoint an existing version** — your in-flight work keeps reading
what it was written against.

Because the raw CSV is pinned by SHA-256, the frozen row counts make this a regression
test on the whole pipeline, not just on column names. I checked the check: renamed
column, type drift, dropped column, changed row count and a broken key are all caught,
the real caches raise no false alarm, and a dataset a teammate hasn't built yet is
reported as *skipped* rather than failed.

Each stage now stamps its contract version into its own report, so you can tell what a
cached file was built against without starting Spark.

---

# D5 · Mock TMS

**`src/tms/`** — FastAPI + SQLite. Orders and shipments live, as the plan specifies;
status updates, exception tickets and invoices are Week 3.

```bash
python -m src.tms.seed        # 1,657 facilities from hubs_v1
python -m src.tms             # http://localhost:8000/docs
pytest tests/test_tms.py -q   # 26 passed
```

**The facilities are real.** All 1,657 centre codes from `hubs_v1`, each carrying its
hub-friction rank. So an order the Order Entry Agent files in Week 5 names a centre
that exists in the corridor audit, and Week 6's Invoice Auditor can ask what that
corridor should have cost. It falls back to the committed 121-hub CSV, so a fresh clone
gets a working TMS before anyone builds the caches. No Spark anywhere in `src/tms/` —
it boots on a machine with no JVM.

Two behaviours exist specifically for the agents (D-017):

- **Idempotent creates.** `POST /orders` with a repeated `external_ref` returns the
  existing order, HTTP 200, `idempotent_replay: true`. Agents retry and mail gets
  redelivered; solving that once here beats solving it in every agent.
- **Rejections name the value.** Unknown centre code, origin equal to destination,
  zero pieces, arrival before departure, a second shipment on one order, reopening a
  cancelled order — all refused with the offending value in the message, so Krishna's
  clarification path has something to quote back to the customer.

Centre codes are upper-cased and trimmed on the way in, exactly as Stage 1 does — an
agent lifting `ind683511aaa` off a scan should not get a rejection no human would call
real.

A high-friction origin returns a **warning, not an error**: the order is legal, the hub
is just slow, and that is the Stage 3 table reaching the agent plane:

```json
"warnings": ["Origin IND683511AAA is hub-friction rank 1 (median dwell 350 min on departure)."]
```

Verified against a running server, not only the test client: seed → `/health` (1,657
facilities, `seeded_from: hubs_v1`) → facility lookup by city → order (201) → same
order again (200, replay) → shipment (201, order auto-confirmed).

---

## Environment: reproduced on a second machine

The whole pipeline was re-run from the raw CSV on a machine that had never built it,
following D-012 exactly (portable Temurin JDK 17 zip, venv outside OneDrive, winutils
in `C:\hadoop`). Stage 1 reproduced 144,867 rows, Stage 2 reproduced all 26,369 legs
and passed `--validate` against Lahari's oracle with the same 1,581 tie-break legs.
One correction to the recipe: **`pip install pyspark` must not use
`--only-binary=:all:`** — PySpark ships an sdist, so that flag fails with "no matching
distribution". The other pins do want it.

## For Lahari

- D-014 needs your confirmation, then regenerate `benchmarks/raw/w1_leg_summary.csv`
  from `trips_v1` so the oracle and pipeline agree exactly and the residual 1,581 drops
  to zero. **Your Week 1 headline numbers do not change** — I checked all of them
  against both rules before touching anything.
- Hub dwell ranking (your W2 D3–D4) reads `benchmarks/raw/w2_hub_dwell.csv`. Both
  candidate metrics are in it; the ranking metric is yours to confirm for the audit
  writeup, and switching costs a sort rather than a re-run.
- The `n=30` support gate leaves 121 hubs. If your significance testing wants more
  hubs, `--min-support` takes any value and the report records what was used.

## For Krishna

- The hub-friction leaderboard page reads `benchmarks/raw/w2_hub_dwell.csv` — it has
  `city` and `state` columns for the India-map join, and `friction_rank` is dense 1..121.
- The TMS is at `http://localhost:8000` with an OpenAPI console at `/docs`. Auth is off
  until `TMS_API_KEY` is set in `.env`; `.env.example` ships one, so if you copy it the
  key is required on every call except `/health`.
