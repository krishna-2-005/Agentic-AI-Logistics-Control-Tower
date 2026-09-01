"""Mock TMS — FastAPI + SQLite.

    python -m src.tms                     # serve on http://localhost:8000
    open http://localhost:8000/docs       # generated OpenAPI console

Week 2 scope was **orders and shipments**. Week 3 adds the three endpoints those
needed to be useful on their own: **shipment status updates, exception tickets, and
invoices** — the lifecycle transitions Week 5's Order Entry Agent, Week 6's Tracking &
Exception Agent, and Week 6's Invoice Auditor write to.

Why a mock TMS exists at all
----------------------------
The Order Entry Agent (Week 5) has to *do* something with an order it extracts from an
email, and the Invoice Auditor (Week 6) has to check an invoice against what was
actually booked. Pointing them at a stub that always returns 200 would make their
evaluation meaningless — the numbers in `benchmarks/agent_evaluation.md` are only
worth reporting if the agent could have failed. So this service validates, rejects,
and persists like a real one.

It is declared openly as synthetic scaffolding in the README. The *facilities* in it
are not synthetic: they are the real centre codes from the network data.

Two behaviours here exist specifically for the agents
-----------------------------------------------------
* **Idempotent creates.** An agent reading an inbox will retry, and mail gets
  redelivered. `POST /orders` with an `external_ref` that already exists returns the
  order that exists, with `idempotent_replay: true` and HTTP 200 instead of 201.
* **Rejections say what to fix.** An unknown centre code comes back as a 422 naming
  the code, so the agent's clarification path has something to ask the customer about
  rather than a bare "invalid request".
"""

# ruff: noqa: B008 — `Depends(...)` and `Query(...)` in argument defaults is how FastAPI
# declares dependencies and parameter metadata. B008 flags the general Python footgun of
# a mutable default evaluated once at import; here that single evaluation is exactly the
# intended mechanism, and rewriting these to satisfy the rule would break the framework.

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from sqlmodel import Session, func, select

from src.common import config
from src.common.logging_setup import get_logger
from src.tms import db
from src.tms.models import (
    ExceptionCreate,
    ExceptionRead,
    ExceptionStatus,
    ExceptionStatusUpdate,
    ExceptionTicket,
    Facility,
    FacilityRead,
    HealthRead,
    Invoice,
    InvoiceCreate,
    InvoiceRead,
    InvoiceStatus,
    InvoiceStatusUpdate,
    Meta,
    Order,
    OrderCreate,
    OrderRead,
    OrderStatus,
    OrderStatusUpdate,
    Shipment,
    ShipmentCreate,
    ShipmentRead,
    ShipmentStatus,
    ShipmentStatusUpdate,
    utcnow,
)

log = get_logger("tms.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on boot. Seeding stays a separate command — a service that
    rewrites its own reference data on every restart would silently discard a
    hand-fixed row."""
    db.init_db()
    yield


app = FastAPI(
    title="Mock TMS — Agentic AI Logistics Control Tower",
    description=(
        "Synthetic transport management system backing the agent plane. "
        "Facilities are the real Delhivery centre codes; orders and shipments are not."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# ── Auth ─────────────────────────────────────────────────────────────────────
def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Check `X-API-Key` when `TMS_API_KEY` is configured, otherwise wave through.

    Off by default so a teammate who has not filled in `.env` is not blocked; on the
    moment a key is set, because the Order Entry Agent should have to authenticate
    against something that behaves like a real carrier API.
    """
    if not config.TMS_API_KEY:
        return
    if x_api_key != config.TMS_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or incorrect X-API-Key header.",
        )


# ── Helpers ──────────────────────────────────────────────────────────────────
def corridor_of(order: Order) -> str:
    """`SOURCE>DEST` — the same key `src/pipeline/clean.py` builds, so a shipment
    joins straight onto the corridor audit."""
    return f"{order.origin_centre}>{order.dest_centre}"


def validate_centres(session: Session, payload: OrderCreate) -> list[str]:
    """Reject unknown or identical centres; warn about unobserved corridors.

    The distinction is the point. An unknown centre code is a *defect* in the order —
    nothing downstream can price or route it. A corridor that simply never appeared in
    the historical data is a perfectly legal order that just has no benchmark, and the
    Week 6 auditor must not dispute an invoice for missing a benchmark that was never
    there.
    """
    if payload.origin_centre == payload.dest_centre:
        raise HTTPException(
            status_code=422,  # literal: Starlette renamed the constant and deprecated the old name
            detail=f"Origin and destination are the same centre ({payload.origin_centre}).",
        )

    unknown = [
        code
        for code in (payload.origin_centre, payload.dest_centre)
        if session.get(Facility, code) is None
    ]
    if unknown:
        raise HTTPException(
            status_code=422,  # literal: Starlette renamed the constant and deprecated the old name
            detail=(
                f"Unknown centre code(s): {', '.join(unknown)}. "
                "Look one up with GET /facilities?query=<city or code>."
            ),
        )

    warnings: list[str] = []
    origin = session.get(Facility, payload.origin_centre)
    if origin is not None and origin.friction_rank is not None and origin.friction_rank <= 20:
        warnings.append(
            f"Origin {origin.centre_code} is hub-friction rank {origin.friction_rank} "
            f"(median dwell {origin.median_dwell_min_out:.0f} min on departure)."
        )
    return warnings


def as_order_read(order: Order, warnings: list[str], replay: bool = False) -> OrderRead:
    return OrderRead(
        **order.model_dump(),
        corridor_id=corridor_of(order),
        warnings=warnings,
        idempotent_replay=replay,
    )


def as_shipment_read(shipment: Shipment, order_ref: str) -> ShipmentRead:
    return ShipmentRead(**shipment.model_dump(), order_ref=order_ref)


# ── Health ───────────────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthRead, tags=["meta"])
def health(session: Session = Depends(db.get_session)) -> HealthRead:
    """Unauthenticated on purpose — the Week 6 boot script waits on this before it
    starts the agents, and it should not need a key to find out the service is up."""
    seeded = session.get(Meta, "seeded_from")
    return HealthRead(
        status="ok",
        database=str(config.TMS_DB_PATH),
        facilities=session.exec(select(func.count()).select_from(Facility)).one(),
        orders=session.exec(select(func.count()).select_from(Order)).one(),
        shipments=session.exec(select(func.count()).select_from(Shipment)).one(),
        seeded_from=seeded.value if seeded else None,
    )


# ── Facilities ───────────────────────────────────────────────────────────────
@app.get("/facilities", response_model=list[FacilityRead], tags=["facilities"])
def list_facilities(
    query: str | None = Query(default=None, description="substring of code, name, city or state"),
    ranked_only: bool = Query(default=False, description="only hubs on the friction leaderboard"),
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> list[Facility]:
    """Look up centres. This is what an agent calls when a customer names a city
    instead of a centre code, which is what customers do."""
    statement = select(Facility)
    if query:
        like = f"%{query.strip()}%"
        statement = statement.where(
            func.upper(Facility.centre_code).like(like.upper())
            | Facility.name.like(like)
            | Facility.city.like(like)
            | Facility.state.like(like)
        )
    if ranked_only:
        statement = statement.where(Facility.friction_rank.is_not(None))
    return list(session.exec(statement.order_by(Facility.centre_code).limit(limit)).all())


@app.get("/facilities/{centre_code}", response_model=FacilityRead, tags=["facilities"])
def get_facility(
    centre_code: str,
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> Facility:
    facility = session.get(Facility, centre_code.strip().upper())
    if facility is None:
        raise HTTPException(status_code=404, detail=f"No facility with code {centre_code}.")
    return facility


# ── Orders ───────────────────────────────────────────────────────────────────
@app.post("/orders", response_model=OrderRead, status_code=201, tags=["orders"])
def create_order(
    payload: OrderCreate,
    response: Response,
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> OrderRead:
    """File an order.

    Returns 201 with the new order, or 200 with the existing one when `external_ref`
    has been seen before — see the module docstring on idempotency.
    """
    if payload.external_ref:
        existing = session.exec(
            select(Order).where(Order.external_ref == payload.external_ref)
        ).first()
        if existing is not None:
            log.info("idempotent replay of external_ref=%s -> %s", payload.external_ref, existing.order_ref)
            response.status_code = status.HTTP_200_OK
            return as_order_read(existing, warnings=[], replay=True)

    warnings = validate_centres(session, payload)

    order = Order(**payload.model_dump(), order_ref="pending")
    session.add(order)
    session.flush()  # assigns the id the reference is derived from
    order.order_ref = f"ORD-{order.id:06d}"
    session.commit()
    session.refresh(order)

    log.info("order %s created (%s, %s)", order.order_ref, corridor_of(order), order.source.value)
    return as_order_read(order, warnings=warnings)


@app.get("/orders", response_model=list[OrderRead], tags=["orders"])
def list_orders(
    status_filter: OrderStatus | None = Query(default=None, alias="status"),
    corridor: str | None = Query(default=None, description="SOURCE>DEST"),
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> list[OrderRead]:
    statement = select(Order)
    if status_filter:
        statement = statement.where(Order.status == status_filter)
    if corridor and ">" in corridor:
        origin, dest = (part.strip().upper() for part in corridor.split(">", 1))
        statement = statement.where(Order.origin_centre == origin, Order.dest_centre == dest)
    orders = session.exec(statement.order_by(Order.id.desc()).limit(limit)).all()
    return [as_order_read(o, warnings=[]) for o in orders]


@app.get("/orders/{order_ref}", response_model=OrderRead, tags=["orders"])
def get_order(
    order_ref: str,
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> OrderRead:
    order = session.exec(select(Order).where(Order.order_ref == order_ref)).first()
    if order is None:
        raise HTTPException(status_code=404, detail=f"No order {order_ref}.")
    return as_order_read(order, warnings=[])


@app.patch("/orders/{order_ref}", response_model=OrderRead, tags=["orders"])
def update_order_status(
    order_ref: str,
    payload: OrderStatusUpdate,
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> OrderRead:
    """Move an order through `received → confirmed`, or cancel it.

    A cancelled order is terminal: reopening one would leave a shipment attached to an
    order that was never confirmed, and no caller in the plan needs it.
    """
    order = session.exec(select(Order).where(Order.order_ref == order_ref)).first()
    if order is None:
        raise HTTPException(status_code=404, detail=f"No order {order_ref}.")
    if order.status == OrderStatus.CANCELLED and payload.status != OrderStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{order_ref} is cancelled; cancelled orders cannot be reopened.",
        )
    order.status = payload.status
    if payload.notes:
        order.notes = payload.notes
    order.updated_at = utcnow()
    session.add(order)
    session.commit()
    session.refresh(order)
    return as_order_read(order, warnings=[])


# ── Shipments ────────────────────────────────────────────────────────────────
@app.post("/shipments", response_model=ShipmentRead, status_code=201, tags=["shipments"])
def create_shipment(
    payload: ShipmentCreate,
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> ShipmentRead:
    """Book a shipment against an order.

    One shipment per order for now. Splitting an order across vehicles is real, and is
    not in any week's plan — when it arrives it changes the shipment reference scheme,
    so it should not be half-supported here in the meantime.
    """
    order = session.exec(select(Order).where(Order.order_ref == payload.order_ref)).first()
    if order is None:
        raise HTTPException(status_code=404, detail=f"No order {payload.order_ref}.")
    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{order.order_ref} is cancelled and cannot be shipped.",
        )

    existing = session.exec(select(Shipment).where(Shipment.order_id == order.id)).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{order.order_ref} already has shipment {existing.shipment_ref}.",
        )

    if (
        payload.planned_departure
        and payload.planned_arrival
        and payload.planned_arrival < payload.planned_departure
    ):
        raise HTTPException(
            status_code=422,  # literal: Starlette renamed the constant and deprecated the old name
            detail="planned_arrival is before planned_departure.",
        )

    shipment = Shipment(
        shipment_ref="pending",
        order_id=order.id,
        corridor_id=corridor_of(order),
        route_type=payload.route_type or order.route_type,
        planned_departure=payload.planned_departure,
        planned_arrival=payload.planned_arrival,
    )
    session.add(shipment)
    session.flush()
    shipment.shipment_ref = f"SHP-{shipment.id:06d}"

    # Booking a shipment confirms the order — otherwise the Week 6 lifecycle ends with
    # a shipment in transit against an order still sitting in `received`.
    if order.status == OrderStatus.RECEIVED:
        order.status = OrderStatus.CONFIRMED
        order.updated_at = utcnow()
        session.add(order)

    session.commit()
    session.refresh(shipment)
    log.info("shipment %s booked for %s on %s", shipment.shipment_ref, order.order_ref, shipment.corridor_id)
    return as_shipment_read(shipment, order.order_ref)


@app.get("/shipments", response_model=list[ShipmentRead], tags=["shipments"])
def list_shipments(
    status_filter: ShipmentStatus | None = Query(default=None, alias="status"),
    corridor: str | None = Query(default=None, description="SOURCE>DEST"),
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> list[ShipmentRead]:
    statement = select(Shipment)
    if status_filter:
        statement = statement.where(Shipment.status == status_filter)
    if corridor:
        statement = statement.where(Shipment.corridor_id == corridor.strip().upper())
    shipments = session.exec(statement.order_by(Shipment.id.desc()).limit(limit)).all()
    return [as_shipment_read(s, _order_ref(session, s.order_id)) for s in shipments]


@app.get("/shipments/{shipment_ref}", response_model=ShipmentRead, tags=["shipments"])
def get_shipment(
    shipment_ref: str,
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> ShipmentRead:
    shipment = session.exec(select(Shipment).where(Shipment.shipment_ref == shipment_ref)).first()
    if shipment is None:
        raise HTTPException(status_code=404, detail=f"No shipment {shipment_ref}.")
    return as_shipment_read(shipment, _order_ref(session, shipment.order_id))


@app.patch("/shipments/{shipment_ref}", response_model=ShipmentRead, tags=["shipments"])
def update_shipment_status(
    shipment_ref: str,
    payload: ShipmentStatusUpdate,
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> ShipmentRead:
    """Move a shipment through `created -> in_transit -> delivered`, or flag it
    `exception`. This is what the Week 5 streaming consumer and the Week 6 Exception
    Agent write to as a shipment's real-world state changes.

    `delivered` is terminal, the same way a cancelled order is (§ orders above) — a
    shipment that has arrived does not go back to `in_transit`, and nothing in the
    plan needs it to.
    """
    shipment = _get_shipment_or_404(session, shipment_ref)
    if shipment.status == ShipmentStatus.DELIVERED and payload.status != ShipmentStatus.DELIVERED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{shipment_ref} is delivered; delivered shipments are terminal.",
        )
    shipment.status = payload.status
    if payload.notes:
        shipment.notes = payload.notes
    shipment.updated_at = utcnow()
    session.add(shipment)
    session.commit()
    session.refresh(shipment)
    log.info("shipment %s -> %s", shipment.shipment_ref, shipment.status.value)
    return as_shipment_read(shipment, _order_ref(session, shipment.order_id))


# ── Exception tickets ────────────────────────────────────────────────────────
@app.post("/exceptions", response_model=ExceptionRead, status_code=201, tags=["exceptions"])
def create_exception(
    payload: ExceptionCreate,
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> ExceptionRead:
    """File an exception ticket against a shipment.

    Filing one also flags the shipment `exception` — the same reasoning as booking a
    shipment confirming its order: the Week 6 lifecycle should not end with an open
    ticket against a shipment that still reads `in_transit`.
    """
    shipment = _get_shipment_or_404(session, payload.shipment_ref)

    ticket = ExceptionTicket(
        ticket_ref="pending",
        shipment_id=shipment.id,
        severity=payload.severity,
        reason=payload.reason,
        notes=payload.notes,
    )
    session.add(ticket)
    session.flush()
    ticket.ticket_ref = f"EXC-{ticket.id:06d}"

    if shipment.status != ShipmentStatus.EXCEPTION:
        shipment.status = ShipmentStatus.EXCEPTION
        shipment.updated_at = utcnow()
        session.add(shipment)

    session.commit()
    session.refresh(ticket)
    log.info(
        "exception %s filed against %s (%s, %s)",
        ticket.ticket_ref, shipment.shipment_ref, payload.severity.value, payload.reason,
    )
    return as_exception_read(ticket, shipment)


@app.get("/exceptions", response_model=list[ExceptionRead], tags=["exceptions"])
def list_exceptions(
    status_filter: ExceptionStatus | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> list[ExceptionRead]:
    statement = select(ExceptionTicket)
    if status_filter:
        statement = statement.where(ExceptionTicket.status == status_filter)
    if severity:
        statement = statement.where(ExceptionTicket.severity == severity)
    tickets = session.exec(statement.order_by(ExceptionTicket.id.desc()).limit(limit)).all()
    return [as_exception_read(t, session.get(Shipment, t.shipment_id)) for t in tickets]


@app.get("/exceptions/{ticket_ref}", response_model=ExceptionRead, tags=["exceptions"])
def get_exception(
    ticket_ref: str,
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> ExceptionRead:
    ticket = session.exec(
        select(ExceptionTicket).where(ExceptionTicket.ticket_ref == ticket_ref)
    ).first()
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"No exception ticket {ticket_ref}.")
    return as_exception_read(ticket, session.get(Shipment, ticket.shipment_id))


@app.patch("/exceptions/{ticket_ref}", response_model=ExceptionRead, tags=["exceptions"])
def update_exception_status(
    ticket_ref: str,
    payload: ExceptionStatusUpdate,
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> ExceptionRead:
    """`open -> acknowledged -> resolved`. `resolved_at` is stamped here rather than
    left to the caller, so it always reflects when the API recorded the close, not
    whatever timestamp a client happened to send."""
    ticket = session.exec(
        select(ExceptionTicket).where(ExceptionTicket.ticket_ref == ticket_ref)
    ).first()
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"No exception ticket {ticket_ref}.")
    ticket.status = payload.status
    if payload.notes:
        ticket.notes = payload.notes
    if payload.status == ExceptionStatus.RESOLVED:
        ticket.resolved_at = utcnow()
    ticket.updated_at = utcnow()
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return as_exception_read(ticket, session.get(Shipment, ticket.shipment_id))


# ── Invoices ─────────────────────────────────────────────────────────────────
@app.post("/invoices", response_model=InvoiceRead, status_code=201, tags=["invoices"])
def create_invoice(
    payload: InvoiceCreate,
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> InvoiceRead:
    """Submit a freight invoice against a shipment.

    Charges are stored exactly as submitted, `total_amount` included — this endpoint
    does not check `freight_charge + other_charges == total_amount` on the way in.
    Whether they agree is what the Week 6 Invoice Auditor checks; an API that silently
    corrected the arithmetic would make D-021's `total_mismatch` seeded error
    unevaluable.
    """
    shipment = _get_shipment_or_404(session, payload.shipment_ref)

    invoice = Invoice(
        invoice_ref="pending",
        shipment_id=shipment.id,
        external_invoice_number=payload.external_invoice_number,
        freight_charge=payload.freight_charge,
        other_charges=payload.other_charges,
        total_amount=payload.total_amount,
        currency=payload.currency,
    )
    session.add(invoice)
    session.flush()
    invoice.invoice_ref = f"INV-{invoice.id:06d}"
    session.commit()
    session.refresh(invoice)
    log.info(
        "invoice %s submitted for %s (%s %.2f)",
        invoice.invoice_ref, shipment.shipment_ref, invoice.currency, invoice.total_amount,
    )
    return as_invoice_read(invoice, shipment)


@app.get("/invoices", response_model=list[InvoiceRead], tags=["invoices"])
def list_invoices(
    status_filter: InvoiceStatus | None = Query(default=None, alias="status"),
    corridor: str | None = Query(default=None, description="SOURCE>DEST"),
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> list[InvoiceRead]:
    statement = select(Invoice)
    if status_filter:
        statement = statement.where(Invoice.status == status_filter)
    invoices = session.exec(statement.order_by(Invoice.id.desc()).limit(limit)).all()
    out = []
    for inv in invoices:
        shipment = session.get(Shipment, inv.shipment_id)
        if corridor and (shipment is None or shipment.corridor_id != corridor.strip().upper()):
            continue
        out.append(as_invoice_read(inv, shipment))
    return out


@app.get("/invoices/{invoice_ref}", response_model=InvoiceRead, tags=["invoices"])
def get_invoice(
    invoice_ref: str,
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> InvoiceRead:
    invoice = session.exec(select(Invoice).where(Invoice.invoice_ref == invoice_ref)).first()
    if invoice is None:
        raise HTTPException(status_code=404, detail=f"No invoice {invoice_ref}.")
    return as_invoice_read(invoice, session.get(Shipment, invoice.shipment_id))


@app.patch("/invoices/{invoice_ref}", response_model=InvoiceRead, tags=["invoices"])
def update_invoice_status(
    invoice_ref: str,
    payload: InvoiceStatusUpdate,
    session: Session = Depends(db.get_session),
    _: None = Depends(require_api_key),
) -> InvoiceRead:
    """`submitted -> approved` or `submitted -> disputed`. The Week 6 Invoice Auditor
    is the intended caller; `dispute_reason` is required on a dispute (enforced on the
    payload itself) so a disputed invoice always says why."""
    invoice = session.exec(select(Invoice).where(Invoice.invoice_ref == invoice_ref)).first()
    if invoice is None:
        raise HTTPException(status_code=404, detail=f"No invoice {invoice_ref}.")
    invoice.status = payload.status
    invoice.dispute_reason = payload.dispute_reason
    invoice.updated_at = utcnow()
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    return as_invoice_read(invoice, session.get(Shipment, invoice.shipment_id))


def _order_ref(session: Session, order_id: int) -> str:
    order = session.get(Order, order_id)
    return order.order_ref if order else ""


def _get_shipment_or_404(session: Session, shipment_ref: str) -> Shipment:
    shipment = session.exec(select(Shipment).where(Shipment.shipment_ref == shipment_ref)).first()
    if shipment is None:
        raise HTTPException(status_code=404, detail=f"No shipment {shipment_ref}.")
    return shipment


def as_exception_read(ticket: ExceptionTicket, shipment: Shipment | None) -> ExceptionRead:
    return ExceptionRead(
        **ticket.model_dump(),
        shipment_ref=shipment.shipment_ref if shipment else "",
        corridor_id=shipment.corridor_id if shipment else "",
    )


def as_invoice_read(invoice: Invoice, shipment: Shipment | None) -> InvoiceRead:
    return InvoiceRead(
        **invoice.model_dump(),
        shipment_ref=shipment.shipment_ref if shipment else "",
        corridor_id=shipment.corridor_id if shipment else "",
    )
