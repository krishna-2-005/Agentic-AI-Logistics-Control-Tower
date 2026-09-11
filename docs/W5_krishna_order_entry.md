# W5 · Krishna — Order Entry Agent, live alerts panel, alert bot

Week 5 D1-D2: an agent that reads a customer order email and either **files a real
order** on the mock TMS or **asks one clarifying question**, plus the corpus of
deliberately imperfect emails that makes the second half testable at all.

```bash
python -m src.agents.order_corpus --count 12          # build the email corpus
python -m src.agents.order_agent --count 6 --dry-run  # extract + validate, never POST
python -m src.agents.order_agent --count 6            # file for real
```

Writes per-email outcomes to `benchmarks/raw/w5_order_agent_runs.json` — outcomes,
never scores. Lahari authors the 50-case evaluation set and measures success and
clarification rates at D5, the same builder/judge split Week 4 used for document
extraction (D-028).

---

## 1. The corpus has to contain bad emails, or the interesting half is untested

The `order_entry` prompt slot has carried one requirement since Week 3: *an ambiguous
order must produce a question, not a confident guess.* You cannot test that with clean
input. On emails that state everything, an agent that never asks anything scores
perfectly — indistinguishable from one that asks correctly.

So `src/agents/order_corpus.py` builds five variants on top of Week 3's
`ConsignmentRecord` generator (no second corridor sampler — those records already draw
real audited corridors and real centre codes, D-021's reasoning reused):

| variant | what the email withholds | a correct agent should |
|---|---|---|
| `clean` | nothing | file it |
| `missing_weight` | "pallets are still being made up, no final weight yet" | ask for `weight_kg` |
| `missing_pieces` | no piece count anywhere | ask for `pieces` |
| `vague_origin` | "our Jalandhar warehouse" — a city, not a centre code | ask for `origin_centre` |
| `ambiguous_route` | "send it whichever way works out best at your end" | ask for `route_type` |

Each email carries `expected_action` and, for the four `clarify` variants,
`expected_missing` — the field a good question has to be *about*. That is the whole
point: it lets D5 score not merely whether the agent asked, but whether it asked the
right question. Ground truth also **drops** whatever the variant removed, so an agent
is never marked wrong for declining to invent a value nobody wrote.

**The first generated corpus was quietly broken and its own summary line looked fine.**
A weighted random draw of 12 produced six `clean`, plus `vague_origin` and
`ambiguous_route` — and zero `missing_weight`, zero `missing_pieces`. Two of the four
clarification paths would have gone completely unexercised while the log cheerfully
reported "12 emails, 6 should file, 6 should clarify". Fixed by seeding one of each
variant before the weighted draw fills the remainder. Weighting is still tilted toward
`clean` (5:2:2:2:2) because the real ratio of good to ambiguous customer email is
nothing like 1:1, and a corpus that is mostly broken teaches the wrong reflex.

## 2. Three stages, kept apart because they break differently

`src/agents/order_agent.py`:

1. **`extract_order()`** — one LLM call through `src.agents.llm.get_llm()` (D-007's
   single construction site) rendering the versioned `order_entry/v1.md` (D-008).
   Returns the model's own `file` / `clarify` decision.
2. **`validate_order()`** — pure Python, no model. Required fields present, centre
   codes `IND` + 6 digits + 3 letters, `route_type` one of the two real ones, `pieces`
   a positive whole number, `weight_kg` positive.
3. **`post_order()`** — the actual `POST /orders`, carrying `external_ref` so a
   replayed email cannot file twice (D-017 built that key for exactly this).

Collapsing these into one try/except would make three genuinely different failures
look identical in the log. A bad extraction is a *prompt* problem; a validation
failure is a *contract* problem; a POST failure is an *environment* problem. And
`validate_order` returns a list rather than raising — an agent that gets one field
wrong should still produce a record naming exactly which one, not an exception that
loses the other five.

`process_email()` never raises for a single email, and records everything it learned in
an `OrderOutcome` — including the failures — because a run that stops at the first bad
email tells you about one email instead of six. Full reasoning in D-036.

## 3. What the run actually produced

Six emails, prompt `order_entry/v1`, real TMS at `http://127.0.0.1:8000`:

**6 of 6 correct actions. 3 filed, 3 clarified. 0 extraction failures. 0 field
mismatches against ground truth.**

| # | variant | expected | got | result |
|---|---|---|---|---|
| 1 | `vague_origin` | clarify `origin_centre` | clarify `origin_centre` | *"Could you please provide the origin centre code for your Farrukhbad warehouse?"* |
| 2 | `clean` | file | file | `ORD-000001` (201) |
| 3 | `ambiguous_route` | clarify `route_type` | clarify `route_type` | *"Would you like this shipment sent via FTL or Carting?"* |
| 4 | `clean` | file | file | `ORD-000002` (201) |
| 5 | `vague_origin` | clarify `origin_centre` | clarify `origin_centre` | *"Could you please provide the centre code (IND code) for your Jalandhar warehouse?"* |
| 6 | `clean` | file | file | `ORD-000003` (201) |

Every extracted field matched the corpus ground truth. Each clarification is one
sentence naming one field — not a form of five questions, which is a real failure mode
in this shape of agent and the reason the prompt's rule 2 exists.

The three filed orders are genuinely in the TMS with `source=agent` and real corridor
centre codes, not a mocked response. **Idempotency verified by hand:** re-posting a
filed `external_ref` returned HTTP 200 with the order count unchanged at 3 — no
duplicate, exactly what D-017 promised.

Six emails, dry-run first (extraction and validation only) and then a real run: 12 LLM
calls against a 20-a-day free tier (D-032), which is why `--count` defaults to 6 rather
than the corpus's 12.

## 4. Two problems worth the write-up

- **P-41 — the agent's own validator passed an order the TMS rejected.** Three clean
  emails extracted perfectly, validated clean, and came back `422`:
  `source: Input should be 'api', 'agent' or 'seed'`. `post_order` was sending
  `"EMAIL"`, invented at the call site because it read well. The structural lesson is
  the useful part: `validate_order` checks *the fields the model extracted*, and
  `source` is not one of them — it is added by the agent afterwards, downstream of
  every check. A validation layer that inspects the model's output rather than the
  payload actually sent has a blind spot exactly the size of whatever the code appends
  later, and everything in that blind spot fails at the far end of an HTTP call where
  it looks like somebody else's bug. Fixed by importing `OrderSource` so an invalid
  value is not merely detectable but impossible.
- **P-40 — `src.tms.seed` cannot do what its docstring promises.** Seeding the TMS died
  on `FOREIGN KEY constraint failed`. `seed()` says orders survive a non-reset re-seed
  and then deletes all facilities unconditionally, which `Order` holds an FK to — so
  that path cannot work once any order exists. It has simply never been exercised,
  because nothing had filed an order before a re-seed until now. Worked around with
  `--reset` (the leftover was one Week 2 test row); logged for Mounika as the module's
  owner rather than patched from an agents branch. It matters in Week 6, when the
  orders in that database are agent-filed and worth keeping.

## 5. Tests

`tests/test_order_agent.py` — 18 tests, no LLM and no HTTP. Pinned here: every way
`validate_order` should reject a bad extraction (including `True` masquerading as an
integer, which sails through `pieces >= 1` because Python says a bool is an int), and
the corpus invariants Lahari's D5 scoring will actually depend on — determinism in the
seed, every variant present, `expected_missing` matching the variant, and ground truth
never containing what the email withheld.

## 6. Live alerts panel (D3-D4)

The dashboard's **Live alerts** page, until now a placeholder, reads the streaming job's
alert sink and nothing else. Two pieces:

- **`src/dashboard/alerts.py`** — the reader. Loads every `alerts_*.jsonl` micro-batch
  file, deduplicates on `alert_id`, parses the two clocks, and computes severity, a
  corridor rollup and freshness. No Streamlit, no Spark, so it is testable. It is also
  shared with the bot (§7), so the panel and the bot cannot come to disagree about which
  alert is worst.
- **The page** — four numbers (alerts, corridors, worst overrun, age of the newest
  alert), the most severe alerts, and the worst corridors. No SparkSession, so it stays
  inside D-009.

```bash
python -m src.streaming.producer --limit 2000 --duration 20 --clean
python -m src.streaming.job --once
streamlit run src/dashboard/app.py          # -> Live alerts
```

### Three design calls, each against a specific way it goes wrong

- **Two clocks, parsed differently on purpose.** `event_time` is the leg's real 2018
  creation time, a bare timestamp with no offset. `alert_time` is when this pipeline
  flagged it, an offset-aware instant from this machine. Reading `event_time` as UTC
  and converting to local time would silently shift every historical timestamp by 5h30.
  So it stays naive, the wall-clock one is converted, and the page shows both under
  labels that say which is which. A replay compresses ~26 days into a minute, so a panel
  that mixed them up would read as a system with a broken clock.
- **Severity is excess over the leg's own threshold**, not raw predicted minutes. Raw
  minutes rank every long haul above every short run regardless of how late either is.
- **Staleness is shown, never hidden.** When the newest alert is over five minutes old
  the page says so: *"This panel is showing a finished replay, not a live stream."* A
  panel that hides staleness hides the one failure that matters most, which is that the
  stream stopped.

### What it showed

Rendered headlessly (Streamlit `AppTest`) against the real sink, no exceptions, both times:

| | full replay, read 38 h later | fresh replay, read immediately |
|---|---|---|
| Alerts | 17,317 | 1,347 |
| Corridors | 2,033 | 846 |
| Worst overrun | 881 min | 652 min |
| Newest alert | **38 h ago** + staleness warning | **just now**, no warning |

The right-hand column is **Gate 5**: a replayed event at one end produced a live alert
on the dashboard at the other. It came from a fresh 4,000-event replay run through the
producer and the job together, with the page reading the sink straight afterwards.

## 7. Alert bot (D5)

`src/agents/alert_bot.py` reads the same sink, picks the alerts worth a person's
attention, and sends each as a message naming the shipment, the corridor and the
predicted delay.

```bash
python -m src.agents.alert_bot --top 10         # send the 10 worst new alerts
python -m src.agents.alert_bot --dry-run        # show them, send and remember nothing
```

**It sends a shortlist, not the stream** (D-039). 17,317 alerts from 26,369 legs is
two pages for every three shipments, and the reliable result of that is a recipient who
stops reading. Three rules, each stated rather than emergent:

1. **New only.** Keyed on `alert_id`, persisted in a small state file. Run twice
   against the real sink it sent 10, then the *next* 10: 20 distinct ids, no repeats.
2. **Worst first**, by excess over the leg's own threshold, the same measure the panel
   ranks by.
3. **Capped per run**, with the held-back count in the log rather than silently dropped
   (`1347 alert(s) in the sink, 1347 new, 3 sent via file (1344 held back by the cap)`).

A real message, from the fresh replay, sent a minute after the job flagged it:

```
[1/3] DELAY PREDICTED - IND712311AAA>IND781018AAB
  shipment trip-153680212532637033 (FTL), leg trip-153680212532637033|20180913012845|IND712311AAA>IND781018AAB
  planned 688 min; predicted 2028 min (+1340 min, +652 past the 688 min threshold)
  created 2018-09-13 01:28 (replayed), flagged 06:34:22
```

The planned time is there because "+1340 min" has no scale without it. When the
prediction was made with no history for the corridor, origin or destination, the message
adds a line saying so (D-023).

**Which channel actually ran, stated plainly:** the **file** channel, which appends to
`data/stream/alert_messages.log`. Telegram (Bot API `sendMessage`) and email (SMTP) are
implemented, but this project has no bot account and no SMTP credentials, so **neither
has been run against a live service**. That is D-035's rule for the Kafka sink applied
a second time. Pick Telegram without credentials and the bot refuses before sending
anything, naming what it needs: `telegram channel needs TELEGRAM_BOT_TOKEN,
TELEGRAM_CHAT_ID`. The seen-id state is left untouched.

## 8. A bug in my own Week 4 page (P-46)

P-45's carry said to grep every place the day-of-week convention is written down. One of
them is mine: the what-if predictor (`src/ml/predict.py`, Week 4 D5) builds its row with
`departure.weekday()`, Monday = 0, and the model was trained on Spark's Sunday = 1. They
never agree on any day. A Wednesday is 2 on the page and 4 to the model. So every
what-if prediction since Week 4 has used a day-of-week value on a different scale from
the one the model learned. No exception, no null, nothing visible.

Fixed at the Week 5 merge, once Lahari's shared `temporal_features` helper had
landed: the what-if row's temporal fields now come from it, and two tests pin the
encoding. Measured on all 5,274 test legs, the effect was real but small. 35.9% of
predictions moved, by 0.6 minutes on average (worst 62.9), and 13 delay calls flipped
(0.2%); test MAE was 36.9 either way. The champion barely leans on day-of-week. That
made the bug cheap, and it was luck: under a model that weighted the day heavily, every
what-if answer would have been wrong and nothing would have said so.

## 9. Tests

- `tests/test_order_agent.py` — 18 tests (D1-D2).
- `tests/test_alerts_panel.py` — 21 tests, no Spark, no Streamlit, no network. They pin:
  - that the historical clock is *not* shifted by the local offset;
  - that replayed batches do not double-count;
  - that a malformed line costs that line and not the panel;
  - the bot's worst-first cap and its never-resend rule, end to end through the file
    channel, twice;
  - that an unconfigured channel refuses before sending.

## 10. What is not in this section

- **The 6-of-6 order-entry result is a smoke test, not an accuracy number.** The number
  that counts is Lahari's, on the 50-case set she authors at D5, which the agent has
  never seen.
- **Telegram and email have never been sent to a live service** (§7). The first real
  send is when a bot token exists.
- **The alert counts describe the sink, not the model's accuracy.** The streaming job
  scores replayed history against an end-of-window snapshot (D-037), so what the panel
  and bot show is how the alert stream behaves, not how well delays are predicted.

**Decisions:** D-036, D-039. **Problems:** P-40, P-41, P-46.
