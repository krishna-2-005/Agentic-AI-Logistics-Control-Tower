"""Alert bot (execution plan W5 D5) -- real stream alerts out to a human.

    python -m src.agents.alert_bot                      # send what is new
    python -m src.agents.alert_bot --channel telegram   # when a token exists
    python -m src.agents.alert_bot --dry-run --top 5    # show, send nothing
    python -m src.agents.alert_bot --reset              # forget what has been sent

Reads the streaming job's alert sink (`src.dashboard.alerts`, the same reader the Live
alerts panel uses -- one way to read the sink, not two), decides which alerts are worth
a person's attention, formats each as a message naming the shipment, its corridor and
the predicted delay, and sends it.

The part that is a decision, not plumbing
-----------------------------------------
The full replay produced **17,317 alerts from 26,369 legs**. A bot that forwards those
is not an alerting system; it is a firehose with a phone number, and the reliable
outcome of paging someone for two of every three shipments is that they stop reading.
So this bot sends a *shortlist*, and every part of that shortlist is a stated policy
rather than an emergent one (D-039):

* **New only.** `alert_id` is the idempotency key the alert schema defines for exactly
  this. Seen ids persist in a small JSON state file, so re-running the bot after a
  restart, or against a re-emitted micro-batch, does not send the same shipment twice.
* **Worst first, by excess over the leg's own threshold.** Not raw predicted minutes: a
  400-minute haul running 30 minutes over plan is ordinary, and a 40-minute run doing
  the same is not. `excess_min` is how far past *its own* D-003 threshold a leg sits.
* **A hard cap per run.** `--top`, default 10. A cap that truncates is visible in the
  message ("10 of 4,312"); a bot that quietly sends everything is not.

Channels, and which one actually ran
------------------------------------
* ``file``     -- appends to `data/stream/alert_messages.log`. **This is the channel
  that runs on this machine**, and it runs by default.
* ``telegram`` -- a real `sendMessage` call against the Bot API. Needs
  `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`; there is no bot account for this project,
  so this path is written and import-checked and **has never been run against the live
  API**. Same honesty D-035 applies to the Kafka sink: the choice is one flag, and the
  documentation says which flag was actually pulled.
* ``email``    -- SMTP via `SMTP_HOST`/`SMTP_USER`/`SMTP_PASSWORD` to `ALERT_EMAIL_TO`.
  Unconfigured here for the same reason, and unrun for the same reason.

A channel that is selected but unconfigured refuses at start-up with the variable it
needs, rather than failing per-message halfway through a send loop.
"""

from __future__ import annotations

import argparse
import json
import smtplib
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger
from src.dashboard.alerts import excess_min, load_alerts

log = get_logger("agents.alert_bot")

#: Which alert ids have already gone out. Small, local, and gitignored with the rest of
#: `data/` -- the point is that a restart does not re-page anybody, not durability.
STATE_PATH = config.STREAM_DIR / "alert_bot_state.json"
MESSAGE_LOG = config.STREAM_DIR / "alert_messages.log"

DEFAULT_TOP = 10


@dataclass
class SendResult:
    """What one run did, per channel and in total."""

    channel: str
    candidates: int = 0
    new: int = 0
    sent: int = 0
    suppressed_seen: int = 0
    suppressed_cap: int = 0
    failed: int = 0
    messages: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "channel": self.channel,
            "candidates": self.candidates,
            "new": self.new,
            "sent": self.sent,
            "suppressed_seen": self.suppressed_seen,
            "suppressed_cap": self.suppressed_cap,
            "failed": self.failed,
        }


def load_seen(path: Path = STATE_PATH) -> set[str]:
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")).get("seen", []))
    except (OSError, json.JSONDecodeError):
        # A corrupt state file must not stop the bot; the cost of losing it is at worst
        # a repeated message, which is strictly better than an alerting system that
        # refuses to start.
        log.warning("could not read %s -- treating every alert as new", path)
        return set()


def save_seen(seen: set[str], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix(".json.tmp")
    staging.write_text(
        json.dumps({"seen": sorted(seen), "updated_at": datetime.now().astimezone().isoformat()}, indent=2),
        encoding="utf-8",
    )
    staging.replace(path)


def shortlist(alerts: pd.DataFrame, seen: set[str], top: int = DEFAULT_TOP) -> tuple[pd.DataFrame, int, int]:
    """The alerts worth sending: unseen, worst first, capped.

    Returns the shortlist plus how many were dropped for having been seen and how many
    for the cap -- both reported, because a bot that silently discards is a bot nobody
    can tell is working.
    """
    if alerts.empty:
        return alerts, 0, 0
    unseen = alerts[~alerts["alert_id"].isin(seen)]
    suppressed_seen = len(alerts) - len(unseen)
    if unseen.empty:
        return unseen, suppressed_seen, 0
    ranked = unseen.assign(excess_min=excess_min(unseen)).sort_values("excess_min", ascending=False)
    return ranked.head(top).reset_index(drop=True), suppressed_seen, max(0, len(ranked) - top)


def format_message(row: pd.Series, position: int = 1, total: int = 1) -> str:
    """One alert, in the words a dispatcher needs: what, where, how late, how sure.

    The plan asks for "shipment, corridor, predicted delay". The two extras are the ones
    that stop a reader drawing a wrong conclusion: the leg's *planned* time, without
    which "+511 min" has no scale, and the cold-history warning, because a prediction
    made off no history at all is a different claim from a confident one (D-023).
    """
    excess = row["predicted_gap_min"] - row["threshold_gap_min"]
    cold = [
        name for name, column in
        (("corridor", "corr_is_cold"), ("origin hub", "src_is_cold"), ("destination hub", "dst_is_cold"))
        if column in row.index and row[column]
    ]
    lines = [
        f"[{position}/{total}] DELAY PREDICTED - {row['corridor_id']}",
        f"  shipment {row['trip_uuid']} ({row['route_type']}), leg {row['leg_id']}",
        (
            f"  planned {row['planned_min']:.0f} min; predicted {row['predicted_total_min']:.0f} min "
            f"({row['predicted_gap_min']:+.0f} min, {excess:+.0f} past the "
            f"{row['threshold_gap_min']:.0f} min threshold)"
        ),
        f"  created {row['event_time']:%Y-%m-%d %H:%M} (replayed), flagged {row['alert_time']:%H:%M:%S}",
    ]
    if cold:
        lines.append(f"  no history yet for the {', '.join(cold)} - prediction made off a cold start")
    return "\n".join(lines)


# ── channels ─────────────────────────────────────────────────────────────────
class FileChannel:
    """Appends to a log file. The channel that actually runs on this machine."""

    name = "file"

    def __init__(self, path: Path = MESSAGE_LOG) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def check(self) -> None:
        return None

    def send(self, message: str) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n\n")


class TelegramChannel:
    """`sendMessage` against the Bot API. Never run against the live API here (D-035's
    honesty rule, applied to the second unexercised path in this project)."""

    name = "telegram"

    def __init__(self, token: str = "", chat_id: str = "") -> None:
        self.token = token or config.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or config.TELEGRAM_CHAT_ID

    def check(self) -> None:
        missing = [
            name for name, value in
            (("TELEGRAM_BOT_TOKEN", self.token), ("TELEGRAM_CHAT_ID", self.chat_id))
            if not value
        ]
        if missing:
            raise RuntimeError(f"telegram channel needs {', '.join(missing)} in .env")

    def send(self, message: str) -> None:
        import httpx

        response = httpx.post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            json={"chat_id": self.chat_id, "text": message},
            timeout=15.0,
        )
        response.raise_for_status()


class EmailChannel:
    """One SMTP message per alert. Unconfigured and unrun here."""

    name = "email"

    def __init__(self) -> None:
        self.host = config.SMTP_HOST
        self.port = config.SMTP_PORT
        self.user = config.SMTP_USER
        self.password = config.SMTP_PASSWORD
        self.to = config.ALERT_EMAIL_TO

    def check(self) -> None:
        missing = [
            name for name, value in
            (("SMTP_HOST", self.host), ("SMTP_USER", self.user),
             ("SMTP_PASSWORD", self.password), ("ALERT_EMAIL_TO", self.to))
            if not value
        ]
        if missing:
            raise RuntimeError(f"email channel needs {', '.join(missing)} in .env")

    def send(self, message: str) -> None:
        email = EmailMessage()
        email["Subject"] = message.splitlines()[0]
        email["From"] = self.user
        email["To"] = self.to
        email.set_content(message)
        with smtplib.SMTP(self.host, self.port, timeout=20) as server:
            server.starttls()
            server.login(self.user, self.password)
            server.send_message(email)


CHANNELS = {"file": FileChannel, "telegram": TelegramChannel, "email": EmailChannel}


def make_channel(name: str):
    if name not in CHANNELS:
        raise ValueError(f"unknown channel {name!r}; one of {sorted(CHANNELS)}")
    channel = CHANNELS[name]()
    channel.check()
    return channel


def run(
    channel_name: str = "file",
    top: int = DEFAULT_TOP,
    dry_run: bool = False,
    alerts_dir: Path | None = None,
    state_path: Path = STATE_PATH,
) -> SendResult:
    """Read the sink, shortlist, send, and remember what went out."""
    feed = load_alerts(alerts_dir)
    result = SendResult(channel=channel_name if not dry_run else f"{channel_name} (dry run)")
    result.candidates = len(feed.alerts)
    if feed.empty:
        log.info("no alerts in the sink -- run the producer and the streaming job first")
        return result

    seen = load_seen(state_path)
    picked, suppressed_seen, suppressed_cap = shortlist(feed.alerts, seen, top)
    result.new = len(feed.alerts) - suppressed_seen
    result.suppressed_seen = suppressed_seen
    result.suppressed_cap = suppressed_cap

    if picked.empty:
        log.info("%d alert(s), none new since the last run", result.candidates)
        return result

    channel = None if dry_run else make_channel(channel_name)
    total = len(picked)
    for position, (_, row) in enumerate(picked.iterrows(), start=1):
        message = format_message(row, position, total)
        result.messages.append(message)
        if dry_run:
            continue
        try:
            channel.send(message)
        except Exception as exc:  # noqa: BLE001 -- one failed send must not lose the rest
            result.failed += 1
            log.warning("send failed for %s: %s", row["alert_id"], exc)
            continue
        result.sent += 1
        seen.add(row["alert_id"])

    if not dry_run:
        save_seen(seen, state_path)
    log.info(
        "%d alert(s) in the sink, %d new, %d sent via %s (%d held back by the cap, %d already sent)",
        result.candidates, result.new, result.sent, result.channel,
        result.suppressed_cap, result.suppressed_seen,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Send stream delay alerts to a human")
    parser.add_argument("--channel", choices=sorted(CHANNELS), default="file")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP,
                        help="most severe N to send this run; the rest wait for the next")
    parser.add_argument("--dry-run", action="store_true", help="print the messages, send nothing, remember nothing")
    parser.add_argument("--alerts", type=Path, default=None, help="alert sink directory")
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--reset", action="store_true", help="forget which alerts have been sent")
    args = parser.parse_args()

    if args.reset and args.state.exists():
        args.state.unlink()
        log.info("removed %s", args.state)

    try:
        result = run(
            channel_name=args.channel, top=args.top, dry_run=args.dry_run,
            alerts_dir=args.alerts, state_path=args.state,
        )
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1

    for message in result.messages:
        print(message + "\n")
    if result.candidates and not result.messages:
        log.info("nothing to send")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
