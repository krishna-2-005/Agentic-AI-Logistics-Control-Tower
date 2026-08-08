"""W1 EDA — distributions, the OSRM gap, and the delay-label definition.

    python -m src.ml.eda

Writes:
  * ``benchmarks/raw/w1_leg_summary.csv``       — one row per OD leg, the analysis grain
  * ``benchmarks/raw/w1_delay_threshold_sensitivity.csv``
  * ``benchmarks/raw/w1_corridor_support.csv``  — corridor trip counts, for the audit threshold
  * ``docs/W1_lahari_eda.md``                   — the written findings

Two things this script settles for Week 1, both of which every later week depends on:

**The analysis grain.** Trip-level columns are cumulative and repeated on every
segment row of the same leg. Any statistic computed over raw rows over-weights long
trips. Everything here collapses to one row per OD leg first.

**The delay label.** ``actual_time > DELAY_THRESHOLD * osrm_time`` at leg level, with
the threshold justified from the observed distribution rather than picked by feel.

Pandas rather than Spark, for the same reason as the data dictionary: this must run
on Day 1 before every member has a JDK. Once ``clean_v1`` exists, Week 3's feature
work reads the Parquet cache in Spark and these numbers get re-confirmed there.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("ml.eda")

OD_KEY = ["trip_uuid", "od_start_time", "od_end_time"]
CANDIDATE_THRESHOLDS = [1.10, 1.15, 1.25, 1.50, 2.00]


#: Columns that are genuinely constant across every segment row of one OD leg.
LEG_CONSTANT = [
    "data",
    "trip_creation_time",
    "route_type",
    "route_schedule_uuid",
    "source_center",
    "source_name",
    "destination_center",
    "destination_name",
    "start_scan_to_end_scan",
]

#: Columns that are RUNNING CUMULATIVE TOTALS within a leg, not constants. The final
#: row of the leg holds the leg total. See ``to_leg_grain``.
LEG_CUMULATIVE = [
    "actual_time",
    "osrm_time",
    "osrm_distance",
    "actual_distance_to_destination",
    "factor",
]


def to_leg_grain(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse segment rows to one row per origin-destination leg.

    **The single most important thing to get right in this dataset.**

    ``actual_time``, ``osrm_time``, ``osrm_distance`` and
    ``actual_distance_to_destination`` are *running cumulative totals within the leg*,
    increasing row by row — they are neither constant nor per-segment. ``factor`` is
    ``actual_time / osrm_time`` recomputed at each row, so it also varies. The leg
    total therefore lives in the **last** row of the leg, and taking ``first`` (or a
    mean) understates every leg.

    Two further traps, both verified against the data rather than assumed:

    * Despite its name, ``actual_distance_to_destination`` *increases* along the leg.
      It is distance **covered so far**, not distance remaining.
    * Summing ``segment_actual_time`` does **not** reproduce the leg total. The
      segment columns are rounded to whole minutes, and the drift reaches 39 minutes
      on the worst leg. The final cumulative value is authoritative.

    The final row is selected by maximum cumulative ``actual_time`` rather than by
    file position, because 0.08% of legs are not perfectly monotonic in file order.
    """
    grouped = df.groupby(OD_KEY, sort=False)

    constant = [c for c in LEG_CONSTANT if grouped[c].nunique(dropna=False).max() > 1]
    if constant:
        raise AssertionError(
            f"Columns assumed constant within an OD leg actually vary: {constant}. "
            "The grain assumption in this script and in Stage 2 is wrong — stop and re-check."
        )

    # Last row per leg = the leg's cumulative totals.
    last_idx = grouped["actual_time"].idxmax()
    legs = df.loc[last_idx, OD_KEY + LEG_CONSTANT + LEG_CUMULATIVE].reset_index(drop=True)

    per_leg = grouped.agg(
        n_segments=("trip_uuid", "size"),
        segment_actual_time_sum=("segment_actual_time", "sum"),
        segment_osrm_time_sum=("segment_osrm_time", "sum"),
        negative_segments=("segment_actual_time", lambda s: int((s <= 0).sum())),
        zero_osrm_segments=("segment_osrm_time", lambda s: int((s == 0).sum())),
    ).reset_index()
    legs = legs.merge(per_leg, on=OD_KEY, how="left", validate="one_to_one")

    legs["corridor_id"] = legs["source_center"] + ">" + legs["destination_center"]
    legs["gap_min"] = legs["actual_time"] - legs["osrm_time"]
    legs["gap_ratio"] = legs["actual_time"] / legs["osrm_time"]
    legs["log_gap_ratio"] = np.log(legs["gap_ratio"])
    legs["is_delayed"] = legs["gap_ratio"] > config.DELAY_THRESHOLD

    # start_scan_to_end_scan is the leg's wall clock; actual_time is moving time.
    # The difference is time the shipment sat still — the raw material for Week 2's
    # hub-friction analysis.
    legs["dwell_min"] = legs["start_scan_to_end_scan"] - legs["actual_time"]
    return legs


def threshold_sensitivity(legs: pd.DataFrame) -> pd.DataFrame:
    """Positive-class rate at each candidate threshold, overall and per route type."""
    rows = []
    for t in CANDIDATE_THRESHOLDS:
        flag = legs["gap_ratio"] > t
        row = {
            "threshold": t,
            "delayed_legs": int(flag.sum()),
            "delayed_pct": round(flag.mean() * 100, 2),
        }
        for rt in sorted(legs["route_type"].dropna().unique()):
            sub = legs[legs["route_type"] == rt]
            row[f"delayed_pct_{rt}"] = round((sub["gap_ratio"] > t).mean() * 100, 2)
        rows.append(row)
    return pd.DataFrame(rows)


def corridor_support(legs: pd.DataFrame) -> pd.DataFrame:
    """Legs observed per corridor — decides the audit's minimum-support threshold."""
    return (
        legs.groupby("corridor_id")
        .agg(
            legs_observed=("trip_uuid", "size"),
            mean_gap_ratio=("gap_ratio", "mean"),
            median_gap_ratio=("gap_ratio", "median"),
            mean_gap_min=("gap_min", "mean"),
            source_name=("source_name", "first"),
            destination_name=("destination_name", "first"),
        )
        .reset_index()
        .sort_values("legs_observed", ascending=False)
    )


def render_markdown(legs: pd.DataFrame, sens: pd.DataFrame, support: pd.DataFrame) -> str:
    o: list[str] = []
    n = len(legs)
    o.append("# W1 · Lahari — EDA and the delay-label definition\n")
    o.append(
        "*Generated by `python -m src.ml.eda` — regenerate rather than editing numbers by hand.*\n"
    )
    o.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    o.append("## 1. The analysis grain — and the trap in it\n")
    o.append(
        f"{int(legs['n_segments'].sum()):,} segment rows collapse to **{n:,} origin-destination "
        f"legs** across {legs['trip_uuid'].nunique():,} trips and "
        f"{legs['corridor_id'].nunique():,} corridors. Segments per leg: min "
        f"{legs['n_segments'].min()}, median {legs['n_segments'].median():.0f}, max "
        f"{legs['n_segments'].max()}.\n"
    )
    o.append(
        "**`actual_time`, `osrm_time`, `osrm_distance` and `actual_distance_to_destination` are "
        "running cumulative totals within a leg, not constants and not per-segment values.** They "
        "grow row by row; the leg total is in the *last* row. `factor` is `actual_time / osrm_time` "
        "recomputed at every row, so it varies too. Taking `first`, or averaging over raw rows, "
        "understates every leg — this is the easiest way to get every downstream number wrong, and "
        "the script asserts the constant columns really are constant so the mistake cannot creep "
        "back in.\n"
    )
    o.append("Two further traps, both verified against the data rather than assumed:\n")
    drift = (legs["actual_time"] - legs["segment_actual_time_sum"]).abs()
    o.append(
        "- **`actual_distance_to_destination` increases along the leg.** Despite the name it is "
        "distance *covered so far*, not distance remaining.\n"
        f"- **Summing `segment_actual_time` does not reproduce the leg total.** The segment columns "
        f"are rounded to whole minutes; the drift is {drift.median():.0f} min at the median but "
        f"reaches {drift.max():.0f} min on the worst leg. The final cumulative value is "
        "authoritative.\n"
    )
    o.append(
        f"- **`start_scan_to_end_scan` is the leg's wall clock** (it matches "
        f"`od_end_time - od_start_time` to within a minute), while `actual_time` is moving time. "
        f"Their difference is time the shipment sat still — median **{legs['dwell_min'].median():,.0f} "
        "min per leg**. That is the raw material for Week 2's hub-friction analysis, available for "
        "free from columns already present.\n"
    )

    o.append("## 2. How wrong is the production planner?\n")
    gr = legs["gap_ratio"]
    o.append("| Statistic | Value |")
    o.append("|---|---|")
    o.append(f"| Legs where actual > OSRM | {int((gr > 1).sum()):,} ({(gr > 1).mean() * 100:.1f}%) |")
    o.append(f"| Median gap ratio (actual / OSRM) | {gr.median():.3f} |")
    o.append(f"| Mean gap ratio | {gr.mean():.3f} |")
    o.append(f"| p90 / p99 gap ratio | {gr.quantile(0.90):.3f} / {gr.quantile(0.99):.3f} |")
    o.append(f"| Median absolute gap | {legs['gap_min'].median():,.1f} min |")
    o.append(f"| Mean absolute gap | {legs['gap_min'].mean():,.1f} min |")
    o.append("")
    o.append(
        f"**The planner is not noisy, it is biased.** OSRM under-predicts on "
        f"{(gr > 1).mean() * 100:.1f}% of legs, and the median leg takes "
        f"{(gr.median() - 1) * 100:.0f}% longer than planned. A symmetric error distribution would "
        "sit near 1.0. This one-sidedness is what makes a corridor-level audit worth doing: the "
        "error is systematic, so it should be localisable.\n"
    )

    o.append("### By route type\n")
    o.append("| Route type | Legs | Median gap ratio | Mean gap min | % legs late |")
    o.append("|---|---|---|---|---|")
    for rt, sub in legs.groupby("route_type"):
        o.append(
            f"| {rt} | {len(sub):,} | {sub['gap_ratio'].median():.3f} "
            f"| {sub['gap_min'].mean():,.1f} | {(sub['gap_ratio'] > 1).mean() * 100:.1f}% |"
        )
    o.append("")

    o.append("## 3. Delay-label threshold\n")
    o.append(
        "The label is `actual_time > T x osrm_time` at leg grain. `T` has to be high enough that the "
        "positive class means *operationally late* rather than *slightly over*, and low enough to "
        "leave a learnable class balance.\n"
    )
    o.append("| Threshold T | Delayed legs | % of legs | " + " | ".join(f"% {c.split('_')[-1]}" for c in sens.columns if c.startswith("delayed_pct_")) + " |")
    o.append("|---|---|---|" + "---|" * sum(c.startswith("delayed_pct_") for c in sens.columns))
    for _, r in sens.iterrows():
        extra = " | ".join(f"{r[c]:.1f}%" for c in sens.columns if c.startswith("delayed_pct_"))
        marker = (
            " **(blueprint)**" if abs(r["threshold"] - config.DELAY_THRESHOLD) < 1e-9 else ""
        )
        o.append(
            f"| {r['threshold']:.2f}{marker} | {int(r['delayed_legs']):,} | {r['delayed_pct']:.1f}% | {extra} |"
        )
    o.append("")

    chosen = sens[np.isclose(sens["threshold"], config.DELAY_THRESHOLD)].iloc[0]
    majority = max(chosen["delayed_pct"], 100 - chosen["delayed_pct"])
    balanced = sens.iloc[(sens["delayed_pct"] - 50).abs().argmin()]

    o.append("### ⚠ The blueprint's 1.25 threshold does not survive contact with the data\n")
    o.append(
        f"The blueprint proposes `T = 1.25`. At leg grain that labels "
        f"**{chosen['delayed_pct']:.1f}% of legs delayed** — because the *median* leg already runs "
        f"at {gr.median():.2f}x plan, so a 25% overrun is not an exception here, it is the norm.\n"
    )
    o.append(
        f"That makes the classifier close to meaningless: a model that outputs \"delayed\" for every "
        f"shipment scores **{majority:.1f}% accuracy** while carrying zero information. Precision "
        "would look excellent and mean nothing, and the Exception Agent built on it in Week 6 would "
        "flag essentially every shipment — which is the same as flagging none.\n"
    )
    o.append(
        f"**Recommendation: move the classification threshold to `T = {balanced['threshold']:.2f}`**, "
        f"which splits the data {balanced['delayed_pct']:.1f}% / {100 - balanced['delayed_pct']:.1f}% "
        "and gives a label that a model can actually be wrong about. Interpretation stays honest: "
        "\"takes at least twice the planned time\" is a defensible definition of *operationally late* "
        "on a network whose planner is biased this hard.\n"
    )
    o.append(
        "**Two supporting moves, both worth taking regardless of the threshold chosen:**\n\n"
        "1. **Lead with regression, not classification.** `gap_min` (median "
        f"{legs['gap_min'].median():,.0f} min, mean {legs['gap_min'].mean():,.0f} min) has no "
        "threshold problem at all, and the headline result the blueprint actually wants — *our MAE "
        "versus OSRM's MAE* — is a regression result. The classifier becomes a secondary framing "
        "rather than the load-bearing one.\n"
        "2. **Report the trivial baseline next to every classifier number.** Any accuracy figure "
        "quoted without the majority-class rate beside it is unreadable, and a viva panel will ask.\n"
    )
    o.append(
        f"**Status: D-003 is OPEN pending team sign-off.** `config.DELAY_THRESHOLD` still holds the "
        f"blueprint's {config.DELAY_THRESHOLD} so nothing silently changes underneath anyone; change "
        "it in one place once the team agrees. Week 5's sensitivity run (1.15 / 1.25 / 1.50) should "
        f"be extended to include {balanced['threshold']:.2f}.\n"
    )

    o.append("## 4. Corridor support\n")
    total_corridors = len(support)
    o.append("| Minimum legs per corridor | Corridors retained | % of corridors | % of legs covered |")
    o.append("|---|---|---|---|")
    for m in (1, 10, 20, 30, 50, 100):
        kept = support[support["legs_observed"] >= m]
        o.append(
            f"| {m} | {len(kept):,} | {len(kept) / total_corridors * 100:.1f}% "
            f"| {kept['legs_observed'].sum() / support['legs_observed'].sum() * 100:.1f}% |"
        )
    o.append("")
    kept30 = support[support["legs_observed"] >= config.MIN_CORRIDOR_SUPPORT]
    o.append(
        f"**Decision (D-004): minimum support = {config.MIN_CORRIDOR_SUPPORT} legs.** That keeps "
        f"{len(kept30):,} of {total_corridors:,} corridors "
        f"({len(kept30) / total_corridors * 100:.1f}%) while still covering "
        f"{kept30['legs_observed'].sum() / support['legs_observed'].sum() * 100:.1f}% of all legs. "
        "The long tail of once-seen corridors cannot support a significance test and would dominate "
        "any 'worst corridor' ranking with noise.\n"
    )

    o.append("### Ten busiest corridors\n")
    o.append("| Corridor | Legs | Median gap ratio | Mean gap (min) |")
    o.append("|---|---|---|---|")
    for _, r in support.head(10).iterrows():
        src = str(r["source_name"]).split("_")[0]
        dst = str(r["destination_name"]).split("_")[0]
        o.append(
            f"| {src} → {dst} | {int(r['legs_observed']):,} | {r['median_gap_ratio']:.2f} "
            f"| {r['mean_gap_min']:,.0f} |"
        )
    o.append("")
    o.append(
        "*Not yet the bottleneck ranking — these are the busiest corridors, not the worst. "
        "The Week 2 audit ranks by significance-tested gap, not by traffic.*\n"
    )

    o.append("## 5. What this hands to Week 2\n")
    o.append(
        "- Corridor key `source_center>destination_center`, at leg grain (D-002).\n"
        f"- Delay label `gap_ratio > {config.DELAY_THRESHOLD}` (D-003 — **open**, see §3).\n"
        f"- Minimum corridor support {config.MIN_CORRIDOR_SUPPORT} legs (D-004).\n"
        "- `log_gap_ratio` as the audit's test statistic — the raw ratio is right-skewed "
        f"(max {legs['gap_ratio'].max():.1f}), so Welch's t-test runs on logs.\n"
        "- `dwell_min` per leg, already computed — Week 2 hub friction does not need new columns.\n"
        "- Leg-level table cached at `benchmarks/raw/w1_leg_summary.csv` for Mounika to validate "
        "Stage 2's Spark reconstruction against, row for row.\n"
    )

    o.append("## 6. Open questions for the Week 1 sync\n")
    o.append(
        "1. **D-003 threshold** (§3) — agree `T`, or agree to lead with regression. Blocks Week 3.\n"
        f"2. **Corridor support vs coverage** — {config.MIN_CORRIDOR_SUPPORT} legs keeps only "
        f"{len(kept30) / total_corridors * 100:.1f}% of corridors and "
        f"{kept30['legs_observed'].sum() / support['legs_observed'].sum() * 100:.1f}% of legs. "
        "The audit is therefore a claim about the busy core of the network, not the whole of it, "
        "and the report must say so. If we want broader coverage, 10 legs retains "
        f"{len(support[support['legs_observed'] >= 10]) / total_corridors * 100:.1f}% of corridors "
        f"and {support[support['legs_observed'] >= 10]['legs_observed'].sum() / support['legs_observed'].sum() * 100:.1f}% "
        "of legs, at the cost of weaker per-corridor tests.\n"
        "3. **City naming** — `Bangalore` and `Bengaluru` both appear as city prefixes on distinct "
        "centre codes. Corridor keys use *codes*, so the statistics are unaffected, but the India "
        "map and any city-level rollup need a normalisation table. Krishna's Week 2 map work "
        "depends on this.\n"
    )
    return "\n".join(o)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=config.RAW_CSV)
    parser.add_argument("--out-md", type=Path, default=config.DOCS_DIR / "W1_lahari_eda.md")
    args = parser.parse_args()

    if not args.input.exists():
        log.error("Raw input not found: %s — see data/README.md", args.input)
        return 1

    config.ensure_dirs()
    log.info("Loading %s", args.input)
    df = pd.read_csv(args.input, low_memory=False)

    legs = to_leg_grain(df)
    log.info("  collapsed %s rows -> %s OD legs", f"{len(df):,}", f"{len(legs):,}")

    sens = threshold_sensitivity(legs)
    support = corridor_support(legs)

    out_dir = config.BENCHMARKS_RAW_DIR
    legs.to_csv(out_dir / "w1_leg_summary.csv", index=False)
    sens.to_csv(out_dir / "w1_delay_threshold_sensitivity.csv", index=False)
    support.to_csv(out_dir / "w1_corridor_support.csv", index=False)
    log.info("  wrote 3 CSVs to %s", out_dir)

    args.out_md.write_text(render_markdown(legs, sens, support), encoding="utf-8")
    log.info("EDA writeup → %s", args.out_md)

    gr = legs["gap_ratio"]
    log.info(
        "Headline: OSRM under-predicts on %.1f%% of legs; median leg runs %.0f%% over plan.",
        (gr > 1).mean() * 100,
        (gr.median() - 1) * 100,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
