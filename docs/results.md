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

Merged to `main` and tagged `audit-v1` and `week2-complete`. Verified at the gate:
`ruff` clean over `src/` and `tests/`, 26 tests passing, and
`python -m src.pipeline.contracts --keys` green on all three caches — `clean_v1`
144,867 rows, `trips_v1` 26,369, `hubs_v1` 1,657.

## Week 3 — baselines — provisional

Source: `python -m src.ml.baselines` → `docs/W3_lahari_baselines.md`,
`benchmarks/raw/w3_baseline_metrics.csv`, `w3_linreg_coefficients.csv`,
`w3_classifier_metrics.csv`, `w3_baseline_report.json`. Same 26,369-leg grain as
Weeks 1–2, on the frozen `features_v1` table (Stage 4, Mounika).

### The split D-005 deferred, fixed

D-005 (Week 1) decided the split would be time-based rather than the dataset's own
`data` column and left the exact cut to whichever week trains something first —
**D-022 fixes it here**: the 80th percentile of `trip_creation_time`, giving 21,095
training legs (up to 2018-09-28 23:12:35 UTC) and 5,274 held out. Every number below
is on the held-out set unless marked otherwise, and Week 4 must reuse
`src.ml.baselines.time_split(frac=0.80)` rather than define its own cut — comparing
against these baselines only means something on the same held-out legs.

### The baseline to beat is the corridor mean, not OSRM

| Model | MAE (min) | RMSE (min) | R2 |
|---|---|---|---|
| OSRM production estimate | 107.1 | 246.7 | −0.230 |
| **Corridor mean** (past-only, D-023) | **36.1** | 101.7 | 0.791 |
| Linear regression (full as-of feature set) | 41.2 | **96.8** | **0.811** |

**The corridor mean alone recovers 66% of OSRM's error**, using nothing but Stage 4's
past-only per-corridor average — the number Week 4's Random Forest and GBT actually
have to clear is 36.1 min, not OSRM's 107.1, or the eventual "beats OSRM" headline
overstates what a model contributes on top of a mean anyone could compute.

**The linear model does not clear the corridor mean, and that is the finding worth
carrying forward — D-024.** It has the better RMSE and R2 and the worse MAE, on the
same test split. OLS minimises squared error, not MAE, and the network's own
heavy-tailed corridors (up to 13.9× per D-018) are exactly the shape of data where that
gap shows up: a few extreme corridors are worth a linear model trading some bias on
ordinary legs for less squared error on them, a trade the corridor mean's per-corridor
local averages never make. **Decided: Week 4 is ranked on MAE**, since it is the metric
this table already reports and the one "average error in minutes" plainly means; RMSE
and R2 stay beside it because their disagreement here is itself informative (P-28).

### Cold start handled explicitly, not dropped

11.09% of legs are a corridor's first sighting and carry no corridor-mean feature
(6.56% / 6.33% for source / destination hub). None are dropped from either evaluated
set: the corridor-mean baseline falls back to OSRM's own prediction on them, and the
linear model gets an explicit `{corr,src,dst}_is_cold` indicator beside a zero-filled
mean (D-023), so "no history yet" is a feature rather than a wrong zero.

### Delay classifier v1 — D-025

D-003's `is_delayed` label (`actual_time > 2.00x planned_min`) is 49.7% positive over
all 26,369 legs — near enough to even that a majority-class baseline scores 0.000 F1
on the positive class while still being "right" 51.1% of the time, which is exactly
why D-003 asked for the majority rate reported beside every classifier metric rather
than trusting accuracy alone.

| Model | Accuracy | Precision | Recall | F1 | Majority rate |
|---|---|---|---|---|---|
| Majority class | 0.511 | 0.000 | 0.000 | 0.000 | 0.511 |
| OSRM (thresholded) | 0.511 | 0.000 | 0.000 | 0.000 | 0.511 |
| Corridor mean (thresholded) | 0.746 | 0.704 | **0.831** | 0.762 | 0.511 |
| Linear regression (thresholded) | 0.727 | 0.699 | 0.774 | 0.735 | 0.511 |
| **Logistic regression (delay classifier v1)** | **0.768** | **0.761** | 0.767 | **0.764** | 0.511 |

`OSRM` predicts "not delayed" for every leg — its own estimate never disagrees with
itself by 2x — so it and the majority class make the identical degenerate call.
**Logistic regression, fit directly on `is_delayed` over the same `FEATURES` as the
Week 3 linear regressor, is the strongest model in this table (0.764 F1)**, ahead of
the corridor mean thresholded the same way (0.762) — the two are close, but on
different trade-offs: the corridor mean's 0.831 recall against logistic regression's
0.767, and 0.761 precision against 0.704. Every regressor's classification score
here is thresholded from its own `gap_min` prediction (`threshold_to_label`) rather
than a second, separately-calibrated model, so the regression and classification
framings stay comparable across the whole table.

### Both Week 3 decisions this section depends on

- **D-022 decided** — the split is the 80th percentile of `trip_creation_time`, and
  Week 4 must reuse it.
- **D-024 decided** — MAE is the metric Week 4 is judged and ranked on, forced by a
  genuine RMSE/MAE disagreement between the linear model and the corridor mean (P-28).
- **D-025 decided** — delay classifier v1 is logistic regression over the Week 3
  `FEATURES`, and Week 4's Random Forest and GBT owe the same classifier table,
  scored with `add_delay_label` / `threshold_to_label` rather than a redefined label.

### Gate 3 — met

All three legs of the gate are on the same branch now: `features_v1` frozen (Mounika,
33 columns, 26,369 rows, leak-free per D-020), baseline numbers on the board including
delay classifier v1 (Lahari, this section), and the 120-document labelled corpus
(Krishna, `docs/W3_krishna_doc_corpus.md`) — Gate 3 asked for 100+.

`ruff` clean over `src/` and `tests/`, 75 tests passing (26 at the Week 2 gate + 49 new
across `tests/test_features.py`, `tests/test_doc_corpus.py`, `tests/test_tms.py` and
`tests/test_baselines.py`), and `python -m src.pipeline.contracts --keys` green on all
four caches — `clean_v1` 144,867 rows, `trips_v1` 26,369, `hubs_v1` 1,657, `features_v1`
26,369.

Merged to `main` and tagged `week3-complete`. The three branches' independently
numbered decisions and problems (`D-020` × 3, `P-25` × 3, `P-26` × 2) were renumbered
clear of each other before merging — Mounika's D-020/P-25 kept their numbers, Krishna's
moved to D-021/P-26/P-27, Lahari's moved to D-022–D-025/P-28/P-29 — rather than left to
collide silently inside a single shared `decisions.md`.

## Week 4 — beat-OSRM headline and the first agent-eval number

Source: `python -m src.ml.models`, `--ablations`, and `python -m src.ml.doc_eval` →
`docs/W4_lahari_beat_osrm.md`, `docs/W4_krishna_doc_agent.md`,
`docs/W4_mounika_auto_retrain.md`, `benchmarks/ml_results.md`,
`benchmarks/agent_evaluation.md`. Same 26,369-leg grain and D-022 split as Weeks 1-3
for the batch numbers; the document numbers are on Week 3's 120-document corpus.

### The headline, reported as it actually landed

| Result | Value |
|---|---|
| Best Week 4 model vs OSRM | Random Forest (MLlib) **36.9 min MAE** vs OSRM's 107.1 — a 65.5% reduction |
| Best Week 4 model vs the real bar | **Does not clear** the corridor-mean baseline's 36.1 min (D-024) — trails by 0.8 min, reported as such rather than reframed |
| Per-corridor gains | 1,369 of 1,646 test corridors improve over OSRM (83%) |
| Feature-block ablations | Corridor-history costs 3.30 (RF) / 2.43 (GBT) min MAE if dropped; temporal costs only 0.11 / 0.72 |
| Delay classifier table | GBT-thresholded reaches 0.771 F1, edging logistic regression's 0.764 (D-025) — a different ranking from the MAE table, and not a contradiction (D-024/P-28's own lesson) |
| Document Intelligence Agent v1→v2 | Field-extraction F1 **0.853 → 0.929** (micro-averaged); `document_number` accuracy 1/16 → 16/16 on the paired comparison (D-027) |
| Auto-retraining loop | First run promoted Random Forest as champion at 36.89 min MAE; hardened with a preflight check and bounded per-stage retry (D-027 on Mounika's branch) |

**The batch-ML headline is an honest one, not a triumphant one, and that is the
finding.** A tuned MLlib Random Forest beats OSRM by a wide margin and improves the
large majority of individual corridors — but it does not beat a single per-corridor
average computed with no model at all. Both facts are reported with equal weight,
per D-024's decision to rank on MAE and P-28's lesson that a model can be a genuine
improvement by one honest metric and not by another.

**The agent-eval headline is a real, measured number, not a demo anecdote.** 0.853
F1 on the first prompt version, improved to 0.929 by one iteration that fixed a
single, concretely-identified failure mode (`document_number` transcribed as raw OCR
noise) — and the harness that produced both numbers never touched the code that
produced the predictions it scored (D-028).

### Real constraints, surfaced and worked around rather than hidden

- **The Gemini free tier's real limit is 20 requests/day, not per minute** (D-026) —
  every document-agent number above is reported with its coverage (22/40, 16/20)
  rather than implying a completed run.
- **This machine's real memory headroom exhausted a first, wider CV grid** (P-30) —
  fixed by capping tree depth and running CV sequentially rather than in parallel.
- **A stale `JAVA_HOME` from a different machine sat masked by variable precedence**
  in this machine's local `.env` (P-31) — found only because D-027's preflight check
  was written and tested against a deliberately broken environment.

### Both Week 4 decisions this section depends on

- **D-024 (Week 3) is what this week is judged against** — MAE, not RMSE or R2, and
  the corridor mean's 36.1 min, not OSRM's 107.1.
- **D-026 decided the document-agent's quota constraint is reported as coverage
  beside every accuracy number**, not treated as a run that silently completed.
- **D-028 decided document-extraction F1 is micro-averaged over (document, field)
  pairs**, with a correctly-returned null counted as neither a hit nor a miss —
  verified against a null-baseline extractor that scores exactly 0.000 F1.

### Gate 4

All three legs are on their branches: batch ML complete with the beat-OSRM headline
(Lahari, this section), Document Intelligence Agent extracting with measured accuracy
(Krishna + Lahari's D5 harness together), and the auto-retraining loop running
end-to-end with a real promoted champion (Mounika). `ruff` clean and the full test
suite passing on every branch (84 tests on Lahari's and Krishna's, including the new
`test_retrain.py` and `test_doc_eval.py` suites — Mounika's branch adds 9 more of its
own). Merge and tag status recorded once `dev` → `main` actually happens, per
GIT_RULES §6.

## Week 5 — streaming

*Pending. See `benchmarks/streaming_throughput.md`.*

## Week 6 — agent evaluation and results freeze

*Pending. See `benchmarks/agent_evaluation.md`.*

## Week 7 — scale appendix

*Pending. See `benchmarks/scale_appendix.md`.*
