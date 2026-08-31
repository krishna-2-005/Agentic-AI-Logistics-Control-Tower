"""Seeded-error taxonomy for the document corpus.

The execution plan puts this design jointly with Lahari (W3 D3-D4: "seeded-error
design ... with Lahari"; W3 D5: "defines the ground-truth label schema and
seeded-error taxonomy ... with Sai Krishna"). Krishna built this module solo and
Lahari confirmed the taxonomy at the W3 D5 sync (docs/decisions.md D-020), with one
fix out of that review: `total_mismatch`'s delta is a percentage of the invoice's own
total rather than a fixed rupee amount, after the fixed range printed a negative total
on one of five generated instances (P-26).

Five error kinds, chosen to be the mistakes an evaluation harness actually needs to
distinguish from an agent's own extraction errors — each maps to a rule already
written into `doc_extraction/v1.md`:

* ``total_mismatch``       — printed total != freight + other (prompt rule 5)
* ``duplicate_document_number`` — an operational error, not a corruption
* ``corridor_mismatch``    — invoice disagrees with the BOL on where the shipment
  went, the cross-document check W2 §4 flagged as the auditor's real job
* ``ocr_confusable_corruption`` — corrupts a character using exactly the confusion
  classes `doc_extraction/v1.md` lists (0/O, 1/I/l, 5/S, 8/B, 2/Z)
* ``missing_field``        — a field the printed document simply does not carry
  (prompt rule 1: return null, never invent)

A record gets **at most one** error kind, chosen independently per record — the point
is to measure field-level accuracy against a known-corrupted set, not to stack
failures no real document would plausibly have.
"""

from __future__ import annotations

import random

from src.agents.doc_corpus.records import ConsignmentRecord

ERROR_TYPES = (
    "total_mismatch",
    "duplicate_document_number",
    "corridor_mismatch",
    "ocr_confusable_corruption",
    "missing_field",
)

# Exactly the confusion classes named in doc_extraction/v1.md's rule 6.
_CONFUSIONS = {
    "0": "O", "O": "0",
    "1": "I", "I": "1", "l": "1",
    "5": "S", "S": "5",
    "8": "B", "B": "8",
    "2": "Z", "Z": "2",
}

# Fields it is realistic for a printed document to simply omit (identifiers and the
# document's own type/date are never blank on a real form).
_OMITTABLE_BY_TYPE = {
    "BOL": ("weight_kg", "pieces", "freight_charge"),
    "INVOICE": ("weight_kg", "pieces", "freight_charge", "other_charges", "total_amount"),
}


def _corrupt_one_char(value: str, rng: random.Random) -> str | None:
    """Flip one confusable character. Returns ``None`` if nothing in `value` is
    confusable, so the caller can fall back rather than silently no-op."""
    positions = [i for i, ch in enumerate(value) if ch in _CONFUSIONS]
    if not positions:
        return None
    i = rng.choice(positions)
    return value[:i] + _CONFUSIONS[value[i]] + value[i + 1 :]


def apply_seeded_errors(
    records: list[ConsignmentRecord],
    bol_labels: dict[int, dict],
    invoice_labels: dict[int, dict],
    seed: int,
    error_rate: float = 0.15,
) -> dict[int, list[str]]:
    """Mutate `bol_labels` / `invoice_labels` in place; return `{seq: [error_types]}`.

    Independent RNG stream from `records.generate_records` (seed offset by a large
    prime) so changing the error rate never reshuffles which corridor each
    consignment drew — the two concerns stay decoupled and reproducible on their own.
    """
    rng = random.Random(seed * 104_729 + 7)
    by_seq = {r.seq: r for r in records}
    applied: dict[int, list[str]] = {r.seq: [] for r in records}
    seen_invoice_numbers: list[str] = []

    for rec in records:
        if rng.random() < error_rate:
            kind = rng.choice(ERROR_TYPES)
            ok = _apply_one(
                kind, rec, by_seq, bol_labels[rec.seq], invoice_labels[rec.seq],
                seen_invoice_numbers, rng,
            )
            if ok:
                applied[rec.seq].append(kind)
        seen_invoice_numbers.append(invoice_labels[rec.seq]["document_number"])

    return applied


def _apply_one(
    kind: str,
    rec: ConsignmentRecord,
    by_seq: dict[int, ConsignmentRecord],
    bol: dict,
    invoice: dict,
    seen_invoice_numbers: list[str],
    rng: random.Random,
) -> bool:
    """Returns False when the chosen kind could not be applied to this record (e.g.
    no prior invoice number yet to duplicate) — the caller treats that record as clean
    rather than forcing a different kind, which would bias the taxonomy's mix."""
    if kind == "total_mismatch":
        # A fixed absolute delta (the first version of this branch used +/-50..500)
        # is not scaled to the invoice it lands on: on this network's smallest Carting
        # shipments `total_amount` itself can be under 50, so a fixed delta can and did
        # push the printed total negative (P-26) - implausible on a real invoice, and a
        # tell that gives the corruption away instead of testing rule 5 honestly. A
        # percentage of the invoice's own total scales with it and cannot cross zero at
        # this magnitude.
        sign = rng.choice([-1, 1])
        pct = rng.uniform(0.05, 0.30)
        invoice["total_amount"] = round(invoice["total_amount"] * (1 + sign * pct), 2)
        return True

    if kind == "duplicate_document_number":
        if not seen_invoice_numbers:
            return False
        invoice["document_number"] = rng.choice(seen_invoice_numbers)
        return True

    if kind == "corridor_mismatch":
        others = [r for r in by_seq.values() if r.seq != rec.seq]
        if not others:
            return False
        other = rng.choice(others)
        invoice["destination_centre_code"] = other.dest_center
        invoice["destination_facility"] = other.dest_name
        return True

    if kind == "ocr_confusable_corruption":
        target_doc, field_name = rng.choice(
            [(bol, "document_number"), (bol, "origin_centre_code"),
             (bol, "destination_centre_code"), (invoice, "document_number")]
        )
        corrupted = _corrupt_one_char(str(target_doc[field_name]), rng)
        if corrupted is None:
            return False
        target_doc[field_name] = corrupted
        return True

    if kind == "missing_field":
        target_doc, doc_type = rng.choice([(bol, "BOL"), (invoice, "INVOICE")])
        candidates = [f for f in _OMITTABLE_BY_TYPE[doc_type] if target_doc[f] is not None]
        if not candidates:
            return False
        target_doc[rng.choice(candidates)] = None
        return True

    raise ValueError(f"unknown seeded-error kind: {kind}")
