# W5 · Krishna — Order Entry Agent (email → structured order → TMS)

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

## 6. What is not in this section

- **This 6-of-6 is a smoke test, not an accuracy number.** Six emails, from the corpus
  the agent was developed against. The number that counts is Lahari's, on the 50-case
  set she authors at D5 and which this agent has never seen.
- `missing_weight` and `missing_pieces` exist in the corpus and are covered by tests,
  but did not appear in the first six emails and so have not yet been put to the model.
- D3-D4 (live alerts panel) and D5 (alert bot) are still ahead this week.

**Decisions:** D-036. **Problems:** P-40, P-41.
