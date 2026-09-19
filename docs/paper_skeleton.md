# Paper skeleton — methodology and results (W8 D5)

**Owner: Lahari.** Companion to `docs/paper_outline.md`. This is the draft's scaffolding:
topic sentences, the order of the argument, and **every number with the file it comes
from**. Prose gets written over it; numbers do not get typed in from memory.

Convention below: `[w2_audit_report.json]` means the value is read from
`benchmarks/raw/w2_audit_report.json`. `benchmarks/experiments_appendix.md` maps every such
file to the command that regenerates it.

---

# 3 · Method

## 3.1 Data and leg reconstruction

**Topic sentence:** the unit of analysis is an origin-destination leg, which the raw
records do not contain.

- Source: Delhivery's public trip records, **144,867 rows** of scan-level segments across
  **14,817 trips** `[data/processed/clean_v1/_quality_report.json]`. Stage 1 drops none of
  them: the cleaning step is type and key repair, not filtering, and the report says
  `rows_dropped_total: 0` so that claim is checkable.
- Reconstruction: segments → **26,369 OD legs** across **2,783 corridors**
  `[w2_audit_report.json]`.
- Each leg carries a planned time (`osrm_time`, the production routing engine's estimate)
  and a realised time (`actual_time`), and the target is their difference.
- **Dwell is separated from movement.** `actual_time` is moving time; hub dwell is
  `start_scan_to_end_scan − actual_time`, median **49 minutes, 34.6% of wall clock**
  `[w2_hub_dwell.csv]`. Every later section that says "finish time" means the scan-out
  timestamp, not departure plus moving time — the distinction cost us a bug in two places
  (P-52).

## 3.2 As-of features, and why the rule is strict

**Topic sentence:** every feature is computed from legs that had **finished** before the
leg being predicted was **created**.

- The rule, its implementation as a union of facts-at-finish and queries-at-creation, and
  the tie-break (a leg finishing at the instant another is created is history to it).
- Cold start is explicit, not imputed: **11.1% of legs** have no prior history on their
  corridor, and carry an indicator rather than a zero that reads as "known to be zero"
  `[w3_baseline_report.json]`.
- Verification, because a leakage rule is a claim: an independent pandas reconstruction of
  the as-of history agrees with the Spark implementation on **100% of warm legs**
  `[w7_ml_diagnostics.json]`. It agreed on 95.2% before P-52 was fixed, which is how the
  bug was found.

## 3.3 The corridor audit

**Topic sentence:** "this corridor is slow" is a statistical claim and is tested as one.

- Statistic: log of realised ÷ planned time per leg, so the comparison is multiplicative
  and symmetric.
- Test: Welch's t-test of each corridor against **the rest of the network**, with the
  comparison group derived by subtracting the corridor's sums from the network totals
  rather than rescanning 1,130 times.
- Multiplicity: Benjamini-Hochberg at **FDR 0.05** across all tested corridors.
- Support floor: **10 legs**, lowered from 30 during the work (D-018), and §4.2 reports
  what that choice does to the answer.

## 3.4 Prediction

**Topic sentence:** the model is asked for the correction to a strong baseline, not for
the time.

- Split: chronological 80/20 on creation time — **21,095 train, 5,274 test**
  `[w3_baseline_report.json]`. Not random: a random split scores a model on legs
  interleaved with its training data, which is not how it would be deployed.
- Metric: **MAE in minutes** (D-024). The choice matters twice over: it sets the fair
  baseline (§4.3) and it makes squared-loss training a mismatch (§4.4).
- Baselines, in increasing strength: OSRM plan, per-corridor mean, **per-corridor median**.
- Target: `gap_min − corridor median`, so a model that learns nothing reproduces the
  baseline exactly.
- Selection protocol, fixed before it ran (D-049): a second chronological cut of the
  training split chooses the one hyperparameter; the winner is refit and scored **once** on
  test; whatever that score says is adopted.

## 3.5 The agent layer

**Topic sentence:** each agent computes its verdict and generates only the sentence a
person reads.

- Five agents and an orchestrator; what each decides arithmetically and what the model
  writes (D-041).
- Evaluation sets are authored by someone other than the agent's builder (D-028), and every
  metric is reported beside the trivial policy on the same set.

## 3.6 Streaming and scale

- The event schema, the two event kinds, and the ordering rule.
- Equality test: identical legs scored in batch and through the event path, **500 of 500
  bit-identical** for the served model `[w5_stream_validation_report.json]` and for the
  adopted model `[w8_stream_validation_v2.json]`.
- Scale: the audit's own aggregation functions, imported unchanged, on NYC TLC records
  mapped into the leg shape `[w7_scale_benchmark.json]`.

---

# 4 · Results

## 4.1 The planner's error is systematic

**Topic sentence:** the planner is not noisy, it is one-sided.

- **98.3%** of 26,369 legs exceed the plan; the median leg takes **2.00×** its planned time
  `[w1_leg_summary.csv]`. **Figure 1.**
- One-sidedness is the premise for everything after it: symmetric noise would cancel and
  leave nothing to localise.

## 4.2 Where it is wrong — and how much that answer depends on one parameter

**Topic sentence:** the error concentrates in identifiable corridors, and the support floor
decides which ones.

- **273 corridors significantly slower, 512 significantly faster**, of 1,130 tested at FDR
  0.05, covering **78.6% of legs** `[w2_audit_report.json]`. **Figures 2, 3.**
- Worst corridor runs **13.9×** the network's typical overrun `[w2_top20_bottlenecks.csv]`.
- **The instability result:** at a 30-leg floor the top-20 list shares **no corridor** with
  the 10-leg list, and its worst corridor is milder than the 10-leg list's fifteenth
  `[w2_corridor_audit_support30.csv]`. **Figure 4.**
- Reading: corridor-level findings are conditional on a support choice that papers rarely
  state. We state ours and show what changing it does.

## 4.3 The baseline that a model has to beat

**Topic sentence:** the fair baseline for an MAE table is the per-corridor median, and it
is stronger than either model the project trained first.

| baseline | test MAE (min) | source |
|---|---|---|
| OSRM plan | 107.09 | `[w7_model_metrics_v2_stepsize.csv]` |
| corridor mean | 36.13 | same |
| **corridor median** | **33.04** | same |

- MAE is minimised by the median; using the mean as the bar would have flattered every
  model by 3.1 minutes.

## 4.4 What was wrong with the first model, and what fixed it

**Topic sentence:** Week 4's model lost to a lookup table for two reasons, both about the
objective rather than the features.

1. **Squared loss on an absolute-error metric.** The same features under absolute loss, in
   a single-node reference implementation, reach **29.52** `[w7_model_metrics_v2.csv]`.
2. **The step size made the fix inert.** MLlib's absolute-loss GBT fits one squared-loss
   tree and then moves each prediction by at most `stepSize` per tree: at 0.05, 199 trees
   can shift a prediction by **9.95 minutes in total** — read out of the saved model, not
   inferred.

Result: **30.90 min**, 6.5% under the median bar, winning on **all 14 slices**
`[w7_model_metrics_v2_stepsize.csv]`. **Figures 5, 6.**

**The sentence that must travel with that number:** most of the gain is on the 294 test
legs whose corridor has no history (111.2 → 75.9 min, −1.97 of the −2.14 overall); on
corridors with history the model beats the lookup by 0.02 to 0.51 minutes.

**And the sentence that must travel with the protocol:** on the validation cut, *every*
step size loses to the median (best 30.17 against 29.89). The rule was applied as written
rather than reopened once the test score was known.

## 4.5 Alerting is a workload decision, not a quality one

- The logistic classifier holds MCC **0.507 → 0.540** across thresholds while the share of
  legs alerted falls **98% → 49%** `[w5_threshold_sensitivity.csv]`. **Figure 7.**
- The stream's own flag is weaker at every threshold (0.315 → 0.477) — reported because it
  is the classifier actually running.

## 4.6 The agent layer, measured

- Order entry: **50 of 50**, clarification precision and recall **100%**, zero invented
  orders `[w5_order_eval_summary.json]`; trivial policy "always file" scores 50%.
- Exception triage, **as-of**: precision **58.6%** overall, **85.3%** at critical, against
  **54.1%** for alerting every leg `[w8_replay_leakage.json]`. **Figure 9.** First published
  as 72.1% / 91.8% from a replay that scored early legs with end-of-data history; the paper
  reports both and the reason (D-054, P-62) — it is a finding about evaluating streaming
  systems in its own right.
- Invoice audit: **100% precision, 82.2% recall**; all eight misses are one seeded kind, an
  overcharge inside the auditor's own 15% tolerance `[w6_invoice_eval.json]`.
- Document extraction: **98.0%** of fields correct, clean 97.6% vs noisy 98.6%, **zero
  hallucinated fields** on 11 of 40 planned rows `[w7_doc_extraction_eval.json]`.
- Analytics assistant: route **90%**, source **83.3%**, refusal precision **100%** and
  recall **50%** `[w7_assistant_run_no_llm.json]`. The recall number is the interesting
  one and §5 discusses it.

## 4.7 Streaming and scale

- **886 events/sec** sustained, **740/sec** scoring, event-to-alert p50 **28.9 s**, p95
  **38.0 s**, on 20 cores and a 4 GB driver, from a file source
  `[w5_stream_throughput_full.json]`.
- The same aggregation, unchanged, on **56,353,613 rows in 14.32 s**; and on 4 cores,
  17.75 s — a **1.24× speedup for 5× the parallelism**, because 914 MB from one disk is
  IO-bound `[w7_scale_benchmark.json]`. **Figure 8.**

---

# 5 · Discussion — the three places we would be challenged

1. **"Your model barely beats a lookup table."** On corridors with history, correct, and
   the paper says so in the same sentence as the headline. The defensible claim is the
   cold-start one: −35 minutes where a lookup has nothing to say.
2. **"Your agents are not agents."** Also correct, and it is the design position: verdicts
   computed, prose generated, therefore reproducible and scorable. The refusal gate's 50%
   recall is the cost of the same honesty — we publish it rather than tuning the gate on
   the test set.
3. **"145,000 rows is not big data."** Correct, which is why the scale appendix exists and
   why the word is "distributed" without it.

## What is owed before submission

- Document extraction rows 12-40 (quota).
- Assistant groundedness, hand-judged (needs the model-phrased run).
- Citations: the related-work table in the outline lists five works, two read in full.
