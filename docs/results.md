# Frozen results

**Owner: Lahari.** Every number that appears in the course report or the paper lands
here first, with the script that produced it and the file it wrote.

A number is **frozen** when it will not change again — the Week 6 results freeze
(execution plan, W6 D1-D2) makes this formal for Layer 1. Before that, entries are
marked *provisional* and may move.

---

## Week 1 — provisional

Source: `python -m src.ml.eda` → `docs/W1_lahari_eda.md`,
`benchmarks/raw/w1_leg_summary.csv`.
Computed at **OD-leg grain** over 26,369 legs (D-002). Not at raw-row grain.

### The premise of the whole project

| Result | Value |
|---|---|
| Legs where realised time exceeds the OSRM plan | **25,922 of 26,369 — 98.3%** |
| Median realised / planned ratio | **2.00×** |
| Mean realised / planned ratio | 2.56× |
| p90 / p99 ratio | 3.79× / 12.08× |
| Median absolute gap | **42 min** |
| Mean absolute gap | 110 min |

**The planner is biased, not noisy.** A well-calibrated routing engine would produce a
roughly symmetric error distribution centred near 1.0. This one under-predicts on
98.3% of legs. That is what makes a corridor-level audit worth doing at all: a
systematic error should be localisable, which is exactly what Week 2 tests.

*Caveat to carry into the report:* because the bias is this large and this one-sided,
a model that learns little more than "multiply OSRM by two" will beat OSRM on MAE.
**The corridor-mean baseline must be reported beside the headline**, or the result
looks stronger than it is.

### By route type

| Route type | Legs | Median ratio | Mean gap (min) | % legs over plan |
|---|---|---|---|---|
| Carting | 12,429 | 2.17× | 56.2 | 98.5% |
| FTL | 13,940 | 1.93× | 158.0 | 98.2% |

Carting is proportionally worse; FTL is worse in absolute minutes. Both framings
belong in the report — the ratio matters for the model, the minutes matter to a
customer.

### Structure

| Property | Value |
|---|---|
| Raw segment rows | 144,867 |
| OD legs | 26,369 |
| Trips | 14,817 |
| Corridors | 2,783 |
| Corridors with ≥ 30 legs (audit set, D-004) | 99 — 3.6% of corridors, 18.9% of legs |
| Observation window | 2018-09-12 → 2018-10-08 (~26 days) |
| Median dwell per leg (`start_scan_to_end_scan − actual_time`) | 49 min |

### Data-quality facts that constrain later analysis

| Finding | Scale | Handling |
|---|---|---|
| `segment_actual_time ≤ 0` (scan clock skew) | 1,973 rows | flagged `is_negative_segment`, kept (D-006) |
| `segment_osrm_time == 0` | 2,347 rows | flagged `is_zero_osrm_segment`, kept |
| `segment_factor` = `-1` sentinel, not a ratio | 2,347 rows | nulled in Stage 1 — **never aggregate the raw column** |
| Null facility names | 554 rows | backfilled from centre codes |
| Exact duplicate rows | 0 | — |

---

## Week 2 — corridor audit

*Pending. Tag `audit-v1`.*

## Week 3 — baselines

*Pending. See `benchmarks/ml_results.md`.*

## Week 4 — beat-OSRM headline

*Pending. Tag `batch-complete`.*

## Week 5 — streaming

*Pending. See `benchmarks/streaming_throughput.md`.*

## Week 6 — agent evaluation and results freeze

*Pending. See `benchmarks/agent_evaluation.md`.*

## Week 7 — scale appendix

*Pending. See `benchmarks/scale_appendix.md`.*
