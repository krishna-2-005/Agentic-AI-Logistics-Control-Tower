# v1.0 — release notes

**Agentic AI Logistics Control Tower**, end of execution plan v3.1 Phase 1 (Weeks 1-8).

## What v1.0 is

A pipeline and an agent layer over Delhivery's public trip records that:

1. **Localises where a production routing engine is systematically wrong** — 273 corridors
   significantly slower and 512 faster than the network, of 1,130 tested at FDR 5%, covering
   78.6% of legs — and shows that the support floor changes the answer (D-018).
2. **Predicts how late each leg will run** with a gradient-boosted model on the residual over a
   per-corridor median: 30.90 min MAE against the median's 33.04, winning on all 14 slices,
   most of the gain on corridors with no history (D-050).
3. **Serves the batch model on a stream** — bit-identical to batch on 500 of 500 legs, and
   through a live Kafka broker with alerts identical to the file source (D-055).
4. **Runs five deterministic-core agents and an orchestrator** — verdicts computed, prose
   generated — each measured against a trivial policy on its own set.
5. **Runs the same aggregation code unchanged on 56.4 million rows.**

## Run it

```bash
python -m src.common.check_env        # environment
bash scripts/rebuild_all.sh           # every artefact from the raw CSV, then verify the numbers
python -m src.common.boot             # TMS -> replay -> streaming -> agents
streamlit run src/dashboard/app.py    # the control tower
```

## Verified at release

- **Fresh-clone rebuild:** `scripts/rebuild_all.sh` on a clone that had never been built, with
  only the raw CSV: 71 minutes, and 35 of 37 frozen numbers came back exactly — the two that
  moved are extraction values the rebuild does not re-run (`w8_fresh_clone_rebuild.json`).
- **End to end in one command:** `python -m src.common.boot` — every preflight check green,
  then TMS, replay (1,000 events), streaming (354 alerts), exception agent and orchestrator
  (5 orders booked), clean teardown, exit 0.
- **Live Kafka:** the same 2,000 legs through a native Kafka broker and through files alert
  on the same 1,347 legs with the same predicted gaps (D-055).
- **Tests:** the full suite passes on the release commit.
- **Results freeze v3** verifies clean (D-056).

## Numbers that changed during Phase 1, and why

Reported here because a release that silently carried corrected numbers would be worse than
one that shows its corrections.

| number | first reported | now | why |
|---|---|---|---|
| model MAE, best | 36.89 (Random Forest) | **30.90** | wrong loss and wrong baseline, fixed in the Week 7 sprint (D-048 to D-050) |
| the bar a model must beat | 36.13 (corridor mean) | **33.04** (corridor median) | MAE is minimised by the median (D-048) |
| exception alert precision | 72.1% | **58.6%** | the replay scored early legs with end-of-data history (D-054, P-62) |
| order-entry evaluation | 40 of 50 | **50 of 50** | the last ten cases ran on later quota days (G-02) |
| hub with the longest dwell | Aluva | **Hubli** | the router sorted by dwell share, not minutes; the model caught it (P-61) |

## Known limits, stated

- **The reported model is not the served model.** Two of its features are seven-day windows
  over event time and two are keyed by hub and hour; the stream's stateless history join cannot
  supply them (D-053). The stream serves the Week 4 champion.
- **Replayed alerts carry the end-of-data history leak** (D-054). Live, the same join is
  correct; on a replay it is not, and the reported alert numbers are the as-of ones.
- **No real alert has been sent** (G-07): the email and Telegram channels are implemented and
  unconfigured, because no credential has been committed to this repository.
- **The public dashboard is packaged, not published** (G-08): the bundle is verified in a clean
  environment and needs a Hugging Face write token.
- **The demo has not been rehearsed by people.** The script's every command was run and
  checked (three errors found and fixed), and the system runs end to end; rehearsing it twice
  in front of someone is the one Gate 8 item no amount of automation replaces.
- **Document extraction is measured on 20 of 40 planned rows**, with the rest running on the
  daily LLM quota.
- **The agent evaluations use synthetic and templated corpora** the team generated; they
  measure the pipeline, not the world.

## Release assets

Built by `python -m src.report.release --out dist/`, each with a SHA-256 in
`release_manifest.json`: parquet caches, models, the document corpus, and the TMS database.
The raw Delhivery CSV is not redistributed.

## Phase 2 and 3

The paper draft is in `docs/paper_draft.md` (ICCCI 2027, D-052). Phase 3 moves the dashboard to
AWS and adds event-time state to the stream so the reported model can be served.
