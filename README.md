# Agentic AI Logistics Control Tower

**A multi-agent digital workforce operating on a distributed big-data delay-prediction pipeline,
built on real Delhivery network data.**

> Big Data Analytics · Transportation & Logistics · Machine Learning · Agentic AI
> 8-week team project · Sai Krishna (AI Agents & Automation) · Lahari (ML & Evaluation) · Mounika (Data & Systems)

---

## The contribution in one sentence

A big-data pipeline that **audits and beats a production routing engine**, wrapped in a
**collaborating team of AI agents** that read logistics documents, enter orders into a TMS, watch
live shipments, resolve exceptions, and validate invoices — a working, student-scale digital
workforce for logistics operations.

---

## Two layers

**Layer 1 — the Big Data core.** A distributed PySpark pipeline over ~145K real Delhivery shipment
segments that reconstructs trips, statistically localises the corridors where the production OSRM
routing engine is systematically wrong, trains MLlib models that outperform that planner, and serves
predictions in real time through Kafka + Spark Structured Streaming.

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

### 7. Explore

```bash
python -m src.pipeline.data_dictionary          # column-by-column profile → docs/
python -m src.ml.eda                            # distributions, corridor counts → benchmarks/raw/
streamlit run src/dashboard/app.py              # control tower skeleton
python -m src.agents.hello_agent                # LangGraph smoke test (needs an LLM key)
```

---

## Repository map

| Path | Owner | Contents |
|---|---|---|
| `src/pipeline/` | Mounika | cleaning, trip reconstruction, feature pipeline |
| `src/ml/` | Lahari | training, evaluation, ablations |
| `src/streaming/` | Mounika | Kafka producer, Structured Streaming job |
| `src/tms/` | Mounika | mock TMS (FastAPI + SQLite) |
| `src/agents/` | Krishna | five agents, orchestrator, MCP server, versioned prompts |
| `src/dashboard/` | Krishna | Streamlit control tower |
| `src/automation/` | Mounika | auto-retraining loop, alert bot |
| `src/common/` | shared | config, Spark session, logging, env check |
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
| 1 | Cleaned Parquet v1 exists; every member loads it in Spark; LLM API responds | — |
| 2 | Bottleneck corridor audit + India map exist | `week2-complete` (`audit-v1`) |
| 3 | Feature table frozen; baselines on the board; 100+ labelled synthetic documents | `week3-complete` |
| 4 | Batch ML complete with the beat-OSRM headline; Doc Agent extracting with measured accuracy | `week4-complete` (`batch-complete`) |
| 5 | Replayed event → live dashboard alert; Order Entry Agent posting real orders to the TMS | `week5-complete` |
| 6 | Full lifecycle runs agent-to-agent with no human in the loop | `week6-complete` |
| 7 | RAG assistant answers grounded questions; agent-eval report; scale appendix | `week7-complete` |
| 8 | Demo rehearsed twice; paper outline + figure set complete | `v1.0` |

---

## Results

*Populated as gates pass. Every figure links to the `benchmarks/` file that produced it.*

| Result | Value | Source |
|---|---|---|
| Corridor audit — significant bottleneck corridors | _pending W2_ | `benchmarks/raw/` |
| Hub friction — ranked hubs (≥30 outbound legs) | 121 of 1,657; median leg dwell 49 min (34.6% of wall clock) | [`benchmarks/raw/w2_hub_dwell.csv`](benchmarks/raw/w2_hub_dwell.csv) |
| Best model MAE vs OSRM MAE | _pending W4_ | `benchmarks/ml_results.md` |
| Sustained streaming throughput | _pending W5_ | `benchmarks/streaming_throughput.md` |
| Agent evaluation summary | _pending W7_ | `benchmarks/agent_evaluation.md` |
| Scale appendix (50M+ rows) | _pending W7_ | `benchmarks/scale_appendix.md` |

---

## Honest scope

The Delhivery file is ~145K rows — real but modest. The project's big-data character rests on three
grounds, stated openly: (1) all batch logic is built in **distributed Spark patterns** that transfer
unchanged to production volumes; (2) the **streaming layer** processes an unbounded event stream with
reported sustained throughput — a big-data architecture by construction; (3) a **scale appendix**
re-runs the identical corridor-aggregation code on 50M+ NYC taxi rows with a runtime table.

Agents operate on synthetic documents and a mock TMS, declared as scaffolding. The network data
underneath is real.

---

## Contributing

Read [`GIT_RULES.md`](GIT_RULES.md) before your first commit. In short: branch
`week<N>-<name>-<topic>` off `dev`, commit `[W<N>][AREA] imperative description` daily, push the same
day, write your weekly doc, then PR → `dev`. Nobody commits to `main`.

---

## License

Academic coursework. Delhivery dataset used under its original Kaggle license.
