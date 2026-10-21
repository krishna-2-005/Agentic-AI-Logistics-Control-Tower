# Corridor-Level Localisation and Correction of Systematic Route-Planner Error in Road-Freight Logistics

*Draft v0.2 for ICCCI 2027 (D-052); v0.2 adds the model and data cards, the agent ablation, related work with verified citations and threats to validity (WP-10). Authors withheld for double-blind review. Every number
below is read from a file in `benchmarks/raw/`; `benchmarks/experiments_appendix.md` maps
each file to the command that regenerates it. Figures are in `docs/figures/`.*

---

## Abstract

Route-planning estimates are used to schedule road freight, and the OSRM estimate recorded in
Delhivery's public trip data is wrong in one direction almost every time: 98.3% of 26,369
origin-destination legs run over it, and the median leg takes 2.00× the estimate. A one-sided
error is systematic; whether it is also concentrated by corridor is an empirical question, and
the one this paper answers. We test every
corridor with at least ten legs against the rest of the network, using Welch's t-test on
log time ratios with Benjamini-Hochberg control at 5%, and find **273 corridors
significantly slower and 512 significantly faster** than the network, covering 78.6% of
legs. We then show that this answer depends heavily on one parameter: raising the support
floor from ten legs to thirty produces a top-20 list with **no corridor in common**. On the
prediction side, a gradient-boosted model trained on the residual over a per-corridor median
reaches 30.90 minutes mean absolute error against the median's 33.04, winning on all fourteen
evaluation slices, with most of the gain on corridors that have no history. We report two
engineering findings that affect how such systems are evaluated: a default optimiser setting
that silently disabled the loss function the model was chosen for, and a replay-based
evaluation that scored early events against later history and inflated a reported alert
precision from 58.6% to 72.1%. The audit's aggregation stage runs unchanged on 56.4 million proxy rows.

---

## 1 · Introduction

A route planner's estimate is a plan, and a plan that is consistently optimistic is still
useful if the operator knows *where* it is optimistic. Delhivery's public trip records carry
both a planned time recorded from OSRM and the realised time for every leg, which makes the
question answerable directly from operational data rather than by simulation.

The premise is a single observation (**Figure 1**): across 26,369 legs, **98.3% exceed their
planned time** and the **median leg runs at 2.00× plan** `[w1_leg_summary.csv]`. That is
one-sided bias: noise would centre on 1.0, so the error is systematic. A systematic error is not
automatically localised: it could be spread evenly over the network, in which case a single
correction factor would remove it. Whether it concentrates in particular corridors is an
empirical question, and the audit in §4 is the test of it.

This paper makes four claims, in order of importance:

1. **An FDR-controlled corridor audit localises the planner's error**: 273 corridors
   significantly slower and 512 significantly faster, of 1,130 tested (§4).
2. **The support threshold decides the answer**: at 10 and 30 legs the top-20 lists are
   disjoint — a methodological warning for any corridor-level analysis (§4.3).
3. **A residual correction over the fair baseline**: 30.90 min MAE against a per-corridor
   median of 33.04, winning on every slice, with the gain concentrated where the baseline
   has no history (§5).
4. **Two evaluation traps we fell into and report**: an MLlib setting that made the chosen
   loss inert, and a streaming replay that leaked future history into alert scoring (§5.4,
   §7.2).

We also describe the surrounding system — a streaming path that serves the batch model with
bit-identical predictions, and a small agent layer built on a deliberate design position —
because the evaluation findings only make sense in context. We do not claim to "beat" the
planner: the OSRM estimate has no access to corridor history, and a model that does is not a
fair comparison. OSRM is reported as context throughout.

## 2 · Related work

**Route engines as the thing measured.** The planned times in our data come from OSRM, an
open-source route planner built on contraction hierarchies over OpenStreetMap [9]. A route
engine estimates the travel time of the best route from per-road-class speed profiles; it has
no notion of hub dwell, loading or a particular corridor's history. Our audit treats its
estimate as a measurement to be checked against outcomes, corridor by corridor, rather than
as a feature to be improved in isolation.

**Residual prediction over a route engine.** DeeprETA [2] post-processes a route planner's
ETA with a deep residual network and reports lower mean and median absolute error than
competitive regression baselines, at the highest query volume of any model at its company.
Our formulation in §5 was arrived at independently and has the same structure: predict the
correction, not the total. We differ in aim, using the model as secondary to localising
*where* the engine is wrong, in scale (a gradient-boosted model on 26,369 legs), and in
reporting the correction's behaviour by slice, which shows that most of its gain is on
corridors with no history.

**Delivery-time prediction.** Gradient boosting is a strong, cheap baseline for delivery
times: on postal data, LightGBM and CatBoost were the most accurate and efficient of the
models compared [10]. Wen et al. survey route and time prediction for instant delivery [3];
by their taxonomy this work is time-only, supervised and non-deep, on line-haul freight
(hours, inter-city) rather than instant delivery (minutes, urban). Deep models for pick-up
route prediction [4] and for timely-rate prediction under anomalies [5] address adjacent
problems with far richer trajectory data.

**Corridor-level travel-time reliability.** Transport research measures freight corridors
with descriptive reliability indices (planning-time and buffer indices, percentile spreads,
fitted distributions), typically from GPS probe data [6]. We share the unit of analysis and
add significance testing with multiplicity control [7, 8], which turns "this corridor looks
unreliable" into "this corridor is slower than the network at a 5% false discovery rate".

**Language-model agents for operations.** Agents that interleave reasoning with tool calls
[11] are now surveyed as a field [12], and the Model Context Protocol [14] standardises how
such agents reach tools and data. Closest to our design position is OptiGuide [13], where a
language model answers supply-chain questions by editing an optimiser's input and explaining
its output, while the optimiser makes the decision. Our agents make the same division more
strictly: every verdict is computed by code, and the model writes only the sentence a person
reads (§7).

**Control towers.** In supply-chain practice a *control tower* is a central point of
visibility and coordination over shipments; Trzuskawska-Grzesińska collects business cases
and argues that whole-chain visibility needs control towers to be integrated with one
another [15]. Our system takes the name for the same role — one view of the network's
corridors, live alerts and the agents acting on them — and contributes an evaluated
prototype rather than a business case.

**On this dataset.** Searches in September and October 2026 found feature-engineering
notebooks and case studies using the Delhivery records, comparing actual against OSRM time,
and **no peer-reviewed study**. There is therefore no published result on these data to put
in a comparison row; we report every result beside a trivial policy computed on the same
set instead; if published, ours would be the first baseline on the dataset.

## 3 · Data and preparation

The raw records are 144,867 scan-level segment rows across 14,817 trips
`[clean_v1/_quality_report.json]`. Cleaning repairs types and keys and drops no rows. Segments
are reconstructed into **26,369 origin-destination legs** on **2,783 corridors**
`[w2_audit_report.json]`, each carrying planned time, realised moving time and scan
timestamps.

**What the planned time is, and what we cannot know.** The planned time is the dataset's
`osrm_time` column (and `osrm_distance`); its name says it comes from OSRM, an open-source route
planner, and the dataset documents nothing more. We call it "the OSRM estimate recorded in the
dataset". We cannot know how, or whether, Delhivery used it operationally, which OSRM version or
speed profile produced it, or whether the carrier's own planning had access to corridor history.
We therefore make no claim about the carrier's planning system: the error we measure is the
error of this recorded estimate, against realised time, directly and not by simulation.

**Dwell is separated from movement.** Realised `actual_time` is moving time; dwell at the hub
is the scan-to-scan interval minus it. The median leg spends **49 minutes, 34.6% of its wall
clock**, parked `[w2_hub_dwell.csv]`. This distinction matters twice later: a leg's *finish*
is its scan-out timestamp, not departure plus moving time — an earlier version of our
pipeline used the latter, placed every finish a median 49.6 minutes early, and counted
unfinished legs as history (§3.1).

### 3.1 As-of features

Every feature describing a corridor's or hub's history is computed only from legs that had
**finished** before the leg being predicted was **created**, with facts ordered before
queries on a tie. 11.1% of legs have no prior history on their corridor
`[w3_baseline_report.json]`; they carry an explicit cold-start indicator rather than a zero
that would read as "known to be zero".

Because a leakage rule is a claim, we verified it: an independent pandas reconstruction of
the as-of history agrees with the Spark implementation on **100% of warm legs**
`[w7_ml_diagnostics.json]`. Before the finish-time correction above, agreement was 95.2%,
which is how that error was found.

## 4 · The corridor audit

### 4.1 Method

For each leg the statistic is the log of realised ÷ planned time, which makes the comparison
multiplicative and symmetric. Each corridor with at least ten legs is tested against **the
rest of the network** with Welch's unequal-variance t-test; the comparison group's sums are
derived by subtracting the corridor's own from the network totals, so 1,130 tests need one
pass over the data. p-values are corrected by Benjamini-Hochberg at 5%. The support floor was
lowered from 30 to 10 legs during the work; §4.3 reports what that choice does.

### 4.2 Result

**273 corridors are significantly slower and 512 significantly faster** than the network, of
1,130 tested, and the tested corridors cover **20,739 of 26,369 legs (78.6%)**
`[w2_audit_report.json]` (**Figure 2**). The worst corridor runs **13.9×** the network's
typical overrun (**Figure 3**) `[w2_top20_bottlenecks.csv]`; 70 of the 273 slow corridors are
intra-city, an operational problem distinct from long-haul delay.

That more corridors are confirmed *faster* than slower is itself informative: the planner's
optimism is not uniform, and a network-wide correction factor would make 512 corridors worse.

### 4.3 The support threshold decides the answer

At a 30-leg floor only 99 corridors are testable; 34 are significantly slower and 36 faster,
and the worst runs 1.92× `[w2_corridor_audit_support30.csv]`. **Its top-20 list shares no
corridor with the 10-leg list**, and its worst corridor is milder than the 10-leg list's
fifteenth (**Figure 4**).

Neither list is wrong. A higher floor keeps only heavily used corridors, which are
systematically less extreme; a lower floor admits thinly observed corridors whose large
effects survive FDR control because they are large. The consequence for practice is that a
"top bottlenecks" list is conditional on a support choice that papers rarely state. We state
ours, and argue that any corridor-level ranking should report at least two floors.

## 5 · Predicting the gap

### 5.1 Setup and baselines

The split is chronological — the last 20% of legs by creation time, **21,095 train and
5,274 test** `[w3_baseline_report.json]` — because a random split scores a model on legs
interleaved in time with its training data, which is not how it would be deployed. The metric
is mean absolute error in minutes.

The fair baseline follows from the metric. MAE is minimised by the median, so the right
comparator is the **per-corridor as-of median**, not the mean (**Table 1**,
`[w7_model_metrics_v2_stepsize.csv]`, `[w7_model_metrics_v2.csv]`):

| model | test MAE (min) |
|---|---|
| OSRM plan (context, not a comparator) | 107.09 |
| Random Forest, squared loss, raw target | 36.89 |
| per-corridor mean | 36.13 |
| **per-corridor median (the bar)** | **33.04** |
| GBT on the median residual, stepSize 0.05 | 32.52 |
| **GBT on the median residual, stepSize 1.0 (reported)** | **30.90** |
| single-node reference, absolute loss (not a candidate) | 29.52 |

Using the mean as the bar would have flattered every model by 3.1 minutes.

### 5.2 Residual formulation

The model is trained on `gap − corridor median` and its prediction is added back to the
median, so a model that learns nothing reproduces the baseline exactly. Features are the
leg's own planned time, distance and departure time; as-of corridor and hub history; and a
second feature table adding corridor dispersion (p90, IQR, standard deviation), a trailing
seven-day corridor mean, and hub dwell by departure hour.

### 5.3 Selection protocol

The one hyperparameter varied was chosen on a second chronological cut of the training
split, and the chosen model was refit on the full training split and scored **once** on test.
We fixed this procedure in writing before running it, including the commitment to adopt
whatever the test score turned out to be.

On validation, **every step size lost to the median** (best 30.17 against 29.89); on test the
chosen one won by 6.5%. We applied the rule as written rather than reopening it once the test
score was known.

### 5.4 An optimiser setting that disabled the loss

Our first residual model, gradient-boosted trees with absolute loss at the default-like step
size of 0.05, reached 32.52 — clearing the bar by 1.6%, but losing to the median lookup on
every corridor with history; the whole margin came from 294 legs on unseen corridors.
Reading the saved model explained why. MLlib's absolute-loss GBT fits its first tree to the
raw target with squared error (leaf values from −1,382 to +2,605 minutes), and every later
tree to the *sign* of the error, with leaf values in [−1, 1] scaled by the step size. At 0.05,
199 corrective trees can move a prediction by at most **9.95 minutes in total**. The loss
function the model was chosen for was barely switched on.

Validation over step sizes {0.05, 0.3, 1.0} — correction caps of 9.95, 59.7 and 199 minutes —
confirmed the mechanism in the ordering of the results.

### 5.5 Where the gain is

The reported model wins on all fourteen slices — by corridor support, route type, distance
band and departure hour (**Figure 5**). **Most of the margin, however, comes from the 294 test
legs whose corridor has no history** (111.2 → 75.9 min, −1.97 of the −2.14 overall); on
corridors with history the model beats the lookup by 0.02 to 0.51 minutes (**Figure 6**).
The model is a large improvement where a lookup table has nothing to say, and a small one
everywhere else. The single-node reference's 29.52 marks the remaining headroom for the MLlib
configuration.

## 6 · Streaming

A producer replays legs as two event kinds — a *query* at creation and a *fact* at finish —
and a Spark Structured Streaming job joins each query to the corridor and hub history, scores
it with the batch model, and writes an alert when the prediction crosses twice the planned
time.

**Equivalence.** The reported model is the one the stream serves. Its history features —
including seven-day windows over event time and dwell keyed by hub and part of the day —
are kept as event-time state per corridor and hub, and folded with the same arithmetic order
Spark uses in batch. Through the running job, over the full 52,738-event replay and across a
restart from the state store, **26,369 of 26,369 legs score bit-identically to batch**
(500 of 500 in the acceptance sample), no history feature differs on any leg, and the stream's
own test-split predictions give the reported 30.90 minutes `[w10_stream_validation_v2.json]`. Replaying the same
2,000 legs through a live Kafka broker and through the file source produces **the same 1,347
alerts on the same legs with the same predicted gaps** (maximum difference 0.0)
`[w7_kafka_source_equivalence.json]`.

**Throughput.** Over the full 52,738-event replay with a stateless history join, the producer
sustained 886 events/s and the job scored at 740 events/s, with event-to-alert latency p50
28.9 s and p95 38.0 s on one 20-core machine `[w5_stream_throughput_full.json]`. Keeping
event-time state costs throughput: the stateful job scored 74 events/s of busy time on the
same machine `[w10_stream_validation_v2.json]`, ample for the real event rate and too slow
for a one-minute replay of three weeks.

**Alerting is a workload decision.** For the best classifier, raising the delay threshold
from 1.15× to 2.0× moves the Matthews correlation only from 0.507 to 0.536 while the share of
legs alerted falls from 98% to 49% (**Figure 7**) `[w5_threshold_sensitivity.csv]`. The
threshold is a policy about how many alerts an operator can act on, not a quality dial.

## 7 · The agent layer as a design position

### 7.1 Verdicts computed, prose generated

Five agents — document extraction, order entry, exception triage, invoice audit and an
analytics assistant — share one rule: **every verdict is computed, and a language model
writes only the sentence a person reads**. Severity is arithmetic over how far past its
threshold a leg is predicted to run; an invoice verdict is four comparisons. The rule makes
each agent decision reproducible, and therefore scorable, and it bounds what a model error
can do to a sentence. Evaluation sets are authored by someone other than each agent's builder.

Measured against trivial policies on the same sets `[agent_evaluation.md]`: order entry filed
or clarified **50 of 50** templated emails correctly, with no invented order (always-file:
50%); invoice audit disputed with **100% precision and 82.2% recall**, all misses being one
seeded kind that falls inside the auditor's own tolerance; document extraction scored
**97.9% of fields** (clean 98.7%, degraded scan 96.9%) with one hallucinated field in 280, on
20 of 40 planned rows; the analytics assistant's model-written answers were judged grounded
in **17 of 18** cases, and its two refusal layers together refused **all six** out-of-scope
questions.

These sets are small: a perfect score on twenty cases is consistent with a true rate of 84%.
Re-run at scale, stratified so the hard cases are a named share, with Wilson 95% intervals
and no model calls `[w9_order_eval.json]`, `[w9_invoice_eval.json]`, `[w9_lifecycle_eval.json]`:
order entry scored **85.0% [79.4–89.3%] on 200 emails held out**, falling to 70.0% on the
adversarial half, where every error was an order filed on a value the email never stated;
invoice audit was correct on **90.0% [85.1–93.4%] of 200 invoices with no correct invoice
disputed**, the misses being the one kind that falls inside the auditor's tolerance; and the
orchestrator routed **100 of 100 lifecycles** as the email deserved [96.3–100%], exercising all
three paths through its graph.

The one groundedness failure is worth describing: asked how many corridors are
statistically slower, the model counted the three slower corridors among its five retrieved
passages and answered "3". Every number was in its context, so a mechanical check passed it;
the error was the generalisation. Conversely, asked which hub has the longest dwell *time*,
the model answered from the numbers it was given and was right where our own table route —
which sorted by dwell *share* — and our own expected answer were wrong.

### 7.2 A replay that scored the past with the future

The exception agent's notification precision was first measured at **72.1%** against 54.1%
for alerting every leg. The measurement replayed the earliest 2,000 legs through the
streaming job — and the job joins each query to the *latest* history snapshot. Live, that is
history up to now; on a replay it is history up to the end of the data. **1,290 of the 2,000
replayed legs had no corridor history at their own creation time and were scored as if they
had fourteen prior legs.**

Scoring the same legs with only the history each had at its own time
`[w8_replay_leakage.json]`, precision is **58.6%**, and by severity 39.7 / 51.3 / 76.6 / 85.3%
against 53.2 / 68.6 / 85.1 / 91.8% as first measured (**Figure 9**). The snapshot run
reproduces the first measurement exactly, so the gap is the leak and nothing else. The
qualitative claim survives — precision rises monotonically with severity, so the grade is a
useful filter — but the gain over the trivial policy is 4.5 points, not 18.

The general lesson is about evaluating streaming systems: **a replay is only an evaluation if
every join inside it is as-of the event being replayed.** Our stream-equals-batch test could
not catch this, because both of its paths read the same feature row; it proved the event
format lossless, not the running job's history correct.

### 7.3 What the language model adds: an ablation

The design position in §7.1 makes a direct question answerable: what does each agent lose
or gain when the language model is removed, or given the decision? Table 2 sets the
measured configurations side by side. A dash is a configuration not measured, not an
assumed result.

**Table 2.** Agent configurations. *Rules*: deterministic code decides and templates write.
*+ LLM phrasing*: the same decision, worded by the model. *LLM decides*: the model makes the
decision. *Human*: a second person's labels.

| agent (set) | rules | rules + LLM phrasing | LLM decides | human |
|---|---|---|---|---|
| Order entry (Week 5, 50 emails) | **50 / 50** | — | **50 / 50** | — |
| Order entry (200 emails, held out) | **85.0%** [79.4–89.3] | — | — | — |
| Analytics assistant (30 questions): route accuracy | 90.0% | **93.3%** | — | — |
| Analytics assistant: out-of-scope refused | 3 / 6 | 4 / 6 by the model layer, **6 / 6** with both layers | — | — |
| Analytics assistant: answers grounded | extractive by construction | **17 / 18** | — | — |
| Exception agent: notification precision (as-of) | **58.6%** (verdict computed; wording does not change it) | same verdicts | — | — |
| Document extraction (20 rows) | — | — | **97.9%** of fields | — |

Sources: `[w5_order_eval_summary.json]`, `[w9_order_eval.json]`, `[w7_assistant_run_no_llm.json]`,
`[w7_assistant_run_llm.json]`, `[w8_replay_leakage.json]`, `[w7_doc_extraction_eval.json]`;
the assistant's groundedness was judged by hand on the saved answers.

Three readings. First, on the 50-email set the model deciding and the rules deciding are
indistinguishable, so that set cannot separate them; separating them needs the 200-email set
scored with the model deciding, which the free tier's daily budget of 20 calls has not yet
allowed. Second, where the model only phrases, its measurable contribution is at the edges:
three more points of route accuracy and one more refusal, with one ungrounded answer in
eighteen (§7.1). Third, document extraction is the one agent where the model decides and no
rule baseline exists; it is also the one result resting on 20 of 40 planned rows. The empty
*human* column is the clearest gap: no agent decision has yet been compared against a second
labeller.

## 8 · Scale

The audit's two aggregation functions, imported unchanged, were run on NYC taxi trip records
mapped into the leg shape (the planned time is a stated stand-in, and no gap statistic is
reported from these data). **56,353,613 rows aggregate in 14.32 s on 20 cores**
(3.9 million rows/s) `[w7_scale_benchmark.json]` (**Figure 8**). Two readings are
unflattering and belong here: at this project's own size the runtime is Spark's fixed cost —
26,369 legs and 2.9 million trips both take 2.4 s — and five times the cores bought only
1.24× the speed, because 914 MB from one disk is IO-bound.

## 9 · Threats to validity

**External validity: one carrier, three weeks.** Every network result is about one operator's
network in one country over 22 days of leg creation (12 September to 3 October 2018). The
audit, the model and the support-floor result describe that network; whether the corridors
the audit flags are stable over months, or across carriers, is untested. The data card
(`docs/data_card.md`) lists what these data cannot support.

**Construct validity: synthetic scaffolding.** The agents read documents, emails and invoices
generated by this project, and post to a mock transport management system. Their scores
therefore measure the pipeline against our own generator, not the world; the invoice
auditor's rate band is the corpus's own pricing model and says nothing about real freight
rates. Only the network data is real.

**Internal validity: replay evaluations.** A streaming replay joined every query to history
from the end of the data and inflated an alert precision from 58.6% to 72.1% (§7.2). The
served model now uses event-time state, which is as-of by construction, and the evaluation
that matters was re-run as-of; but any further replay-based measurement inherits this risk,
and our stream-equals-batch test alone would not catch it.

**Statistical conclusion validity: set sizes.** Agent evaluations range from 20 to 200 cases.
Small sets are reported with their size beside the rate, and the 200-case runs carry Wilson
95% intervals (§7.1). Document extraction rests on 20 of 40 planned rows, the assistant's
groundedness on 18 judged answers. On the model, the validation cut favoured the median
baseline (29.89 against 30.17) while the test split favoured the model (33.04 against 30.90);
both are reported, and adoption followed a rule fixed before the test split was scored
(§5.3).

**Evaluator independence.** Each agent's evaluation set was authored by someone other than its
builder, but no agent decision has been labelled by a second person to measure agreement
(Table 2, *human*). The groundedness judgements were made by one reader.

**Serving conditions.** The public system runs on free tiers: the API on a 512 MB host that
sleeps when idle, the language model under a daily cap of 20 calls. These bound sample sizes
for model-written results and the latency a first visitor sees, not the measurements above,
which were taken on one 20-core machine. The public predictor answers for "today" from each
corridor's history as it stood at the end of the data.

## 10 · Conclusion

The recorded OSRM estimate's error on this network is systematic and localisable: an FDR-controlled
audit identifies the corridors where it is wrong in either direction, and the choice of
support floor changes which ones. A residual model over a per-corridor median improves
prediction most where history is absent. Two of our findings are about evaluation rather
than the network — an optimiser default that disabled the chosen loss, and a replay that
leaked the future into alert scoring — and both were found only by comparing a number with
the same number computed another way. The reported model is now served on event-time state with predictions identical to batch on
every leg. Future work: scoring the agents with the model deciding at scale and against a
second human labeller (Table 2), a live-deployment evaluation of alert precision, and
extending the audit to a longer period to test whether the corridors it flags are stable.

---

## References

*Verification status per entry is in `docs/references.md`; metadata below was checked against
the source's own listing on 14 October 2026. Format to the venue before submission.*

1. Delhivery logistics trip records, public release on Kaggle.
   <https://www.kaggle.com/datasets/devarajv88/delhivery-logistics-dataset>
2. X. Hu, T. Binaykiya, E. Frank and O. Cirit, "DeeprETA: An ETA Post-processing System at
   Scale," arXiv:2206.02127, 2022.
3. H. Wen et al., "A Survey on Service Route and Time Prediction in Instant Delivery: Taxonomy,
   Progress, and Prospects," arXiv:2309.01194, 2023.
4. "DRL4Route: A Deep Reinforcement Learning Framework for Pick-up and Delivery Route
   Prediction," arXiv:2307.16246, 2023. *[authors and venue to confirm]*
5. "DeepSTA: A Spatial-Temporal Attention Network for Logistics Delivery Timely Rate
   Prediction in Anomaly Conditions," arXiv:2505.00402. *[authors and venue to confirm]*
6. FHWA, "Freight Performance Measurement: Travel Time in Freight-Significant Corridors."
   *[to read in full]*
7. B. L. Welch, "The generalization of Student's problem when several different population
   variances are involved," *Biometrika* 34(1–2), 28–35, 1947.
8. Y. Benjamini and Y. Hochberg, "Controlling the false discovery rate: a practical and powerful
   approach to multiple testing," *J. R. Stat. Soc. B* 57(1), 289–300, 1995.
9. D. Luxen and C. Vetter, "Real-time routing with OpenStreetMap data," in *Proc. 19th ACM
   SIGSPATIAL Int. Conf. on Advances in Geographic Information Systems (GIS '11)*, Chicago,
   pp. 513–516, 2011.
10. J. Khiari and C. Olaverri-Monreal, "Boosting Algorithms for Delivery Time Prediction in
    Transportation Logistics," in *2020 Int. Conf. on Data Mining Workshops (ICDMW)*, IEEE,
    2020. doi:10.1109/ICDMW51313.2020.00043. arXiv:2009.11598.
11. S. Yao, J. Zhao, D. Yu, N. Du, I. Shafran, K. Narasimhan and Y. Cao, "ReAct: Synergizing
    Reasoning and Acting in Language Models," in *Proc. ICLR*, 2023. arXiv:2210.03629.
12. L. Wang, C. Ma, X. Feng et al., "A survey on large language model based autonomous
    agents," *Frontiers of Computer Science* 18(6), 186345, 2024.
    doi:10.1007/s11704-024-40231-1.
13. B. Li, K. Mellou, B. Zhang, J. Pathuri and I. Menache, "Large Language Models for Supply
    Chain Optimization," arXiv:2307.03875, 2023.
14. Anthropic, "Model Context Protocol," open standard announced 25 November 2024.
    *[cite the specification's own page before submission]*
15. A. Trzuskawska-Grzesińska, "Control towers in supply chain management – past and future,"
    *Journal of Economics and Management* 27(1), 114–133, 2017. doi:10.22367/jem.2017.27.07.
