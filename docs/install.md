# Install and run

Everything needed to run this repository on your own machine. The README keeps only the
90-second path for a reviewer; this file has the full setup, the individual commands and the
platform notes (Windows without admin rights, Tesseract mirrors, OneDrive).

For the short version: `make test` runs the fast tests, `make rebuild` regenerates every result from
the raw CSV, and `make paper` builds both manuscripts. See the `Makefile`.

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
