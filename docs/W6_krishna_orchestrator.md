# W6 · Krishna — exception agent, lifecycle orchestrator, invoice auditor

Week 6 is my hard week (execution plan §1), and Gate 6 is the lifecycle running
agent-to-agent with nobody in the middle:

    order email -> Order Entry Agent -> TMS order + shipment
                -> monitoring (the streaming job's alerts)
                -> Tracking & Exception Agent -> notification + exception ticket

```bash
python -m src.agents.exception_agent --limit 5        # D1-D2, on the live alert sink
python -m src.agents.orchestrator --cases 10          # D3-D4, the whole lifecycle
python -m src.agents.mcp_server --list                # D3-D4, the tool server
python -m src.agents.invoice_auditor --count 20       # D5
```

Every one of those takes `--no-llm` or `--no-draft` and runs with **zero model calls**.
That is not a convenience flag; it is the shape of the week (D-041).

## 1. The decision that shaped everything: arithmetic decides, the model writes

Both agents this week compute their verdict and generate only the sentence that carries
it. Severity is a rule over how far past its own threshold a leg is predicted to run.
An invoice verdict is four comparisons. Neither is a judgement a model is better at than
a division.

The reason that matters is not elegance, it is **measurability**: Lahari scores both
agents this week, and a score means nothing if re-running the same input can produce a
different grade. The free-tier quota (20 calls a day, D-032) made the same choice
convenient, but it is the third reason, not the first. Full argument: D-041.

What it costs is honesty about the word "agentic": these agents do not reason their way
to a severity, they compute one. Everything a model would have decided here, the project
can already calculate.

## 2. Tracking & Exception Agent (D1-D2)

`alert -> investigate -> severity -> notification -> ticket`.

**Investigation is three lookups**: the Week 2 corridor audit (is this route a confirmed
bottleneck, and by how much), the hub-friction table (are either of its ends congested),
and the TMS (which shipment is this, and is it still ours). **Severity** is
`excess_ratio = predicted_gap / threshold_gap` against stated cut points, escalated one
step when the audit confirms the corridor genuinely is slower than the network. The cut
points are a **policy, not a measurement** — nothing in the data says 3× is
"critical" — so they live in one constant that can be argued with.

**First real run:** three alerts on corridors the TMS was actually carrying, three
tickets filed (`EXC-000001` to `EXC-000003`), three notifications sent on the file
channel.

**Two of those three severities were wrong**, and finding out why is the most useful
thing that happened this week (P-48). The escalation rule compared the audit's direction
against `"slower"`; the audit writes `"worse"`. The comparison never matched, so the
escalation had been dead code since the moment it was written, and the customer template
made the mirror-image mistake — it read "statistically significant" as "slow", which
is also true of the **512 corridors the audit confirmed are faster than the network**.
One customer was told their route is a confirmed slow one when the audit says the
opposite.

The fix is one predicate used by all three call sites, plus vocabulary validation at
load time so the next renamed value raises instead of quietly disabling the rule. Re-run
on the same three alerts: the confirmed-slow corridor escalated `high -> critical`, the
confirmed-fast one stayed `low` and dropped the false claim.

**A second bug, found by running it twice** (P-49): after filing, every shipment
vanished from the agent's view, because filing a ticket flags the shipment `exception`
and the agent's "in flight" filter listed only `created` and `in_transit`. The second
problem on an already-troubled consignment was exactly the one it could no longer see.

## 3. The lifecycle, as a graph (D3-D4)

`src/agents/orchestrator.py` is a LangGraph `StateGraph`. The composition is a graph
rather than four calls because **two edges are decided by agents, not by the
orchestrator**: an ambiguous email stops at a question and never reaches the TMS, and a
shipment the stream never flagged never becomes an exception (D-042).

**Ten cases, three distinct paths, no human in the middle:**

| path | cases | what happened |
|---|---|---|
| `intake -> clarify` | 5 | the email was missing a field; no TMS write at all |
| `intake -> book -> monitor -> done` | 3 | order + shipment filed; the stream had not flagged the corridor |
| `intake -> book -> monitor -> triage -> done` | 2 | flagged, graded, notified, ticketed |

That produced orders `ORD-000004`..`ORD-000008`, shipments `SHP-000004`..`SHP-000008`
and tickets `EXC-000004`/`EXC-000005`, all real rows in the TMS. The two tickets were
filed **after** P-48 was fixed, so their severities are the corrected ones.

**The MCP tool server** exposes twelve tools over three families — corridor stats,
predictions, TMS operations — and **computes none of them**. Each is a thin wrapper
over a module that already exists and is already tested. The one expensive tool,
`what_if_delay`, starts Spark and says so in its own docstring, pointing callers at
`alerts_for_corridor`, which answers the same question instantly from what the stream
already decided.

## 4. Freight Invoice Auditor (D5)

Four checks, all arithmetic: the invoice's own sum against its parts; the freight charge
against the corridor's audited rate band; the share taken by other charges; and repeated
invoice numbers.

**20 of 20 verdicts matched the seeded ground truth** — 10 disputed, 10 approved,
and **no clean invoice was disputed**, which is the direction that matters: a false
dispute costs a supplier relationship, a missed marginal overcharge costs a few hundred
rupees.

**The limitation is structural and is stated in D-043 rather than buried.** The rate band
comes from the same generator model that produced the invoices, so it is exact for this
corpus and **circular as a claim about real freight pricing**. It shows the auditor
catches invoices that depart from the network's own observed rates. It does not show
those rates are correct.

One deliberate non-finding: a corridor with no audited distance produces **no finding at
all**. "We cannot check this" is a different statement from "this is wrong", and the TMS
has only approve/dispute to say them in. Disputing an invoice because we lack history on
its corridor would bill a supplier for our own data gap.

## 5. A defect I inherited, and one I predicted

`POST /shipments` returned 500 on every order: the SQLite file had drifted from the
models, missing `shipment.notes` (P-47). **P-40 predicted this in Week 5, almost word for
word** — that by Week 6 the database would hold agent-filed orders worth keeping and
the obvious escape would be `--reset`, destroying them. It held three. A schema diff
found the one drifted column and `ALTER TABLE` added it with the data intact. The
ten-line diff belongs in Mounika's boot script, which is the one place already
responsible for starting everything.

## 6. Tests

- `tests/test_exception_agent.py` — 28 tests: the severity cut points, the
  escalation that only fires on a confirmed *slow* corridor, the vocabulary validation
  that would have caught P-48, and that a failed draft never costs a ticket.
- `tests/test_orchestrator.py` — 19 tests: both conditional edges, including that a
  `file` decision with nothing extracted still stops rather than posting an empty order.
- `tests/test_invoice_auditor.py` — 22 tests: every check, both band edges, and that
  an unauditable corridor is never a dispute.

## 7. What is not in this section

- **Neither agent has been evaluated by me**, and neither result above is an accuracy
  claim. Lahari scores the Exception Agent on the replay (notification precision,
  time-to-notification) and the Invoice Auditor on her own seeded set at her D3-D4 and
  D5. That separation is D-028's, and it is the only reason 20-of-20 is worth printing.
- **The drafted wording has not been run at scale.** Today's 20-call quota went to
  finishing Week 5's order evaluation, so every run above used the template fallback.
  The prompts are written and exercised; the drafted variants run on the next day's
  quota.
- The MCP server has been started and its tools called directly; it has **not** been
  driven by a real MCP client over stdio.

**Decisions:** D-041, D-042, D-043. **Problems:** P-47, P-48, P-49.
