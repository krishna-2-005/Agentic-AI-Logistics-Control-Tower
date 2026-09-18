"""Analytics Assistant (execution plan v3.1 W7 D3-D4) -- grounded answers over the project's data.

    python -m src.agents.analytics_assistant "which corridors are the worst bottlenecks?"
    python -m src.agents.analytics_assistant "why was the delay threshold set to 2x?" --no-llm

Retrieval-augmented, with two deterministic stages around the one model call:

    question -> route -> (table lookup | vector retrieval) -> scope gate -> answer

Why a table route exists at all
-------------------------------
D-045 recorded what semantic search cannot do: asked "which hub has the longest dwell
time", it returned rank 11 above rank 1, because nothing in an embedding knows 350 > 257.
Superlative questions -- worst, slowest, top N, most congested -- are therefore answered
from the ranked tables themselves, and the model only phrases a ranking it was handed. A
retrieval system that answers "which is worst" by nearest-neighbour is confidently wrong
in exactly the questions people ask a control tower most.

Refusal is two layers, and only the first is deterministic
----------------------------------------------------------
**Layer 1, before any call: the retrieval distance.** If the nearest document is far from
the question, nothing in the project answers it, and the assistant refuses at zero quota.
On the fixed 30-question set this layer refused 3 of 6 out-of-scope questions with 100%
precision -- it never refused a real question.

**It cannot catch domain-adjacent questions, and no threshold would.** "How many trucks
does Delhivery own?" lands at distance 0.502 and "What is the GST rate on road freight?"
at 0.539 -- *closer* than three genuine in-scope questions (0.510, 0.531, 0.598). The two
distributions overlap; logistics vocabulary pulls a freight question near freight
documents whether or not they answer it. The first calibration missed this because its
out-of-scope probes were easy ones (capital of France, sourdough), which is exactly why the
fixed set exists (P-56).

**Layer 2, the model: grounded refusal.** The prompt's rule 1 refuses when the context
does not contain the answer, and a retrieved block of hub-dwell rows does not contain a
fleet size. That layer is measured by the model-phrased run of the question set, not
assumed. A second deterministic gate tuned on these same 30 questions was considered and
rejected: calibrating a gate on the set that scores it is tuning to the test set.

Every call is traced (`src.agents.tracing`), including refusals.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field

import pandas as pd

from src.agents.tracing import traced
from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("agents.analytics_assistant")

RAW = config.BENCHMARKS_RAW_DIR
REFUSAL = "I don't have that in the project data."
#: Cosine distance above which the nearest document is judged not to answer the question.
#: Calibrated, not chosen by feel (`benchmarks/raw/w7_assistant_refusal_calibration.json`):
#: ten in-scope probes landed at 0.349-0.588 and ten out-of-scope probes at 0.681-0.941,
#: so 0.63 splits the gap with ~0.05 of margin each side. The first draft used 0.55, which
#: would have refused "how was the champion model chosen" (0.588) -- a real question the
#: project can answer. Twenty probes calibrate; the fixed 30-question set measures, and it
#: showed this gate alone refuses only half the out-of-scope questions (see the module
#: docstring and P-56) -- it is kept for its precision, not relied on for its recall.
REFUSAL_DISTANCE = 0.63
TOP_N_DEFAULT = 5

_TOP_N = re.compile(r"\btop\s+(\d{1,2})\b|\b(\d{1,2})\s+(?:worst|slowest|best|fastest|most)\b", re.IGNORECASE)
_CORRIDOR = re.compile(r"\bcorridors?\b|\broutes?\b|\blanes?\b", re.IGNORECASE)
_HUB = re.compile(r"\bhubs?\b|\bcent(?:re|er)s?\b|\bfacilit(?:y|ies)\b", re.IGNORECASE)
_WORST = re.compile(r"\b(worst|slowest|most delayed|biggest bottleneck|bottlenecks?|most late|least reliable)\b", re.IGNORECASE)
_BEST = re.compile(r"\b(fastest|best|quickest|most reliable|ahead of plan)\b", re.IGNORECASE)
_DWELL = re.compile(r"\b(dwell|congest\w*|friction|longest wait|wait(?:ing)? time|parked)\b", re.IGNORECASE)
#: A ranking word. A hub question goes to the ranked table only when it asks for a ranking:
#: "tell me about dwell at the Hubli hub" mentions dwell and a hub and wants that one hub,
#: not the top five -- routing it to the table answers a different question.
_RANK = re.compile(r"\b(worst|slowest|longest|highest|most|biggest|top|ranked|least reliable)\b", re.IGNORECASE)


@dataclass
class AssistantAnswer:
    question: str
    route: str                      # "table" | "retrieval" | "refused"
    answer: str
    sources: list[str] = field(default_factory=list)
    nearest_distance: float | None = None
    draft_source: str = "none"      # "llm" | "extractive" | "none"
    context: str = ""


# ── routing ──────────────────────────────────────────────────────────────────
def _top_n(question: str) -> int:
    match = _TOP_N.search(question)
    if not match:
        return TOP_N_DEFAULT
    return max(1, min(20, int(match.group(1) or match.group(2))))


def table_route(question: str) -> tuple[str, list[str]] | None:
    """A ranked answer for a superlative question, from the table that ranks it."""
    n = _top_n(question)
    if _HUB.search(question) and _DWELL.search(question) and _RANK.search(question):
        frame = pd.read_csv(RAW / "w2_hub_friction_top20.csv").sort_values("friction_rank").head(n)
        lines = [
            f"rank {int(r.friction_rank)}: hub {r.centre_code} ({r.city}, {r.state}) -- median outbound dwell "
            f"{r.median_dwell_min_out:.0f} min, p90 {r.p90_dwell_min_out:.0f} min, over {int(r.n_legs_out)} legs"
            for r in frame.itertuples()
        ]
        return "\n".join(lines), ["w2_hub_friction_top20.csv"]
    if _CORRIDOR.search(question) and _WORST.search(question):
        frame = pd.read_csv(RAW / "w2_top20_bottlenecks.csv").sort_values("bottleneck_rank").head(n)
        lines = [
            f"rank {int(r.bottleneck_rank)}: corridor {r.corridor_id} ({r.source_city} to {r.dest_city}) -- "
            f"{r.excess_ratio:.2f}x the network's typical overrun over {int(r.n_legs)} legs, "
            f"median gap ratio {r.median_gap_ratio:.2f}"
            for r in frame.itertuples()
        ]
        return "\n".join(lines), ["w2_top20_bottlenecks.csv"]
    if _CORRIDOR.search(question) and _BEST.search(question):
        audit = pd.read_csv(RAW / "w2_corridor_audit.csv")
        frame = audit[audit["is_significant"] & (audit["direction"] == "better")].sort_values("excess_ratio").head(n)
        lines = [
            f"corridor {r.corridor_id} ({r.source_city} to {r.dest_city}) -- {r.excess_ratio:.2f}x the network's "
            f"typical overrun over {int(r.n_legs)} legs (statistically confirmed faster)"
            for r in frame.itertuples()
        ]
        return "\n".join(lines), ["w2_corridor_audit.csv"]
    return None


def _source_label(metadata: dict) -> str:
    kind = metadata.get("kind")
    if kind == "corridor":
        return f"corridor_audit ({metadata.get('corridor_id')})"
    if kind == "hub":
        return f"hub_friction ({metadata.get('centre_code')})"
    heading = metadata.get("heading") or ""
    return f"{metadata.get('source')} -- {heading}".strip(" -")


# ── answering ────────────────────────────────────────────────────────────────
def extractive_answer(context_blocks: list[tuple[str, str]]) -> str:
    """No-model answer: the most relevant passage, cited. Used with --no-llm and on any
    model failure -- a worse sentence, never an ungrounded one."""
    label, text = context_blocks[0]
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return f"{' '.join(sentences[:3])} ({label})"


def answer(question: str, use_llm: bool = True, k: int = 5) -> AssistantAnswer:
    with traced("analytics_assistant", inputs={"question": question, "use_llm": use_llm}) as span:
        result = _answer(question, use_llm, k)
        span.outputs = {"route": result.route, "sources": result.sources, "answer": result.answer,
                        "nearest_distance": result.nearest_distance, "draft_source": result.draft_source}
        return result


def _answer(question: str, use_llm: bool, k: int) -> AssistantAnswer:
    routed = table_route(question)
    if routed is not None:
        context, sources = routed
        blocks = [(sources[0], context)]
        route, nearest = "table", None
    else:
        from src.common.vectordb import search

        hits = search(question, k=k)
        nearest = hits[0]["distance"] if hits else None
        if nearest is None or nearest > REFUSAL_DISTANCE:
            log.info("refused (nearest distance %s)", nearest)
            return AssistantAnswer(question, "refused", REFUSAL, [], nearest, "none")
        blocks = [(_source_label(h["metadata"]), h["text"]) for h in hits]
        sources = [label for label, _ in blocks]
        context = "\n\n".join(f"[{i}] ({label})\n{text}" for i, (label, text) in enumerate(blocks, 1))
        route = "retrieval"

    if not use_llm:
        text = context if route == "table" else extractive_answer(blocks)
        return AssistantAnswer(question, route, text, sources, nearest, "extractive", context)

    from src.agents.llm import get_llm
    from src.agents.prompts.registry import load_prompt

    rendered = load_prompt("analytics_assistant").render(context=context, question=question)
    try:
        response = get_llm().invoke(rendered)
        content = getattr(response, "content", response)
        text = (content if isinstance(content, str) else "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content)).strip()
        if not text:
            raise ValueError("empty answer")
        draft = "llm"
    except Exception as exc:  # noqa: BLE001 -- a failed call falls back to a grounded extract
        log.warning("model call failed (%s) -- extractive fallback", str(exc)[:120])
        text = context if route == "table" else extractive_answer(blocks)
        draft = "extractive"
    return AssistantAnswer(question, route, text, sources, nearest, draft, context)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask the control tower's own data a question")
    parser.add_argument("question")
    parser.add_argument("--no-llm", action="store_true", help="extractive answer, no model call")
    parser.add_argument("-k", type=int, default=5)
    args = parser.parse_args()
    result = answer(args.question, use_llm=not args.no_llm, k=args.k)
    print(f"[{result.route}] {result.answer}")
    if result.sources:
        print("sources:", "; ".join(result.sources))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

