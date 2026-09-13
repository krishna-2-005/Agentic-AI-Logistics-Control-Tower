"""Tracking & Exception Agent (execution plan W6 D1-D2).

    python -m src.agents.exception_agent --limit 5            # investigate, draft, file
    python -m src.agents.exception_agent --limit 5 --dry-run  # nothing posted, nothing sent
    python -m src.agents.exception_agent --no-draft           # template wording, no LLM call

Takes the streaming job's flagged predictions and carries each one to a human outcome:

    alert -> investigate -> severity -> notification -> exception ticket

Investigation reads the corridor audit (Week 2) and the hub friction table, and looks the
shipment up in the TMS. Severity is arithmetic. The notification is the one step a
language model does, and the ticket is filed through `POST /exceptions`.

What is deterministic, and why that is the point
-----------------------------------------------
Only the **wording** is generated. Severity is a rule over measured quantities
(`SEVERITY_CUTS` below), the evidence is table lookups, and the ticket's `reason` is a
formatted string. This is deliberate, and not only to stay inside a 20-call-a-day free
tier (D-032):

* A severity a model assigns is not reproducible. Two runs over the same alert can
  disagree, and nothing in the output says which run you are reading. Lahari's D3-D4
  evaluation scores this agent against what actually happened on the replay; that
  scoring means nothing if the thing being scored is a coin flip.
* "How far past its own threshold is this leg" is arithmetic with a right answer.
  Asking a model to re-derive it replaces a right answer with a plausible one.
* The customer-facing sentence genuinely is a language problem, and a template writes a
  worse one. So that is where the call goes, and `--no-draft` falls back to the template
  so the whole lifecycle still runs with no quota at all.

Idempotency
-----------
One ticket per `alert_id`, remembered in a small state file. The alert schema defines
`alert_id` as the consumer-side idempotency key; a shipment already carrying a ticket
from this agent does not get a second one when the stream re-emits its micro-batch.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.agents.llm import get_llm
from src.agents.prompts.registry import Prompt, load_prompt
from src.agents.tms_client import TMSClient, TMSError
from src.common import config
from src.common.logging_setup import get_logger
from src.dashboard.alerts import excess_min, load_alerts

log = get_logger("agents.exception_agent")

STATE_PATH = config.STREAM_DIR / "exception_agent_state.json"
RUNS_JSON = config.BENCHMARKS_RAW_DIR / "w6_exception_runs.json"

AUDIT_CSV = config.BENCHMARKS_RAW_DIR / "w2_corridor_audit.csv"
FRICTION_CSV = config.BENCHMARKS_RAW_DIR / "w2_hub_friction_top20.csv"

#: Severity from how far past its own delay threshold a leg is predicted to run:
#: `excess_ratio = predicted_gap / threshold_gap`, which is 1.0 at the threshold itself.
#: These cut points are a **policy, not a measurement** -- nothing in the data says
#: 3x is "critical". They are written here, once, so that the policy can be argued with
#: and changed in one place, and so two runs over the same alert always agree.
SEVERITY_CUTS = ((3.0, "critical"), (2.0, "high"), (1.3, "medium"))
LOWEST_SEVERITY = "low"
SEVERITY_ORDER = ["low", "medium", "high", "critical"]

#: The corridor audit's own word for "slower than the rest of the network"
#: (`src/ml/audit.py` line 248: `where(excess_ratio >= 1, "worse", "better")`), and the
#: same pairing with `is_significant` that audit.py uses to call something a bottleneck.
#: Written here as a constant because the first version of this module guessed the word
#: was "slower": the comparison then never matched, the escalation silently never fired,
#: and a corridor confirmed *faster* than the network was described to customers as a
#: confirmed slow route (P-48). `load_audit` now validates the vocabulary on the way in.
SLOWER_THAN_NETWORK = "worse"
AUDIT_DIRECTIONS = {"worse", "better"}

#: Shipment statuses that mean "still in our hands". `delivered` is the only terminal
#: one; `exception` is emphatically not, and reading it that way is a mistake this
#: module made first time out. Filing a ticket flags the shipment `exception` (the TMS
#: does that deliberately), so a filter of {created, in_transit} made every shipment
#: invisible to the agent the moment it had one ticket -- the second alert on a
#: consignment already in trouble was the one it stopped being able to see.
IN_FLIGHT_STATUSES = {"created", "in_transit", "exception"}


@dataclass
class Investigation:
    """What the agent found out before deciding anything."""

    corridor_id: str
    audit_n_legs: int | None = None
    audit_excess_ratio: float | None = None
    audit_is_significant: bool = False
    audit_direction: str | None = None
    audit_bottleneck_rank: int | None = None
    source_friction_rank: int | None = None
    dest_friction_rank: int | None = None
    shipment_ref: str | None = None
    order_ref: str | None = None
    shipment_status: str | None = None
    cold_history: bool = False

    @property
    def confirmed_slow(self) -> bool:
        """The audit's own definition of a bottleneck: significant **and** slower.

        One predicate, three callers (severity, the evidence list, the template). The
        bug this replaces had the severity rule and the customer-facing sentence each
        deciding "is this a known slow corridor" their own way, and both wrong.
        """
        return self.audit_is_significant and self.audit_direction == SLOWER_THAN_NETWORK

    def evidence_lines(self) -> list[str]:
        """The investigation as a human reads it -- also what the prompt is given."""
        lines = []
        if self.audit_n_legs is None:
            lines.append("- this corridor is not in the Week 2 audit (too few legs to test)")
        else:
            if not self.audit_is_significant:
                verdict = "not statistically distinguishable from the network"
            elif self.audit_direction == SLOWER_THAN_NETWORK:
                verdict = "statistically confirmed SLOWER than the network"
            else:
                verdict = "statistically confirmed FASTER than the network"
            rank = f", bottleneck rank {self.audit_bottleneck_rank}" if self.audit_bottleneck_rank else ""
            lines.append(
                f"- corridor audit over {self.audit_n_legs} legs: {verdict}, "
                f"running {self.audit_excess_ratio:.2f}x the network's typical overrun{rank}"
            )
        for label, rank in (("origin", self.source_friction_rank), ("destination", self.dest_friction_rank)):
            if rank is not None:
                lines.append(f"- {label} hub is rank {rank} in the network's hub-friction table")
        if self.cold_history:
            lines.append("- no prior history for at least one of the corridor or hubs: a cold-start estimate")
        if self.shipment_ref:
            lines.append(f"- TMS shipment {self.shipment_ref} ({self.shipment_status}) for order {self.order_ref}")
        else:
            lines.append("- no shipment on this corridor in the TMS")
        return lines


@dataclass
class ExceptionOutcome:
    """What happened to one alert, whatever happened. Lahari's D3-D4 harness reads this."""

    alert_id: str
    corridor_id: str
    leg_id: str
    alert_time: str
    planned_min: float
    predicted_total_min: float
    excess_min: float
    excess_ratio: float
    severity: str
    investigation: dict = field(default_factory=dict)
    notification: str | None = None
    draft_source: str | None = None          # "llm" | "template"
    prompt_version: str | None = None
    filed: bool = False
    ticket_ref: str | None = None
    notified: bool = False
    skipped_reason: str | None = None
    error: str | None = None
    #: Wall-clock seconds from the alert being written to the notification going out --
    #: the plan's "time-to-notification", measured rather than asserted.
    seconds_alert_to_notification: float | None = None


# ── the investigation's tables ───────────────────────────────────────────────
def load_audit(path: Path = AUDIT_CSV) -> pd.DataFrame:
    if not path.exists():
        log.warning("no corridor audit at %s -- investigating without it", path)
        return pd.DataFrame()
    frame = pd.read_csv(path).set_index("corridor_id")
    # Validate the vocabulary rather than trust it. A renamed direction value would
    # otherwise make `confirmed_slow` quietly false for every corridor, disabling the
    # severity escalation and the "known slow route" sentence with no error anywhere
    # (P-48 is what that looks like when it happens).
    unknown = set(frame["direction"].dropna().unique()) - AUDIT_DIRECTIONS
    if unknown:
        raise ValueError(
            f"{path.name} uses direction values {sorted(unknown)}; this agent knows "
            f"{sorted(AUDIT_DIRECTIONS)}. src/ml/audit.py decides these -- update both together."
        )
    return frame


def load_friction(path: Path = FRICTION_CSV) -> dict[str, int]:
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    return dict(zip(frame["centre_code"], frame["friction_rank"], strict=True))


def investigate(alert: pd.Series, audit: pd.DataFrame, friction: dict[str, int],
                client: TMSClient | None) -> Investigation:
    """Look the corridor up in the audit, the hubs up in the friction table, and the
    shipment up in the TMS. No model, no guesswork -- three lookups."""
    corridor_id = alert["corridor_id"]
    found = Investigation(
        corridor_id=corridor_id,
        source_friction_rank=friction.get(alert["source_center"]),
        dest_friction_rank=friction.get(alert["destination_center"]),
        cold_history=bool(
            alert.get("corr_is_cold") or alert.get("src_is_cold") or alert.get("dst_is_cold")
        ),
    )
    if not audit.empty and corridor_id in audit.index:
        row = audit.loc[corridor_id]
        found.audit_n_legs = int(row["n_legs"])
        found.audit_excess_ratio = float(row["excess_ratio"])
        found.audit_is_significant = bool(row["is_significant"])
        found.audit_direction = str(row["direction"])
        rank = row.get("bottleneck_rank")
        found.audit_bottleneck_rank = None if pd.isna(rank) else int(rank)

    if client is not None:
        try:
            shipments = client.shipments_on_corridor(corridor_id)
        except (TMSError, OSError) as exc:
            log.warning("TMS lookup failed for %s: %s", corridor_id, exc)
            shipments = []
        # The oldest open shipment on the corridor: a ticket belongs against the
        # consignment that is still moving, not one already delivered.
        live = [s for s in shipments if s.get("status") in IN_FLIGHT_STATUSES]
        if live:
            found.shipment_ref = live[0]["shipment_ref"]
            found.shipment_status = live[0]["status"]
            found.order_ref = live[0].get("order_ref")
    return found


# ── severity, which is arithmetic ────────────────────────────────────────────
def severity_for(excess_ratio: float, investigation: Investigation) -> str:
    """Severity from the excess ratio, escalated one step on a confirmed bottleneck.

    The escalation is the one place the investigation feeds the decision: a leg running
    2.1x its threshold on a corridor the Week 2 audit *confirmed* is slower than the
    network is a different problem from the same overrun on an ordinary corridor -- the
    first is the route behaving as it always does, and it will not fix itself.
    """
    severity = LOWEST_SEVERITY
    for cut, name in SEVERITY_CUTS:
        if excess_ratio >= cut:
            severity = name
            break
    if investigation.confirmed_slow:
        index = min(SEVERITY_ORDER.index(severity) + 1, len(SEVERITY_ORDER) - 1)
        severity = SEVERITY_ORDER[index]
    return severity


# ── the one language step ────────────────────────────────────────────────────
def template_notification(alert: pd.Series, investigation: Investigation, severity: str) -> str:
    """The wording used when no model is called. Deliberately plain.

    Kept as a real fallback rather than a stub so `--no-draft` exercises the entire
    lifecycle -- investigate, decide, notify, file -- on a machine with no quota left.
    """
    late_min = alert["predicted_total_min"] - alert["planned_min"]
    known = " This corridor is a confirmed slow route in our own audit." if investigation.confirmed_slow else ""
    return (
        f"Shipment {investigation.shipment_ref or alert['leg_id']} on {alert['corridor_id']} is "
        f"predicted to run about {late_min / 60:.1f} hours over its planned "
        f"{alert['planned_min'] / 60:.1f} hours ({severity} severity).{known} "
        "The control tower is tracking it and will update you if the estimate changes."
    )


def draft_notification(alert: pd.Series, investigation: Investigation, severity: str,
                       prompt: Prompt | None) -> tuple[str, str]:
    """Returns (text, source). Falls back to the template on any model failure.

    A quota refusal or a provider error must not cost the exception ticket: the
    customer-facing sentence is the least important part of this pipeline to get
    perfect, and the most expensive to retry.
    """
    if prompt is None:
        return template_notification(alert, investigation, severity), "template"
    rendered = prompt.render(
        shipment_ref=investigation.shipment_ref or "(not yet in the TMS)",
        corridor_id=alert["corridor_id"],
        source_name=alert["source_center"],
        dest_name=alert["destination_center"],
        planned_min=f"{alert['planned_min']:.0f}",
        predicted_total_min=f"{alert['predicted_total_min']:.0f}",
        excess_min=f"{alert['predicted_gap_min'] - alert['threshold_gap_min']:.0f}",
        severity=severity,
        evidence="\n".join(investigation.evidence_lines()),
    )
    try:
        response = get_llm().invoke(rendered)
        content = getattr(response, "content", response)
        text = content if isinstance(content, str) else "".join(
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        )
        text = text.strip()
        if not text:
            raise ValueError("empty draft")
    except Exception as exc:  # noqa: BLE001 -- wording must never cost the ticket
        log.warning("draft failed (%s) -- falling back to the template", str(exc)[:120])
        return template_notification(alert, investigation, severity), "template"
    return text, "llm"


# ── state ────────────────────────────────────────────────────────────────────
def load_state(path: Path = STATE_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("tickets", {})
    except (OSError, json.JSONDecodeError):
        log.warning("could not read %s -- treating every alert as new", path)
        return {}


def save_state(tickets: dict[str, str], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix(".json.tmp")
    staging.write_text(
        json.dumps({"tickets": tickets, "updated_at": datetime.now().astimezone().isoformat()}, indent=2),
        encoding="utf-8",
    )
    staging.replace(path)


def process_alert(alert: pd.Series, audit: pd.DataFrame, friction: dict[str, int],
                  client: TMSClient | None, prompt: Prompt | None, channel,
                  dry_run: bool = False) -> ExceptionOutcome:
    """One alert, all the way through. Never raises for a single alert."""
    threshold_gap = float(alert["threshold_gap_min"])
    excess = float(alert["predicted_gap_min"]) - threshold_gap
    ratio = float(alert["predicted_gap_min"]) / threshold_gap if threshold_gap > 0 else float("inf")

    found = investigate(alert, audit, friction, client)
    severity = severity_for(ratio, found)
    outcome = ExceptionOutcome(
        alert_id=alert["alert_id"],
        corridor_id=alert["corridor_id"],
        leg_id=alert["leg_id"],
        alert_time=alert["alert_time"].isoformat(),
        planned_min=float(alert["planned_min"]),
        predicted_total_min=float(alert["predicted_total_min"]),
        excess_min=round(excess, 1),
        excess_ratio=round(ratio, 3),
        severity=severity,
        investigation=asdict(found),
        prompt_version=prompt.label if prompt else None,
    )

    text, source = draft_notification(alert, found, severity, prompt)
    outcome.notification, outcome.draft_source = text, source

    if dry_run:
        outcome.skipped_reason = "dry run"
        return outcome

    if channel is not None:
        try:
            channel.send(f"[{severity.upper()}] {text}")
            outcome.notified = True
            outcome.seconds_alert_to_notification = round(
                (datetime.now().astimezone() - alert["alert_time"]).total_seconds(), 1
            )
        except Exception as exc:  # noqa: BLE001 -- a failed send must not lose the ticket
            outcome.error = f"notify failed: {exc}"

    if found.shipment_ref is None:
        outcome.skipped_reason = "no shipment on this corridor in the TMS"
        return outcome
    if client is None:
        outcome.skipped_reason = "TMS not reachable"
        return outcome

    reason = (
        f"predicted {outcome.predicted_total_min:.0f} min against {outcome.planned_min:.0f} planned "
        f"({ratio:.1f}x the delay threshold)"
    )
    try:
        ticket = client.create_exception(
            shipment_ref=found.shipment_ref, severity=severity, reason=reason,
            notes="\n".join(found.evidence_lines() + ["", text]),
        )
        outcome.filed, outcome.ticket_ref = True, ticket["ticket_ref"]
        log.info("%s -> %s (%s) on %s", alert["alert_id"][:28], ticket["ticket_ref"], severity, found.shipment_ref)
    except (TMSError, OSError) as exc:
        outcome.error = f"filing failed: {exc}"
        log.warning("could not file for %s: %s", alert["alert_id"][:28], exc)
    return outcome


def live_shipment_corridors(client: TMSClient | None) -> set[str]:
    """Corridors the TMS is actually carrying something on, right now."""
    if client is None:
        return set()
    try:
        shipments = client.list_shipments(limit=500)
    except (TMSError, OSError) as exc:
        log.warning("could not list shipments: %s", exc)
        return set()
    return {s["corridor_id"] for s in shipments if s.get("status") in IN_FLIGHT_STATUSES}


def run(limit: int = 10, dry_run: bool = False, draft: bool = True,
        alerts_dir: Path | None = None, state_path: Path = STATE_PATH,
        channel_name: str = "file", any_corridor: bool = False,
        out_path: Path = RUNS_JSON) -> dict:
    """Process the worst `limit` unhandled alerts. Returns a summary dict."""
    feed = load_alerts(alerts_dir)
    if feed.empty:
        log.info("no alerts in the sink -- run the producer and the streaming job first")
        return {"alerts": 0, "processed": 0, "filed": 0}

    client = TMSClient()
    if not client.is_up():
        log.warning("TMS is not answering at %s -- investigating and drafting only", client.base_url)
        client = None
    prompt = load_prompt("exception_triage") if draft else None

    handled = load_state(state_path)
    pending = feed.alerts[~feed.alerts["alert_id"].isin(handled)]

    # By default, only alerts on a corridor the TMS is actually carrying a shipment on.
    # The stream scores every leg in a 26-day replay; the company is carrying a few
    # dozen of them. An alert about a corridor we have nothing on is real but not
    # actionable -- there is no shipment to ticket, nobody to notify, and working
    # through thousands of them worst-first would never reach the ones that matter.
    # `--any-corridor` restores the unfiltered view for measuring the stream itself.
    carrying = set() if any_corridor else live_shipment_corridors(client)
    not_ours = 0
    if carrying:
        before = len(pending)
        pending = pending[pending["corridor_id"].isin(carrying)]
        not_ours = before - len(pending)

    # Worst first, by excess over each leg's own threshold -- the same ordering the
    # alert bot uses (D-039), so the panel, the bot and this agent agree on "worst".
    pending = pending.assign(excess=excess_min(pending)).sort_values("excess", ascending=False).head(limit)
    log.info(
        "%d alert(s), %d already ticketed, %d on corridors we are not carrying, processing %d",
        len(feed.alerts), len(handled), not_ours, len(pending),
    )

    channel = None
    if not dry_run:
        from src.agents.alert_bot import make_channel

        channel = make_channel(channel_name)

    outcomes = []
    for _, alert in pending.iterrows():
        outcome = process_alert(alert, load_audit(), load_friction(), client, prompt, channel, dry_run)
        outcomes.append(outcome)
        if outcome.ticket_ref:
            handled[outcome.alert_id] = outcome.ticket_ref

    if not dry_run:
        save_state(handled, state_path)

    latencies = [o.seconds_alert_to_notification for o in outcomes if o.seconds_alert_to_notification is not None]
    summary = {
        "alerts": len(feed.alerts),
        "processed": len(outcomes),
        "filed": sum(1 for o in outcomes if o.filed),
        "notified": sum(1 for o in outcomes if o.notified),
        "drafted_by_llm": sum(1 for o in outcomes if o.draft_source == "llm"),
        "no_shipment": sum(1 for o in outcomes if o.skipped_reason == "no shipment on this corridor in the TMS"),
        "errors": sum(1 for o in outcomes if o.error),
        "by_severity": {s: sum(1 for o in outcomes if o.severity == s) for s in SEVERITY_ORDER},
        "median_seconds_alert_to_notification": (
            round(float(pd.Series(latencies).median()), 1) if latencies else None
        ),
        "dry_run": dry_run,
        "generated_at": datetime.now().astimezone().isoformat(),
        "outcomes": [asdict(o) for o in outcomes],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info(
        "%d processed, %d ticket(s) filed, %d notified (%d drafted by the model) -> %s",
        summary["processed"], summary["filed"], summary["notified"], summary["drafted_by_llm"], out_path,
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Investigate flagged predictions and file exceptions")
    parser.add_argument("--limit", type=int, default=10, help="worst N unhandled alerts")
    parser.add_argument("--dry-run", action="store_true", help="investigate and draft; post nothing, send nothing")
    parser.add_argument("--no-draft", action="store_true", help="template wording, no LLM call")
    parser.add_argument("--alerts", type=Path, default=None)
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--channel", type=str, default="file")
    # A demonstration run must not overwrite a recorded one: `boot` points this at
    # logs/ so the committed benchmarks artefact stays the run the write-up cites (P-51).
    parser.add_argument("--out", type=Path, default=RUNS_JSON)
    parser.add_argument("--reset", action="store_true", help="forget which alerts have been ticketed")
    args = parser.parse_args()

    if args.reset and args.state.exists():
        args.state.unlink()
        log.info("removed %s", args.state)

    summary = run(
        limit=args.limit, dry_run=args.dry_run, draft=not args.no_draft,
        alerts_dir=args.alerts, state_path=args.state, channel_name=args.channel,
        out_path=args.out,
    )
    if not summary.get("processed"):
        return 0
    for outcome in summary["outcomes"][:3]:
        print(f"\n[{outcome['severity'].upper()}] {outcome['corridor_id']} "
              f"({outcome['excess_ratio']:.1f}x threshold, {outcome['draft_source']})\n{outcome['notification']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
