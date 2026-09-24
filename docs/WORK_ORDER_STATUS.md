# Work order status — WP-01 to WP-12

Updated at the end of every package. Companion to `docs/HUMAN_ACTIONS.md`.

A package is **done** only when the evidence named in its Acceptance row exists in the repository.
"Fixed in code" is not done.

| WP | Package | Status | Blocked on | Evidence |
|---|---|---|---|---|
| 01 | Foundation — README, main, license, CI, secret scan | **code done; release blocked** | v1.0 release + branch protection need repo-owner rights (HUMAN_ACTIONS §1.1, §1.2) | `.github/workflows/tests.yml`, `tests/test_readme_numbers.py` (20 green), `LICENSE`, `DATA_LICENSE.md`, `CITATION.cff`, `.pre-commit-config.yaml`, `.gitattributes` |
| 02 | Agent evaluation at scale (n ≥ 150, Wilson intervals) | not started | nothing — runs `--no-llm` | `benchmarks/raw/w9_order_eval.json`, `w9_invoice_eval.json`, `w9_lifecycle_eval.json` |
| 03 | Public site phase 1 — export, scaffold, Overview, Network, Corridors, About | **done, ahead of order** | — | `src/report/export_web.py`, `web/`, production URL, `tests/test_web_numbers.py` (21 green) |
| 04 | Public API Space — read-only API, TMS isolation, rate limits, predict | not started | **HF token + Space** (HUMAN_ACTIONS §2.2) | `src/api/app.py`, `benchmarks/raw/f1_api_latency.json`, D-064 |
| 05 | Public site phase 2 — live pages, Playwright, Lighthouse | **partly done** | WP-04 for the live half; user test needs three people | pages built; `web/e2e/` and Lighthouse CI outstanding |
| 06 | Real alert channel + monitoring | not started | **Telegram token** (HUMAN_ACTIONS §2.5), UptimeRobot | `benchmarks/raw/f2_alert_channel_live.json` |
| 07 | One measured LLM decision + approval queue + cost traces | not started | 2 labellers × 2 h (HUMAN_ACTIONS §3.2) | `benchmarks/raw/w9_llm_decision_eval.json`, D-065, D-067 |
| 08 | Real documents for the doc agent | not started | 10 phone photos (HUMAN_ACTIONS §3.4) | `benchmarks/raw/w9_doc_eval_real.json` |
| 09 | Code hygiene — ruff, mypy, split modules, LF, lock file, compose | not started | Docker Desktop for the compose half only | `requirements.lock`, ruff + mypy CI jobs |
| 10 | Paper readiness — model card, data card, ablations, related work | not started | depends on WP-02 and WP-07 numbers | `docs/model_card.md`, `docs/data_card.md` |
| 11 | Serve the v2 model in the stream (close D-053) | not started | nothing | `benchmarks/raw/w10_stream_validation_v2.json` |
| 12 | Demo video, screenshots, README hero, social preview | not started | recording + voice by the team | `docs/demo_video_script.md`, README hero |

---

## Corrections to the work order, found by auditing the repository

The work order and the addendum were written against an earlier state of `dev`. Recorded here so
nobody spends time closing something already closed.

| Work order says | Actually | Consequence |
|---|---|---|
| WP-03 is package 3, not started | **Done** — the Next.js site is built and live on Vercel with all ten routes | WP-01 and WP-02 are the real front of the queue |
| A-01: README reports "Random Forest 36.9 min … behind the corridor-mean baseline" | README already reports 30.90 vs the 33.04 median baseline and the 14-slice win | Only the two `pending W7` rows and the missing as-of alert precision are genuinely stale |
| A-01: Honest Scope still says Kafka never reached a live broker and MCP was never driven over stdio | Both caveats were already removed; the section states the live-broker run and the 13-tool stdio transcript | No rewrite needed; keep it accurate |
| A-05: cut Gate F1 from seven pages to four | All ten routes are built and deployed | The scope-cut decision is moot; logged as D-066 resolved-by-delivery |
| §5 item 10: a MapTiler key may be needed | The basemap needs no key at all | One fewer account |
| §5 item 5: LLM key needed | `GEMINI_API_KEY` is already set | WP-02 needs no key regardless (`--no-llm`) |

---

## Known problems, and what WP-01 found

1. **The test suite now passes: 382 without Spark, 49 with.** It did not when this audit
   started. Three separate causes, only one of which was a missing local install:
   - Ten test files could not import because the working virtualenv lacked packages that
     `requirements.txt` does declare (`fastapi`, `sqlmodel`, `sklearn`, `mcp`, `reportlab`).
     Installed.
   - **`rapidfuzz` was used and never declared** (P-64). Without it the extraction scorer
     silently fell back to exact string matching, so the published 98.7% per-field accuracy
     would have come out several points lower on a clean machine with nothing saying why.
     Declared, and the scorer now refuses to run rather than degrade.
   - **The TMS stopped accepting its own timestamps on a fresh dependency resolve** (P-65).
     Current sqlmodel rejects naive datetimes unless the field declares it means one.
   The last two were invisible to everyone who already had a working environment — which is
   the entire team. Putting the suite in CI is what surfaced them, within an hour.
2. **`LLM_MODEL` disagrees between files** — `.env.example` says `gemini-3.6-flash`,
   `src/common/config.py` defaults to `gemini-2.0-flash`. Not yet reconciled; needs a decision
   on which model actually answered the Week 7 runs before either file is changed.
3. **The frontend went to `dev` without a PR** (23 Sep), a GIT_RULES §5 miss. Not rewritten —
   §11 restricts rewrites to metadata fixes and the metadata is clean. Everything since is on
   `wo-01-mounika-foundation`.
4. **`requirements.txt` uses floors, not pins.** P-65 is the first thing that has broken
   because of it. The lock file is WP-09; until then a green CI run is the only evidence that
   a fresh install still works.
