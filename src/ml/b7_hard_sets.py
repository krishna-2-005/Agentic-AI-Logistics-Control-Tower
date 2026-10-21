"""Harder, held-out evaluation sets for the B7 ablation (D-086).

    python -m src.ml.b7_hard_sets --build      # write the two sets (deterministic, seeded)
    python -m src.ml.b7_hard_sets --score      # first-run score of the deterministic agents

What the 200-case sets did not cover
-------------------------------------
The existing order set (`order_eval_scale`) has contradiction, two-consignment, pounds,
Hinglish and city-only cases. It has no weight with **no unit at all**, no **malformed centre
code** (a code of the wrong shape, which is different from a city name), no conflict on pieces
or service level, and only one Hinglish phrasing per outcome. The invoice set (20 of each of 10
kinds) has no case **either side of the 15% tolerance edge**, nor either side of the other
charge share's edges or the 0.01 total tolerance. This module fills exactly those gaps:

order set, 10 templates x 10 = 100 emails

========================  ======  ==============================================
template                  expect  what it tests
========================  ======  ==============================================
``unit_missing``          ask     "Weight: 1450" with no unit anywhere
``code_short_origin``     ask     origin code with 5 digits
``code_long_dest``        ask     destination code with 7 digits
``code_scrambled``        ask     letters and digits swapped (``IND`` + AAD + digits)
``conflict_pieces``       ask     two different piece counts, neither superseded
``conflict_service``      ask     FTL in the subject, Carting in the body
``two_orders_hinglish``   ask     two bookings, Hindi-English, "aur ek"
``hinglish_file``         file    complete booking in code-mixed phrasing
``hinglish_no_weight``    ask     "vajan abhi pata nahi" (weight not known yet)
``hinglish_tonnes``       file    weight in "ton", converted by the reader
========================  ======  ==============================================

invoice boundary set, 10 kinds x 10 = 100 invoices: freight just inside and just outside both
ends of the tolerated rate band (2% either side of the edge), other charges just inside and
just outside both ends of the 5-18% share (plus the one-point slack), and a total that is off
by half a paisa versus two paise.

Builder and judge are separate (D-028)
--------------------------------------
Nothing here imports the agents' rules (`order_rules`, `audit_invoice`, `freight_band`). The
expected labels come from this module's own statement of the policy and its own copy of the
corpus rate model. Both sets are **still synthetic**, and for the invoices the label policy is
the same 15% tolerance the auditor uses (D-043 and D-047), so what is measured is edge
behaviour, not whether the tolerance is right. Seeds are fixed. The sets are held out: the
agents are not tuned against them, and the first-run result is the one reported.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass
from datetime import datetime

from src.agents.doc_corpus.records import ConsignmentRecord, generate_records
from src.common import config
from src.ml.stats import wilson

RAW = config.BENCHMARKS_RAW_DIR
ORDER_SET_JSON = RAW / "b7_order_hard_set.json"
INVOICE_SET_JSON = RAW / "b7_invoice_boundary_set.json"
RESULT_JSON = RAW / "b7_hard_sets_deterministic.json"
ORDER_SEED = 9031
INVOICE_SEED = 9033  # 9032 hits a corridor with a null facility name in the corpus pool (records.py)
PER_TEMPLATE = 10

# The policy, restated here and not imported from the auditor.
TOLERANCE = 0.15
SHARE_LOW, SHARE_HIGH, SHARE_SLACK = 0.05, 0.18, 0.01
TOTAL_TOLERANCE = 0.01
EDGE_MARGIN = 0.02

SIGNERS = ["Priya Nair", "Rahul Menon", "Anita Desai", "Vikram Shah", "Sneha Iyer",
           "Arjun Rao", "Meera Krishnan", "Imran Sheikh", "Kavya Reddy", "Nikhil Bose"]


@dataclass
class HardOrder:
    seq: int
    template: str
    adversarial: bool
    subject: str
    body: str
    expected_action: str
    expected_missing: str | None
    expected_fields: dict


def _mode(r: ConsignmentRecord) -> str:
    return "FTL" if r.route_type == "FTL" else "Carting"


def _sign(r: ConsignmentRecord, i: int) -> str:
    return f"Regards,\n{SIGNERS[i % len(SIGNERS)]}\n{r.shipper_name}"


def _truth(r: ConsignmentRecord, **over) -> dict:
    fields = {"customer_name": r.shipper_name, "origin_centre": r.source_center,
              "dest_centre": r.dest_center, "route_type": r.route_type,
              "pieces": r.pieces, "weight_kg": r.weight_kg}
    fields.update(over)
    return {k: v for k, v in fields.items() if v is not None}


def _digits(code: str) -> str:
    return code[3:9]


def o_unit_missing(r, i):
    body = (f"Hello,\n\nPlease collect from {r.source_name} ({r.source_center}) for "
            f"{r.dest_name} ({r.dest_center}).\nPackages: {r.pieces}\nWeight: {int(r.weight_kg)}\n"
            f"Service: {_mode(r)}\n\n{_sign(r, i)}")
    return "Booking", body, "clarify", "weight_kg", _truth(r, weight_kg=None)


def o_code_short_origin(r, i):
    bad = f"IND{_digits(r.source_center)[:5]}{r.source_center[-3:]}"
    body = (f"Hi,\n\nBooking: from {bad} to {r.dest_center}. {r.pieces} pieces, "
            f"{r.weight_kg} kg, {_mode(r)}.\n\n{_sign(r, i)}")
    return "New booking", body, "clarify", "origin_centre", _truth(r, origin_centre=None)


def o_code_long_dest(r, i):
    bad = f"IND{_digits(r.dest_center)}7{r.dest_center[-3:]}"
    body = (f"Hi,\n\nPlease book {r.pieces} pieces ({r.weight_kg} kg) from {r.source_center} "
            f"to {bad}. {_mode(r)}.\n\n{_sign(r, i)}")
    return "New booking", body, "clarify", "dest_centre", _truth(r, dest_centre=None)


def o_code_scrambled(r, i):
    bad = f"IND{r.dest_center[-3:]}{_digits(r.dest_center)}"
    body = (f"Dear team,\n\nOrigin {r.source_center}, destination {bad}. {r.pieces} pieces, "
            f"{r.weight_kg} kg, {_mode(r)}.\n\n{_sign(r, i)}")
    return "Transfer request", body, "clarify", "dest_centre", _truth(r, dest_centre=None)


def o_conflict_pieces(r, i):
    other = r.pieces + 3
    body = (f"Hello,\n\nShipment from {r.source_center} to {r.dest_center}, {_mode(r)}, "
            f"{r.weight_kg} kg.\nNo. of packages: {r.pieces}\n"
            f"(Warehouse sheet shows {other} packages loaded.)\n\n{_sign(r, i)}")
    return "Booking", body, "clarify", "pieces", _truth(r, pieces=None)


def o_conflict_service(r, i):
    other = "Carting" if r.route_type == "FTL" else "FTL"
    body = (f"Hello,\n\nPlease move {r.pieces} pieces, {r.weight_kg} kg, from {r.source_center} "
            f"to {r.dest_center} as {other}.\n\n{_sign(r, i)}")
    return f"Booking - {_mode(r)}", body, "clarify", "route_type", _truth(r, route_type=None)


def o_two_orders_hinglish(r, i):
    body = (f"Hi,\n\nDo booking karni hain.\nPehli: {r.source_center} se {r.dest_center}, "
            f"{r.pieces} pieces, {r.weight_kg} kg, {_mode(r)}.\n"
            f"Aur ek: {r.dest_center} se {r.source_center}, {max(1, r.pieces - 1)} pieces, "
            f"{round(r.weight_kg / 3, 1)} kg, {_mode(r)}.\n\nDono confirm kar dena.\n\n{_sign(r, i)}")
    return "Two bookings", body, "clarify", "consignment", _truth(r, dest_centre=None, weight_kg=None, pieces=None)


def o_hinglish_file(r, i):
    body = (f"Namaste,\n\n{r.source_center} se {r.dest_center} tak ek booking karni hai. "
            f"Total {r.pieces} packets hain aur vajan {r.weight_kg} kg hai. {_mode(r)} chahiye.\n"
            f"Kripya jaldi confirm karein.\n\n{_sign(r, i)}")
    return "Booking confirm karna", body, "file", None, _truth(r)


def o_hinglish_no_weight(r, i):
    body = (f"Bhai,\n\n{r.source_center} se {r.dest_center} ke liye {r.pieces} packets bhejne hain, "
            f"{_mode(r)}. Vajan abhi pata nahi hai, godown mein tolna baaki hai.\n\n{_sign(r, i)}")
    return "Booking", body, "clarify", "weight_kg", _truth(r, weight_kg=None)


def o_hinglish_tonnes(r, i):
    tonnes = round(r.weight_kg / 1000, 1) or 0.1
    body = (f"Hello ji,\n\n{r.source_center} se {r.dest_center} ke liye {r.pieces} pieces, "
            f"total {tonnes} ton maal hai. {_mode(r)} mein bhejna hai.\n\n{_sign(r, i)}")
    return "Maal booking", body, "file", None, _truth(r, weight_kg=round(tonnes * 1000, 1))


ORDER_TEMPLATES = [
    ("unit_missing", o_unit_missing), ("code_short_origin", o_code_short_origin),
    ("code_long_dest", o_code_long_dest), ("code_scrambled", o_code_scrambled),
    ("conflict_pieces", o_conflict_pieces), ("conflict_service", o_conflict_service),
    ("two_orders_hinglish", o_two_orders_hinglish), ("hinglish_file", o_hinglish_file),
    ("hinglish_no_weight", o_hinglish_no_weight), ("hinglish_tonnes", o_hinglish_tonnes),
]


def build_order_hard(per_template: int = PER_TEMPLATE, seed: int = ORDER_SEED) -> list[HardOrder]:
    records = generate_records(per_template * len(ORDER_TEMPLATES), seed=seed)
    random.Random(seed).shuffle(records)
    out: list[HardOrder] = []
    k = 0
    for name, builder in ORDER_TEMPLATES:
        for j in range(per_template):
            r = records[k]
            k += 1
            subject, body, action, missing, fields = builder(r, j)
            out.append(HardOrder(len(out) + 1, name, True, subject, body, action, missing, fields))
    return out


# ── invoices ────────────────────────────────────────────────────────────────
INVOICE_KINDS = {
    # kind: (expected verdict, expected reason code)
    "freight_top_inside": ("approve", None),
    "freight_top_outside": ("dispute", "rate_above_band"),
    "freight_bottom_inside": ("approve", None),
    "freight_bottom_outside": ("dispute", "rate_below_band"),
    "share_high_inside": ("approve", None),
    "share_high_outside": ("dispute", "other_charges_out_of_band"),
    "share_low_inside": ("approve", None),
    "share_low_outside": ("dispute", "other_charges_out_of_band"),
    "total_off_half_paisa": ("approve", None),
    "total_off_two_paise": ("dispute", "total_mismatch"),
}


@dataclass
class HardInvoice:
    seq: int
    kind: str
    corridor_id: str
    route_type: str
    weight_kg: float
    pieces: int
    external_invoice_number: str
    freight_charge: float
    other_charges: float
    total_amount: float
    mean_osrm_km: float
    currency: str
    expected_verdict: str
    expected_finding: str | None


def _own_band(r: ConsignmentRecord) -> tuple[float, float]:
    """The corpus's rate model, restated here: untolerated (low, high) freight for the record."""
    if r.route_type == "FTL":
        return 28.0 * r.mean_osrm_km, 45.0 * r.mean_osrm_km
    tonnes = r.weight_kg / 1000
    return (6.0 * r.mean_osrm_km * tonnes + 2.0 * r.weight_kg,
            10.0 * r.mean_osrm_km * tonnes + 4.0 * r.weight_kg)


def build_invoice_boundary(per_kind: int = PER_TEMPLATE, seed: int = INVOICE_SEED) -> list[HardInvoice]:
    kinds = list(INVOICE_KINDS)
    records = generate_records(per_kind * len(kinds), seed=seed)
    random.Random(seed).shuffle(records)
    out: list[HardInvoice] = []
    k = 0
    for kind in kinds:
        for _ in range(per_kind):
            r = records[k]
            k += 1
            low, high = _own_band(r)
            freight, share, total_extra = r.freight_charge, 0.12, 0.0
            if kind == "freight_top_inside":
                freight = high * (1 + TOLERANCE) * (1 - EDGE_MARGIN)
            elif kind == "freight_top_outside":
                freight = high * (1 + TOLERANCE) * (1 + EDGE_MARGIN)
            elif kind == "freight_bottom_inside":
                freight = low * (1 - TOLERANCE) * (1 + EDGE_MARGIN)
            elif kind == "freight_bottom_outside":
                freight = low * (1 - TOLERANCE) * (1 - EDGE_MARGIN)
            elif kind == "share_high_inside":
                share = SHARE_HIGH + SHARE_SLACK - 0.005
            elif kind == "share_high_outside":
                share = SHARE_HIGH + SHARE_SLACK + 0.005
            elif kind == "share_low_inside":
                share = SHARE_LOW - SHARE_SLACK + 0.005
            elif kind == "share_low_outside":
                share = SHARE_LOW - SHARE_SLACK - 0.005
            elif kind == "total_off_half_paisa":
                total_extra = 0.005
            elif kind == "total_off_two_paise":
                total_extra = 0.02
            freight = round(freight, 2)
            other = round(freight * share, 2)
            verdict, finding = INVOICE_KINDS[kind]
            out.append(HardInvoice(
                seq=len(out) + 1, kind=kind, corridor_id=r.corridor_id, route_type=r.route_type,
                weight_kg=r.weight_kg, pieces=r.pieces, external_invoice_number=f"BND-{len(out) + 1:06d}",
                freight_charge=freight, other_charges=other,
                total_amount=round(freight + other + total_extra, 3), mean_osrm_km=r.mean_osrm_km,
                currency="INR", expected_verdict=verdict, expected_finding=finding))
    return out


# ── first-run score of the deterministic agents ─────────────────────────────
def score_deterministic() -> dict:
    from src.agents.exception_agent import load_audit
    from src.agents.invoice_auditor import (
        InvoiceCase,
        audit_invoice,
        corridor_km_lookup,
        verdict_for,
    )
    from src.agents.order_rules import extract_order_rules
    from src.ml.order_eval_scale import Case, field_matches, score_case

    orders = build_order_hard()
    rows = []
    for o in orders:
        got = extract_order_rules(o.subject, o.body)
        sc = score_case(Case(**asdict(o)), got)
        # Why a wrong case was wrong, for the write-up: the action, or which stated fields differ.
        wrong_fields = [k for k, v in o.expected_fields.items()
                        if got.get("action") == "file" and o.expected_action == "file"
                        and not field_matches(k, (got.get("order") or {}).get(k), v)]
        rows.append({"template": o.template, "correct": bool(sc["correct"]),
                     "invented": bool(sc["invented_fields"]), "got": sc["got_action"],
                     "wrong_fields": wrong_fields})
    by_t = {}
    for name, _ in ORDER_TEMPLATES:
        sub = [x for x in rows if x["template"] == name]
        by_t[name] = wilson(sum(x["correct"] for x in sub), len(sub)).as_dict()

    km = corridor_km_lookup(load_audit())
    inv = build_invoice_boundary()
    irows = []
    for c in inv:
        case = InvoiceCase(seq=c.seq, kind=c.kind, corridor_id=c.corridor_id, route_type=c.route_type,
                           weight_kg=c.weight_kg, pieces=c.pieces,
                           external_invoice_number=c.external_invoice_number, freight_charge=c.freight_charge,
                           other_charges=c.other_charges, total_amount=c.total_amount, currency=c.currency)
        findings = audit_invoice(case, km.get(c.corridor_id), set())
        verdict = verdict_for(findings)
        irows.append({"kind": c.kind, "correct": verdict == c.expected_verdict,
                      "right_reason": (c.expected_finding in [f.code for f in findings]) if c.expected_finding else None})
    by_k = {}
    for kind in INVOICE_KINDS:
        sub = [x for x in irows if x["kind"] == kind]
        by_k[kind] = wilson(sum(x["correct"] for x in sub), len(sub)).as_dict()
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "pre_registered_in": "D-086", "held_out": True, "synthetic": True,
        "note": "first run of the unmodified deterministic agents; nothing was tuned on these sets",
        "order": {"n": len(rows), "overall": wilson(sum(x["correct"] for x in rows), len(rows)).as_dict(),
                  "orders_filed_on_invented_values": sum(x["invented"] for x in rows), "by_template": by_t,
                  "failures": [{"template": x["template"], "got_action": x["got"], "wrong_fields": x["wrong_fields"]}
                               for x in rows if not x["correct"]]},
        "invoice": {"n": len(irows), "overall": wilson(sum(x["correct"] for x in irows), len(irows)).as_dict(),
                    "by_kind": by_k},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--score", action="store_true")
    args = ap.parse_args()
    if args.build or not args.score:
        ORDER_SET_JSON.write_text(json.dumps([asdict(o) for o in build_order_hard()], indent=2), encoding="utf-8")
        INVOICE_SET_JSON.write_text(json.dumps([asdict(c) for c in build_invoice_boundary()], indent=2), encoding="utf-8")
        print(f"wrote {ORDER_SET_JSON.name} and {INVOICE_SET_JSON.name}")
    if args.score:
        result = score_deterministic()
        RESULT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({k: result[k] for k in ("order", "invoice")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
