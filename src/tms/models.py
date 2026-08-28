"""Tables and payloads for the mock TMS.

The TMS is **synthetic scaffolding**, declared as such in the README: it exists so the
agents have a real API to integrate with rather than a stub that always says yes. The
*facilities* in it are not synthetic — they are seeded from the 1,657 centre codes the
Delhivery network actually ran through (`src/tms/seed.py`), so an order the Order Entry
Agent files in Week 5 references a centre that exists in the corridor audit and can be
priced against it in Week 6.

Model notes
-----------
* Both tables carry a human-readable business reference (`ORD-000001`, `SHP-000001`)
  beside the integer primary key. The agents quote references in emails and tickets,
  and a raw row id in a customer notification reads as a bug.
* `Order.external_ref` is the **idempotency key**. The Order Entry Agent reads an
  inbox; retries and redeliveries are normal, and a duplicate POST must not create a
  second order. It is unique, and the API returns the existing order instead of
  creating another.
* `Order.source` records who filed it — `api`, `agent`, or `seed`. Week 5 evaluation
  measures how many orders the agent placed and how many it got right, which is not
  answerable if agent traffic is indistinguishable from a curl.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, field_validator, model_validator
from pydantic import Field as PydanticField
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Timezone-aware UTC. SQLite has no native tz type, so timestamps are stored
    naive-UTC and rendered with an explicit `Z` by the response models."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RouteType(str, Enum):
    """Matches the `route_type` partition of the cached Parquet — same two values."""

    FTL = "FTL"
    CARTING = "Carting"


class OrderStatus(str, Enum):
    RECEIVED = "received"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class ShipmentStatus(str, Enum):
    CREATED = "created"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    EXCEPTION = "exception"


class OrderSource(str, Enum):
    API = "api"
    AGENT = "agent"
    SEED = "seed"


class ExceptionSeverity(str, Enum):
    """How urgently a flagged shipment needs a human, or the Week 6 agent, to look at
    it. Not derived from anything yet — Week 6's Tracking & Exception Agent is what
    classifies severity from the streaming prediction; here it is just a field a
    ticket carries."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExceptionStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class InvoiceStatus(str, Enum):
    """Freight-invoice lifecycle. `disputed`/`approved` are what Week 6's Invoice
    Auditor sets after cross-checking against the corridor audit — the field exists
    now so the agent has something to write to."""

    SUBMITTED = "submitted"
    APPROVED = "approved"
    DISPUTED = "disputed"


# ── Tables ───────────────────────────────────────────────────────────────────
class Meta(SQLModel, table=True):
    """Key/value notes about the database itself.

    Holds `seeded_from` so `/health` can say *which* artefact the facility list came
    from. It matters: the full seed is 1,657 centres from the uncommitted Parquet
    cache, while the fallback is the 121-hub CSV that is in git. An agent that cannot
    find a centre code needs to know which of those it is talking to.
    """

    key: str = Field(primary_key=True)
    value: str


class Facility(SQLModel, table=True):
    """A Delhivery centre code, seeded from `hubs_v1`. Reference data, not written by
    the API — an order naming a code that is not here is rejected."""

    centre_code: str = Field(primary_key=True)
    name: str | None = None
    city: str | None = None
    state: str | None = None
    #: Carried over from the Week 2 hub table so an agent can see, at order time, that
    #: it is dispatching out of a facility known to be slow. Null when the hub has too
    #: few legs to rank (D-015).
    friction_rank: int | None = Field(default=None, index=True)
    median_dwell_min_out: float | None = None
    n_legs_out: int = 0


class Order(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    order_ref: str = Field(index=True, unique=True)
    external_ref: str | None = Field(default=None, index=True, unique=True)

    customer_name: str
    customer_email: str | None = None

    origin_centre: str = Field(foreign_key="facility.centre_code", index=True)
    dest_centre: str = Field(foreign_key="facility.centre_code", index=True)
    route_type: RouteType

    pieces: int
    weight_kg: float
    requested_pickup: datetime | None = None

    status: OrderStatus = Field(default=OrderStatus.RECEIVED, index=True)
    source: OrderSource = Field(default=OrderSource.API, index=True)
    notes: str | None = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Shipment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    shipment_ref: str = Field(index=True, unique=True)
    order_id: int = Field(foreign_key="order.id", index=True)

    #: `SOURCE>DEST`, the same key the corridor audit aggregates on — this is the join
    #: that lets the Week 6 Invoice Auditor ask what a leg *should* have cost.
    corridor_id: str = Field(index=True)
    route_type: RouteType

    status: ShipmentStatus = Field(default=ShipmentStatus.CREATED, index=True)
    planned_departure: datetime | None = None
    planned_arrival: datetime | None = None
    #: Set on a status transition — why it moved to `exception`, why it was marked
    #: `delivered` late, and so on. Free text, same role `Order.notes` plays.
    notes: str | None = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ExceptionTicket(SQLModel, table=True):
    """Filed against a shipment that needs attention. Week 6's Tracking & Exception
    Agent files these automatically off the streaming prediction; Week 3 gives it the
    table and the manual-filing endpoint to write to in the meantime."""

    id: int | None = Field(default=None, primary_key=True)
    ticket_ref: str = Field(index=True, unique=True)
    shipment_id: int = Field(foreign_key="shipment.id", index=True)

    severity: ExceptionSeverity = Field(index=True)
    reason: str
    status: ExceptionStatus = Field(default=ExceptionStatus.OPEN, index=True)
    notes: str | None = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None


class Invoice(SQLModel, table=True):
    """A freight invoice submitted against a shipment. Week 6's Invoice Auditor
    cross-checks `freight_charge`/`total_amount` against the corridor audit and sets
    `status`; Week 3 gives it somewhere to land and a place to record the dispute."""

    id: int | None = Field(default=None, primary_key=True)
    invoice_ref: str = Field(index=True, unique=True)
    shipment_id: int = Field(foreign_key="shipment.id", index=True)
    #: The number printed on the (synthetic) invoice document itself — distinct from
    #: `invoice_ref`, which is this system's own reference. Not unique: the doc
    #: corpus's `duplicate_document_number` seeded error (D-020) exists precisely so
    #: the same external number can legitimately arrive twice.
    external_invoice_number: str | None = Field(default=None, index=True)

    freight_charge: float
    other_charges: float = 0.0
    total_amount: float
    currency: str = "INR"

    status: InvoiceStatus = Field(default=InvoiceStatus.SUBMITTED, index=True)
    dispute_reason: str | None = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ── Request payloads ─────────────────────────────────────────────────────────
class OrderCreate(BaseModel):
    """What a client (or the Order Entry Agent) posts to `/orders`.

    Deliberately strict on the numbers and permissive on the free text: an agent
    parsing an email gets the customer's name wrong in harmless ways, but a negative
    weight or zero pieces is a parse failure that should come back as a 422 it can act
    on rather than a row in the database.
    """

    customer_name: str = PydanticField(min_length=1, max_length=200)
    customer_email: str | None = None
    origin_centre: str = PydanticField(min_length=1)
    dest_centre: str = PydanticField(min_length=1)
    route_type: RouteType
    pieces: int = PydanticField(ge=1)
    weight_kg: float = PydanticField(gt=0)
    requested_pickup: datetime | None = None
    external_ref: str | None = None
    source: OrderSource = OrderSource.API
    notes: str | None = None

    @field_validator("origin_centre", "dest_centre")
    @classmethod
    def normalise_centre(cls, v: str) -> str:
        """Upper-case and trim, exactly as Stage 1 does to the centre codes.

        Without this an agent that lifts `ind282002aad` off a scanned document files an
        order that fails the facility lookup for a reason no human would call real.
        """
        return v.strip().upper()


class ShipmentCreate(BaseModel):
    order_ref: str
    planned_departure: datetime | None = None
    planned_arrival: datetime | None = None
    #: Defaults to the order's route type; overridable because a planner may downgrade
    #: an FTL booking to Carting.
    route_type: RouteType | None = None


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    notes: str | None = None


class ShipmentStatusUpdate(BaseModel):
    status: ShipmentStatus
    notes: str | None = None


class ExceptionCreate(BaseModel):
    shipment_ref: str
    severity: ExceptionSeverity
    reason: str = PydanticField(min_length=1)
    notes: str | None = None


class ExceptionStatusUpdate(BaseModel):
    status: ExceptionStatus
    notes: str | None = None


class InvoiceCreate(BaseModel):
    """What the Week 6 Invoice Auditor (or, for now, a curl against the corpus)
    submits. Charges are handed over exactly as printed — `total_amount` is *not*
    recomputed from `freight_charge + other_charges` here, because whether the two
    agree is precisely what the auditor is for (D-020's `total_mismatch` seeded
    error exists to be caught downstream, not silently fixed on the way in)."""

    shipment_ref: str
    external_invoice_number: str | None = None
    freight_charge: float = PydanticField(ge=0)
    other_charges: float = PydanticField(default=0.0, ge=0)
    total_amount: float = PydanticField(gt=0)
    currency: str = "INR"


class InvoiceStatusUpdate(BaseModel):
    status: InvoiceStatus
    dispute_reason: str | None = None

    @model_validator(mode="after")
    def require_reason_when_disputed(self) -> InvoiceStatusUpdate:
        # A `field_validator` on `dispute_reason` alone would not fire here: pydantic
        # skips per-field validation on a field left at its default, and an omitted
        # `dispute_reason` *is* the default. The check depends on `status` too, so it
        # belongs on the whole model regardless.
        if self.status == InvoiceStatus.DISPUTED and not self.dispute_reason:
            raise ValueError("dispute_reason is required when status is 'disputed'.")
        return self


# ── Response payloads ────────────────────────────────────────────────────────
class OrderRead(BaseModel):
    """An order plus the advisory warnings raised when it was filed.

    `warnings` is not an error channel. An order into a corridor the network has never
    run is perfectly legal — it just cannot be checked against corridor history, and
    the Week 6 Invoice Auditor needs to know that before it disputes an invoice for
    being off a benchmark that does not exist.
    """

    model_config = {"from_attributes": True}

    id: int
    order_ref: str
    external_ref: str | None
    customer_name: str
    customer_email: str | None
    origin_centre: str
    dest_centre: str
    corridor_id: str
    route_type: RouteType
    pieces: int
    weight_kg: float
    requested_pickup: datetime | None
    status: OrderStatus
    source: OrderSource
    notes: str | None
    created_at: datetime
    updated_at: datetime
    warnings: list[str] = []
    idempotent_replay: bool = False


class ShipmentRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    shipment_ref: str
    order_id: int
    order_ref: str
    corridor_id: str
    route_type: RouteType
    status: ShipmentStatus
    planned_departure: datetime | None
    planned_arrival: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ExceptionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    ticket_ref: str
    shipment_id: int
    shipment_ref: str
    corridor_id: str
    severity: ExceptionSeverity
    reason: str
    status: ExceptionStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class InvoiceRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    invoice_ref: str
    shipment_id: int
    shipment_ref: str
    corridor_id: str
    external_invoice_number: str | None
    freight_charge: float
    other_charges: float
    total_amount: float
    currency: str
    status: InvoiceStatus
    dispute_reason: str | None
    created_at: datetime
    updated_at: datetime


class FacilityRead(BaseModel):
    model_config = {"from_attributes": True}

    centre_code: str
    name: str | None
    city: str | None
    state: str | None
    friction_rank: int | None
    median_dwell_min_out: float | None
    n_legs_out: int


class HealthRead(BaseModel):
    status: str
    database: str
    facilities: int
    orders: int
    shipments: int
    seeded_from: str | None
