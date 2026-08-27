"""Synthetic consignment records, derived from real audited corridors.

W2's template research (docs/W2_krishna_india_map.md §4) found that most of a BOL and
invoice's fields already exist in project data, and that the two documents have to be
generated **together from one consignment** — an auditor's real job is cross-document
consistency, which a template set built independently per document makes impossible to
evaluate. `ConsignmentRecord` is that one shared source of truth: `templates.py` and
`noise.py` both render from it, and `labels.py` reads the same object back out, so a
label can never drift from what was actually printed (the failure mode P-22 recorded
for a different generator).

What is real and what is scaffolding
-------------------------------------
Corridor, centre code, facility name, distance and the FTL/Carting split all come from
`benchmarks/raw/w2_corridor_audit.csv` — the same 1,130 audited corridors the India map
and hub leaderboard read. Customer names, GSTINs, vehicle numbers and amounts do not
exist anywhere in the Delhivery data and are synthesised, exactly as W2 §4 flagged they
would have to be. They are declared as such wherever they appear (D-017 uses the same
word for the mock TMS).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from src.common import config

CORRIDOR_AUDIT_CSV = config.BENCHMARKS_RAW_DIR / "w2_corridor_audit.csv"

# ── Public reference data ─────────────────────────────────────────────────────
# CBIC's GST state codes and the RTO vehicle-registration state letters are both
# standard published tables (the same kind of public reference GeoNames is for
# D-019's coordinates) — not sourced from any teammate's data. Covers the 27
# states/UTs actually present in w2_corridor_audit.csv; a corridor whose state is not
# in this table gets state_code "00" / plate letters "XX" rather than a guess, so a
# gap is visible instead of a silently wrong-looking GSTIN (same instinct as D-019's
# "report what neither route places").
STATE_GST_CODE = {
    "Andhra Pradesh": "37", "Arunachal Pradesh": "12", "Assam": "18", "Bihar": "10",
    "Chandigarh": "04", "Chhattisgarh": "22", "Dadra and Nagar Haveli": "26",
    "Delhi": "07", "Goa": "30", "Gujarat": "24", "Haryana": "06",
    "Himachal Pradesh": "02", "Jharkhand": "20", "Karnataka": "29", "Kerala": "32",
    "Madhya Pradesh": "23", "Maharashtra": "27", "Meghalaya": "17", "Orissa": "21",
    "Pondicherry": "34", "Punjab": "03", "Rajasthan": "08", "Tamil Nadu": "33",
    "Telangana": "36", "Uttar Pradesh": "09", "Uttarakhand": "05", "West Bengal": "19",
}
STATE_RTO_LETTERS = {
    "Andhra Pradesh": "AP", "Arunachal Pradesh": "AR", "Assam": "AS", "Bihar": "BR",
    "Chandigarh": "CH", "Chhattisgarh": "CG", "Dadra and Nagar Haveli": "DN",
    "Delhi": "DL", "Goa": "GA", "Gujarat": "GJ", "Haryana": "HR",
    "Himachal Pradesh": "HP", "Jharkhand": "JH", "Karnataka": "KA", "Kerala": "KL",
    "Madhya Pradesh": "MP", "Maharashtra": "MH", "Meghalaya": "ML", "Orissa": "OD",
    "Pondicherry": "PY", "Punjab": "PB", "Rajasthan": "RJ", "Tamil Nadu": "TN",
    "Telangana": "TS", "Uttar Pradesh": "UP", "Uttarakhand": "UK", "West Bengal": "WB",
}

_SHIPPER_FORMS = ["Traders", "Logistics Pvt Ltd", "Enterprises", "Freight Carriers",
                  "Distributors", "Industries", "Exports"]
_CONSIGNEE_FORMS = ["Trading Co", "Retail Pvt Ltd", "Warehousing", "Stores",
                    "Distribution Hub", "Mart", "Agencies"]


def _company_name(city: str | None, forms: list[str], rng: random.Random) -> str:
    """A plausible Indian business name from a real city, never a real company."""
    base = (city or "National").strip().title() or "National"
    return f"{base} {rng.choice(forms)}"


def _city_of(facility_name: str) -> str | None:
    """Fallback city extraction when the audit's own city column is null.

    Mirrors the dashboard's `city_of()` (P-21): facility names split the city from the
    state either on `_` or on the space before `(State)`.
    """
    if not facility_name:
        return None
    head = facility_name.split("(")[0]
    return head.replace("_", " ").split()[0].strip() if head.strip() else None


def _vehicle_number(state: str | None, rng: random.Random) -> str:
    letters = STATE_RTO_LETTERS.get(state or "", "XX")
    return f"{letters}{rng.randint(1, 60):02d}{rng.choice('ABCDEFGHJKLMNPQRSTUVWXYZ')}{rng.choice('ABCDEFGHJKLMNPQRSTUVWXYZ')}{rng.randint(1000, 9999)}"


def _gstin(state: str | None, rng: random.Random) -> str:
    """Shape-only synthetic GSTIN: right length and character classes, **not** a
    checksum-valid number. D-020 declares this scaffolding rather than validated —
    see docs/decisions.md.
    """
    code = STATE_GST_CODE.get(state or "", "00")
    pan = "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(5))
    pan += "".join(rng.choice("0123456789") for _ in range(4))
    pan += rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    entity = rng.choice("123456789")
    checksum = rng.choice("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    return f"{code}{pan}{entity}Z{checksum}"


@dataclass
class ConsignmentRecord:
    """One consignment, and everything both the BOL and the invoice print about it.

    A single instance backs both documents so they can never disagree unless
    `seed_errors.py` deliberately makes them (D-020).
    """

    seq: int
    corridor_id: str
    source_center: str
    dest_center: str
    source_name: str
    dest_name: str
    source_city: str
    dest_city: str
    source_state: str
    dest_state: str
    route_type: str  # "FTL" | "Carting"
    mean_osrm_km: float
    mean_osrm_time_min: float
    document_date: str  # ISO YYYY-MM-DD

    shipper_name: str
    consignee_name: str
    shipper_gstin: str
    consignee_gstin: str
    vehicle_number: str

    pieces: int
    weight_kg: float
    freight_charge: float
    other_charges: float
    total_amount: float
    currency: str = "INR"

    bol_number: str = ""
    invoice_number: str = ""

    # Populated by seed_errors.py; empty for a clean record.
    seeded_error_types: list[str] = field(default_factory=list)

    @property
    def shipment_ref(self) -> str:
        return f"SHP-{self.seq:06d}"


def _load_corridor_pool() -> pd.DataFrame:
    """The audited corridors (D-018's 1,130) — same source as the India map (D-009:
    read the cached CSV, never Spark)."""
    if not CORRIDOR_AUDIT_CSV.exists():
        raise FileNotFoundError(
            f"{CORRIDOR_AUDIT_CSV} not found — run Lahari's Week 2 audit first, or "
            "pull it from git (it is a tracked benchmarks/raw/*.csv)."
        )
    cols = [
        "corridor_id", "source_center", "destination_center", "source_name",
        "destination_name", "source_city", "dest_city", "source_state", "dest_state",
        "mean_osrm_km", "mean_osrm_time", "ftl_share",
    ]
    return pd.read_csv(CORRIDOR_AUDIT_CSV, usecols=cols)


# A fixed 90-day window ending the day the raw dataset's observation period ends
# (2018-10-08, per docs/results.md) — documents read as belonging to the network they
# are drawn from rather than to today.
_DOC_DATE_END = date(2018, 10, 8)
_DOC_DATE_START = _DOC_DATE_END - timedelta(days=89)


def generate_records(count: int, seed: int) -> list[ConsignmentRecord]:
    """`count` synthetic consignments sampled from real audited corridors.

    Deterministic in `seed`: the same seed reproduces the same corpus byte-for-byte,
    the same discipline `contracts.py` applies to the Spark caches (D-016).
    """
    pool = _load_corridor_pool()
    rng = random.Random(seed)
    n_pool = len(pool)
    # Sample with replacement once the corpus asks for more documents than there are
    # audited corridors — 1,130 covers any corpus size Gate 3 asks for (100+), but the
    # fallback keeps this from raising if MIN_CORRIDOR_SUPPORT ever tightens.
    replace = count > n_pool
    rows = pool.sample(n=count, replace=replace, random_state=seed).reset_index(drop=True)

    records: list[ConsignmentRecord] = []
    for i, row in rows.iterrows():
        seq = i + 1
        source_city = row["source_city"] if pd.notna(row["source_city"]) else _city_of(row["source_name"])
        dest_city = row["dest_city"] if pd.notna(row["dest_city"]) else _city_of(row["destination_name"])
        source_state = row["source_state"] if pd.notna(row["source_state"]) else ""
        dest_state = row["dest_state"] if pd.notna(row["dest_state"]) else ""

        route_type = "FTL" if rng.random() < float(row["ftl_share"]) else "Carting"
        if route_type == "FTL":
            pieces = rng.randint(1, 6)
            weight_kg = round(rng.uniform(1000, 9000), 1)
            rate_per_km = rng.uniform(28, 45)
            freight_charge = round(float(row["mean_osrm_km"]) * rate_per_km, 2)
        else:
            pieces = rng.randint(1, 20)
            weight_kg = round(rng.uniform(5, 500), 1)
            freight_charge = round(
                float(row["mean_osrm_km"]) * (weight_kg / 1000) * rng.uniform(6, 10)
                + weight_kg * rng.uniform(2, 4),
                2,
            )
        other_charges = round(freight_charge * rng.uniform(0.05, 0.18), 2)
        total_amount = round(freight_charge + other_charges, 2)

        offset_days = rng.randint(0, (_DOC_DATE_END - _DOC_DATE_START).days)
        document_date = (_DOC_DATE_START + timedelta(days=offset_days)).isoformat()

        rec = ConsignmentRecord(
            seq=seq,
            corridor_id=row["corridor_id"],
            source_center=row["source_center"],
            dest_center=row["destination_center"],
            source_name=row["source_name"],
            dest_name=row["destination_name"],
            source_city=source_city or "",
            dest_city=dest_city or "",
            source_state=source_state,
            dest_state=dest_state,
            route_type=route_type,
            mean_osrm_km=round(float(row["mean_osrm_km"]), 1),
            mean_osrm_time_min=round(float(row["mean_osrm_time"]), 1),
            document_date=document_date,
            shipper_name=_company_name(source_city, _SHIPPER_FORMS, rng),
            consignee_name=_company_name(dest_city, _CONSIGNEE_FORMS, rng),
            shipper_gstin=_gstin(source_state, rng),
            consignee_gstin=_gstin(dest_state, rng),
            vehicle_number=_vehicle_number(source_state, rng),
            pieces=pieces,
            weight_kg=weight_kg,
            freight_charge=freight_charge,
            other_charges=other_charges,
            total_amount=total_amount,
            bol_number=f"LR{seq:07d}",
            invoice_number=f"INV{seq:07d}",
        )
        records.append(rec)
    return records
