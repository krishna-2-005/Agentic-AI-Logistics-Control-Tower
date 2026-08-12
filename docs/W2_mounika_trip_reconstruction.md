# W2 · Mounika — trip and corridor reconstruction (D1–D2)

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

## Next (my W2 D3–D4, not started)

- Hub dwell-time computation per hub. `dwell_min` already exists per leg from this
  stage, so this is a regrouping rather than new derivation.
- Freeze and version the Parquet schema.
- Then D5: mock TMS skeleton (FastAPI + SQLite), orders and shipments endpoints.

## For Lahari

D-014 needs your confirmation, then regenerate `benchmarks/raw/w1_leg_summary.csv` from
`trips_v1` so the oracle and pipeline agree exactly and the residual 1,581 drops to zero.
**Your Week 1 headline numbers do not change** — I checked all of them against both rules
before touching anything.
