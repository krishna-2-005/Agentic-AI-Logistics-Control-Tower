"""Synthetic order emails for the Order Entry Agent (execution plan W5 D1-D2).

    python -m src.agents.order_corpus --count 12

Turns Week 3's `ConsignmentRecord` generator into **order emails a customer might
actually send**, each paired with the ground truth of what a correct agent should do
with it. No second corridor sampler: `doc_corpus.records.generate_records` already
draws from the real audited corridors and real centre codes, so an order email in
this corpus books a route the network genuinely ran (D-021's reasoning, reused).

Why the corpus has to contain bad emails
----------------------------------------
The plan's D1-D2 line asks for "a clarification-question path for ambiguous orders",
and the `order_entry` prompt slot has said since Week 3 that *"an ambiguous order must
produce a question, not a confident guess."* A corpus of clean emails cannot test
that at all -- every agent looks perfect on input that has nothing missing. So each
email carries a `variant`:

* ``clean``            -- everything stated plainly; the agent should file it.
* ``missing_weight``   -- no weight anywhere; unanswerable without asking.
* ``missing_pieces``   -- piece count absent.
* ``vague_origin``     -- a city, not a centre code, where that city has several
  centres; a guess is a coin-flip the customer never authorised.
* ``ambiguous_route``  -- no FTL/Carting signal either way.

`expected_action` is `file` or `clarify`, and for the `clarify` variants
`expected_missing` names the field a good question has to be about. That is what makes
Lahari's D5 evaluation possible: it can score not just *whether* the agent asked, but
whether it asked about the right thing.

**This is development material, not the eval set.** Lahari authors the formal 50-case
set at D5 (execution plan), and keeping the two separate is the same builder/judge
split D-028 already applies to document extraction -- an agent tuned against the very
cases it is later scored on is not being measured.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass

from src.agents.doc_corpus.records import ConsignmentRecord, generate_records
from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("agents.order_corpus")

ORDER_CORPUS_JSON = config.BENCHMARKS_RAW_DIR / "w5_order_email_corpus.json"

#: Which variants exist, and how often each is drawn. Weighted toward `clean` because
#: a corpus that is mostly broken would train the reader (and a future prompt) to
#: expect trouble; the real ratio of good to ambiguous email is nothing like 1:1.
VARIANT_WEIGHTS = {
    "clean": 5,
    "missing_weight": 2,
    "missing_pieces": 2,
    "vague_origin": 2,
    "ambiguous_route": 2,
}

CLARIFY_FIELD = {
    "missing_weight": "weight_kg",
    "missing_pieces": "pieces",
    "vague_origin": "origin_centre",
    "ambiguous_route": "route_type",
}


@dataclass
class OrderEmail:
    """One email plus the ground truth of what should happen to it."""

    seq: int
    variant: str
    subject: str
    body: str
    expected_action: str  # "file" | "clarify"
    expected_missing: str | None
    #: What a correct extraction should produce for the fields the email does state.
    #: Fields the variant deliberately removes are absent here too, so a scorer never
    #: penalises an agent for not inventing what was never written.
    expected_fields: dict

    @property
    def external_ref(self) -> str:
        """Idempotency key, so re-running the corpus cannot double-file an order
        (D-017's own reasoning for `external_ref` on the TMS side)."""
        return f"W5-ORD-{self.seq:04d}"


def _signature(record: ConsignmentRecord) -> str:
    return f"Regards,\n{record.shipper_name}\nConsignor"


def _clean_body(record: ConsignmentRecord) -> str:
    return (
        f"Hello,\n\n"
        f"Please book a shipment for us.\n\n"
        f"Pickup: {record.source_name} (centre {record.source_center})\n"
        f"Delivery: {record.dest_name} (centre {record.dest_center})\n"
        f"Consignee: {record.consignee_name}\n"
        f"Load: {record.pieces} pieces, {record.weight_kg} kg total\n"
        f"Service: {record.route_type}\n\n"
        f"{_signature(record)}"
    )


def _missing_weight_body(record: ConsignmentRecord) -> str:
    return (
        f"Hi team,\n\n"
        f"We need a pickup from {record.source_name} ({record.source_center}) going to "
        f"{record.dest_name} ({record.dest_center}).\n"
        f"Consignee is {record.consignee_name}. {record.pieces} pieces. "
        f"{record.route_type} please.\n\n"
        f"The pallets are still being made up so I do not have the final weight yet.\n\n"
        f"{_signature(record)}"
    )


def _missing_pieces_body(record: ConsignmentRecord) -> str:
    return (
        f"Hello,\n\n"
        f"Booking request: {record.source_name} ({record.source_center}) to "
        f"{record.dest_name} ({record.dest_center}).\n"
        f"Consignee {record.consignee_name}, total weight {record.weight_kg} kg, "
        f"{record.route_type} service.\n\n"
        f"{_signature(record)}"
    )


def _vague_origin_body(record: ConsignmentRecord) -> str:
    city = record.source_city or "our usual"
    return (
        f"Hi,\n\n"
        f"Please arrange a collection from our {city} warehouse for delivery to "
        f"{record.dest_name} ({record.dest_center}).\n"
        f"Consignee: {record.consignee_name}\n"
        f"{record.pieces} pieces, {record.weight_kg} kg, {record.route_type}.\n\n"
        f"{_signature(record)}"
    )


def _ambiguous_route_body(record: ConsignmentRecord) -> str:
    return (
        f"Hello,\n\n"
        f"Need this moved from {record.source_name} ({record.source_center}) to "
        f"{record.dest_name} ({record.dest_center}).\n"
        f"Consignee {record.consignee_name}, {record.pieces} pieces, "
        f"{record.weight_kg} kg.\n"
        f"Send it whichever way works out best at your end.\n\n"
        f"{_signature(record)}"
    )


BODY_BUILDERS = {
    "clean": _clean_body,
    "missing_weight": _missing_weight_body,
    "missing_pieces": _missing_pieces_body,
    "vague_origin": _vague_origin_body,
    "ambiguous_route": _ambiguous_route_body,
}


def _expected_fields(record: ConsignmentRecord, variant: str) -> dict:
    fields = {
        "customer_name": record.shipper_name,
        "origin_centre": record.source_center,
        "dest_centre": record.dest_center,
        "route_type": record.route_type,
        "pieces": record.pieces,
        "weight_kg": record.weight_kg,
    }
    # Whatever the variant removed from the email is removed from the truth too: an
    # agent must not be scored wrong for declining to invent a value nobody wrote.
    dropped = {
        "missing_weight": "weight_kg",
        "missing_pieces": "pieces",
        "vague_origin": "origin_centre",
        "ambiguous_route": "route_type",
    }.get(variant)
    if dropped:
        fields.pop(dropped)
    return fields


def build_email(record: ConsignmentRecord, variant: str) -> OrderEmail:
    return OrderEmail(
        seq=record.seq,
        variant=variant,
        subject=f"Booking request {record.source_city or record.source_center} to "
                f"{record.dest_city or record.dest_center}",
        body=BODY_BUILDERS[variant](record),
        expected_action="file" if variant == "clean" else "clarify",
        expected_missing=CLARIFY_FIELD.get(variant),
        expected_fields=_expected_fields(record, variant),
    )


def generate_emails(count: int, seed: int = 42) -> list[OrderEmail]:
    """`count` order emails over a deterministic variant mix.

    Deterministic in `seed`, the same discipline `generate_records` and the Spark
    caches already hold to (D-016) -- a corpus that changed between runs would make
    two agent scores incomparable for a reason that has nothing to do with the agent.
    """
    records = generate_records(count, seed=seed)
    rng = random.Random(seed)

    # Every variant appears at least once before the weighted draw fills the rest.
    # A purely weighted sample of a dozen emails can miss a variant entirely -- the
    # first run of this generator produced no `missing_weight` and no `missing_pieces`
    # at all, which would have left two clarification paths completely unexercised
    # while the corpus still looked fine from its own summary line.
    variants = list(VARIANT_WEIGHTS)[:count]
    population = [v for v, w in VARIANT_WEIGHTS.items() for _ in range(w)]
    variants += [rng.choice(population) for _ in range(max(0, count - len(variants)))]
    rng.shuffle(variants)
    return [build_email(record, variant) for record, variant in zip(records, variants, strict=True)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=12, help="emails to generate")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=str, default=str(ORDER_CORPUS_JSON))
    parser.add_argument("--show", type=int, default=0, help="print the first N emails")
    args = parser.parse_args()

    config.ensure_dirs()
    emails = generate_emails(args.count, args.seed)

    from pathlib import Path

    out = Path(args.out)
    out.write_text(json.dumps([asdict(e) for e in emails], indent=2), encoding="utf-8")

    counts: dict[str, int] = {}
    for email in emails:
        counts[email.variant] = counts.get(email.variant, 0) + 1
    clarify = sum(1 for e in emails if e.expected_action == "clarify")
    log.info("%d emails -> %s", len(emails), out)
    log.info("variants: %s", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    log.info("%d should file, %d should clarify", len(emails) - clarify, clarify)

    for email in emails[: args.show]:
        print(f"\n--- #{email.seq} [{email.variant}] {email.subject} ---\n{email.body}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
