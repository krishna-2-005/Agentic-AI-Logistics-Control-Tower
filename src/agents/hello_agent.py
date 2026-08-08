"""Gate 1 smoke test — a real LangGraph agent, not a print statement.

    python -m src.agents.hello_agent
    python -m src.agents.hello_agent --dry-run     # graph wiring only, no API call

Deliberately small, and deliberately the same shape as the five real agents that
follow. It exercises every mechanism Week 6 depends on, so a wiring mistake surfaces
in Week 1 instead of during the orchestrator build:

* a typed ``TypedDict`` state passed between nodes,
* a conditional edge that routes on state rather than running straight through,
* a tool node reading **real project data** (the corridor support table from Lahari's
  EDA) rather than a stub,
* an LLM node grounded strictly on what the tool returned,
* a compiled graph with a checkpointer, so conversations are resumable.

The question it answers — *how busy is this corridor, and how far over plan does it
run?* — is a miniature of the Analytics Assistant, which is the same graph with a
vector store where the CSV lookup is.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Annotated, Literal, TypedDict

import pandas as pd
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.agents.llm import LLMNotConfigured, describe, get_llm
from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("agents.hello")

CORRIDOR_TABLE = config.BENCHMARKS_RAW_DIR / "w1_corridor_support.csv"


class AgentState(TypedDict, total=False):
    """State threaded through the graph. Each node adds keys; none mutates in place."""

    question: str
    city: str | None
    corridors: list[dict]
    answer: str
    grounded: bool
    trace: Annotated[list[str], lambda a, b: a + b]


# ── Node 1: understand the question ──────────────────────────────────────────
def parse_question(state: AgentState) -> AgentState:
    """Pull a city out of the question by matching against cities we actually have.

    A real agent would let the LLM do this. Doing it deterministically here keeps the
    smoke test meaningful when no API key is configured — the graph still runs and
    the routing still gets exercised.
    """
    question = state["question"]
    if not CORRIDOR_TABLE.exists():
        return {"city": None, "trace": [f"corridor table missing at {CORRIDOR_TABLE}"]}

    df = pd.read_csv(CORRIDOR_TABLE)
    cities = (
        pd.concat([df["source_name"], df["destination_name"]])
        .dropna()
        .astype(str)
        .str.split("_")
        .str[0]
        .str.strip()
        .unique()
    )
    lowered = question.lower()
    hits = sorted(
        (c for c in cities if len(c) > 3 and c.lower() in lowered),
        key=len,
        reverse=True,
    )
    city = hits[0] if hits else None
    return {"city": city, "trace": [f"parse_question -> city={city!r}"]}


# ── Router ───────────────────────────────────────────────────────────────────
def route_after_parse(state: AgentState) -> Literal["lookup", "refuse"]:
    """The conditional edge. Week 6's orchestrator is this, many times over."""
    return "lookup" if state.get("city") else "refuse"


# ── Node 2: the tool ─────────────────────────────────────────────────────────
def lookup_corridors(state: AgentState) -> AgentState:
    """Read the real corridor table — the Week 1 stand-in for an MCP tool call."""
    city = state["city"]
    df = pd.read_csv(CORRIDOR_TABLE)
    mask = df["source_name"].astype(str).str.startswith(f"{city}_") | df[
        "destination_name"
    ].astype(str).str.startswith(f"{city}_")
    top = df[mask].nlargest(5, "legs_observed")

    corridors = [
        {
            "corridor": f"{str(r.source_name).split('_')[0]} -> {str(r.destination_name).split('_')[0]}",
            "legs_observed": int(r.legs_observed),
            "median_gap_ratio": round(float(r.median_gap_ratio), 2),
            "mean_gap_min": round(float(r.mean_gap_min), 1),
        }
        for r in top.itertuples()
    ]
    return {
        "corridors": corridors,
        "trace": [f"lookup_corridors -> {len(corridors)} corridors for {city!r}"],
    }


# ── Node 3: answer ───────────────────────────────────────────────────────────
ANSWER_PROMPT = """You are the analytics assistant for a logistics control tower.

Answer the question using ONLY the corridor data below. Quote the numbers exactly as
given — do not round or re-derive them. Two or three sentences. Times are minutes;
`median_gap_ratio` is realised time divided by the routing engine's planned time, so
2.0 means the corridor takes twice as long as planned.

Corridor data:
{data}

Question: {question}

Answer:"""


def answer_with_llm(state: AgentState) -> AgentState:
    """Ground the LLM on the tool output. Falls back to a deterministic summary."""
    data = json.dumps(state["corridors"], indent=2)
    prompt = ANSWER_PROMPT.format(data=data, question=state["question"])

    try:
        llm = get_llm(temperature=0.0)
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
        return {"answer": str(text).strip(), "grounded": True, "trace": ["answer_with_llm -> ok"]}
    except LLMNotConfigured as exc:
        log.warning("No LLM configured (%s) — using the deterministic fallback.", exc)
    except Exception as exc:  # noqa: BLE001 — provider errors vary; the graph must survive
        log.warning("LLM call failed (%s: %s) — using the deterministic fallback.", type(exc).__name__, exc)

    worst = max(state["corridors"], key=lambda c: c["median_gap_ratio"])
    summary = (
        f"{len(state['corridors'])} corridors found for {state['city']}. "
        f"The busiest is {state['corridors'][0]['corridor']} with "
        f"{state['corridors'][0]['legs_observed']} legs observed. "
        f"The furthest over plan is {worst['corridor']} at "
        f"{worst['median_gap_ratio']}x planned time "
        f"({worst['mean_gap_min']} min mean gap)."
    )
    return {
        "answer": summary,
        "grounded": True,
        "trace": ["answer_with_llm -> fallback (no LLM configured)"],
    }


# ── Node 4: refusal ──────────────────────────────────────────────────────────
def refuse(state: AgentState) -> AgentState:
    """Refusing when the data cannot support an answer is the behaviour being tested.

    The Analytics Assistant is scored on groundedness in Week 7; a confident answer
    with nothing behind it scores worse than this.
    """
    return {
        "answer": (
            "I don't have that in the project data. Ask about a city that appears in "
            "the Delhivery network — for example Gurgaon, Bengaluru, Bhiwandi, "
            "Hyderabad, or Kolkata."
        ),
        "grounded": False,
        "trace": ["refuse -> no city matched the corridor table"],
    }


# ── Graph ────────────────────────────────────────────────────────────────────
def build_graph() -> StateGraph:
    """Compile the graph. Same construction the Week 6 orchestrator uses."""
    graph = StateGraph(AgentState)
    graph.add_node("parse", parse_question)
    graph.add_node("lookup", lookup_corridors)
    graph.add_node("answer", answer_with_llm)
    graph.add_node("refuse", refuse)

    graph.set_entry_point("parse")
    graph.add_conditional_edges("parse", route_after_parse, {"lookup": "lookup", "refuse": "refuse"})
    graph.add_edge("lookup", "answer")
    graph.add_edge("answer", END)
    graph.add_edge("refuse", END)

    return graph.compile(checkpointer=MemorySaver())


DEFAULT_QUESTIONS = [
    "How bad are the corridors around Gurgaon?",
    "What does the Bhiwandi network look like?",
    "What is the weather in Paris?",  # must refuse
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="*", help="question(s) to ask")
    parser.add_argument("--dry-run", action="store_true", help="compile the graph, make no API call")
    args = parser.parse_args()

    if not CORRIDOR_TABLE.exists():
        log.error(
            "Missing %s — run `python -m src.ml.eda` first (it builds the corridor table).",
            CORRIDOR_TABLE,
        )
        return 1

    log.info("LLM config: %s", describe())
    app = build_graph()
    log.info("Graph compiled: nodes=%s", sorted(app.get_graph().nodes))

    if args.dry_run:
        log.info("Dry run — graph wiring is valid, no API call made.")
        return 0

    questions = args.question or DEFAULT_QUESTIONS
    for i, question in enumerate(questions, start=1):
        result = app.invoke(
            {"question": question, "trace": []},
            config={"configurable": {"thread_id": f"hello-{i}"}},
        )
        print(f"\n  Q: {question}")
        print(f"  A: {result['answer']}")
        print(f"     grounded={result.get('grounded')}  trace={result.get('trace')}")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
