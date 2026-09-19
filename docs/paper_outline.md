# Paper outline (G-09)

**Owner: Lahari** (execution plan v3.1 W8 D3-D4, §4.1). Target: **ICCCI 2027, submission
20 February 2027**, 4-10 pages, double-blind (D-052). arXiv preprint when the draft is
done, not when the venue answers.

Every section below names the frozen result it rests on. A section with no result assigned
does not get written.

---

## Title (working)

**"Where is the planner wrong? Corridor-level localisation of systematic routing error in
a national logistics network"**

The title is deliberately about the audit, not about agents or about beating a model. §4.2
of the plan forbids the other two headlines, and for good reasons repeated below.

## Contributions, in the order the paper claims them

| # | claim | evidence | figure |
|---|---|---|---|
| 1 | An FDR-corrected corridor audit localises where a production routing engine is systematically wrong: **273 slower and 512 faster of 1,130 corridors**, covering 78.6% of legs | `w2_corridor_audit.csv`, `w2_top20_bottlenecks.csv` | fig2, fig3 |
| 2 | **The support threshold decides the answer.** Top-20 lists at a 10-leg and a 30-leg floor share **no corridor**, and the 30-leg list is far milder | `w2_corridor_audit_support30.csv` | fig4 |
| 3 | Alerting is **threshold-insensitive in quality, sensitive in workload**: the logistic classifier holds MCC 0.507→0.540 while alert volume falls 98%→49% of legs. The stream's own flag is the weaker classifier at every threshold (0.315→0.477) | `w5_threshold_sensitivity.csv` | fig7 |
| 4 | A learned **residual correction over a strong per-corridor baseline** reaches 30.90 min MAE against the median baseline's 33.04, winning on all 14 slices — with the gain concentrated on corridors with no history | `w7_model_metrics_v2_stepsize.csv` | fig5, fig6 |
| 5 | Streaming serves the batch model with **bit-identical predictions** (500/500) at 886 events/sec, p50 28.9 s event-to-alert | `w5_stream_validation_report.json`, `w5_stream_throughput_full.json` | — |
| 6 | A **deterministic-core agent architecture**: verdicts computed, prose generated, so every decision is reproducible and scored — five agents, each against a trivial policy | `benchmarks/agent_evaluation.md`, `final_tables.md` | fig9 |
| 7 | Document extraction with a **clean-vs-degraded split and a hallucination rate** (0 of 153 fields) | `w7_doc_extraction_eval.json` | — |
| 8 | The corridor-aggregation code runs **unchanged at 56.4M rows**, with the runtime table and its ceiling | `w7_scale_benchmark.json` | fig8 |

**Claim 5 is now complete** — the live-broker run happened on a native Kafka broker, with
alerts identical to the file source (D-055). **Claim 7 rests on 20 of 40 planned rows**; the
rest run on the daily LLM quota, and the draft says so beside the number.

---

## Section plan

### 1. Introduction
The premise in three numbers, all from `w1_leg_summary.csv`: 26,369 OD legs, **98.3% run
over the plan**, median leg takes **2.00×** its planned time. One-sidedness is the argument
— noise cancels, so a systematic error should be localisable. Contributions list above.

### 2. Related work
Three strands, and an honest note about the dataset. Table below.

### 3. Data and preparation
Delhivery's public trip records (145,000 rows → 26,369 OD legs after reconstruction).
Stage-by-stage: clean → reconstruct legs → hub dwell → as-of feature table. **Figure: none
needed; a table of row counts per stage.** The leakage rule (D-020: every feature computed
from legs that had *finished* before the query leg was created) belongs here, because it is
what makes §5 honest — and it is also where P-52 lives: an earlier version derived a leg's
finish time as departure plus moving time, which excluded hub dwell and counted 1,128
unfinished legs as history.

### 4. Corridor audit (the headline)
Welch's t-test on log time ratios per corridor against the rest of the network, sums
carried so the comparison group is derived by subtraction rather than 1,130 rescans;
Benjamini-Hochberg at 5%. Results: claim 1. Then claim 2 — **the methodological warning is
part of the contribution, not a limitation paragraph.** Figures 2, 3, 4.

### 5. Predicting the gap
Baselines first, in this order: OSRM (107.09), corridor mean (36.13), corridor median
(**33.04** — the bar, because MAE is minimised by the median). Then the correction sprint:
what Week 4 got wrong (squared loss on an absolute-error metric), what the diagnostics
found, and the residual formulation. The step-size finding is a genuine methods result:
MLlib's absolute-loss GBT moves a prediction by at most `stepSize` per tree, so the default
made the objective inert — 9.95 minutes of total correction across 199 trees. Selection
protocol (D-049) stated before results (D-050). Figures 5, 6.

### 6. Streaming
Same model, two paths, **500 of 500 bit-identical predictions** (max absolute difference
0.0); throughput and latency with the measurement conditions stated. Claim 5. The threshold
sweep belongs here rather than in §5: it is a policy question about alert workload, and the
figure carries both the best classifier and the stream's own flag because they behave
differently.

### 7. The agent layer as a design position
The argument, not the feature list: **verdicts are computed and only prose is generated**,
which is what makes an agent decision reproducible and therefore scorable. Five agents with
their trivial policies. The two places this costs us — the invoice auditor's 15% tolerance
blind spot, and the assistant's 50% refusal recall on domain-adjacent questions — are
reported as results, not omitted. Claim 6, figure 9.

### 8. Scale
Claim 8, figure 8, including the two unflattering readings: at this project's own size the
runtime is Spark's fixed cost, and 5× the cores bought 1.24× the speed on one disk.

### 9. Limitations and threats to validity
One dataset, one country, one operator, 21 days. The support-threshold instability (claim 2)
applies to our own top-20 list. The document and agent evaluations use synthetic corpora we
generated, so they measure the pipeline, not the world. One local broker, not a cluster. OSRM is reported as
context, never as a defeated competitor.

### 10. Conclusion and future work
Serving the adopted model (the stream carries the corridor mean, not the median, so the
residual model cannot be served today — D-053); a multi-node broker; extraction rows 21-40.

---

## Related work — the closest published work, and where we differ

| work | what it does | how we differ |
|---|---|---|
| **DeepETA** (Uber, 2022) — engineering paper, read in full | Predicts the **residual between a routing engine's ETA and the observed outcome**, with an asymmetric Huber loss chosen because MAE is the reported metric | The closest methodological precedent, and it validates our formulation independently. We differ in aim: DeepETA improves a served ETA; we *localise where the engine is wrong* and treat the model as secondary to the audit. We also report the residual model's slice behaviour, which the blog does not |
| **Wen et al., "A Survey on Service Route and Time Prediction in Instant Delivery"** (arXiv 2309.01194, 2023) — read in full | Taxonomy of route/time prediction: task type, architecture, learning paradigm | Positions our work: we are time-only, supervised, and *non-deep*. The survey's corpus is instant delivery (minutes, urban); ours is line-haul freight (hours, inter-city) |
| **DRL4Route** (arXiv 2307.16246, 2023) — abstract only | Deep RL for pick-up and delivery **route** prediction, deployed at Cainiao | Different task (route order, not duration) and a much richer data setting (courier trajectories). Cited for the deployment framing, not compared numerically |
| **DeepSTA** (arXiv 2505.00402) — abstract only | Spatial-temporal attention for delivery timely-rate under **anomaly conditions** | Adjacent motivation — systematic disruption — with a deep model and city-level data. Our anomaly analogue is the corridor audit, which is statistical rather than learned |
| **Freight travel-time reliability literature** (FHWA freight performance measures; corridor-level truck travel time from archived ITS/GPS data) — surveyed via published reports | Corridor-level reliability **indices**: planning-time index, buffer index, percentile spreads, distribution fitting | The same unit of analysis — the corridor — with descriptive indices. We add **significance testing with multiplicity control**, which turns "this corridor looks unreliable" into "this corridor is slower than the network at FDR 5%" |
| **The Delhivery dataset's own literature** | Kaggle notebooks and GitHub repositories doing feature engineering and actual-vs-OSRM comparison | **No peer-reviewed comparator was found for this dataset.** That is a claim about our search, not about the world, and the paper must say it that way. It also means our numbers cannot be compared to a published baseline on the same data — which is an argument for reporting the trivial policies we do |

**Search note for the draft:** the five entries above come from a search on 18 September
2026; two were read in full and three from abstracts or reports. Before submission, each
needs a proper citation and the arXiv entries need checking for a published venue version.

---

## What the paper must not claim (v3.1 §4.2, kept verbatim in spirit)

1. **"Beats the production planner" as a headline.** OSRM has no access to corridor
   history. A model that has seen a corridor's past beating it is not a fair fight. OSRM is
   context; the median baseline is the comparator.
2. **"Multi-agent AI" without the qualifier.** The agents are less agentic than the word
   suggests, by design. That is claim 6, stated as a position.
3. **"Big data" without the scale appendix.** 26,369 legs is not big data. Claim 8 is the
   licence for the phrase; without it, the word is "distributed".
4. **The invoice auditor as a pricing result.** Its rate band is the corpus's own generator
   (D-043). It is a document-audit result only.
5. **Anything about the model that omits where its gain is.** −35 min on 294 unseen-corridor
   legs and −0.2 min elsewhere is one sentence, not two claims.

## Ownership

| section | author |
|---|---|
| 1, 2, 4, 5, 9 | Lahari |
| 6, 8, 3 | Mounika |
| 7, figures, deck | Krishna |
| 10, assembly, submission | all three at the W8 sync |

## Open question, carried from D-052

**One paper or two.** The corridor audit (claims 1-3) and the agent-architecture position
(claims 6-7) address different audiences. This outline assumes one paper because v3.1's
claims map does. If the draft runs past ten pages with both, the audit paper goes to ICCCI
and the agent paper to a systems venue — decided at the W8 sync, not by whichever section
is written first.
