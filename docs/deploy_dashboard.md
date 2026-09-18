# Deploying the dashboard (G-08)

**Owner: Krishna** (execution plan v3.1 W8 D3-D4). Streamlit Community Cloud is the
interim host; Phase 3 moves it to AWS.

## What gets deployed, and what cannot

The repository is the deployment. Everything the public dashboard reads —
`benchmarks/raw/*.csv`, `*.json`, the prompt library, the decisions and problem logs — is
committed. Everything under `data/` is gitignored and **stays local**: the cleaned Parquet
caches, the trained models, the vector index, the document corpus, the trace log.

That is a deliberate split, not an accident of `.gitignore`. Those artefacts are 900 MB
of regenerable output, and a public host has no business holding a copy of a model that a
teammate can rebuild with one command.

**The consequence, stated rather than hidden:** four pages are partial in the deployed app.

| page | deployed | why |
|---|---|---|
| Overview, Corridor audit, India map, Hub friction, Prompt library | **fully working** | every number is a committed CSV |
| Delay predictor | the form renders; scoring is disabled | needs `data/models/champion` and a SparkSession |
| Live alerts | shows the recorded run's figures | needs a live `data/stream/alerts` directory |
| Agent console | shows the MCP transcript | the trace log is local |
| Analytics assistant | shows the 30-question scorecard; the ask box is disabled | needs the local Chroma index |

Each of those pages says so on screen. Verified by rendering all nine pages from a fresh
clone with **no `data/` directory and with `pyspark`, `chromadb`, `langchain`, `sklearn`,
`onnxruntime`, `torch` and `kafka` made unimportable** — zero exceptions.

## Deploy

1. Push the branch to be deployed (`main` after the v1.0 tag).
2. At `share.streamlit.io`, **New app** → this repository → branch `main` → main file
   `src/dashboard/app.py`.
3. **Advanced settings → Python 3.13**, and set the requirements file to
   `requirements-cloud.txt`. The default `requirements.txt` pulls PySpark, Torch and
   ChromaDB; the free tier's build will either time out or run out of memory, and none of
   the three is used by a page that works there anyway.
4. Add **no secrets**. The deployed app makes no model call, and there is no API key on the
   host. If a future page needs one, that is a decision to log first, not a field to fill.
5. When the URL is live, put it at the top of `README.md` and record it here.

**Deployed URL:** _not yet deployed — this file is the runbook, and the README link lands
with the URL._

## What to check after the first deploy

- The India map draws. It is the one page whose rendering depends on a third-party tile
  server rather than on data in the repo.
- The Overview figure count matches `benchmarks/raw/w1_leg_summary.csv` — if a page is
  reading something the deploy did not carry, the number goes missing rather than wrong,
  which is the failure mode to look for.
- Cold start time. The free tier sleeps an idle app; a demo should open the URL a few
  minutes before it is needed.
