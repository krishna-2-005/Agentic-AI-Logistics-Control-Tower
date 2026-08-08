# Demo script

**Owner: Krishna.** Authored Week 8 D1-D2, rehearsed twice (W8 D3-D5).
Started in Week 1 so the demo shapes the build, rather than being assembled from
whatever happens to exist in Week 8.

---

## The shape (blueprint / execution plan W8)

1. **Quiet dashboard** — control tower open, India map showing audited corridors.
2. **Producer starts** — events begin replaying.
3. **Alerts fire on known-bad corridors** — not random ones. Pre-identified from the
   Week 2 audit so the panel sees prediction, not coincidence.
4. **Order email processed live** — Order Entry Agent reads it, validates, POSTs to
   the TMS. Shipment appears.
5. **Exception Agent notifies** — flagged shipment investigated, severity assigned,
   customer notification drafted and sent, exception ticket logged.
6. **Assistant answers a question** — live, grounded, with a source cited.
7. **India map close** — back to the wide shot.

Target: **2-3 minutes** of running system, then questions.

---

## The one-line claim to open with

> The production routing engine this network runs on under-predicts delivery time on
> **98.3% of legs**, and the median leg takes **twice** its planned time. We localised
> that error to specific corridors, built a model that beats the planner, and put a
> team of AI agents on top that acts on the prediction without a human in the loop.

*(Week 1 numbers, `docs/results.md`. Replace the "beats the planner" clause with the
actual Week 4 figure once it exists.)*

---

## Rehearsal rules

- **Rehearse the failure path.** Free-tier LLMs rate-limit. Know what the demo looks
  like when a provider 429s, and have `LLM_PROVIDER` switchable mid-demo (D-007 makes
  this a one-line `.env` change).
- **Pre-warm every cache.** Nothing in the demo may trigger a Spark job (D-009).
- **The refusal is a feature, not a risk** — ask the assistant something out of scope
  on purpose. It refusing correctly is a stronger result than a fluent answer.
- **Have the numbers ready without the dashboard**, in case a screen dies.

---

## Assets to collect as we go

| Asset | When | Where |
|---|---|---|
| `screenshots/W2_map.png` | Week 2 | India map, first version |
| `screenshots/W4_beat_osrm.png` | Week 4 | the headline table |
| `screenshots/W5_live_alert.png` | Week 5 | an alert firing |
| `sample_events/*.json` | Week 5 | a handful of replay events |
| `sample_documents/*.pdf` | Week 3 | 5-10 synthetic BOLs / invoices |
| `video/` | Week 8 | final 2-3 min recording |

## Questions to have answers rehearsed for

1. *"145K rows isn't big data."* — Blueprint §12: distributed patterns throughout,
   unbounded streaming with measured throughput, and the scale appendix running the
   identical code on 50M+ rows.
2. *"Your accuracy is 93% — is that good?"* — D-003. Know the majority-class rate and
   why the project leads with regression.
3. *"The documents are fake."* — Declared openly. The network data underneath is real;
   the corpus is labelled with a seeded-error set so the agents are *scored*, not
   demoed.
4. *"Which corridor is worst, and why?"* — The audit answers *that*; it does not
   answer *why*. Say so — the assistant is prompted to draw the same line.
