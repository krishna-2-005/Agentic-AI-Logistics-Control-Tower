# W7 · Krishna — analytics assistant, tracing, MCP over stdio, extraction evaluation

Week 7 is the first week under execution plan v3.1, which reopened gaps in earlier weeks
before adding anything new. My share of the gap register was G-01 (the Document agent was
never scored per field), G-06 (the MCP server had only been called in-process) and G-07
(alerts never left the machine). My Week 7 build work was the Analytics assistant, the
agent tracing and the two dashboard pages that show them.

```bash
python -m src.agents.mcp_stdio_client                       # G-06: real MCP client over stdio
python -m src.agents.analytics_assistant "which hub has the longest dwell time?" --no-llm
python -m src.agents.assistant_eval --no-llm                # the fixed 30 questions, zero quota
python -m src.ml.eval_extraction --consignments 20          # G-01, resumable across quota days
streamlit run src/dashboard/app.py                          # Agent console, Analytics assistant
```

## 1. G-06 — the MCP server, driven by a real client

Until this week every MCP test called the tool functions in the same Python process, so
the protocol itself had never run. `src/agents/mcp_stdio_client.py` starts
`python -m src.agents.mcp_server` as a subprocess, does the MCP handshake over stdin and
stdout, lists the tools, and makes 8 calls with arguments taken from real data (a real
corridor, a real hub).

**Result:** 13 tools discovered, 8 calls to 7 distinct tools, **0 errors**, every result
valid JSON. Handshake 1,594 ms; the slowest calls are `tms_health` (2.4 s, a network
round trip) and `search_knowledge` (1.8 s, which loads the embedding model). The table
lookups take 6 to 52 ms. Transcript: `benchmarks/raw/w7_mcp_stdio_transcript.json`.

It found two real bugs before it passed:

- **P-54.** With the TMS stopped, `tms_health` crashed instead of reporting it down.
  `httpx` connection errors are not `OSError`, which is what callers caught. The client
  now turns every transport failure into `TMSError`, and a test points it at a dead port.
- **P-57.** The server's tool-name list was typed by hand and missed `search_knowledge`.
  I committed that with two red tests, because `pytest | tail` hides pytest's exit code.
  The next commit registers names in the `@tool` decorator itself and says in its message
  that the previous one went up red.

## 2. The Analytics assistant

Questions about the project's own results, answered from its tables, audits, decisions
and problem log:

    question -> route -> (ranked table | vector retrieval) -> refusal gate -> answer

**Ranking questions do not use retrieval.** D-045 recorded that semantic search, asked
"which hub has the longest dwell time", ranked the 11th hub above the 1st: an embedding
does not know that 350 is more than 257. Questions with a ranking word (worst, slowest,
top N, longest) about corridors or hubs are answered straight from the ranked CSV, and the
model only phrases a ranking it was given. A hub question without a ranking word ("tell me
about dwell at the Hubli hub") goes to retrieval, because the top-5 table would answer a
different question.

**Out-of-scope questions are refused before any model call**, when the nearest indexed
document is further than a cosine distance of 0.63. That costs no quota, and it means a
model never gets the chance to answer from general knowledge. The threshold was
calibrated on 20 probes (`w7_assistant_refusal_calibration.json`): in-scope questions
landed at 0.349 to 0.588, out-of-scope ones at 0.681 to 0.941. My first draft used 0.55,
which would have refused "how was the champion model chosen" (0.588).

## 3. The fixed 30-question set, without the model

`benchmarks/raw/w7_assistant_questions_v1.json`: 6 ranking, 6 corridor and hub facts,
8 decisions, 4 problems and 6 out-of-scope questions, each with its expected route and
expected source. I wrote it before running the assistant over it.

| | result |
|---|---|
| route correct | **27 of 30 (90.0%)** |
| source correct | **25 of 30 (83.3%)** |
| ranking questions | 6 of 6 |
| refusal precision | **100%** — nothing in scope was refused |
| refusal recall | **50%** — 3 of 6 out-of-scope questions refused |

**The refusal misses are the finding (P-56).** The questions it failed to refuse are
questions close to the project's topic: diesel prices next month (0.595), GST on road
freight (0.539) and Delhivery's fleet size (0.502). Real in-scope questions sit at 0.510,
0.531 and 0.598, so no threshold separates them. Distance measures *topic*, not whether a
document answers the question. My calibration probes were general knowledge (capitals,
bread, football) and too easy to show this.

I did not tune the threshold on the 30 questions until the misses disappeared. That would
fit the gate to the test. The gate stays for its precision, and the second layer is the
prompt's rule to answer only from context. The model-phrased run measures that layer.

**The two source misses have different causes.** D08 expects D-048, which was written
after the vector index was last built, so no retrieval could have found it. The index is
rebuilt after the Week 7 merge, and the no-model run is repeated then. D02 ("why does the
streaming job drop fact events?") is a real miss. D-037 is in the index, but the three
nearest documents were the Week 5 streaming write-ups, which discuss the same job without
the decision.

## 4. Every agent call is traced

`src/agents/tracing.py` writes one JSON line per unit of work to
`data/traces/agent_calls.jsonl`: agent, start time, duration, inputs, outputs, and the
error if it raised. Failed calls are traced too, because a log that records only
successes cannot answer "what happened to that request". Long fields are truncated with a
note of how much was cut, not dropped.

Traced: Order entry (per email), Document extraction (per document), Invoice auditor (per
invoice), Exception triage (per alert), the Orchestrator (per lifecycle, with its agents'
own traces beside it) and the Analytics assistant (per question, refusals included). A
test conftest points the log at a temporary file, so test runs never write fake calls
into the real log.

**Dashboard.** The *Agent console* page shows calls, failures and median duration per
agent, a filterable list of recent calls, the full inputs and outputs of any call, and the
MCP stdio transcript. The *Analytics assistant* page takes a question, answers without the
model unless asked (a model call spends daily quota), and shows the route, sources,
retrieval distance and the context the answer was built from, beside the 30-question
scorecard. Both pages render without exceptions under Streamlit's `AppTest`.

## 5. G-01 — per-field extraction accuracy, clean against noisy

`src/ml/eval_extraction.py` scores the Document agent field by field on 20 consignments,
stratified by seeded error type. Each document is scored as a clean PDF (text layer) and as
a noisy scan (Tesseract OCR), so the gap between the two is the cost of OCR. Results are
cached per document, so a run that hits the quota resumes where it stopped.

**Status: 3 extractions cached, the rest owed.** The first smoke run hung for twenty
minutes after the third call. The model client had no request timeout, and retries can
spend quota the cache never sees (P-53). `get_llm()` now sets a 120 s timeout and 2
retries. The full run spans quota days (20 calls a day, resetting at 12:30 IST).

## Owed

| item | waits on |
|---|---|
| G-01 full run, then one prompt iteration on the weakest three fields | daily Gemini quota |
| Model-phrased run of the 30 questions (second refusal layer, answers for Lahari's groundedness judging) | daily Gemini quota |
| Vector index rebuild and no-model rerun after the Week 7 merge | merge to `dev` |
| G-07 real alert channel (email or Telegram) | credentials from the team, never committed |

Problems logged this week: P-53, P-54, P-56, P-57.
