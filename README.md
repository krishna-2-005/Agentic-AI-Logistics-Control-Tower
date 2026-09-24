# Agentic AI Logistics Control Tower

**A multi-agent digital workforce operating on a distributed big-data delay-prediction pipeline,
built on real Delhivery network data.**

[![tests](https://github.com/krishna-2-005/Agentic-AI-Logistics-Control-Tower/actions/workflows/tests.yml/badge.svg?branch=dev)](https://github.com/krishna-2-005/Agentic-AI-Logistics-Control-Tower/actions/workflows/tests.yml)
[![web](https://github.com/krishna-2-005/Agentic-AI-Logistics-Control-Tower/actions/workflows/web.yml/badge.svg?branch=dev)](https://github.com/krishna-2-005/Agentic-AI-Logistics-Control-Tower/actions/workflows/web.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python 3.11–3.13](https://img.shields.io/badge/python-3.11–3.13-blue.svg)](requirements.txt)

> Big Data Analytics · Transportation & Logistics · Machine Learning · Agentic AI
> 8-week team project · Sai Krishna (AI Agents & Automation) · Lahari (ML & Evaluation) · Mounika (Data & Systems)

### ▶ **[Open the control tower](https://control-tower-mu-rouge.vercel.app)** — `control-tower-mu-rouge.vercel.app`

The network map, the corridor audit, the agent workforce and every frozen number, live.
Eight of its ten pages need no backend at all: the site reads JSON written from
`benchmarks/raw/` by `python -m src.report.export_web` and committed beside the code, so a
number on screen and a number in the paper cannot drift apart (D-059).

---

## The contribution in one sentence

A big-data pipeline that **localises, corridor by corridor, where a production routing engine is
systematically wrong** — 273 corridors significantly slower and 512 faster than the network, at a
5% false discovery rate — wrapped in a team of **deterministic-core agents** that read logistics
documents, enter orders into a TMS, watch live shipments, resolve exceptions and validate
invoices, each measured against a trivial policy.

> **Not claimed:** "beats the planner". OSRM has no access to corridor history, so a model that
> has seen it is not a fair comparison. Every model result is reported against the per-corridor
> median, the baseline an MAE table should use (D-048).

> **The model was wrong once, and the correction is part of the result.** Week 4's Random Forest
> reached 36.9 min and *lost* to a corridor-mean lookup. Two defects, found by diagnosing rather
> than retuning: the reported baseline was the mean when MAE is minimised by the median (33.04,
> not 36.13), and the gradient-booster chosen for absolute loss ran at a step size where its
> corrective trees could move a prediction by at most 9.95 minutes in total — the objective it was
> picked for was barely switched on. Fixing the step size gives **30.90 min**, beating the median
> baseline on all fourteen slices (D-048 → D-050).

## Project status and where everything is

| | |
|---|---|
| **Rebuild everything from the raw CSV** | `bash scripts/rebuild_all.sh` — every stage in dependency order, ending in `results_freeze --verify` |
| **Run the whole system** | `python -m src.common.boot` (TMS → replay → streaming → agents), `--dashboard` to keep Streamlit up |
| **Live Kafka, no Docker** | `scripts/kafka_native.ps1` (G-05; alerts identical to the file source) |
| **Paper draft** | [`docs/paper_draft.md`](docs/paper_draft.md) — target ICCCI 2027 (D-052); outline and skeleton beside it |
| **Figures** | [`docs/figures/`](docs/figures/) — nine, png and vector pdf, each from a `benchmarks/raw/` file |
| **Final numbers** | [`benchmarks/final_tables.md`](benchmarks/final_tables.md), [`benchmarks/agent_evaluation.md`](benchmarks/agent_evaluation.md), [`benchmarks/experiments_appendix.md`](benchmarks/experiments_appendix.md) |
| **Demo** | [`docs/demo_script.md`](docs/demo_script.md) — ten minutes, with what to do when each beat fails |
| **Public site** | **[control-tower-mu-rouge.vercel.app](https://control-tower-mu-rouge.vercel.app)** — Next.js, static, on Vercel; rebuilt from GitHub on every push ([`docs/deploy_web.md`](docs/deploy_web.md)) |
| **Work on the site** | `python -m src.report.export_web` then `cd web && pnpm install && pnpm dev` |
| **Still open** | G-07 real alert channel (needs a credential); the four live pages need the API Space (W-01); extraction rows 21-40 (daily LLM quota); serving the reported model in the stream (D-053, Phase 3) |

---

## Two layers

**Layer 1 — the Big Data core.** A distributed PySpark pipeline over ~145K real Delhivery shipment
segments that reconstructs trips, statistically localises the corridors where the production OSRM
routing engine is systematically wrong, trains an MLlib model on the residual over a per-corridor
median, and serves predictions through Kafka + Spark Structured Streaming.

**Layer 2 — the Agentic AI workforce.** Five LangGraph agents plus an orchestrator that consume
Layer 1's intelligence and act on it autonomously, calling tools through an MCP server.

The layers are **causally connected, not bolted together**: the Exception Agent only exists because
Layer 1's streaming model flags at-risk shipments; the Invoice Auditor only exists because Layer 1's
corridor statistics define what a leg *should* cost and take.

---

## Architecture

```
                              ┌───────────────────────────────────────────────┐
                              │      STREAMLIT CONTROL TOWER (Krishna)        │
                              │  India map · leaderboards · live alerts ·     │
                              │  agent console · RAG assistant                │
                              └───────────────▲───────────────────────────────┘
                                              │
┌─────────────────────────────────────────────┴───────────────────────────────┐
│                        AGENT PLANE  (Krishna)                               │
│                                                                             │
│   ①  Document      ②  Order       ③  Tracking &    ④  Invoice   ⑤ Analytics │
│      Intelligence     Entry          Exception        Auditor      Assistant│
│      (OCR + LLM)      (email→TMS)    (flagship)       (approve/    (RAG)    │
│           │               │               │            dispute)       │     │
│           └───────────────┴──── LangGraph Orchestrator ───┴───────────┘     │
│                                       │                                     │
│                            ┌──────────┴───────────┐                         │
│                            │   MCP TOOL SERVER    │                         │
│                            │ corridor stats ·     │                         │
│                            │ predictions · TMS ·  │                         │
│                            │ vector search        │                         │
│                            └──────────┬───────────┘                         │
└───────────────────────────────────────┼─────────────────────────────────────┘
                                        │  (consumes frozen outputs only)
┌───────────────────────────────────────┼─────────────────────────────────────┐
│                     REAL-TIME PLANE  (Mounika)                              │
│   Kafka producer (trip replay) → Spark Structured Streaming                 │
│   → broadcast feature join → PipelineModel → delay-flagged alert stream     │
└───────────────────────────────────────┬─────────────────────────────────────┘
┌───────────────────────────────────────┼─────────────────────────────────────┐
│                    INTELLIGENCE PLANE  (Lahari)                             │
│   MLlib LR / RF / GBT → PipelineModel · corridor audit statistics           │
│   · auto-retraining loop with champion/challenger promotion                 │
└───────────────────────────────────────┬─────────────────────────────────────┘
┌───────────────────────────────────────┼─────────────────────────────────────┐
│                        DATA PLANE  (Mounika)                                │
│   Delhivery raw CSV → Spark cleaning → trip/corridor reconstruction         │
│   → cached Parquet → feature tables → audit tables → vector DB              │
└─────────────────────────────────────────────────────────────────────────────┘
```

Supporting scaffolding: a **mock TMS** (FastAPI + SQLite) giving agents a real API to integrate
with, and a **synthetic document corpus** (300–500 labelled BOLs / invoices / PODs with seeded
errors) so the document and audit agents can be *scored*, not just demoed. Both are declared openly
as synthetic scaffolding around real network data.

---

## Quickstart

### 0. Prerequisites

| Requirement | Why | Check |
|---|---|---|
| Python 3.11-3.13 | everything | `python --version` |
| **JDK 17** on `JAVA_HOME` | PySpark will not start without it | `java -version` |
| Tesseract (Week 4+) | Document Intelligence Agent OCR | `tesseract --version` |
| Docker (Week 5+, optional) | Kafka; file-source fallback documented | `docker --version` |

#### Installing JDK 17 without admin rights

`winget install EclipseAdoptium.Temurin.17.JDK` needs UAC elevation and hangs in a
non-interactive shell. The portable zip needs neither:

```powershell
$dest = "$env:USERPROFILE\jdks"; New-Item -ItemType Directory -Force $dest | Out-Null
Invoke-WebRequest "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse" -OutFile "$env:TEMP\jdk17.zip" -UseBasicParsing
Expand-Archive "$env:TEMP\jdk17.zip" -DestinationPath $dest -Force
$jh = (Get-ChildItem $dest -Directory | Select-Object -First 1).FullName
[Environment]::SetEnvironmentVariable("JAVA_HOME", $jh, "User")
[Environment]::SetEnvironmentVariable("Path", "$([Environment]::GetEnvironmentVariable('Path','User'));$jh\bin", "User")
```

Reopen the terminal afterwards so the new environment is picked up.

#### Installing Tesseract when the official mirror is unreachable

The installer UB-Mannheim's wiki links to
(`digi.bib.uni-mannheim.de/tesseract/...`) does not resolve from every network. The
identical installer is also a release asset on Tesseract's own GitHub repo, which is
a legitimate alternate host for the same official artefact — and it can be extracted
without running it, the same portable instinct as the JDK zip above:

```powershell
$dest = "$env:USERPROFILE\tesseract-ocr"; New-Item -ItemType Directory -Force $dest | Out-Null
Invoke-WebRequest "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/tesseract-ocr-w64-setup-5.5.3.20260724.exe" -OutFile "$env:TEMP\tesseract-setup.exe" -UseBasicParsing
& "C:\Program Files\7-Zip\7z.exe" x -y -o"$env:TEMP\tess_extract" "$env:TEMP\tesseract-setup.exe"
Copy-Item "$env:TEMP\tess_extract\*.exe","$env:TEMP\tess_extract\*.dll" $dest
New-Item -ItemType Directory -Force "$dest\tessdata" | Out-Null
Invoke-WebRequest "https://github.com/tesseract-ocr/tessdata_fast/raw/main/eng.traineddata" -OutFile "$dest\tessdata\eng.traineddata" -UseBasicParsing
[Environment]::SetEnvironmentVariable("TESSDATA_PREFIX", "$dest\tessdata", "User")
[Environment]::SetEnvironmentVariable("Path", "$([Environment]::GetEnvironmentVariable('Path','User'));$dest", "User")
```

The base installer does not bundle language data — it fetches it during setup via an
NSIS plugin, which extraction skips, hence the separate `eng.traineddata` download.
Needs 7-Zip; reopen the terminal afterwards. See `docs/problems.md` P-34.

### 1. Setup

```bash
git clone https://github.com/krishna-2-005/Agentic-AI-Logistics-Control-Tower.git
cd Agentic-AI-Logistics-Control-Tower

python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

pip install -r requirements.txt
nbstripout --install          # clears notebook outputs on commit (GIT_RULES §7)

cp .env.example .env          # then fill in your keys
```

> **If this repo lives in a OneDrive-synced folder**, put the virtualenv *outside* it —
> e.g. `python -m venv %USERPROFILE%\venvs\control-tower`. A venv with PySpark in it is
> several GB of small files, and OneDrive will try to sync every one of them.

> **Do not downgrade the pins in `requirements.txt` without checking wheels exist for
> your Python version.** The obvious "stable" versions (`numpy==1.26.4`,
> `pyspark==3.5.1`, …) have no cp313 wheels, and pip silently falls back to building
> from source. See the comment block at the top of the file.

### 2. Get the data

The raw dataset is **not committed** (GIT_RULES §7). See [`data/README.md`](data/README.md) for
download instructions and the expected checksum, then place it at `data/raw/delhivery_data.csv`.

### 3. Verify your environment

```bash
python -m src.common.check_env
```

This prints a pass/fail table for Python, Java/Spark, the raw dataset, the LLM provider, and the
optional extras. **Every member runs this on Day 1 of Week 1** — Gate 1 is not passed until all three
machines are green.

### 4. Build the cleaned data cache (Stage 1)

```bash
python -m src.pipeline.clean --input data/raw/delhivery_data.csv --output data/processed/clean_v1
```

Writes partitioned Parquet plus a `_quality_report.json` describing every row dropped and why.

### 5. Build the rest of the batch caches (Stages 2–3)

```bash
python -m src.pipeline.reconstruct --validate   # 144,867 segments -> 26,369 OD legs
python -m src.pipeline.hubs                     # 26,369 legs -> 1,657 hubs
python -m src.ml.audit                          # 1,130 corridors tested -> 273 bottlenecks
python -m src.pipeline.contracts --keys         # verify all caches against the frozen schema
```

`--validate` diffs Stage 2 against an independent pandas implementation and exits
non-zero on failure. `contracts` is the schema gate — see `docs/decisions.md` D-016 for
the rule on bumping a version rather than repointing one.

### 6. Run the mock TMS

```bash
python -m src.tms.seed        # 1,657 real centre codes from hubs_v1
python -m src.tms             # http://localhost:8000/docs
```

### 7. Run the whole thing with one command

```bash
python -m src.common.boot --check          # what is ready, what is missing, and the fix for each
python -m src.common.boot                  # TMS → replay → streaming → agents, then tear down
python -m src.common.boot --dashboard      # ...and leave Streamlit running
```

`boot` checks every prerequisite **before** starting anything and reports all problems at
once, repairs TMS schema drift in place (P-47, without destroying agent-filed rows), and
stops every child process on the way out. It runs the agents with template wording by
default; add `--llm` to let them draft.

### 8. Or run the pieces

```bash
# streaming: replay trips, score them, alert on the ones predicted late
python -m src.streaming.producer --sink file --limit 2000 --duration 20 --clean
python -m src.streaming.job --once
python -m src.streaming.throughput --legs 2000 --durations 20,5,2   # the D5 measurements

# agents (every one takes --no-llm or --no-draft and then costs zero API calls)
python -m src.agents.order_agent --count 6          # email → validated order → TMS
python -m src.agents.exception_agent --limit 5      # alert → severity → notification → ticket
python -m src.agents.orchestrator --cases 10        # the whole lifecycle, as a graph
python -m src.agents.invoice_auditor --count 20     # invoice vs order vs corridor rate band
python -m src.agents.alert_bot --dry-run --top 5

# retrieval and tools
python -m src.common.vectordb --build               # index corridors, hubs and docs
python -m src.common.vectordb --query "which corridors are worst for delays"
python -m src.agents.mcp_server --list              # the MCP tools, or run it for stdio

# exploration
python -m src.pipeline.data_dictionary          # column-by-column profile → docs/
python -m src.ml.eda                            # distributions, corridor counts → benchmarks/raw/
streamlit run src/dashboard/app.py              # the dashboard on its own
```

> **The producer needs `--sink file` on a machine with no Kafka broker.** `STREAM_SOURCE`
> defaults to `kafka`, so the bare command spends 30 seconds timing out against
> `localhost:9092` and exits 1 (D-035, P-50). `boot` passes the flag for you.

---

## Repository map

| Path | Owner | Contents |
|---|---|---|
| `src/pipeline/` | Mounika | cleaning, trip reconstruction, feature pipeline |
| `src/ml/` | Lahari | training, evaluation, ablations |
| `src/streaming/` | Mounika | Kafka producer, Structured Streaming job |
| `src/tms/` | Mounika | mock TMS (FastAPI + SQLite) |
| `src/agents/` | Krishna | order entry, document, exception and invoice agents, alert bot, orchestrator, MCP server, TMS client, versioned prompts |
| `src/dashboard/` | Krishna | Streamlit control tower |
| `src/automation/` | Mounika | auto-retraining loop |
| `src/common/` | shared | config, Spark session, logging, env check, **boot script**, **vector store** |
| `docs/` | all | one weekly writeup per member + `decisions.md` + `problems.md` + `results.md` |
| `benchmarks/` | all | every number in the report traces to a file here |
| `demo/` | Krishna | demo script, screenshots, sample events/documents |
| `notebooks/` | all | exploration only, `w3_lahari_baselines.ipynb` naming |
| `tests/` | all | pytest suites for the parts that can be tested without Spark |
| `data/` | — | **gitignored** |

---

## Weekly gates

| Week | Gate | Tag |
|---|---|---|
| 1 | Cleaned Parquet v1 exists; every member loads it in Spark; LLM API responds | `week1-complete` — **met** |
| 2 | Bottleneck corridor audit + India map exist | `week2-complete` (`audit-v1`) — **met** |
| 3 | Feature table frozen; baselines on the board; 100+ labelled synthetic documents | `week3-complete` — **met** |
| 4 | Batch ML complete with the beat-OSRM headline; Doc Agent extracting with measured accuracy | `week4-complete` (`batch-complete`) — **met**. The Week 4 model was superseded in Week 7 (D-050) and extraction accuracy recorded at 98.0% on the first 11 of 40 rows (G-01) |
| 5 | Replayed event → live dashboard alert; Order Entry Agent posting real orders to the TMS | `week5-complete` — **met** |
| 6 | Full lifecycle runs agent-to-agent with no human in the loop | `week6-complete` — **met** |
| 7 | RAG assistant answers grounded questions; agent-eval report; scale appendix | `week7-complete` — **met**; G-05 (live broker) closed in Week 8 without Docker, G-07 (a real alert channel) still carried: it needs a credential, and none is faked |
| 8 | Demo rehearsed twice; paper outline + figure set complete | `v1.0` |

---

## Results

*Populated as gates pass. Every figure links to the `benchmarks/` file that produced it.*

| Result | Value | Source |
|---|---|---|
| Corridor audit — significant bottleneck corridors | 273 slower and 512 faster of 1,130 tested corridors covering 78.6% of legs (FDR 0.05); worst runs 13.88× the network's typical overrun | [`benchmarks/raw/w2_top20_bottlenecks.csv`](benchmarks/raw/w2_top20_bottlenecks.csv) |
| Corridor audit — robustness view at the old 30-leg floor | 34 slower and 36 faster of 99 tested; worst 1.92×. Shares **no corridor** with the 10-leg top 20 — see D-018 | [`benchmarks/raw/w2_corridor_audit_support30.csv`](benchmarks/raw/w2_corridor_audit_support30.csv) |
| Hub friction — ranked hubs (≥30 outbound legs) | 121 of 1,657; median leg dwell 49 min (34.6% of wall clock) | [`benchmarks/raw/w2_hub_dwell.csv`](benchmarks/raw/w2_hub_dwell.csv) |
| India map — audited corridors placed | 1,130 of 1,130; the 273 bottlenecks sit in 169 cities and 70 of them are intra-city | [`benchmarks/raw/w2_corridor_audit.csv`](benchmarks/raw/w2_corridor_audit.csv) |
| Feature table and baselines (Week 3) | 26,369 legs frozen as `features_v1` with past-only corridor and hub history (11.1% cold-start); chronological 80/20 split (21,095 / 5,274). Test MAE: OSRM 107.1 min, corridor mean 36.1, linear regression 41.2. Delay classifier v1 (logistic) F1 0.764 against a 51.1% majority-class rate. Document corpus: 120 consignments, 240 labelled documents (BOL + invoice), 20 with seeded errors | [`benchmarks/raw/w3_baseline_report.json`](benchmarks/raw/w3_baseline_report.json), [`w3_baseline_metrics.csv`](benchmarks/raw/w3_baseline_metrics.csv), [`w3_doc_corpus_manifest.csv`](benchmarks/raw/w3_doc_corpus_manifest.csv) |
| Best model MAE vs OSRM MAE | v2 GBT on the corridor-median residual **30.90 min** vs OSRM 107.1 min — 71% lower, and 6.5% under the corridor-median baseline (33.04 min) it is judged against, winning on all 14 slices (D-050). Week 4's Random Forest (36.9 min) is now an ablation row | [`benchmarks/raw/w7_model_metrics_v2_stepsize.csv`](benchmarks/raw/w7_model_metrics_v2_stepsize.csv), [`w4_model_metrics.csv`](benchmarks/raw/w4_model_metrics.csv) |
| Sustained streaming throughput | all 52,738 replayed events scored, nothing dropped: **886 events/sec** produced, **740 events/sec** of saturated scoring, event-to-alert **p50 28.9 s** | [`benchmarks/raw/w5_stream_throughput_full.json`](benchmarks/raw/w5_stream_throughput_full.json) |
| Stream equals batch | **500 of 500** predictions bit-identical across the batch and event paths | [`benchmarks/raw/w5_stream_validation_report.json`](benchmarks/raw/w5_stream_validation_report.json) |
| Delay-threshold sensitivity | 2.00× holds: the best classifier's MCC barely moves across thresholds (0.507→0.536) while the alert volume falls from 98% of legs to 49%. The stream's own flag is the weakest real classifier (MCC 0.477) | [`benchmarks/raw/w5_threshold_sensitivity.csv`](benchmarks/raw/w5_threshold_sensitivity.csv) |
| Order Entry Agent evaluation | **50 of 50** authored cases run, **50 correct**; 0 orders filed on invented values, 0 needless questions | [`benchmarks/raw/w5_order_eval_summary.json`](benchmarks/raw/w5_order_eval_summary.json) |
| Lifecycle, end to end (Gate 6) | 10 emails, 3 distinct paths, no human in the middle: 5 stopped at a question, 3 booked and unflagged, 2 booked → flagged → notified → ticketed | [`benchmarks/raw/w6_orchestrator_runs.json`](benchmarks/raw/w6_orchestrator_runs.json) |
| Freight Invoice Auditor v1 | **20 of 20** verdicts matched the seeded ground truth; no clean invoice disputed. Band is the corpus's own rate model — exact here, circular as a pricing claim (D-043) | [`benchmarks/raw/w6_invoice_audit_runs.json`](benchmarks/raw/w6_invoice_audit_runs.json) |
| Agent evaluation summary | Every agent beside the trivial policy on its own set. Exception agent notification precision **58.6%** as-of against 54.1% for alerting on every leg — the first published 72.1% came from a replay that leaked future history (D-054). Invoice auditor dispute precision/recall **100% / 82.2%** on 60 seeded invoices. Order entry **50 of 50**, 0 invented orders. Document extraction **98.7%** per-field on clean PDFs, 96.9% on noisy scans. Assistant route accuracy **93.3%**, refusal recall 6 of 6 | [`benchmarks/agent_evaluation.md`](benchmarks/agent_evaluation.md), [`w8_replay_leakage.json`](benchmarks/raw/w8_replay_leakage.json) |
| Scale appendix (50M+ rows) | The **same two functions** (`network_baseline`, `corridor_aggregate`), imported unchanged, on **56,353,613** NYC TLC rows → 51,515 corridors in **14.32 s** (3.9M rows/sec) on one 20-core laptop. 2,138× the Delhivery row count | [`benchmarks/scale_appendix.md`](benchmarks/scale_appendix.md), [`w7_scale_benchmark.json`](benchmarks/raw/w7_scale_benchmark.json) |

---

## Honest scope

The Delhivery file is ~145K rows — real but modest. The project's big-data character rests on three
grounds, stated openly: (1) all batch logic is built in **distributed Spark patterns** that transfer
unchanged to production volumes; (2) the **streaming layer** processes an unbounded event stream with
reported sustained throughput — a big-data architecture by construction; (3) a **scale appendix**
re-runs the identical corridor-aggregation code on 50M+ NYC taxi rows with a runtime table.

Agents operate on synthetic documents and a mock TMS, declared as scaffolding. The network data
underneath is real.

**What the agents decide, and what a model decides.** Severity, invoice verdicts and routing are
computed, not generated; a language model writes only the customer-facing sentence, and every agent
runs with `--no-llm` or `--no-draft` and no API call at all (D-041). That is a deliberate trade: the
agents are less "agentic" than the word suggests, and in exchange every verdict is reproducible and
therefore measurable.

**What has never run here, stated plainly.** The alert bot's Telegram and email channels are
implemented and unconfigured, so only the file channel has sent anything (D-039); the steps to
configure one are in `docs/W7_krishna_rag_assistant.md`. **Kafka has now run against a live
broker** — Apache Kafka 4.1.2, natively on the JVM, no Docker (`scripts/kafka_native.ps1`) —
and alerted on exactly the same 1,347 legs as the file source (`benchmarks/raw/
w7_kafka_source_equivalence.json`). The MCP server has been driven by a real client over
stdio — 13 tools, 8 calls, 0 errors (`benchmarks/raw/w7_mcp_stdio_transcript.json`). The
adopted Week 7 model is reported but not yet served by the stream (D-053).

---

## Contributing

Read [`GIT_RULES.md`](GIT_RULES.md) before your first commit. In short: branch
`week<N>-<name>-<topic>` off `dev`; commit a **short lowercase imperative with no bracketed prefix**
(§7 — `add the streaming scoring job`, not `[W5][STREAM] add job`); push the same day; write your
weekly doc; then PR → `dev`. Nobody commits to `main`.

> This section told you to write `[W<N>][AREA] ...` until Week 6. GIT_RULES §7 has banned bracketed
> prefixes since Week 1 and no commit in the history uses one, so the README was the thing that was
> wrong. Fixed rather than left as a trap for the next person who reads it first.

---

## License

Code: **MIT** ([`LICENSE`](LICENSE)) — so anyone may actually run it.

Data: not redistributed here. The Delhivery records carry their own Kaggle terms and the NYC TLC
records their own; both, plus what this project generates synthetically, are set out in
[`DATA_LICENSE.md`](DATA_LICENSE.md).

Citing this work: [`CITATION.cff`](CITATION.cff) — GitHub renders it as a *Cite this repository*
button. Please cite the Delhivery dataset separately.
