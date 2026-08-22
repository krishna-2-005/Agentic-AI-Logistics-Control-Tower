"""Build the centre-code → coordinate table the India map places its dots with.

    python -m src.dashboard.build_centre_coords

Writes `src/dashboard/reference/centre_coords.csv`, one row per centre code, and is
**not** run by the dashboard — the CSV is committed and the map reads only that
(D-009). This is a tooling script: it needs the network once, and `pgeocode` is
installed for that run rather than pinned as a runtime dependency.

Why this exists
---------------
The map used to place a corridor by parsing a city out of its facility name and looking
that name up in a hand-maintained table. That worked while the audited set was 99
metro corridors. D-018 widened it to 1,130, reaching into 139 towns the table had never
heard of, and the map fell to placing **101 of 273 bottlenecks** — silently, because an
unplaceable corridor is a dot that never appears (P-21, and now P-24).

A hand-maintained city list cannot follow the audit anywhere it goes. A centre code
can: `IND282002AAD` carries PIN 282002, and D-011 already leans on exactly that shape
to recover a facility's state. So placement moves onto the code — the same reasoning
D-002 gives for keying corridors on centre codes rather than names. **Names are for
reading, codes are for geometry.**

The hand table stays as the fallback for the codes whose PIN is `000000` or is absent
from the postal data, and the map reports whatever is left over rather than dropping it
quietly.

Source and licence
------------------
Coordinates come from the **GeoNames** postal-code dataset for India, via `pgeocode`.
GeoNames is licensed **CC BY 4.0** and is attributed here, in the generated CSV's
provenance column, and in `data/README.md`. This is third-party data about Indian
postal codes; no shipment data leaves the machine.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("dashboard.coords")

REFERENCE_DIR = Path(__file__).parent / "reference"
OUT_CSV = REFERENCE_DIR / "centre_coords.csv"

#: `IND` + six-digit PIN + three characters (D-011). Asserted rather than assumed:
#: `IND68004AAA` is in the data with **five** digits, so a code that does not match is
#: reported, not silently skipped.
CENTRE_CODE = re.compile(r"^IND(\d{6})[A-Z0-9]{3}$")

#: PIN 000000 is a placeholder the publisher uses for a number of real facilities —
#: `IND000000ACB` is a working Gurgaon centre. There is nothing to look up, so these
#: fall through to the city-name table.
NULL_PIN = "000000"


def centre_codes(hubs_path: Path) -> pd.DataFrame:
    """Every centre code and facility name, from the Stage 3 hub cache."""
    hubs = pd.read_parquet(hubs_path, columns=["centre_code", "centre_name", "city", "state"])
    return hubs.drop_duplicates("centre_code").reset_index(drop=True)


def resolve(codes: pd.DataFrame) -> pd.DataFrame:
    """Attach lat/lon to each centre code from the PIN embedded in it."""
    import pgeocode  # imported here so the dashboard never pulls it in

    parsed = codes["centre_code"].str.extract(CENTRE_CODE, expand=False)
    malformed = codes.loc[parsed.isna(), "centre_code"].tolist()
    if malformed:
        log.warning(
            "%s centre code(s) do not match IND + 6-digit PIN + 3 chars: %s",
            len(malformed),
            ", ".join(malformed[:8]),
        )

    lookup = parsed[parsed.notna() & (parsed != NULL_PIN)].unique().tolist()
    nomi = pgeocode.Nominatim("IN")
    found = nomi.query_postal_code(lookup)
    coords = {
        r.postal_code: (r.latitude, r.longitude, r.place_name, r.state_name)
        for r in found.itertuples()
        if pd.notna(r.latitude)
    }
    log.info("%s of %s distinct PINs resolved against GeoNames", len(coords), len(lookup))

    out = codes.copy()
    out["pin"] = parsed
    out["lat"] = [coords.get(p, (None,) * 4)[0] for p in parsed]
    out["lon"] = [coords.get(p, (None,) * 4)[1] for p in parsed]
    out["pin_place"] = [coords.get(p, (None,) * 4)[2] for p in parsed]
    out["pin_state"] = [coords.get(p, (None,) * 4)[3] for p in parsed]
    out["source"] = "geonames-pin"
    out.loc[out["lat"].isna(), "source"] = None
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the centre-code coordinate table")
    parser.add_argument("--hubs", type=Path, default=config.HUBS_V1)
    parser.add_argument("--out", type=Path, default=OUT_CSV)
    args = parser.parse_args()

    if not args.hubs.exists():
        log.error("Missing %s — run `python -m src.pipeline.hubs` first.", args.hubs)
        return 1

    codes = centre_codes(args.hubs)
    log.info("%s distinct centre codes in %s", f"{len(codes):,}", args.hubs.name)

    resolved = resolve(codes)
    placed = int(resolved["lat"].notna().sum())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    resolved.to_csv(args.out, index=False)

    log.info(
        "%s of %s centres placed (%.1f%%) -> %s",
        f"{placed:,}",
        f"{len(resolved):,}",
        placed / len(resolved) * 100,
        args.out,
    )
    unplaced = resolved[resolved["lat"].isna()]
    if len(unplaced):
        log.info(
            "%s unplaced, falling back to india_city_coords.csv by facility name: %s",
            len(unplaced),
            ", ".join(unplaced["centre_code"].head(8)),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
