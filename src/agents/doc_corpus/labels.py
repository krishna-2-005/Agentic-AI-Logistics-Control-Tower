"""The ground-truth label schema — reused, not reinvented.

D-008 already froze what a Document Intelligence Agent must return:
`src/agents/prompts/doc_extraction/v1.md`'s fifteen-field table. Defining a second,
slightly-different schema for the corpus would make Week 4's evaluation harness
translate between two shapes for no reason, so `bol_label()` and `invoice_label()`
emit exactly those fifteen keys, in the same order, with the same names.

A label is **what is printed on that specific document**, after `seed_errors.py` has
had its chance to corrupt it — never the "intended" clean value. The extraction
prompt's own rule 5 ("do not reconcile arithmetic... report all three exactly as
printed") only makes sense if the ground truth it is scored against is the printed
number too. `records.ConsignmentRecord` keeps the intended values; a label is a
snapshot taken from the printed fields at render time, which is also why
`seed_errors.apply()` mutates label dicts rather than the record.
"""

from __future__ import annotations

from src.agents.doc_corpus.records import ConsignmentRecord

# The exact fifteen keys from doc_extraction/v1.md, in its order. Anything producing a
# label dict must carry exactly this key set — `generate.py` asserts it.
LABEL_FIELDS = (
    "document_type", "document_number", "document_date",
    "shipper_name", "consignee_name",
    "origin_facility", "destination_facility",
    "origin_centre_code", "destination_centre_code",
    "weight_kg", "pieces",
    "freight_charge", "other_charges", "total_amount", "currency",
)


def bol_label(rec: ConsignmentRecord) -> dict:
    """The Lorry Receipt / consignment note.

    An LR states the freight terms (paid / to-pay) but is not a tax document — it does
    not itemise surcharges or carry a grand total the way the invoice does. Those two
    fields are printed `null` here by design, not because they were forgotten: a
    Document Intelligence Agent that returns a fabricated total for a document that
    never carried one is the exact failure the extraction prompt's rule 1 exists to
    catch ("never invent a value").
    """
    return {
        "document_type": "BOL",
        "document_number": rec.bol_number,
        "document_date": rec.document_date,
        "shipper_name": rec.shipper_name,
        "consignee_name": rec.consignee_name,
        "origin_facility": rec.source_name,
        "destination_facility": rec.dest_name,
        "origin_centre_code": rec.source_center,
        "destination_centre_code": rec.dest_center,
        "weight_kg": rec.weight_kg,
        "pieces": rec.pieces,
        "freight_charge": rec.freight_charge,
        "other_charges": None,
        "total_amount": None,
        "currency": rec.currency,
    }


def invoice_label(rec: ConsignmentRecord) -> dict:
    """The GST tax invoice — carries the full amount breakdown the LR does not."""
    return {
        "document_type": "INVOICE",
        "document_number": rec.invoice_number,
        "document_date": rec.document_date,
        "shipper_name": rec.shipper_name,
        "consignee_name": rec.consignee_name,
        "origin_facility": rec.source_name,
        "destination_facility": rec.dest_name,
        "origin_centre_code": rec.source_center,
        "destination_centre_code": rec.dest_center,
        "weight_kg": rec.weight_kg,
        "pieces": rec.pieces,
        "freight_charge": rec.freight_charge,
        "other_charges": rec.other_charges,
        "total_amount": rec.total_amount,
        "currency": rec.currency,
    }
