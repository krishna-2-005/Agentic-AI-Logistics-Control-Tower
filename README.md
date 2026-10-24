# Agentic AI Logistics Control Tower

**A big-data pipeline that localises where a route-planning estimate is wrong on a real freight network,
a prediction model judged against a fair baseline with confidence intervals, and a measured agent layer.**

[![tests](https://github.com/krishna-2-005/Agentic-AI-Logistics-Control-Tower/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/krishna-2-005/Agentic-AI-Logistics-Control-Tower/actions/workflows/tests.yml)
[![web](https://github.com/krishna-2-005/Agentic-AI-Logistics-Control-Tower/actions/workflows/web.yml/badge.svg?branch=main)](https://github.com/krishna-2-005/Agentic-AI-Logistics-Control-Tower/actions/workflows/web.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python 3.11–3.13](https://img.shields.io/badge/python-3.11–3.13-blue.svg)](requirements.txt)

> Sai Krishna (AI agents and automation) · Lahari (ML and evaluation) · Mounika (data and systems)

### ▶ **[Open the control tower](https://control-tower-mu-rouge.vercel.app)** — `control-tower-mu-rouge.vercel.app`

## Start here (90 seconds)

1. **Look.** The [site](https://control-tower-mu-rouge.vercel.app) shows the map, the corridor audit, the agents and every frozen number; its **Paper** page has the abstract and figures.
2. **Read.** The manuscripts are LaTeX in [`paper/conference/`](paper/conference/main.tex) (LNCS, 16 pages with references) and [`paper/journal/`](paper/journal/main.tex) (journal draft). Every number in them is a macro generated from [`benchmarks/results_freeze_v6.json`](benchmarks/results_freeze_v6.json). Build them with `make paper`; [`docs/paper_draft.md`](docs/paper_draft.md) points here.
3. **Reproduce.** `make test` runs the fast tests; `make rebuild` regenerates every result from the raw CSV and ends in `results_freeze --verify`. [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) has hardware, versions and runtimes; [`docs/install.md`](docs/install.md) has the full setup.

## What the data say, at the strength they support

The corridor audit and the model were re-examined in an upgrade pass in which every experiment was pre-registered as a
dated entry in [`docs/decisions.md`](docs/decisions.md) before it was run. Several results got weaker, and that is the point of reporting them.

| Question | Result | Source |
|---|---|---|
| Is the OSRM estimate recorded in the data one-sided? | **Yes.** 98.3% of 26,369 legs run over it; the median leg takes 2.0 times the estimate | [`w1_leg_summary.csv`](benchmarks/raw/w1_leg_summary.csv) |
| Which corridors are significantly slower? | The standard Welch + BH audit flags **273 slower and 512 faster** of 1,130 tested corridors. **That list is a screening list**: legs of one recurring service are correlated (design effect about 2), a placebo with meaningless corridor labels gives about **680** "discoveries" with the same procedure, and the cluster-aware permutation test confirms **0** at its pre-registered strictness (also at ten times the permutations). A power study shows why: that test is correctly sized but finds only about 8% of corridors (12% under BH) even when each has a 2.7-fold overrun planted in it, so its zero says little, while Welch is wrong in about 96% of its discoveries | [`b3_audit_robust.json`](benchmarks/raw/b3_audit_robust.json), [`b3_audit_robust_1e6.json`](benchmarks/raw/b3_audit_robust_1e6.json) |
| Do corridor effects persist? | **Yes, between halves of the period**: rank correlation 0.91 over 807 corridors; 97.7% of first-half slower corridors are slower again. This is persistence of recurring services, not independent replication | [`b5_stability.json`](benchmarks/raw/b5_stability.json) |
| Does shrinkage fix the support-floor instability? | **Barely.** Top-20 overlap across floors is 0.15 (empirical Bayes) against 0.10 (raw); the cause is who is eligible, not noise | [`b4_eb_ranking.json`](benchmarks/raw/b4_eb_ranking.json) |
| Is the model better than a fair baseline? | The bar is a hierarchical **back-off median** (32.39 min test MAE; the old median's 0.0-minute cold fallback was handicapping it). The **reported model** (LightGBM, L1, chosen on validation) scores **29.66 min** [27.86, 31.12], **−2.74** against the bar [−3.41, −2.11] by a day-block bootstrap, and wins on all 13 slices and in 4 of 4 rolling-origin folds. The **served model** (Spark MLlib, what the API and the stream run) scores 30.90, −1.49 against the bar [−2.25, −0.74], but beats it in only 2 of 4 rolling-origin folds (the reported model: 4 of 4). The gain is on corridors with no history (cold legs 132.97 → 87.41). The validation cut did not favour the Spark model over the bar | [`b1_backoff_baseline.json`](benchmarks/raw/b1_backoff_baseline.json), [`b2_significance.json`](benchmarks/raw/b2_significance.json), [`b6_model_zoo.json`](benchmarks/raw/b6_model_zoo.json) |
| Do the agents help? | Each agent is scored beside a trivial policy. The exception agent's as-of precision is **58.6%** [56.2, 60.9] (the first published 72.1% came from a leaking replay), **+4.45 points** over alerting on every leg, significant under the valid paired test; its lowest severity grade is *worse* than alerting on everything. A pilot ablation (18 order cases, one open model) found a model deciding in place of the rules scored 87.8% against the rules' 100% (not held out; 70% on a new held-out hard set) | [`b8_exception_stats.json`](benchmarks/raw/b8_exception_stats.json), [`b7_agent_ablation.json`](benchmarks/raw/b7_agent_ablation.json) |

> **Not claimed:** "beats the planner". OSRM has no access to corridor history, so a model that has seen it is not a fair
> comparison. **Limits, in one place:** one operator, 22 calendar days, a recorded planned time whose provenance we cannot
> know, six test days (so six bootstrap blocks), synthetic agent data, one pilot-scale agent ablation.

### Other measured results (v1.0, unchanged)

| Result | Value | Source |
|---|---|---|
| Stream equals batch | all 26,369 legs score identically in the running event-time stream job (largest difference 0.0 minutes); 52,738 events replayed, 886 events/s produced, 740 events/s of saturated scoring on the stateless path | [`w10_stream_validation_v2.json`](benchmarks/raw/w10_stream_validation_v2.json), [`w5_stream_throughput_full.json`](benchmarks/raw/w5_stream_throughput_full.json) |
| Document extraction | **97.9% [95.4-99.0]** per-field overall (274 of 280 fields, 20 of 40 planned rows; 98.7% on the clean split, 96.9% on the noisy split) | [`w7_doc_extraction_eval.json`](benchmarks/raw/w7_doc_extraction_eval.json) |
| Order entry | **50 of 50** on the Week 5 set, 0 invented orders; **85.0% [79.4-89.3]** on 200 held-out emails (70.0% on the adversarial half) | [`w9_order_eval.json`](benchmarks/raw/w9_order_eval.json) |
| Freight Invoice Auditor v1 (Week 6 development corpus; the 200-invoice stratified run is below) | **20 of 20** verdicts matched the seeded truth, no clean invoice disputed. The rate band is the corpus's own pricing model: exact here, circular as a pricing claim (D-043). On 200 stratified invoices **90.0% [85.1-93.4]** correct, 0 false disputes | [`w6_invoice_audit_runs.json`](benchmarks/raw/w6_invoice_audit_runs.json), [`w9_invoice_eval.json`](benchmarks/raw/w9_invoice_eval.json) |
| Orchestrator | 100 of 100 lifecycles routed as the email deserved, all three graph paths exercised | [`w9_lifecycle_eval.json`](benchmarks/raw/w9_lifecycle_eval.json) |
| Assistant | route accuracy 93.3% with model phrasing (90.0% without), n = 30 questions | [`w7_assistant_run_llm.json`](benchmarks/raw/w7_assistant_run_llm.json) |
| Scale appendix | the same two aggregation functions, unchanged, on **56,353,613** NYC TLC proxy rows: 51,515 corridors in **14.32 s** on a 20-core laptop (the audit's aggregation stage only) | [`w7_scale_benchmark.json`](benchmarks/raw/w7_scale_benchmark.json) |

## Two layers

**Layer 1: the big-data core.** A PySpark pipeline over about 145K real shipment segments reconstructs trips, audits
corridors, trains the models, and serves the Spark model through Kafka and Structured Streaming with event-time state; the
stream scores all 26,369 legs identically to batch.

**Layer 2: the agent workforce.** Five agents plus an orchestrator consume Layer 1's output and act on it through an MCP
tool server and a mock TMS. Every verdict is computed by code; a language model only words it, and every agent runs with
`--no-llm` (D-041). The architecture figure is [`docs/figures/fig_architecture.png`](docs/figures/fig_architecture.png).

## Where everything is

| | |
|---|---|
| **Rebuild everything** | `make rebuild` (or `bash scripts/rebuild_all.sh`); see [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md) |
| **Run the whole system** | `python -m src.common.boot` (TMS, replay, streaming, agents); `--dashboard` keeps Streamlit up |
| **Live Kafka without Docker** | `scripts/kafka_native.ps1`; alerts identical to the file source |
| **Final numbers** | [`benchmarks/final_tables.md`](benchmarks/final_tables.md), [`benchmarks/agent_evaluation.md`](benchmarks/agent_evaluation.md), [`benchmarks/experiments_appendix.md`](benchmarks/experiments_appendix.md) |
| **Figures** | [`docs/figures/`](docs/figures/): PNG and vector PDF, each from a `benchmarks/raw/` file |
| **Decisions and problems** | [`docs/decisions.md`](docs/decisions.md) (every pre-registration and every deviation), [`docs/problems.md`](docs/problems.md) |
| **Public site and API** | [control-tower-mu-rouge.vercel.app](https://control-tower-mu-rouge.vercel.app) (static, Vercel); [control-tower-api.onrender.com](https://control-tower-api.onrender.com/health) (free plan, no JVM; warm predict p95 345 ms) |
| **Demo** | [`docs/demo_script.md`](docs/demo_script.md) |
| **Still open (needs people)** | [`docs/HUMAN_ACTIONS.md`](docs/HUMAN_ACTIONS.md): venue choice, a second labeller, phone photos, a user test, the Zenodo DOI. No AWS, by decision (D-074) |

## Repository map

| Path | Contents |
|---|---|
| `src/pipeline/` | cleaning, trip reconstruction, feature pipeline |
| `src/ml/` | audit, baselines, models, significance, model zoo, agent statistics |
| `src/streaming/`, `src/tms/`, `src/automation/` | Kafka producer and Structured Streaming job; mock TMS; retraining loop |
| `src/agents/`, `src/dashboard/` | the agents, orchestrator, MCP server; Streamlit control tower |
| `src/api/`, `web/` | the public API; the Next.js site |
| `src/report/` | figures, tables, site export, **paper numbers** |
| `paper/` | conference and journal LaTeX, shared sections, bibliography |
| `docs/`, `benchmarks/` | decision log, cards, weekly write-ups; every number traces to a file in `benchmarks/raw/` |
| `tests/` | pytest suites; Spark-dependent ones skip without PySpark |
| `data/` | **gitignored** |

## Honest scope

The Delhivery file is about 145K rows: real but modest. The big-data character rests on three stated grounds: distributed
Spark patterns that transfer to production volumes; a streaming layer with measured throughput; and a scale appendix that
runs the identical aggregation on 56.4M NYC taxi rows in 14.3 s (the audit's aggregation stage only). Agents operate on
synthetic documents and a mock TMS, declared as scaffolding; the network data are real.

The alert bot has sent real stream alerts to Telegram and an inbox (masked receipts in
`benchmarks/raw/f2_alert_channel_live.json`); Kafka has run against a live broker and alerted on exactly the same 1,347 legs
as the file source; the MCP server has been driven by a real client over stdio. The stateful stream scores about 74 events/s
of busy time, enough for the real event rate but not for a one-minute replay of the whole window.

## Citing

Please cite the work as below and the Delhivery dataset separately (see [`DATA_LICENSE.md`](DATA_LICENSE.md)). A DOI will be
added after the first archived release (HUMAN_ACTIONS 6.8); until then this is a working draft, not a publication.

```bibtex
@misc{reddy2026localising,
  title  = {Localising Systematic Route-Estimate Error in Road Freight: Dependence-Aware Corridor Auditing and Residual Prediction},
  author = {Reddy, Kuchuru Sai Krishna and Lahari, Makkena and Reddy, Shery Mounika},
  year   = {2026},
  note   = {Working draft. Code and data pipeline: https://github.com/krishna-2-005/Agentic-AI-Logistics-Control-Tower}
}
```

## Contributing

Read [`GIT_RULES.md`](GIT_RULES.md) first: short lowercase imperative commit subjects, a branch per work package, a PR to `dev`,
nobody commits to `main`. The week-by-week history (gates, weekly write-ups) is in
[`docs/WORK_ORDER_STATUS.md`](docs/WORK_ORDER_STATUS.md) and is **historical**: the weekly gates were met for v1.0 and are not a to-do list.

## License

Code: **MIT** ([`LICENSE`](LICENSE)). Data: not redistributed; the Delhivery and NYC TLC records carry their own terms, set out in
[`DATA_LICENSE.md`](DATA_LICENSE.md). `CITATION.cff` drives GitHub's *Cite this repository* button.
