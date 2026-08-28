"""API tests for the mock TMS.

    pytest tests/test_tms.py -q

Runs against a throwaway SQLite file, never the developer's `data/tms.sqlite`, and
never touches Spark — the point of the TMS is that it boots without a JVM.

These are the behaviours the Week 5 and 6 agents depend on. Every one of them is a
rule someone could plausibly "simplify" away later without noticing what it was for,
which is why they are asserted rather than left to the demo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from src.common import config
from src.tms import db
from src.tms.app import app
from src.tms.models import Facility

ORIGIN = "IND683511AAA"
DEST = "IND580028AAA"


@pytest.fixture(name="client")
def client_fixture(tmp_path):
    """A fresh database per test, with two known facilities seeded.

    The client carries the API key whenever one is configured, because whether auth is
    on depends on the developer's `.env` and the rest of these tests are not about
    auth. `test_auth_*` below controls `config.TMS_API_KEY` itself rather than
    inheriting whatever the machine happens to have set.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_tms.sqlite'}", connect_args={"check_same_thread": False}
    )
    db.set_engine(engine)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            Facility(
                centre_code=ORIGIN,
                name="Aluva_Peedika_H (Kerala)",
                city="Aluva",
                state="Kerala",
                friction_rank=1,
                median_dwell_min_out=350.0,
                n_legs_out=86,
            )
        )
        session.add(
            Facility(
                centre_code=DEST,
                name="Hubli_Adargchi_IP (Karnataka)",
                city="Hubli",
                state="Karnataka",
                friction_rank=2,
                median_dwell_min_out=373.0,
                n_legs_out=78,
            )
        )
        session.commit()

    headers = {"X-API-Key": config.TMS_API_KEY} if config.TMS_API_KEY else {}
    with TestClient(app, headers=headers) as test_client:
        yield test_client

    db.set_engine(None)  # type: ignore[arg-type]
    SQLModel.metadata.drop_all(engine)


def order_payload(**overrides) -> dict:
    payload = {
        "customer_name": "Acme Traders",
        "customer_email": "ops@acme.example",
        "origin_centre": ORIGIN,
        "dest_centre": DEST,
        "route_type": "FTL",
        "pieces": 12,
        "weight_kg": 480.5,
    }
    payload.update(overrides)
    return payload


# ── Health and reference data ────────────────────────────────────────────────
def test_health_is_open_and_counts_rows(client):
    """The Week 6 boot script waits on /health before starting the agents, so it must
    answer without a key."""
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["facilities"] == 2
    assert body["orders"] == 0


def test_facility_search_matches_city_not_only_code(client):
    """Customers name cities; the agent has to turn 'Aluva' into a centre code."""
    found = client.get("/facilities", params={"query": "Aluva"}).json()
    assert [f["centre_code"] for f in found] == [ORIGIN]


def test_unknown_facility_is_404(client):
    assert client.get("/facilities/IND000000ZZZ").status_code == 404


# ── Auth ─────────────────────────────────────────────────────────────────────
def test_auth_is_off_when_no_key_is_configured(client, monkeypatch):
    """A teammate who has not filled in `.env` should not be locked out of their own
    mock service."""
    monkeypatch.setattr(config, "TMS_API_KEY", "")
    assert client.get("/facilities", headers={"X-API-Key": ""}).status_code == 200


def test_auth_rejects_a_wrong_key_and_accepts_the_right_one(client, monkeypatch):
    monkeypatch.setattr(config, "TMS_API_KEY", "secret-key")
    assert client.get("/facilities", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/facilities", headers={"X-API-Key": "secret-key"}).status_code == 200


def test_health_stays_open_even_with_auth_on(client, monkeypatch):
    monkeypatch.setattr(config, "TMS_API_KEY", "secret-key")
    assert client.get("/health", headers={"X-API-Key": "wrong"}).status_code == 200


# ── Order creation ───────────────────────────────────────────────────────────
def test_create_order_assigns_reference_and_corridor(client):
    body = client.post("/orders", json=order_payload()).json()
    assert body["order_ref"] == "ORD-000001"
    assert body["corridor_id"] == f"{ORIGIN}>{DEST}"
    assert body["status"] == "received"
    assert body["idempotent_replay"] is False


def test_centre_codes_are_upper_cased(client):
    """An agent lifting a code off a scanned document gets the case wrong; that is not
    a real rejection reason."""
    body = client.post(
        "/orders", json=order_payload(origin_centre=ORIGIN.lower(), dest_centre=DEST.lower())
    ).json()
    assert body["origin_centre"] == ORIGIN
    assert body["dest_centre"] == DEST


def test_unknown_centre_is_rejected_and_names_the_code(client):
    """The 422 body is what the agent's clarification path quotes back to the
    customer, so the offending code has to be in it."""
    response = client.post("/orders", json=order_payload(dest_centre="IND999999XXX"))
    assert response.status_code == 422
    assert "IND999999XXX" in response.json()["detail"]


def test_same_origin_and_destination_is_rejected(client):
    response = client.post("/orders", json=order_payload(dest_centre=ORIGIN))
    assert response.status_code == 422


@pytest.mark.parametrize(
    "bad",
    [{"pieces": 0}, {"weight_kg": 0}, {"weight_kg": -5}, {"route_type": "Air"}, {"customer_name": ""}],
)
def test_malformed_orders_are_rejected(client, bad):
    assert client.post("/orders", json=order_payload(**bad)).status_code == 422


def test_high_friction_origin_raises_a_warning_not_an_error(client):
    """A slow hub is information, not a defect — the order still goes through."""
    body = client.post("/orders", json=order_payload()).json()
    assert body["status"] == "received"
    assert any("friction" in w for w in body["warnings"])


# ── Idempotency ──────────────────────────────────────────────────────────────
def test_repeated_external_ref_returns_the_same_order(client):
    """Mail gets redelivered and agents retry. Two POSTs of one email must not produce
    two orders."""
    first = client.post("/orders", json=order_payload(external_ref="email-42"))
    second = client.post("/orders", json=order_payload(external_ref="email-42"))

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["order_ref"] == first.json()["order_ref"]
    assert second.json()["idempotent_replay"] is True
    assert client.get("/health").json()["orders"] == 1


def test_orders_without_external_ref_are_not_deduplicated(client):
    """Two identical orders with no idempotency key are two real orders — a customer
    is allowed to book the same lane twice."""
    client.post("/orders", json=order_payload())
    client.post("/orders", json=order_payload())
    assert client.get("/health").json()["orders"] == 2


# ── Status transitions ───────────────────────────────────────────────────────
def test_cancelled_orders_cannot_be_reopened(client):
    ref = client.post("/orders", json=order_payload()).json()["order_ref"]
    client.patch(f"/orders/{ref}", json={"status": "cancelled"})
    response = client.patch(f"/orders/{ref}", json={"status": "confirmed"})
    assert response.status_code == 409


# ── Shipments ────────────────────────────────────────────────────────────────
def test_booking_a_shipment_confirms_the_order(client):
    """Otherwise the Week 6 lifecycle ends with a shipment in transit against an order
    still sitting in `received`."""
    ref = client.post("/orders", json=order_payload()).json()["order_ref"]
    shipment = client.post("/shipments", json={"order_ref": ref})

    assert shipment.status_code == 201
    assert shipment.json()["shipment_ref"] == "SHP-000001"
    assert shipment.json()["corridor_id"] == f"{ORIGIN}>{DEST}"
    assert client.get(f"/orders/{ref}").json()["status"] == "confirmed"


def test_shipment_inherits_route_type_and_can_override_it(client):
    ref = client.post("/orders", json=order_payload(route_type="FTL")).json()["order_ref"]
    body = client.post("/shipments", json={"order_ref": ref, "route_type": "Carting"}).json()
    assert body["route_type"] == "Carting"


def test_one_shipment_per_order(client):
    ref = client.post("/orders", json=order_payload()).json()["order_ref"]
    client.post("/shipments", json={"order_ref": ref})
    second = client.post("/shipments", json={"order_ref": ref})
    assert second.status_code == 409
    assert "SHP-000001" in second.json()["detail"]


def test_cancelled_order_cannot_be_shipped(client):
    ref = client.post("/orders", json=order_payload()).json()["order_ref"]
    client.patch(f"/orders/{ref}", json={"status": "cancelled"})
    assert client.post("/shipments", json={"order_ref": ref}).status_code == 409


def test_arrival_before_departure_is_rejected(client):
    ref = client.post("/orders", json=order_payload()).json()["order_ref"]
    depart = datetime(2018, 9, 20, 8, 0, tzinfo=timezone.utc)
    response = client.post(
        "/shipments",
        json={
            "order_ref": ref,
            "planned_departure": depart.isoformat(),
            "planned_arrival": (depart - timedelta(hours=2)).isoformat(),
        },
    )
    assert response.status_code == 422


def test_shipment_for_unknown_order_is_404(client):
    assert client.post("/shipments", json={"order_ref": "ORD-999999"}).status_code == 404


def test_shipments_are_filterable_by_corridor(client):
    ref = client.post("/orders", json=order_payload()).json()["order_ref"]
    client.post("/shipments", json={"order_ref": ref})
    hits = client.get("/shipments", params={"corridor": f"{ORIGIN}>{DEST}"}).json()
    assert len(hits) == 1
    assert hits[0]["order_ref"] == ref
    assert client.get("/shipments", params={"corridor": "IND1>IND2"}).json() == []


# ── Week 3: shipment status updates ──────────────────────────────────────────
def make_shipment(client) -> str:
    order_ref = client.post("/orders", json=order_payload()).json()["order_ref"]
    return client.post("/shipments", json={"order_ref": order_ref}).json()["shipment_ref"]


def test_shipment_status_moves_through_the_lifecycle(client):
    ref = make_shipment(client)
    body = client.patch(f"/shipments/{ref}", json={"status": "in_transit"}).json()
    assert body["status"] == "in_transit"
    body = client.patch(
        f"/shipments/{ref}", json={"status": "delivered", "notes": "signed for at the dock"}
    ).json()
    assert body["status"] == "delivered"
    assert body["notes"] == "signed for at the dock"


def test_delivered_shipments_are_terminal(client):
    ref = make_shipment(client)
    client.patch(f"/shipments/{ref}", json={"status": "delivered"})
    response = client.patch(f"/shipments/{ref}", json={"status": "in_transit"})
    assert response.status_code == 409


def test_unknown_shipment_status_update_is_404(client):
    assert client.patch("/shipments/SHP-999999", json={"status": "in_transit"}).status_code == 404


# ── Week 3: exception tickets ─────────────────────────────────────────────────
def test_filing_an_exception_flags_the_shipment_and_assigns_a_reference(client):
    ref = make_shipment(client)
    body = client.post(
        "/exceptions",
        json={"shipment_ref": ref, "severity": "high", "reason": "predicted delay 3.2x plan"},
    ).json()
    assert body["ticket_ref"] == "EXC-000001"
    assert body["shipment_ref"] == ref
    assert body["corridor_id"] == f"{ORIGIN}>{DEST}"
    assert body["status"] == "open"
    assert client.get(f"/shipments/{ref}").json()["status"] == "exception"


def test_exception_against_unknown_shipment_is_404(client):
    response = client.post(
        "/exceptions",
        json={"shipment_ref": "SHP-999999", "severity": "low", "reason": "n/a"},
    )
    assert response.status_code == 404


def test_exception_resolution_stamps_resolved_at(client):
    ref = make_shipment(client)
    ticket_ref = client.post(
        "/exceptions", json={"shipment_ref": ref, "severity": "medium", "reason": "late scan"}
    ).json()["ticket_ref"]

    acknowledged = client.patch(f"/exceptions/{ticket_ref}", json={"status": "acknowledged"}).json()
    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["resolved_at"] is None

    resolved = client.patch(
        f"/exceptions/{ticket_ref}", json={"status": "resolved", "notes": "customer notified"}
    ).json()
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"] is not None
    assert resolved["notes"] == "customer notified"


def test_exceptions_are_filterable_by_status_and_severity(client):
    ref = make_shipment(client)
    client.post("/exceptions", json={"shipment_ref": ref, "severity": "critical", "reason": "a"})
    assert len(client.get("/exceptions", params={"severity": "critical"}).json()) == 1
    assert client.get("/exceptions", params={"status": "resolved"}).json() == []


def test_unknown_exception_ticket_is_404(client):
    assert client.get("/exceptions/EXC-999999").status_code == 404


# ── Week 3: invoices ─────────────────────────────────────────────────────────
def invoice_payload(shipment_ref: str, **overrides) -> dict:
    payload = {
        "shipment_ref": shipment_ref,
        "external_invoice_number": "INVOICE-0001",
        "freight_charge": 4200.0,
        "other_charges": 300.0,
        "total_amount": 4500.0,
        "currency": "INR",
    }
    payload.update(overrides)
    return payload


def test_submitting_an_invoice_assigns_a_reference_and_carries_the_corridor(client):
    ref = make_shipment(client)
    body = client.post("/invoices", json=invoice_payload(ref)).json()
    assert body["invoice_ref"] == "INV-000001"
    assert body["shipment_ref"] == ref
    assert body["corridor_id"] == f"{ORIGIN}>{DEST}"
    assert body["status"] == "submitted"


def test_invoice_totals_are_stored_as_submitted_even_if_they_do_not_add_up(client):
    """Reconciling `freight_charge + other_charges` against `total_amount` is the
    Week 6 auditor's job — the API must not silently fix a mismatched invoice, or
    D-020's `total_mismatch` seeded error would have nothing to be caught by."""
    ref = make_shipment(client)
    body = client.post(
        "/invoices",
        json=invoice_payload(ref, freight_charge=1000.0, other_charges=0.0, total_amount=9999.0),
    ).json()
    assert body["total_amount"] == 9999.0


def test_invoice_against_unknown_shipment_is_404(client):
    assert client.post("/invoices", json=invoice_payload("SHP-999999")).status_code == 404


def test_disputing_an_invoice_requires_a_reason(client):
    ref = make_shipment(client)
    invoice_ref = client.post("/invoices", json=invoice_payload(ref)).json()["invoice_ref"]
    response = client.patch(f"/invoices/{invoice_ref}", json={"status": "disputed"})
    assert response.status_code == 422


def test_disputing_an_invoice_with_a_reason_succeeds(client):
    ref = make_shipment(client)
    invoice_ref = client.post("/invoices", json=invoice_payload(ref)).json()["invoice_ref"]
    body = client.patch(
        f"/invoices/{invoice_ref}",
        json={"status": "disputed", "dispute_reason": "freight_charge inconsistent with corridor history"},
    ).json()
    assert body["status"] == "disputed"
    assert "corridor history" in body["dispute_reason"]


def test_invoices_are_filterable_by_corridor(client):
    ref = make_shipment(client)
    client.post("/invoices", json=invoice_payload(ref))
    hits = client.get("/invoices", params={"corridor": f"{ORIGIN}>{DEST}"}).json()
    assert len(hits) == 1
    assert client.get("/invoices", params={"corridor": "IND1>IND2"}).json() == []


def test_unknown_invoice_is_404(client):
    assert client.get("/invoices/INV-999999").status_code == 404
