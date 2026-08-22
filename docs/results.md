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
| Corridors with ≥ 10 legs (audit set, D-018) | 1,130 — 40.6% of corridors, 78.6% of legs |
| Corridors with ≥ 30 legs (D-004's floor, retained as the robustness view) | 99 — 3.6% of corridors, 18.9% of legs |
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

## Week 2 — corridor audit — provisional

Source: `python -m src.ml.audit` → `docs/W2_lahari_corridor_audit.md`,
`benchmarks/raw/w2_corridor_audit.csv`, `w2_top20_bottlenecks.csv`,
`w2_corridor_audit_support30.csv`, `w2_audit_report.json`. Same 26,369-leg grain as
Week 1.

### The result the project stands on

Week 1 established that the planner is wrong nearly everywhere. Week 2 asks the only
question left worth asking — **is it wrong in a localisable way?** Every test compares
one corridor against the other ~26,300 legs, never against the planner's 1.0, so the
effect size `excess_ratio` reads as *this corridor's overrun as a multiple of the
network's own typical overrun*.

| Result | Value |
|---|---|
| Corridors tested (≥ 10 legs, D-018) | **1,130** of 2,783 — 78.6% of legs |
| Differ from the network at FDR 0.05 | **785 of 1,130 — 69%** |
| — significantly slower (bottlenecks) | **273** |
| — significantly faster | **512** |
| Worst corridor | Kanpur → Kanpur, **13.88×** the network's typical overrun on 13 legs (q = 6.3e-07) |

**The error localises, and in both directions.** 273 slower and 512 faster is the
number to quote — the planner is not uniformly optimistic by a varying amount, it is
differently wrong in different places. That is what makes a per-corridor model worth
training, and it is why "beats OSRM overall" is a weaker claim than "beats OSRM where
OSRM is worst".

### The support floor moved, and it changed the finding — D-018

D-004's 30-leg floor was set in Week 1, before any significance test existed. Re-running
the whole audit at each threshold showed it was not trading power for coverage:

| Min legs | Corridors tested | % of legs | Significant | Bottlenecks | Worst excess |
|---|---|---|---|---|---|
| **10 (decided)** | 1,130 | **78.6%** | 69% | 273 | **13.88×** |
| 20 | 268 | 33.4% | 74% | 78 | 4.08× |
| 30 (D-004, superseded) | 99 | 18.9% | 71% | 34 | 1.92× |
| 50 | 33 | 9.8% | 70% | 11 | 1.54× |
| 100 | 8 | 3.5% | 88% | 1 | 1.17× |

The significant share barely moves between 10 and 30 legs, so the extra corridors are
not noise passing a weaker test. What the 30-leg floor was removing was the finding.

**The two tables describe different networks, and this is the most quotable thing in
the section.** The 10-leg and 30-leg top-20s **share no corridor at all.** The 30-leg
table is metro — Maharashtra 11 of 20, Mumbai/Bhiwandi, Delhi/Gurgaon, intra-Hyderabad
— and reads as urban congestion. The 10-leg table is district feeders between towns —
Bihar 4, Maharashtra 3, Uttar Pradesh 2 — Phulpur → Allahabad at 13.3×, Malvan →
Sawantwadi at 12.2×, three separate corridors running into Muzaffarpur. **What the busy
core suffers from and what the network's worst corridors suffer from are not the same
thing.** Both tables are kept and both are cited; Week 4's per-corridor claim must name
which set it was evaluated on.

*Caveat to carry into the report:* winner's curse. With 1,130 tests, the single largest
`excess_ratio` is the likeliest in the family to be a lucky sample, and the worst
corridor rests on 13 legs. Every ranked row prints its leg count for that reason, and
`w2_corridor_audit_support30.csv` is the comparison view whose top rows carry no curse
worth naming. A claim that survives both tables goes in the paper; a claim that appears
only at the top of the loose table is a lead.

*Second caveat, unchanged in substance:* the bottleneck table is short-haul either way.
The median bottleneck is a 28-minute planned leg over 34 km. Free-flow routing models
short congested legs worst, so the story is coherent — but **the headline is a claim
about the network's short legs**, not about long-haul planning.

### Method

| Choice | Value |
|---|---|
| Statistic | `log(actual_time / osrm_time)` — the raw ratio is right-skewed |
| Test | Welch t-test, corridor vs rest of network |
| Correction | Benjamini-Hochberg, FDR 0.05 over 1,130 tests |
| Minimum support | 10 legs (D-018, superseding D-004) |
| Ranking | on `excess_ratio`, not p-value — a p-value grows with support |

Three checks that the ranking is not an artefact, Spearman over the tested corridors:
planned distance **−0.30** (short corridors overrun proportionally more), legs observed
**−0.07** (not a traffic ranking), FTL share **−0.28** (not a route-type ranking).

### Hub friction — D-015 confirmed

| Spearman ρ | `dwell_share` | `dwell_min` |
|---|---|---|
| vs mean corridor `excess_ratio` | −0.05 | −0.00 |
| vs mean **planned** leg minutes | **−0.30** | **+0.55** |

Ranked on `dwell_share`. Raw minutes correlate +0.55 with how long a hub's legs are
*planned* to take — a column neither dwell metric is built from — so a leaderboard on
minutes would substantially rank hubs by the length of the legs they happen to serve.

**Hub friction is not corridor friction.** Neither metric tracks the overrun of the
corridors leaving the hub. The India map and the hub leaderboard are two separate
claims and must not be presented as one.

121 of 1,657 hubs are ranked (≥30 outbound legs); median leg dwell 49 min, 34.6% of
wall clock. Worst hub Aluva (Kerala) at 82%.

### Both Week 2 decisions are closed

- **D-018 decided** — the support floor is 10 legs; every number in this section is at
  that floor, and the 30-leg table is retained beside it.
- **D-003 decided** — `DELAY_THRESHOLD` moves to 2.00 (49.6 / 50.4), the project leads
  with regression on `gap_min`, and the majority-class rate is reported beside every
  classifier metric permanently. The Week 1 finding that 1.25 labels 93.6% of legs
  delayed stays in the report as the evidence for the move.

### Gate 2 — met

The India map and the hub-friction leaderboard are on the dashboard, both reading the
cached CSVs above rather than running Spark (D-009). Two things the map changed about
how this section should be read:

- **All audited corridors place on the map.** The 19 null city fields Stage 1 emits were
  one parser bug rather than missing data — a facility named `Mumbai Hub (Maharashtra)`
  separates its city with a space, not `_` — and the map re-derives cities from raw
  facility names rather than inheriting the nulls (P-21). The wider 10-leg set exposed
  four more unmapped city codes, fixed the same way (P-23).
- **The bottlenecks are not routes, they are places.** A large share begin and end in
  the same city and the median one spans a short distance, so the planned
  corridors-as-lines map drew the network's worst corridors as marks of zero length. The
  page maps cities instead (P-20).

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
