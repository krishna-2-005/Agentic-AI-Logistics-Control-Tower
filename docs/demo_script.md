# Demo script — 10 minutes, one laptop, no internet required

**Owner: Krishna** (execution plan v3.1 W8 D1-D2). Rehearsed twice before the demo; every
number said aloud is in `benchmarks/` and every command below has been run.

**Setup, 15 minutes before**, not during:

```bash
python -m src.common.boot --check           # every artefact present, TMS reachable
streamlit run src/dashboard/app.py          # leave it on the Overview page
python -m src.tms                           # the mock TMS, in its own terminal
```

Three terminals, one browser. The dashboard is on **Overview**, quiet. Nothing else is
running — the producer is started live, on stage, because a stream that was already
running is not a demonstration of anything.

---

## 0 · The premise (45 s, on Overview)

> "This is a control tower for a logistics network — 145,000 shipment records from
> Delhivery, 26,369 origin-destination legs. One number sets up everything else."

Point at the two metrics on screen: **the median leg takes 2.0× its planned time**, and
**98.3% of legs run over plan**.

> "The planner under-predicts almost every leg. That is not noise — noise cancels. It is
> systematic, so it should be findable in specific places. That is the whole project."

## 1 · The headline: where the planner is wrong (90 s, Corridor audit → India map)

Switch to **Corridor audit**.

> "We tested all 1,130 corridors with at least ten legs against the rest of the network,
> Welch's t-test on log ratios, FDR-corrected at 5%. **273 corridors are significantly
> slower. 512 are significantly faster.** The worst runs 13.9× the network's typical
> overrun."

Switch to **India map**. Let it draw.

> "Every audited corridor, coloured by severity. The bottlenecks are not spread evenly —
> 70 of the 273 are intra-city legs, which is a different operational problem from
> long-haul delay."

**The honest line, say it here:** 

> "One caution we publish rather than hide: change the support threshold from ten legs to
> thirty and the top-20 list shares **no corridor** with this one. Corridor-level findings
> are sensitive to that choice, and papers that do not state their threshold are not
> reproducible."

## 2 · The stream: a prediction becoming an alert (2 min)

Terminal 2:

```bash
python -m src.streaming.producer --sink file --limit 2000 --duration 60
```

Terminal 3, immediately:

```bash
python -m src.streaming.job --once
```

While they run, switch the dashboard to **Live alerts** and press **R** every few seconds.

> "The producer is replaying real legs as events. The job scores each one with the batch
> model and writes an alert when the prediction crosses 2× planned time."

When rows appear:

> "886 events a second sustained, 740 a second of actual scoring, event to alert at a
> median of 29 seconds. And the predictions the stream produces are **bit-identical** to
> the batch path on 500 of 500 checked legs — the same model, not a re-implementation."

**If no alerts appear within 40 seconds:** the job is still loading the model. Say so, and
keep talking — the numbers above are on the Live alerts page from the recorded run.

## 3 · The agents: an email to a booked order (2 min)

Terminal 2:

```bash
python -m src.agents.orchestrator --cases 1
```

> "One customer email. The agent extracts the order, validates it, files it in the TMS,
> the stream flags its corridor, the exception agent investigates and writes the
> notification, and a ticket is filed. No human between any two of those steps."

Then the point that matters:

> "The verdicts are **computed, not generated**. Severity is arithmetic on how far past its
> threshold a leg is predicted to run; an invoice verdict is four comparisons. A language
> model writes only the sentence a person reads. That is a deliberate design position: it
> is why every agent decision is reproducible and can be scored at all."

Numbers to have ready: **50 of 50** order-entry cases correct, clarification precision and
recall **100%**; exception notification precision **59%** overall and **85%** at critical,
against 54% for alerting every leg — and if asked, the 72% first published came from a
replay that scored early legs with the future (D-054). Say it before anyone else does;
invoice verdicts **100% precision, 82% recall**, with the one blind spot published.

**Say what is not live:** the notification goes to a file channel. Email and Telegram are
implemented and unconfigured — no credential has been committed to this repository, and we
would rather show a file than fake a send.

## 4 · Documents (90 s)

```bash
python -m src.ml.eval_extraction --consignments 1 --cache-only --tag _demo
```

`--tag _demo` is not optional. Without it this writes `w7_doc_extraction_eval.json`, the
file the write-ups cite, and a one-consignment demo would replace a 40-row evaluation with
a 4-row one. That is P-51 exactly, and rehearsing this script is how it was caught a second
time.

> "Scanned bills of lading and invoices, fifteen fields each, read by an OCR-plus-model
> pipeline. **98% of fields correct**, and — the number we care about more — **zero
> hallucinated fields**: it never invents a value for a field the document leaves blank.
> Clean PDFs and degraded scans score within a point of each other on the rows measured so
> far."

## 5 · Ask the project a question (90 s, Analytics assistant page)

Type: **"Which hub has the longest dwell time?"**

Expect **Hubli, 373 minutes median dwell**.

> "That question is answered from a sorted table, not from the vector store — an embedding
> does not know that 373 is larger than 350, so nearest-neighbour search cannot answer 'which
> is longest'. Ranking questions go to the table, and the model only phrases what it was
> handed."

**If there is time, the story behind it** — it is the best one in the evaluation:

> "When we first ran this, the table was sorted by *friction*, dwell as a share of leg time,
> which puts Aluva first. The model was handed both hubs' numbers, noticed Hubli's dwell
> was longer, and answered Hubli. It was right and our router was wrong. Our own question
> set had the wrong expected answer too. We fixed the router; the model's answer is in the
> evaluation as it was given."

Then type: **"What is the GST rate on road freight?"**

> "Close to our topic, and not in our data."

**Whatever it answers, narrate what happened.** If it refuses: that is the grounding rule
working. If it answers from a retrieved document: say that the distance gate has 100%
precision and 50% recall, that domain-adjacent questions are the hard case, and that we
publish the number rather than tuning the gate on our own test set.

## 6 · Close (45 s, back to Overview or the India map)

> "Three things to take away. The audit localises a production planner's error to specific
> corridors, with a stated significance method and a stated sensitivity. The agent layer is
> deterministic at its core and measured everywhere. And the same aggregation code runs
> unchanged on 56 million rows — the architecture is not justified by our 26,000."

---

## Rehearsal checklist

- [ ] Rehearsal 1 (Krishna drives, W8 D3-D4) — note every pause over three seconds
- [ ] Rehearsal 2 (W8 D5) — with the figure exports open in a second window
- [ ] `python -m src.common.boot --check` green on the demo machine, from a fresh clone
- [ ] Browser zoom at 125% — the map legend is unreadable at 100% on a projector
- [ ] Terminals at a font size the back row can read
- [ ] `data/traces/agent_calls.jsonl` **not** cleared — the Agent console is a fallback if
      anything live fails: it shows real calls with real inputs and outputs

## If something breaks

| failure | what to do |
|---|---|
| TMS not running | orchestrator reports it and continues; the order still extracts and validates. Say so and move on |
| Stream produces no alerts | switch to Live alerts and read the recorded run; the page states its own source and timestamp |
| Assistant errors (no vector index) | `python -m src.common.vectordb --build` takes ~90 s. Do not do this on stage — check it in setup |
| Quota exhausted (20 calls/day) | every agent takes `--no-llm`; the assistant answers extractively. The verdicts are unchanged, because the model never decided them |
