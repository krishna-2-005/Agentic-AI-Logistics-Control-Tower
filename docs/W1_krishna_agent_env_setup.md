# W1 · Krishna — agent environment, prompt library, and dashboard skeleton

## What I built

**LLM provider layer** — `src/agents/llm.py`. One `get_llm()` that every agent calls;
nothing else constructs a provider client (D-007). Supports Gemini, Anthropic, and a
local Ollama model, selected by `LLM_PROVIDER` in `.env`, with
`get_llm(with_fallback=True)` chaining the other configured providers behind the
primary so a rate-limited free tier cannot kill a Week 7 evaluation run mid-way.
Temperature defaults to 0.0 — extraction and audit agents must be deterministic; only
the Week 6 customer-notification drafting raises it.

**Versioned prompt library** — `src/agents/prompts/` with `registry.py`. Prompts live
at `<agent>/v<N>.md` and are **never overwritten** (D-008); `load_prompt("doc_extraction")`
takes the newest, `load_prompt("doc_extraction", "v1")` pins one for an ablation.
Rendering uses `string.Template` rather than `str.format` because prompts are full of
literal JSON braces, and a placeholder that silently fails to substitute shows up
three days later as an unexplained accuracy drop.

Two v1 prompts written now, because they encode decisions that shape later weeks:
- `doc_extraction/v1.md` — fifteen fields, and the rule that matters most: **never
  invent a value; return `null`.** It also forbids reconciling invoice arithmetic —
  detecting a total that doesn't add up is the Auditor's job in Week 6, and silently
  fixing it here would hide the exact errors the seeded-error set exists to catch.
- `analytics_assistant/v1.md` — answers only from retrieved context, with a required
  verbatim refusal string and mandatory source attribution. Refusal is scored as
  correct; a fluent unsupported answer is scored as failure.

The other three directories carry a `_README.md` naming the week they land and the
behaviour they'll be scored on.

**LangGraph hello-world** — `src/agents/hello_agent.py`. Deliberately the same shape
as the five real agents, so wiring mistakes surface now rather than during the Week 6
orchestrator build. It exercises a typed state, a **conditional edge** that routes on
state, a tool node reading **real project data** (Lahari's corridor table, not a stub),
an LLM node grounded strictly on that tool output, and a compiled graph with a
checkpointer. It answers *"how busy is this corridor and how far over plan does it
run?"* — a miniature of the Analytics Assistant, which is this graph with a vector
store where the CSV lookup sits.

It has a **deterministic fallback**: with no API key configured the graph still runs
end-to-end and answers from the tool output, so the wiring is testable before keys
exist. And it refuses — "what is the weather in Paris?" hits the refusal branch, which
is the behaviour Week 7 scores.

**Streamlit control tower skeleton** — `src/dashboard/app.py`. Nine-page navigation
covering every page Weeks 2-7 fill. Pages without data say which week and which owner
fills them rather than showing placeholder charts. The Overview page is live now,
built from Lahari's leg summary.

**India city-coordinate lookup** — `src/dashboard/reference/india_city_coords.csv`,
49 facility-name prefixes → canonical city, state, lat/lon, covering ~67% of all
facility mentions. The aliases are the whole point: `Bangalore` and `Bengaluru` are
both in the data, `MAA` means Chennai, `FBD` means Faridabad, `Del` means Delhi, and
`Mumbai Hub (Maharashtra)` has no underscore so naive parsing takes the entire string
as the city. Unmapped prefixes would be **silently missing dots** on the Week 2 map, so
the map page reports coverage and lists what's unmapped instead.

## How to run / verify

```bash
python -m src.agents.hello_agent --dry-run    # compiles the graph, no API call
python -m src.agents.hello_agent              # 3 questions, incl. one that must refuse
streamlit run src/dashboard/app.py            # → http://localhost:8501
```

## Numbers

No agent-evaluation numbers this week by design — the first are Week 4's field-level
extraction accuracies, which Lahari produces (builder and judge stay separate).

| Item | Value |
|---|---|
| Providers wired | 3 (Gemini, Anthropic, Ollama) |
| Prompt versions committed | 2 (`doc_extraction/v1`, `analytics_assistant/v1`) |
| Hello-agent questions answered | 3/3, including 1 correct refusal |
| Dashboard pages scaffolded | 9 |
| City-coordinate rows | 49, covering ~67% of facility mentions |

## Status — verified by running, not by inspection

- ✅ **LangGraph hello agent runs end-to-end.** Graph compiles
  (`['__start__','parse','lookup','answer','refuse','__end__']`), the conditional
  edge routes on state, the tool node reads Lahari's real corridor table, and the
  **refusal branch fires correctly** — "what is the weather in Paris?" returns the
  refusal, `grounded=False`. Sample output on real data:

  > *How bad are the corridors around Gurgaon?* → "5 corridors found for Gurgaon. The
  > busiest is Delhi → Gurgaon with 100 legs observed. The furthest over plan is
  > Gurgaon → Sonipat at 2.07× planned time (119.0 min mean gap)."

- ✅ **The deterministic fallback works**, which matters more than it sounds: with no
  API key the graph still completes and answers from the tool output, so the wiring is
  testable before keys exist and a rate-limited free tier cannot block a Week 7
  evaluation run.
- ✅ Streamlit skeleton boots and the Overview page renders against the leg summary.
- ✅ Prompt registry loads and versions resolve (`doc_extraction/v1`, 2,594 chars).
- ⬜ **No LLM key in `.env`.** `GEMINI_API_KEY` is unset, so Gate 1's "LLM API responds"
  is **not met** — the agent is running its fallback, not a real model. This is the one
  Gate 1 item still open and it is mine.

### Note on langgraph versions

`langgraph` resolves to **1.2.10** on Python 3.13, not the 0.2.x the blueprint era
assumed. The graph API used here (`StateGraph`, `add_conditional_edges`,
`MemorySaver`, `compile(checkpointer=...)`) is unchanged across that jump and was
verified by running. Worth knowing before anyone follows a 0.2-era tutorial.

## Next (Week 2)

- India map v1 — corridors coloured by delay severity from Lahari's audit table.
- Hub-friction leaderboard page.
- Collect 3-4 real BOL/invoice layouts to model the Week 3 synthetic templates on.

## Role-preparation log (personal thread, execution plan §5)

**W1 — LangGraph basics.** Practised: state graphs with typed state, conditional edges
as the routing primitive, tool nodes over real data, checkpointers for resumable runs,
and provider abstraction with fallback chains. The transferable lesson is that the
hello-world should be the same *shape* as the real system — a print-statement smoke
test would have proved nothing about Week 6.
