"""Lifecycle orchestrator (execution plan W6 D3-D4) -- Gate 6's one command.

    python -m src.agents.orchestrator --case 1              # one email, all the way
    python -m src.agents.orchestrator --case 1 --no-llm     # no model call anywhere
    python -m src.agents.orchestrator --cases 3 --dry-run   # decide, post nothing

Composes the agents Weeks 5 and 6 built into the lifecycle Gate 6 asks for:

    order email -> Order Entry Agent -> TMS order + shipment
                -> monitoring (the streaming job's alerts)
                -> Tracking & Exception Agent -> notification + exception ticket

and runs it **without human intervention** between the steps. A LangGraph
`StateGraph` holds the composition, because the interesting part is not that the four
calls happen in order -- a function could do that -- but that the route changes with
what the agents decide: an ambiguous email stops at a question and never reaches the
TMS, and a shipment the stream has not flagged stops after booking.

Why a graph rather than four function calls
-------------------------------------------
Two of the three edges out of a node are conditional and decided by an agent, not by
the caller:

* `intake` ends in `clarify` (stop, ask the customer) or `book` (file it), depending on
  what the Order Entry Agent returned;
* `monitor` ends in `triage` or `done`, depending on whether the streaming job has
  actually flagged the corridor the shipment is on.

Written as straight-line code those branches become `if` statements tangled with the
work; as a graph they are edges, and the run records which path it took. The state
carries a `steps` trail for exactly that reason -- Lahari's D3-D4 evaluation reads it,
and so does anyone asking "why did this email never reach the TMS".

Quota
-----
`--no-llm` runs the whole lifecycle with no model call at all: the order is taken from
the eval case's ground truth instead of being extracted, and the notification uses the
template. That is a **demonstration mode, not an evaluation** -- it skips the one step
whose quality is in question -- and it exists so the wiring can be exercised on a day
when the 20-call free tier (D-032) is spent.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Literal, TypedDict

import pandas as pd
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.agents.exception_agent import (
    draft_notification,
    investigate,
    load_audit,
    load_friction,
    severity_for,
)
from src.agents.order_agent import process_email, validate_order
from src.agents.order_corpus import OrderEmail
from src.agents.prompts.registry import load_prompt
from src.agents.tms_client import TMSClient, TMSError
from src.common import config
from src.common.logging_setup import get_logger
from src.dashboard.alerts import excess_min, load_alerts
from src.ml.order_eval import load_eval_set
from src.tms.models import OrderSource

log = get_logger("agents.orchestrator")

RUNS_JSON = config.BENCHMARKS_RAW_DIR / "w6_orchestrator_runs.json"


class LifecycleState(TypedDict, total=False):
    """What travels between nodes. Every field a later node reads is set by an earlier
    one, so a partial run is still readable: the fields that are absent say where it
    stopped."""

    case_seq: int
    email_subject: str
    email_body: str
    expected_fields: dict
    use_llm: bool
    dry_run: bool

    action: str | None            # "file" | "clarify"
    order: dict | None
    question: str | None
    missing_field: str | None

    order_ref: str | None
    shipment_ref: str | None
    corridor_id: str | None

    alert: dict | None
    severity: str | None
    notification: str | None
    draft_source: str | None
    ticket_ref: str | None

    steps: list[str]
    error: str | None


def _client() -> TMSClient | None:
    client = TMSClient()
    return client if client.is_up() else None


# ── nodes ────────────────────────────────────────────────────────────────────
def intake(state: LifecycleState) -> LifecycleState:
    """Order Entry Agent: read the email, decide file or clarify."""
    steps = [*state.get("steps", []), "intake"]
    if not state.get("use_llm"):
        # Demonstration mode: the case's own ground truth stands in for extraction.
        order = dict(state["expected_fields"])
        problems = validate_order(order)
        action = "file" if not problems else "clarify"
        return {
            **state, "steps": steps, "action": action, "order": order,
            "missing_field": problems[0].split()[0] if problems else None,
            "question": "; ".join(problems) if problems else None,
        }

    email = OrderEmail(
        seq=state["case_seq"], variant="orchestrator", subject=state["email_subject"],
        body=state["email_body"], expected_action="file", expected_missing=None,
        expected_fields=state.get("expected_fields", {}),
    )
    outcome = process_email(email, load_prompt("order_entry"), dry_run=True)
    return {
        **state, "steps": steps, "action": outcome.action, "order": outcome.order,
        "question": outcome.question, "missing_field": outcome.missing_field,
        "error": outcome.error,
    }


def route_after_intake(state: LifecycleState) -> Literal["book", "clarify"]:
    """The first conditional edge, and the reason this is a graph.

    An ambiguous email must never reach the TMS. The Order Entry Agent's own decision
    routes here -- the orchestrator does not second-guess it.
    """
    return "book" if state.get("action") == "file" and state.get("order") else "clarify"


def clarify(state: LifecycleState) -> LifecycleState:
    """Terminal: the customer owes us an answer, so the lifecycle stops here."""
    log.info("case %s -> clarify (%s)", state.get("case_seq"), state.get("missing_field"))
    return {**state, "steps": [*state.get("steps", []), "clarify"]}


def book(state: LifecycleState) -> LifecycleState:
    """File the order and book a shipment against it."""
    steps = [*state.get("steps", []), "book"]
    order = state["order"]
    if state.get("dry_run"):
        return {**state, "steps": steps, "corridor_id": f"{order['origin_centre']}>{order['dest_centre']}"}

    client = _client()
    if client is None:
        return {**state, "steps": steps, "error": "TMS is not reachable"}

    payload = {
        "customer_name": order["customer_name"],
        "origin_centre": order["origin_centre"],
        "dest_centre": order["dest_centre"],
        "route_type": order["route_type"],
        "pieces": order["pieces"],
        "weight_kg": order["weight_kg"],
        # Deterministic in the case number, so a re-run replays rather than duplicating
        # (D-017's idempotency key doing its job for a second caller).
        "external_ref": f"W6-ORCH-{state['case_seq']:04d}",
        "source": OrderSource.AGENT.value,
        "notes": order.get("notes"),
    }
    try:
        filed = client.create_order(payload)
        order_ref, corridor_id = filed["order_ref"], filed["corridor_id"]
        shipment_ref = _book_shipment(client, order_ref)
    except (TMSError, OSError) as exc:
        return {**state, "steps": steps, "error": f"booking failed: {exc}"}

    log.info("case %s -> %s / %s on %s", state.get("case_seq"), order_ref, shipment_ref, corridor_id)
    return {**state, "steps": steps, "order_ref": order_ref,
            "shipment_ref": shipment_ref, "corridor_id": corridor_id}


def _book_shipment(client: TMSClient, order_ref: str) -> str | None:
    """Book, or find the booking a replayed order already has.

    The TMS answers 409 for a second shipment on one order, which on a re-run is the
    right answer to the wrong question: the orchestrator wants *the* shipment, not a
    new one.
    """
    try:
        return client.create_shipment(order_ref)["shipment_ref"]
    except TMSError as exc:
        if exc.status_code != 409:
            raise
        existing = [s for s in client.list_shipments(limit=200) if s.get("order_ref") == order_ref]
        return existing[0]["shipment_ref"] if existing else None


def monitor(state: LifecycleState) -> LifecycleState:
    """Monitoring: has the streaming job flagged this shipment's corridor?

    Reads the alert sink the Week 5 job writes -- the orchestrator does not re-score
    anything, it consumes what the stream already decided (D-037).
    """
    steps = [*state.get("steps", []), "monitor"]
    corridor_id = state.get("corridor_id")
    feed = load_alerts()
    if feed.empty or not corridor_id:
        return {**state, "steps": steps, "alert": None}
    on_corridor = feed.alerts[feed.alerts["corridor_id"] == corridor_id]
    if on_corridor.empty:
        log.info("case %s -> no alert on %s", state.get("case_seq"), corridor_id)
        return {**state, "steps": steps, "alert": None}
    worst = on_corridor.assign(excess=excess_min(on_corridor)).sort_values("excess", ascending=False).iloc[0]
    return {**state, "steps": steps, "alert": json.loads(worst.to_json())}


def route_after_monitor(state: LifecycleState) -> Literal["triage", "done"]:
    """The second conditional edge: no flag, no exception. A shipment nobody predicted
    to be late is not an exception, and inventing one would be the system talking to
    itself."""
    return "triage" if state.get("alert") else "done"


def triage(state: LifecycleState) -> LifecycleState:
    """Exception Agent: investigate, grade, draft, file."""
    steps = [*state.get("steps", []), "triage"]
    alert = pd.Series(state["alert"])
    alert["alert_time"] = pd.Timestamp(alert["alert_time"], unit="ms")

    found = investigate(alert, load_audit(), load_friction(), None if state.get("dry_run") else _client())
    if state.get("shipment_ref"):
        found.shipment_ref = state["shipment_ref"]
    ratio = float(alert["predicted_gap_min"]) / float(alert["threshold_gap_min"])
    severity = severity_for(ratio, found)
    prompt = load_prompt("exception_triage") if state.get("use_llm") else None
    text, source = draft_notification(alert, found, severity, prompt)

    ticket_ref = None
    if not state.get("dry_run"):
        client = _client()
        if client and found.shipment_ref:
            try:
                ticket = client.create_exception(
                    shipment_ref=found.shipment_ref, severity=severity,
                    reason=f"predicted {float(alert['predicted_total_min']):.0f} min against "
                           f"{float(alert['planned_min']):.0f} planned ({ratio:.1f}x the delay threshold)",
                    notes="\n".join(found.evidence_lines() + ["", text]),
                )
                ticket_ref = ticket["ticket_ref"]
            except (TMSError, OSError) as exc:
                return {**state, "steps": steps, "severity": severity, "notification": text,
                        "draft_source": source, "error": f"filing failed: {exc}"}

    log.info("case %s -> %s (%s)", state.get("case_seq"), ticket_ref or "not filed", severity)
    return {**state, "steps": steps, "severity": severity, "notification": text,
            "draft_source": source, "ticket_ref": ticket_ref}


def done(state: LifecycleState) -> LifecycleState:
    return {**state, "steps": [*state.get("steps", []), "done"]}


def build_graph():
    """The lifecycle, as edges. Compiled with a checkpointer so a run is resumable."""
    graph = StateGraph(LifecycleState)
    graph.add_node("intake", intake)
    graph.add_node("clarify", clarify)
    graph.add_node("book", book)
    graph.add_node("monitor", monitor)
    graph.add_node("triage", triage)
    graph.add_node("done", done)

    graph.set_entry_point("intake")
    graph.add_conditional_edges("intake", route_after_intake, {"book": "book", "clarify": "clarify"})
    graph.add_edge("clarify", END)
    graph.add_edge("book", "monitor")
    graph.add_conditional_edges("monitor", route_after_monitor, {"triage": "triage", "done": "done"})
    graph.add_edge("triage", "done")
    graph.add_edge("done", END)
    return graph.compile(checkpointer=MemorySaver())


def run_case(case: OrderEmail, use_llm: bool = True, dry_run: bool = False) -> dict:
    """One email through the whole lifecycle. Returns the final state."""
    app = build_graph()
    initial: LifecycleState = {
        "case_seq": case.seq,
        "email_subject": case.subject,
        "email_body": case.body,
        "expected_fields": case.expected_fields,
        "use_llm": use_llm,
        "dry_run": dry_run,
        "steps": [],
    }
    final = app.invoke(initial, config={"configurable": {"thread_id": f"case-{case.seq}"}})
    return {k: v for k, v in final.items() if k not in ("email_body", "expected_fields")}


def run(cases: int = 1, start: int = 0, use_llm: bool = True, dry_run: bool = False,
        out_path: Path = RUNS_JSON) -> dict:
    eval_set = load_eval_set()
    selected = eval_set[start:start + cases]
    results = [run_case(case, use_llm, dry_run) for case in selected]

    summary = {
        "cases": len(results),
        "used_llm": use_llm,
        "dry_run": dry_run,
        "reached_clarify": sum(1 for r in results if "clarify" in r["steps"]),
        "booked": sum(1 for r in results if r.get("shipment_ref")),
        "alerted": sum(1 for r in results if r.get("alert")),
        "ticketed": sum(1 for r in results if r.get("ticket_ref")),
        "errors": sum(1 for r in results if r.get("error")),
        "paths": [" -> ".join(r["steps"]) for r in results],
        "generated_at": datetime.now().astimezone().isoformat(),
        "runs": results,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    log.info(
        "%d case(s): %d booked, %d alerted, %d ticketed, %d stopped at a question -> %s",
        summary["cases"], summary["booked"], summary["alerted"], summary["ticketed"],
        summary["reached_clarify"], out_path,
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the order-to-exception lifecycle")
    parser.add_argument("--cases", type=int, default=1, help="how many eval cases to run")
    parser.add_argument("--start", type=int, default=0, help="index into the eval set")
    parser.add_argument("--no-llm", action="store_true", help="demonstration mode: no model call anywhere")
    parser.add_argument("--dry-run", action="store_true", help="decide everything, post nothing")
    # See P-51: boot writes its demonstration runs to logs/, not over the cited artefact.
    parser.add_argument("--out", type=Path, default=RUNS_JSON)
    args = parser.parse_args()

    summary = run(cases=args.cases, start=args.start, use_llm=not args.no_llm,
                  dry_run=args.dry_run, out_path=args.out)
    for result, path in zip(summary["runs"], summary["paths"], strict=True):
        print(f"\ncase {result['case_seq']}: {path}")
        for label, key in (("order", "order_ref"), ("shipment", "shipment_ref"),
                           ("ticket", "ticket_ref"), ("severity", "severity")):
            if result.get(key):
                print(f"  {label:9} {result[key]}")
        if result.get("question"):
            print(f"  question  {result['question']}")
        if result.get("notification"):
            print(f"  notice    {result['notification'][:160]}")
        if result.get("error"):
            print(f"  error     {result['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
