"""BOL and GST-invoice PDF layouts, modelled on the real Indian document forms W2
researched (docs/W2_krishna_india_map.md §4) rather than the US VICS BOL that most
"bill of lading template" material online actually shows.

Both renderers print from a `labels.py` dict (the fifteen extraction-schema fields —
whatever `seed_errors.py` has already mutated is what appears on the page) plus a
handful of realism fields straight off the `ConsignmentRecord` that are not part of
the extraction schema (GSTIN, vehicle number) and so are never touched by seeded
errors. Printing from the label dict rather than the record is what keeps the PDF and
its ground truth from ever drifting apart (see the module docstring in `labels.py`).
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from src.agents.doc_corpus.records import ConsignmentRecord

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm

TITLES = {"BOL": "CONSIGNMENT NOTE / LORRY RECEIPT", "INVOICE": "TAX INVOICE"}


def _money(value, currency: str) -> str:
    return "—" if value is None else f"{currency} {value:,.2f}"


def _text(value) -> str:
    return "—" if value is None else str(value)


def _header(c: canvas.Canvas, title: str) -> float:
    y = PAGE_H - MARGIN
    c.setFont("Helvetica-Bold", 15)
    c.drawString(MARGIN, y, title)
    c.setLineWidth(1)
    c.line(MARGIN, y - 4, PAGE_W - MARGIN, y - 4)
    return y - 14 * mm


def _kv(c: canvas.Canvas, x: float, y: float, label: str, value: str, label_w=42 * mm) -> None:
    c.setFont("Helvetica", 9)
    c.drawString(x, y, label)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x + label_w, y, value)


def _rule(c: canvas.Canvas, y: float) -> None:
    c.setStrokeColor(colors.grey)
    c.setLineWidth(0.5)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)
    c.setStrokeColor(colors.black)


def field_rows(rec: ConsignmentRecord, label: dict, doc_type: str) -> list[tuple[str, str]]:
    """The (label, value) pairs both this module's PDF and `noise.py`'s simulated
    scan draw. One shared list means a field added to the layout cannot silently go
    missing from only one of the two renderers — the two-copies-of-one-truth trap
    P-23 recorded for the city-alias tables, here avoided rather than repeated."""
    if doc_type == "BOL":
        return [
            ("LR No.", _text(label["document_number"])),
            ("Date", _text(label["document_date"])),
            ("Consignor", _text(label["shipper_name"])),
            ("Consignee", _text(label["consignee_name"])),
            ("Origin", _text(label["origin_facility"])),
            ("Origin centre code", _text(label["origin_centre_code"])),
            ("Destination", _text(label["destination_facility"])),
            ("Destination centre code", _text(label["destination_centre_code"])),
            ("Vehicle No.", rec.vehicle_number),
            ("Route type", rec.route_type),
            ("Pieces", _text(label["pieces"])),
            ("Weight (kg)", _text(label["weight_kg"])),
            ("Freight charges", _money(label["freight_charge"], label["currency"])),
            ("Terms", "Paid" if rec.route_type == "FTL" else "To-Pay"),
        ]
    tax_note = "IGST applicable" if rec.source_state != rec.dest_state else "CGST + SGST applicable"
    return [
        ("Invoice No.", _text(label["document_number"])),
        ("Date", _text(label["document_date"])),
        ("Consignment (LR) No.", rec.bol_number),
        ("Vehicle No.", rec.vehicle_number),
        ("Supplier", _text(label["shipper_name"])),
        ("Supplier GSTIN", rec.shipper_gstin),
        ("Recipient", _text(label["consignee_name"])),
        ("Recipient GSTIN", rec.consignee_gstin),
        ("Place of supply", rec.dest_state or "—"),
        ("Tax treatment", tax_note),
        ("Origin", _text(label["origin_facility"])),
        ("Origin code", _text(label["origin_centre_code"])),
        ("Destination", _text(label["destination_facility"])),
        ("Destination code", _text(label["destination_centre_code"])),
        ("Description", "Goods Transport Agency service"),
        ("HSN/SAC", "996791"),
        ("Pieces", _text(label["pieces"])),
        ("Weight (kg)", _text(label["weight_kg"])),
        ("Freight charges", _money(label["freight_charge"], label["currency"])),
        ("Other charges", _money(label["other_charges"], label["currency"])),
        ("Total amount", _money(label["total_amount"], label["currency"])),
    ]


def render_bol_pdf(rec: ConsignmentRecord, label: dict, path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    y = _header(c, TITLES["BOL"])

    left = MARGIN
    right = PAGE_W / 2 + 4 * mm
    row_h = 7 * mm

    _kv(c, left, y, "LR No.:", _text(label["document_number"]))
    _kv(c, right, y, "Date:", _text(label["document_date"]))
    y -= row_h * 1.6
    _rule(c, y); y -= row_h

    _kv(c, left, y, "Consignor:", _text(label["shipper_name"]))
    y -= row_h
    _kv(c, left, y, "Consignee:", _text(label["consignee_name"]))
    y -= row_h * 1.6
    _rule(c, y); y -= row_h

    _kv(c, left, y, "Origin:", _text(label["origin_facility"]))
    y -= row_h
    _kv(c, left, y, "Origin centre code:", _text(label["origin_centre_code"]))
    y -= row_h
    _kv(c, left, y, "Destination:", _text(label["destination_facility"]))
    y -= row_h
    _kv(c, left, y, "Destination centre code:", _text(label["destination_centre_code"]))
    y -= row_h * 1.6
    _rule(c, y); y -= row_h

    _kv(c, left, y, "Vehicle No.:", rec.vehicle_number)
    _kv(c, right, y, "Route type:", rec.route_type)
    y -= row_h
    _kv(c, left, y, "Pieces:", _text(label["pieces"]))
    _kv(c, right, y, "Weight (kg):", _text(label["weight_kg"]))
    y -= row_h
    _kv(c, left, y, "Freight charges:", _money(label["freight_charge"], label["currency"]))
    _kv(c, right, y, "Terms:", "Paid" if rec.route_type == "FTL" else "To-Pay")
    y -= row_h * 2.5
    _rule(c, y); y -= row_h * 2

    c.setFont("Helvetica", 9)
    c.drawString(left, y, f"For {label['shipper_name']}")
    c.drawString(right, y, "Received in good condition — Consignee signature")
    c.setFont("Helvetica-Oblique", 7)
    c.setFillColor(colors.grey)
    c.drawString(left, MARGIN / 2, "Synthetic document — Agentic AI Logistics Control Tower, Week 3 corpus.")
    c.showPage()
    c.save()


def render_invoice_pdf(rec: ConsignmentRecord, label: dict, path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    y = _header(c, TITLES["INVOICE"])

    left = MARGIN
    right = PAGE_W / 2 + 4 * mm
    row_h = 7 * mm

    _kv(c, left, y, "Invoice No.:", _text(label["document_number"]))
    _kv(c, right, y, "Date:", _text(label["document_date"]))
    y -= row_h
    _kv(c, left, y, "Consignment (LR) No.:", rec.bol_number)
    _kv(c, right, y, "Vehicle No.:", rec.vehicle_number)
    y -= row_h * 1.6
    _rule(c, y); y -= row_h

    _kv(c, left, y, "Supplier:", _text(label["shipper_name"]))
    _kv(c, right, y, "GSTIN:", rec.shipper_gstin)
    y -= row_h
    _kv(c, left, y, "Recipient:", _text(label["consignee_name"]))
    _kv(c, right, y, "GSTIN:", rec.consignee_gstin)
    y -= row_h
    _kv(c, left, y, "Place of supply:", rec.dest_state or "—")
    tax_note = "IGST applicable" if rec.source_state != rec.dest_state else "CGST + SGST applicable"
    _kv(c, right, y, "Tax treatment:", tax_note)
    y -= row_h * 1.6
    _rule(c, y); y -= row_h

    _kv(c, left, y, "Origin:", _text(label["origin_facility"]))
    _kv(c, right, y, "Origin code:", _text(label["origin_centre_code"]))
    y -= row_h
    _kv(c, left, y, "Destination:", _text(label["destination_facility"]))
    _kv(c, right, y, "Destination code:", _text(label["destination_centre_code"]))
    y -= row_h
    _kv(c, left, y, "Description:", "Goods Transport Agency service")
    _kv(c, right, y, "HSN/SAC:", "996791")
    y -= row_h
    _kv(c, left, y, "Pieces:", _text(label["pieces"]))
    _kv(c, right, y, "Weight (kg):", _text(label["weight_kg"]))
    y -= row_h * 1.6
    _rule(c, y); y -= row_h

    _kv(c, left, y, "Freight charges:", _money(label["freight_charge"], label["currency"]))
    y -= row_h
    _kv(c, left, y, "Other charges (surcharge, tax):", _money(label["other_charges"], label["currency"]))
    y -= row_h
    c.setFont("Helvetica-Bold", 11)
    c.drawString(left, y, "Total amount:")
    c.drawString(left + 55 * mm, y, _money(label["total_amount"], label["currency"]))
    y -= row_h * 2.5
    _rule(c, y); y -= row_h * 2

    c.setFont("Helvetica", 9)
    c.drawString(left, y, f"For {label['shipper_name']}, Authorised Signatory")
    c.setFont("Helvetica-Oblique", 7)
    c.setFillColor(colors.grey)
    c.drawString(left, MARGIN / 2, "Synthetic document — Agentic AI Logistics Control Tower, Week 3 corpus.")
    c.showPage()
    c.save()
