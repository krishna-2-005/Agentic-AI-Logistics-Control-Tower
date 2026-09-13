# W6 · Mounika — one-command boot, vector store, README v1

Week 6's three deliverables are all about a person who is not me being able to run this:
a single command that starts everything, a way to ask the project what it knows, and a
README that does not lie.

```bash
python -m src.common.boot --check     # what is ready, what is missing, and the fix for each
python -m src.common.boot             # TMS -> replay -> streaming -> agents, then tear down
python -m src.common.vectordb --build
python -m src.common.vectordb --query "which corridors are worst for delays"
```

## 1. Boot (D1-D2)

Starts the mock TMS, replays trips, scores them through the streaming job, runs the
Exception Agent and the orchestrator over the result, optionally opens Streamlit, and
**stops every child process on the way out** — in that order, because that is the
order they actually depend on each other.

**Preflight runs first and reports everything at once.** Six weeks have produced one
recurring failure: a run dies twenty minutes in because an artefact three stages back was
never built. So:

```
  [OK  ] cleaned parquet: clean_v1
  [OK  ] feature table: features_v1
  [OK  ] champion model: data/models/champion
  [OK  ] corridor audit: w2_corridor_audit.csv
  [OK  ] TMS schema: matches the models
  [OK  ] java: C:\Program Files\Common Files\Oracle\Java\javapath\java.EXE
  [OK  ] LLM (gemini): key present
```

Each failing line carries the command that fixes it. A missing LLM key is reported and
**not** blocking, because every agent runs without one.

**Full run, all four steps green:**

| step | what it did |
|---|---|
| `producer` | 300 legs replayed to the file sink over 8s |
| `streaming` | scored, alerts written |
| `exception_agent` | worst alerts investigated, graded, notified, ticketed |
| `orchestrator` | 5 emails through the whole lifecycle |

### The schema repair, and why it is not a nice-to-have

`SQLModel.metadata.create_all` creates missing *tables* and **never alters an existing
one**. So every model change after the first run is invisible until something writes the
new column — which in Week 6 was `POST /shipments` returning 500 on every order
because `shipment.notes` existed in the model and not in the file (P-47).

The obvious fix is a re-seed. It would have destroyed three real agent-filed orders, and
**P-40 predicted exactly that in Week 5**, almost word for word. So `boot` diffs
`SQLModel.metadata` against `PRAGMA table_info` and adds what is missing with
`ADD COLUMN`, in place, rows intact. A column whose *type* changed is reported and never
rewritten: that is a migration, and a migration is a decision with data loss attached
(D-044).

### A default that had been wrong since Week 5 (P-50)

Boot's first run failed at the producer: `STREAM_SOURCE` defaults to `kafka`, and this
machine has never had a broker (D-035). Every Week 5 run passed `--sink file` explicitly
or called the sink directly, so **nothing had ever exercised the default**. A default
every caller overrides is not a default, it is a trap with a long fuse — and the way
to find one is to run the documented command with no flags, which is precisely what a
boot script does.

## 2. Vector store (D3-D4)

ChromaDB over **1,434 documents**: 1,130 audited corridors, 20 congested hubs, and 284
documentation sections. Exposed as the `search_knowledge` MCP tool alongside Krishna's
others.

**A document per corridor, not per table.** Retrieval is only as good as its unit:

```
[0.4257] corridor :: IND203390AAA>IND201301AAF
Corridor IND203390AAA>IND201301AAF runs from Anupshahar_DcntCLY_D in Anupshahar to
Noida_Sec 02_DPC in Noida, Uttar Pradesh. Over 20 legs it averages 299 minutes against
an OSRM plan of 97 minutes, a median gap ratio of 2.59. It runs 1.36 times the network's
typical overrun and is statistically confirmed slower than the network (q = 0.0002).
It is bottleneck rank 15.
```

Docs are split at their own headings rather than at a character count, because a decision
entry is a unit of meaning and a fixed window cuts it mid-argument. Asked *"why was the
delay threshold set to 2x"*, the store returns D-003's own section first.

The audit's word `worse` is translated to "slower than the network" on the way in.
P-48 is what that word costs when it travels raw to a reader.

**Embeddings:** Chroma's default ONNX MiniLM — ~80 MB, downloaded once, CPU-only,
1,434 documents in about 90 seconds. `sentence-transformers` would pull ~2.5 GB of torch
onto a machine with ~5.6 GB usable for an embedding of the same family.

### What retrieval cannot do, stated before anyone relies on it

Asked *"which hub has the longest dwell time"*, it returns **rank 11 above rank 1**. Both
are relevant; nothing in an embedding knows that 350 minutes is more than 257. **Semantic
search finds the right document; it does not order documents by a number inside them.**
Superlatives belong to the tables. Week 7's assistant has to consult the table for
"worst", or it will answer confidently with whatever sounded closest (D-045).

The index is never a source of truth. Every document is generated from a table or a file
that remains the authority, so it is always safe to delete and rebuild.

## 3. README v1 and repo cleanup (D5)

The README now documents the whole system: one-command boot, the streaming pipeline, all
five agents with their zero-API-call flags, the vector store, the MCP server, and the
Week 5-6 results with links to the `benchmarks/` files that produced them.

**The cleanup that mattered was a contradiction, not clutter.** The Contributing section
told every new member to commit `[W<N>][AREA] imperative description`. **GIT_RULES §7 has
banned bracketed prefixes since Week 1, and not one commit in the history uses one.** The
README was the document that was wrong, and it is the document a new contributor reads
first. Fixed, with a note saying so rather than a silent edit.

Also corrected: `src/automation/` was credited with the alert bot, which lives in
`src/agents/` and is Krishna's; `src/agents/` was described as "five agents" without
naming them; `src/common/` did not mention the boot script or the vector store.

The Honest scope section gained the two things a reader deserves up front: that the
agents **compute** their verdicts and a model writes only the sentence (D-041), and that
the Kafka sink, the Telegram and email channels, and a real MCP client have **never run
here**.

### A demonstration that rewrote the evidence (P-51)

Boot's first clean run left `git diff` showing two benchmarks artefacts shrunk by a
combined 297 lines. Nothing had failed: each agent writes its run to a fixed path under
`benchmarks/raw/`, so boot's five-case orchestrator run had **silently replaced the
ten-case run Krishna's write-up cites**. Every number in this project is supposed to
trace to a file in `benchmarks/`; a demonstration that rewrites those files breaks the
trace without touching the prose, and it would have surfaced when someone opened the JSON
to check a figure in the report. Both agents now take `--out`, boot writes to `logs/boot/`,
and the overwritten files were restored.

## 4. Tests

- `tests/test_boot.py` — 10 tests: the preflight report, and schema drift found,
  repaired, idempotent, **and non-destructive** — the last one asserts a row
  survives the repair, because that is the whole difference between this and a re-seed.
- `tests/test_vectordb.py` — 12 tests: how a table row becomes a sentence, that
  `worse` is translated, and that a short section folds forward instead of being indexed
  alone.

## 5. What is not in this section

- **Boot has only been run on this machine.** It shells out to `sys.executable`, uses
  `CREATE_NEW_PROCESS_GROUP` on Windows and `start_new_session` elsewhere; the POSIX path
  is written and unexercised.
- **The Kafka sink still has not run against a broker** (D-035), and boot pins the file
  sink rather than fixing the default (P-50, left for the Week 7 sync).
- **The MCP tools have not been driven by a real MCP client** over stdio — they have
  been called directly and through `--list`.
- The index holds no *numbers* anyone should quote: it is for finding the document that
  holds the number.

**Decisions:** D-044, D-045. **Problems:** P-47 (found by Krishna, fixed here), P-50.
