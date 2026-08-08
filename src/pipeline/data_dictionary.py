"""Generate the column-by-column data dictionary for the raw Delhivery dataset.

    python -m src.pipeline.data_dictionary

Writes ``docs/W1_lahari_data_dictionary.md`` (the profile) and
``benchmarks/raw/w1_column_profile.csv`` (the same numbers, machine-readable).

Deliberately pandas, not Spark: this is a one-shot profile of a 53 MiB file that has
to be runnable on Day 1 of Week 1, before every member has a JDK installed. Every
*pipeline* stage from Stage 1 onward is Spark; profiling is not a pipeline stage.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("pipeline.data_dictionary")

# What each column means, and why the project cares. Written by hand — this is the
# part of the dictionary a profiler cannot generate.
COLUMN_NOTES: dict[str, tuple[str, str]] = {
    "data": ("Split marker assigned by the dataset publisher: training / test.", "Not our time-based split. Lahari defines the real split in Week 3 — see decisions.md D-005."),
    "trip_creation_time": ("When the trip was created in the source system.", "Anchor for time-based train/test splitting and for past-only feature windows."),
    "route_schedule_uuid": ("Identifier of the planned route schedule the trip runs on.", "Groups trips that follow the same plan; candidate feature."),
    "route_type": ("FTL (full truck load, trunk) or Carting (short-haul feeder).", "Behaves very differently; every audit and model is reported split by this."),
    "trip_uuid": ("Unique trip identifier. Multiple rows share one.", "The grouping key for Stage 2 reconstruction."),
    "source_center": ("Origin facility code, e.g. IND388121AAA.", "Left half of the corridor key. Always present."),
    "source_name": ("Origin facility name: City_Facility_Type (State).", "Parsed into source_city / source_state. 293 nulls, all recoverable from the code."),
    "destination_center": ("Destination facility code.", "Right half of the corridor key. Always present."),
    "destination_name": ("Destination facility name, same convention.", "261 nulls, recoverable the same way."),
    "od_start_time": ("Start of the origin-destination leg.", "With od_end_time and trip_uuid, identifies one leg — the Stage 2 grain."),
    "od_end_time": ("End of the origin-destination leg.", "Leg wall-clock duration = od_end_time - od_start_time."),
    "start_scan_to_end_scan": ("Minutes from first to last scan of the leg.", "A second realised-duration measure; cross-checked against actual_time."),
    "is_cutoff": ("Whether this segment row crossed an operational cutoff.", "Segment-level; constant within a row, not within a leg."),
    "cutoff_factor": ("Cutoff-related numeric attribute from the source system.", "Undocumented upstream; treated as an opaque candidate feature."),
    "cutoff_timestamp": ("Timestamp of the cutoff event.", "Only column without sub-second precision — parsed with its own format."),
    "actual_distance_to_destination": ("Remaining distance to destination (km).", "Decreases along a trip; encodes trip progress."),
    "actual_time": ("Cumulative realised time for the trip so far (minutes).", "**Numerator of the project's core claim.** Cumulative, not per-segment."),
    "osrm_time": ("Cumulative OSRM-predicted time for the same stretch (minutes).", "**The production planner's estimate — the baseline this project beats.**"),
    "osrm_distance": ("Cumulative OSRM-predicted distance (km).", "Paired with osrm_time; their ratio is an implied planned speed."),
    "factor": ("actual_time / osrm_time at trip level.", "The delay ratio. > 1.25 defines the delay label (decisions.md D-003)."),
    "segment_actual_time": ("Realised time for this segment alone (minutes).", "1,973 rows are <= 0 — clock skew. Flagged, not deleted."),
    "segment_osrm_time": ("OSRM-predicted time for this segment alone (minutes).", "2,347 rows are exactly 0 — the routing engine returned nothing for that segment."),
    "segment_osrm_distance": ("OSRM-predicted distance for this segment (km).", "Used for hub-dwell separation in Stage 2."),
    "segment_factor": ("segment_actual_time / segment_osrm_time.", "**Carries a -1 sentinel, not a ratio, on the 2,347 zero-OSRM rows.** Stage 1 nulls it there."),
}


def profile(df: pd.DataFrame) -> pd.DataFrame:
    """Build one profile row per column."""
    rows = []
    total = len(df)
    for col in df.columns:
        s = df[col]
        nulls = int(s.isna().sum())
        row: dict[str, object] = {
            "column": col,
            "dtype": str(s.dtype),
            "non_null": total - nulls,
            "nulls": nulls,
            "null_pct": round(nulls / total * 100, 3),
            "distinct": int(s.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            desc = s.describe()
            row.update(
                min=round(float(desc["min"]), 3),
                p25=round(float(desc["25%"]), 3),
                median=round(float(desc["50%"]), 3),
                p75=round(float(desc["75%"]), 3),
                p99=round(float(s.quantile(0.99)), 3),
                max=round(float(desc["max"]), 3),
                mean=round(float(desc["mean"]), 3),
                std=round(float(desc["std"]), 3),
                nonpositive=int((s <= 0).sum()),
            )
            row["example"] = f"{s.dropna().iloc[0]}" if nulls < total else ""
        else:
            top = s.value_counts(dropna=True).head(3)
            row["example"] = "; ".join(f"{k} ({v:,})" for k, v in top.items())[:120]
        rows.append(row)
    return pd.DataFrame(rows)


def _md_escape(text: str) -> str:
    return str(text).replace("|", "\\|")


def render_markdown(df: pd.DataFrame, prof: pd.DataFrame, source: Path) -> str:
    total = len(df)
    n_trips = df["trip_uuid"].nunique()
    n_legs = df.groupby(["trip_uuid", "od_start_time", "od_end_time"]).ngroups
    segs_per_trip = df.groupby("trip_uuid").size()

    out: list[str] = []
    out.append("# W1 · Lahari — Delhivery data dictionary\n")
    out.append(
        "*Generated by `python -m src.pipeline.data_dictionary` — do not edit by hand; "
        "edit the prose in `COLUMN_NOTES` and regenerate.*\n"
    )
    # Relative to the repo root so the committed file is byte-identical whichever
    # member regenerates it — an absolute path would churn the diff every time.
    try:
        shown = source.resolve().relative_to(config.REPO_ROOT).as_posix()
    except ValueError:
        shown = source.name
    out.append(f"Source: `{shown}`  ")
    out.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    out.append("## Shape\n")
    out.append("| Property | Value |")
    out.append("|---|---|")
    out.append(f"| Rows (segments) | {total:,} |")
    out.append(f"| Columns | {len(df.columns)} |")
    out.append(f"| Distinct trips (`trip_uuid`) | {n_trips:,} |")
    out.append(f"| Distinct OD legs (`trip_uuid` + od window) | {n_legs:,} |")
    out.append(
        f"| Segments per trip | min {segs_per_trip.min()}, median {segs_per_trip.median():.0f}, "
        f"mean {segs_per_trip.mean():.1f}, max {segs_per_trip.max()} |"
    )
    out.append(f"| Exact duplicate rows | {int(df.duplicated().sum()):,} |")
    out.append(
        f"| Observation window | {df['trip_creation_time'].min()[:10]} → {df['od_end_time'].max()[:10]} |"
    )
    out.append(f"| Distinct source centres | {df['source_center'].nunique():,} |")
    out.append(f"| Distinct destination centres | {df['destination_center'].nunique():,} |")
    corridors = (df["source_center"] + ">" + df["destination_center"]).nunique()
    out.append(f"| Distinct corridors (source>dest) | {corridors:,} |")
    out.append("")

    out.append("### The grain, stated once\n")
    out.append(
        f"**One row = one shipment *segment*** (a scan-to-scan hop), not one shipment. "
        f"{total:,} rows collapse to {n_legs:,} origin-destination legs across {n_trips:,} trips. "
        "Trip-level columns (`actual_time`, `osrm_time`, `factor`, …) are *cumulative and repeated* "
        "on every segment row of the same leg. **Averaging them over raw rows over-weights long "
        "trips and is wrong.** Stage 2 collapses to the leg grain; all corridor statistics are "
        "computed there.\n"
    )

    out.append("## Categorical breakdowns\n")
    for col in ("data", "route_type", "is_cutoff"):
        counts = df[col].value_counts()
        pairs = ", ".join(f"`{k}` {v:,} ({v / total * 100:.1f}%)" for k, v in counts.items())
        out.append(f"- **`{col}`** — {pairs}")
    out.append("")

    out.append("## Columns\n")
    out.append("| # | Column | Type | Nulls | Distinct | Meaning | Why it matters |")
    out.append("|---|---|---|---|---|---|---|")
    for i, col in enumerate(df.columns, start=1):
        p = prof[prof["column"] == col].iloc[0]
        meaning, why = COLUMN_NOTES.get(col, ("—", "—"))
        nulls = f"{int(p['nulls']):,}" if p["nulls"] else "0"
        out.append(
            f"| {i} | `{col}` | {p['dtype']} | {nulls} | {int(p['distinct']):,} "
            f"| {_md_escape(meaning)} | {_md_escape(why)} |"
        )
    out.append("")

    out.append("## Numeric distributions\n")
    num = prof[prof["min"].notna()] if "min" in prof.columns else prof.iloc[0:0]
    out.append("| Column | min | p25 | median | p75 | p99 | max | mean | std | ≤ 0 |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for _, p in num.iterrows():
        out.append(
            f"| `{p['column']}` | {p['min']:,.3f} | {p['p25']:,.3f} | {p['median']:,.3f} "
            f"| {p['p75']:,.3f} | {p['p99']:,.3f} | {p['max']:,.3f} | {p['mean']:,.3f} "
            f"| {p['std']:,.3f} | {int(p['nonpositive']):,} |"
        )
    out.append("")

    out.append("## Data-quality findings that change how we code\n")
    neg = int((df["segment_actual_time"] <= 0).sum())
    zero_osrm = int((df["segment_osrm_time"] == 0).sum())
    src_null = int(df["source_name"].isna().sum())
    dst_null = int(df["destination_name"].isna().sum())
    out.append(
        f"1. **`segment_actual_time` goes negative** — {neg:,} rows are ≤ 0 "
        f"(minimum {df['segment_actual_time'].min():.0f} min). Scan clock skew in the source system. "
        "Stage 1 flags these as `is_negative_segment` and keeps them; deleting them would bias hub "
        "dwell downward.\n"
    )
    sentinel = int(((df["segment_osrm_time"] == 0) & (df["segment_factor"] == -1.0)).sum())
    out.append(
        f"2. **`segment_factor` carries a `-1` sentinel, not a ratio, on {sentinel:,} rows.** "
        f"Wherever `segment_osrm_time == 0` ({zero_osrm:,} rows) the publisher wrote exactly `-1.0` "
        "rather than dividing by zero. This is more dangerous than an infinity would be: an infinity "
        "is loud, whereas `-1` is a plausible-looking number that silently drags any mean or "
        "regression downward. Verified: where `segment_osrm_time > 0` the column equals "
        "`segment_actual_time / segment_osrm_time` to floating-point precision, so `-1` is a sentinel "
        "and not a real observation. **Stage 1 nulls `segment_factor` on those rows and flags them "
        "`is_zero_osrm_segment`. Never aggregate the raw column.**\n"
    )
    out.append(
        f"3. **Facility names have nulls** — `source_name` {src_null}, `destination_name` {dst_null} — "
        "but the centre *codes* are never null, and every affected code appears with a name on other "
        "rows. Stage 1 backfills from a code→name map built from the data itself.\n"
    )
    out.append(
        "4. **No exact duplicate rows** in the published file. Stage 1 still de-duplicates, to keep "
        "the pipeline safe against a re-download from a different mirror.\n"
    )
    out.append(
        f"5. **`factor` is heavily right-tailed** — median {df['factor'].median():.2f}, "
        f"p99 {df['factor'].quantile(0.99):.2f}, max {df['factor'].max():.1f}. The corridor audit uses "
        "Welch's t-test on log-ratios with a minimum-support threshold rather than raw means "
        "(decisions.md D-004).\n"
    )
    out.append(
        f"6. **The observation window is short** — roughly "
        f"{(pd.to_datetime(df['od_end_time'].max()) - pd.to_datetime(df['trip_creation_time'].min())).days} days "
        "(Sept–Oct 2018). Too short for seasonality; long enough for day-of-week and hour-of-day "
        "effects, which is what the temporal features encode.\n"
    )

    out.append("## Next\n")
    out.append(
        "- Mounika: Stage 1 consumes this profile — every finding above has a corresponding step in "
        "`src/pipeline/clean.py`.\n"
        "- Lahari: null/outlier analysis and the delay-label definition (`python -m src.ml.eda`).\n"
        "- Both: confirm the corridor key and delay threshold in `docs/decisions.md` before Week 2.\n"
    )
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=config.RAW_CSV)
    parser.add_argument(
        "--out-md", type=Path, default=config.DOCS_DIR / "W1_lahari_data_dictionary.md"
    )
    parser.add_argument(
        "--out-csv", type=Path, default=config.BENCHMARKS_RAW_DIR / "w1_column_profile.csv"
    )
    args = parser.parse_args()

    if not args.input.exists():
        log.error("Raw input not found: %s — see data/README.md", args.input)
        return 1

    config.ensure_dirs()
    log.info("Loading %s", args.input)
    df = pd.read_csv(args.input, low_memory=False)
    log.info("  %s rows x %d columns", f"{len(df):,}", len(df.columns))

    prof = profile(df)
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    prof.to_csv(args.out_csv, index=False)
    log.info("Column profile → %s", args.out_csv)

    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(render_markdown(df, prof, args.input), encoding="utf-8")
    log.info("Data dictionary → %s", args.out_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
