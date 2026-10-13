# The public API

The API behind the four live pages of [the project site](https://control-tower-mu-rouge.vercel.app):
`src/api/app.py`, deployed from this folder on Render's free plan (`render.yaml`, D-072, D-073).

| Route | What it serves |
|---|---|
| `GET /health` | liveness, and whether the model is loaded |
| `POST /api/predict` | how late a leg will run, from the **v2 residual GBT the results report** (30.90 min test MAE), with corridor history as of the departure. Every answer names its model. |
| `GET /api/predict/status` | `warming` for a second or two after a cold start, then `ready` |
| `GET /api/alerts` | alerts from a **recorded run** of the v2 stream, released in order. No live stream runs here, and every response says so. |
| `GET /api/traces` | the newest agent calls (timing and outcome only, never what a visitor typed) |
| `POST /api/ask` | the analytics assistant. Extractive by default; a model-written answer is opt-in and capped at **10 a day** for everyone. |

**Not here:** the mock TMS and anything that writes. Every TMS route is a 404.

**Limits:** 30 predictions a minute per visitor and 2 running at once, 5 questions a minute,
bounded inputs, 4 KB bodies. Over a limit is a `429` with `Retry-After`.

## How it fits a free 512 MB host

* **No JVM.** The served model's 200 trees are walked in numpy (`src/ml/gbt_local.py`), which
  gives the same answers as Spark, bit for bit, on all 26,369 legs
  (`benchmarks/raw/w10_gbt_local_equivalence.json`).
* **No data.** The Delhivery records are never redistributed (`DATA_LICENSE.md`). The
  predictor reads per-corridor and per-hub aggregates (`serving/history_snapshot.json.gz`),
  which equal the full fold for any departure after mid-October 2018, which "today" always is.

## `serving/`, and how to rebuild it

| File | What it is |
|---|---|
| `v2_forest.json.gz` | the model's trees and weights |
| `history_snapshot.json.gz` | aggregates per corridor, hub, and hub-and-part-of-day |
| `alert_feed.jsonl.gz`, `alert_feed_meta.json` | the v2 stream's alerts: corridor, predicted gap, severity |
| `agent_calls.jsonl` | agent call log, trimmed to agent, time, duration and outcome |

Rebuild on a machine that has the data with `python scripts/build_api_bundle.py`. The script
refuses to finish if any file carries a trip id, a leg id or an event time.

Run locally: `SERVING_ENGINE=numpy uvicorn src.api.app:app --port 7860` (with the bundle
copied to `data/serving/`), or `docker build -f deploy/api/Dockerfile .` from the repo root.
