"""Seed the TMS facility table from the real Delhivery network.

    python -m src.tms.seed              # load facilities from the best source available
    python -m src.tms.seed --reset      # drop the orders and shipments too

The facilities in the mock TMS are the actual centre codes the network ran through.
That is what makes the Week 5 and 6 agent work meaningful rather than a puppet show:
an order the Order Entry Agent files names a centre that appears in the corridor
audit, so the Invoice Auditor can later ask what that corridor should have cost.

**No Spark here on purpose.** The TMS has to boot on a machine with no JVM — Krishna
runs the agents and the dashboard, not the pipeline. The Parquet is read with pyarrow
through pandas, which is a dependency the dashboard already has.

Source preference
-----------------
1. ``data/processed/hubs_v1`` — all 1,657 centres, produced by `src.pipeline.hubs`.
   Not in git (the whole `data/` tree is ignored), so only present after a pipeline run.
2. ``benchmarks/raw/w2_hub_dwell.csv`` — the 121 ranked hubs. This one *is* committed,
   so a fresh clone gets a working TMS without building the caches first.
3. Nothing. The API still boots and answers `/health`; every order is rejected for an
   unknown centre code, which is the honest behaviour — better than inventing
   facilities that do not exist.
"""

from __future__ import annotations

import argparse

import pandas as pd
from sqlmodel import Session, delete, select

from src.common import config
from src.common.logging_setup import get_logger
from src.tms import db
from src.tms.models import Facility, Meta, Order, Shipment

log = get_logger("tms.seed")

LEADERBOARD_CSV = config.BENCHMARKS_RAW_DIR / "w2_hub_dwell.csv"

#: hub-table column -> Facility field. The leaderboard CSV carries the same names,
#: so one mapping covers both sources.
COLUMN_MAP = {
    "centre_code": "centre_code",
    "centre_name": "name",
    "city": "city",
    "state": "state",
    "friction_rank": "friction_rank",
    "median_dwell_min_out": "median_dwell_min_out",
    "n_legs_out": "n_legs_out",
}


def load_facility_frame() -> tuple[pd.DataFrame, str]:
    """Return the facility reference data and a label naming where it came from."""
    if config.HUBS_V1.exists():
        # pyarrow skips files whose names start with `_`, so the `_hub_report.json`
        # and `_SUCCESS` markers Spark leaves in the directory are not read as data.
        return pd.read_parquet(config.HUBS_V1, columns=list(COLUMN_MAP)), "hubs_v1"
    if LEADERBOARD_CSV.exists():
        return pd.read_csv(LEADERBOARD_CSV, usecols=list(COLUMN_MAP)), "w2_hub_dwell.csv"
    return pd.DataFrame(columns=list(COLUMN_MAP)), "none"


def to_facilities(frame: pd.DataFrame) -> list[Facility]:
    """Convert the frame to rows, keeping SQLite's types honest.

    pandas hands back `numpy.int64` and `NaN`; SQLite accepts the first as a blob-ish
    surprise and stores the second as the float nan, which then serialises to invalid
    JSON. Both are converted here rather than being discovered in a response body.
    """
    rows: list[Facility] = []
    for record in frame.rename(columns=COLUMN_MAP).to_dict("records"):
        clean = {k: (None if pd.isna(v) else v) for k, v in record.items()}
        rows.append(
            Facility(
                centre_code=str(clean["centre_code"]),
                name=clean["name"],
                city=clean["city"],
                state=clean["state"],
                friction_rank=int(clean["friction_rank"]) if clean["friction_rank"] is not None else None,
                median_dwell_min_out=(
                    float(clean["median_dwell_min_out"])
                    if clean["median_dwell_min_out"] is not None
                    else None
                ),
                n_legs_out=int(clean["n_legs_out"] or 0),
            )
        )
    return rows


def seed(session: Session, reset: bool = False) -> dict:
    """Replace the facility reference data. Orders and shipments survive unless
    ``reset`` — re-seeding after a pipeline re-run should not throw away the orders
    an agent filed."""
    if reset:
        session.exec(delete(Shipment))
        session.exec(delete(Order))
        log.warning("reset: orders and shipments deleted")

    frame, source = load_facility_frame()
    facilities = to_facilities(frame)

    session.exec(delete(Facility))
    for facility in facilities:
        session.add(facility)

    existing = session.get(Meta, "seeded_from")
    if existing:
        existing.value = source
    else:
        session.add(Meta(key="seeded_from", value=source))
    session.commit()

    ranked = sum(1 for f in facilities if f.friction_rank is not None)
    log.info("seeded %s facilities from %s (%s ranked for friction)", len(facilities), source, ranked)
    if source == "none":
        log.warning(
            "No facility source found. The API will boot but reject every order as an "
            "unknown centre code. Run `python -m src.pipeline.hubs` first."
        )
    return {"facilities": len(facilities), "source": source, "ranked": ranked}


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the mock TMS facility table")
    parser.add_argument(
        "--reset", action="store_true", help="also delete existing orders and shipments"
    )
    args = parser.parse_args()

    db.init_db()
    with Session(db.get_engine()) as session:
        result = seed(session, reset=args.reset)
        orders = len(session.exec(select(Order)).all())
    log.info("Done. %s facilities, %s orders in the database.", result["facilities"], orders)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
