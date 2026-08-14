"""Stage 3 — hub dwell time and hub friction (PySpark).

    python -m src.pipeline.hubs
    python -m src.pipeline.hubs --min-support 30

Aggregates the OD legs from Stage 2 into one row per **facility** (centre code), so
that the Week 2 hub-friction leaderboard and Lahari's hub dwell ranking read a single
cached table rather than each re-deriving it.

Where the dwell number comes from — and where it does not
--------------------------------------------------------
The obvious definition of hub dwell is the gap *between* legs: a shipment arrives at
hub H at the end of leg *i* and departs on leg *i+1*, so ``next.od_start_time −
this.od_end_time`` is how long it sat there. **On this dataset that gap does not
measure dwell**, and building the leaderboard on it would have been wrong. Measured
over all 11,552 in-trip handoffs:

* on the 9,987 handoffs where the trip continues from the **same** centre, the gap is
  **exactly zero on 98.6%** of them (median 0, mean 1.5 min). The OD windows are
  recorded back to back — the publisher closes one leg's window at the instant it
  opens the next. There is no dwell left in the gap to measure.
* on the 1,565 handoffs where the next leg starts at a **different** centre than the
  previous leg ended at, the gap is non-zero **100%** of the time (median 90 min).
  That gap is not the shipment resting at a hub, it is the shipment *moving between
  two facilities on a leg the file does not contain*.

So the between-leg gap is a chain-break detector, not a dwell meter. It is still
computed and emitted, under names that say what it is, because 13.5% of handoffs
being discontinuous is a data-quality fact the corridor audit and the streaming
replay both need to know about.

The measurable friction is **within** the leg: ``dwell_min = start_scan_to_end_scan −
actual_time`` (Stage 2), the part of a leg's wall clock the shipment was not moving.
Verified on all 26,369 legs: ``start_scan_to_end_scan`` equals the OD window to the
minute, and ``dwell_min`` is never negative.

Two metrics, because they disagree — see D-015
----------------------------------------------
``dwell_min`` correlates 0.54 with the leg's wall clock, so ranking hubs by raw
minutes partly ranks them by how long their legs happen to be. The scale-free
alternative is ``dwell_share = dwell_min / start_scan_to_end_scan``. The two rankings
agree on only **8 of the top 20** hubs (rank correlation 0.48), so which one you pick
changes the leaderboard, and the choice cannot be left implicit.

Both are emitted. ``dwell_share`` is the primary — it is comparable across hubs
serving short and long corridors — and ``friction_rank`` is assigned on it.

Attribution: a leg's idle time cannot be split between its origin and its destination
from leg-grain data, so it is credited to **both** ends and reported separately as
``*_out`` (legs departing the hub) and ``*_in`` (legs arriving). The report carries a
diagnostic comparing the two so the choice can be argued from numbers rather than
assumed.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from src.common import config
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark
from src.pipeline import contracts

log = get_logger("pipeline.hubs")

def trip_chain() -> Window:
    """Orders the legs of one trip.

    ``od_start_time`` alone is already unique within a trip (checked: 0 duplicate
    trip+start pairs); ``od_end_time`` is a stable tie-break in case a future mirror
    is not. Built on call rather than at import — ``Window`` needs a live
    SparkContext, and this module is imported by the dashboard before one exists.
    """
    return Window.partitionBy("trip_uuid").orderBy("od_start_time", "od_end_time")


def add_dwell_share(legs: DataFrame) -> DataFrame:
    """Add the scale-free dwell metric.

    ``start_scan_to_end_scan`` is the leg's wall clock and is > 0 on every leg (Stage 1
    drops legs without a usable OD window), but the guard stays so a future mirror
    cannot produce a silent division by zero.
    """
    return legs.withColumn(
        "dwell_share",
        F.when(
            F.col("start_scan_to_end_scan") > 0,
            F.col("dwell_min") / F.col("start_scan_to_end_scan"),
        ),
    )


def _side_aggregate(legs: DataFrame, centre_col: str, suffix: str) -> DataFrame:
    """Per-hub dwell statistics for one side of the leg (origin or destination)."""
    return (
        legs.groupBy(F.col(centre_col).alias("centre_code"))
        .agg(
            F.count(F.lit(1)).alias(f"n_legs_{suffix}"),
            F.countDistinct("corridor_id").alias(f"n_corridors_{suffix}"),
            F.expr("percentile_approx(dwell_min, 0.5)").alias(f"median_dwell_min_{suffix}"),
            F.mean("dwell_min").alias(f"mean_dwell_min_{suffix}"),
            F.expr("percentile_approx(dwell_min, 0.9)").alias(f"p90_dwell_min_{suffix}"),
            F.expr("percentile_approx(dwell_share, 0.5)").alias(f"median_dwell_share_{suffix}"),
            F.mean("dwell_share").alias(f"mean_dwell_share_{suffix}"),
            F.expr("percentile_approx(gap_ratio, 0.5)").alias(f"median_gap_ratio_{suffix}"),
        )
    )


def leg_chain(legs: DataFrame) -> DataFrame:
    """Attach each leg's successor within its trip.

    The last leg of every trip gets nulls, and is dropped by the handoff aggregate —
    60.5% of trips are single-leg and contribute no handoff at all.
    """
    chain = trip_chain()
    return (
        legs.withColumn("leg_seq", F.row_number().over(chain))
        .withColumn("next_source_center", F.lead("source_center").over(chain))
        .withColumn("next_od_start_time", F.lead("od_start_time").over(chain))
    )


def handoff_aggregate(legs: DataFrame) -> tuple[DataFrame, DataFrame]:
    """Per-hub handoff counts and the chain-break diagnostic.

    A *handoff* is a leg followed by another leg of the same trip. It is credited to
    the centre where the inbound leg ended — the last place the file saw the shipment.

    ``continuation_gap_min`` is the wall-clock gap to the next leg. On continuous
    handoffs it is structurally ~0 (see the module docstring), so it is reported for
    chain breaks only, where it measures **unobserved transfer time** rather than
    dwell.
    """
    chain = leg_chain(legs).filter(F.col("next_source_center").isNotNull())
    handoffs = (
        chain.withColumn(
            "continuation_gap_min",
            (F.col("next_od_start_time").cast("long") - F.col("od_end_time").cast("long")) / 60.0,
        )
        .withColumn("is_chain_break", F.col("destination_center") != F.col("next_source_center"))
    )

    per_hub = handoffs.groupBy(F.col("destination_center").alias("centre_code")).agg(
        F.count(F.lit(1)).alias("n_handoffs"),
        F.sum(F.col("is_chain_break").cast("int")).alias("n_chain_breaks"),
        # Gap statistics over chain breaks only: on continuous handoffs the gap is an
        # artefact of how the windows are written, and averaging the two together
        # would produce a number that means nothing.
        F.expr(
            "percentile_approx(CASE WHEN is_chain_break THEN continuation_gap_min END, 0.5)"
        ).alias("median_unobserved_gap_min"),
        F.mean(F.when(F.col("is_chain_break"), F.col("continuation_gap_min"))).alias(
            "mean_unobserved_gap_min"
        ),
    )
    return per_hub, handoffs


def centre_directory(legs: DataFrame) -> DataFrame:
    """One name / city / state per centre code, from whichever side carries it.

    A code appears as both an origin and a destination and the name is identical on
    both, but 14 codes have no name anywhere (D-011) and keep nulls here. The
    row_number tie-break keeps the directory deterministic across runs regardless.
    """
    as_source = legs.select(
        F.col("source_center").alias("centre_code"),
        F.col("source_name").alias("centre_name"),
        F.col("source_city").alias("city"),
        F.col("source_state").alias("state"),
    )
    as_dest = legs.select(
        F.col("destination_center").alias("centre_code"),
        F.col("destination_name").alias("centre_name"),
        F.col("dest_city").alias("city"),
        F.col("dest_state").alias("state"),
    )
    both = as_source.union(as_dest)
    ranked = both.groupBy("centre_code", "centre_name", "city", "state").agg(
        F.count(F.lit(1)).alias("_n")
    )
    window = Window.partitionBy("centre_code").orderBy(
        F.col("_n").desc(), F.col("centre_name").asc_nulls_last()
    )
    return (
        ranked.withColumn("_rank", F.row_number().over(window))
        .filter(F.col("_rank") == 1)
        .drop("_n", "_rank")
    )


def build_hubs(legs: DataFrame, min_support: int) -> tuple[DataFrame, DataFrame]:
    """Join the outbound, inbound, handoff and directory views into the hub table."""
    outbound = _side_aggregate(legs, "source_center", "out")
    inbound = _side_aggregate(legs, "destination_center", "in")
    handoffs_per_hub, handoffs = handoff_aggregate(legs)

    hubs = (
        centre_directory(legs)
        .join(outbound, on="centre_code", how="left")
        .join(inbound, on="centre_code", how="left")
        .join(handoffs_per_hub, on="centre_code", how="left")
    )

    # A hub with no legs on one side is a genuine endpoint, not missing data: fill the
    # counts with 0 so downstream sums are honest, and leave the dwell statistics null
    # so nobody averages a facility that never dispatched anything.
    hubs = hubs.fillna(
        {
            "n_legs_out": 0,
            "n_legs_in": 0,
            "n_corridors_out": 0,
            "n_corridors_in": 0,
            "n_handoffs": 0,
            "n_chain_breaks": 0,
        }
    )

    hubs = hubs.withColumn("n_legs_total", F.col("n_legs_out") + F.col("n_legs_in")).withColumn(
        "chain_break_rate",
        F.when(F.col("n_handoffs") > 0, F.col("n_chain_breaks") / F.col("n_handoffs")),
    )

    # Support gate. Below it a hub's median is a handful of legs and will move under
    # resampling; the leaderboard and the audit both filter on this flag rather than
    # each inventing a threshold. Mirrors D-004 for corridors.
    hubs = hubs.withColumn("has_support", F.col("n_legs_out") >= F.lit(min_support))

    # friction_rank is assigned on dwell_share (D-015) and only among supported hubs,
    # so rank 1 always means "worst hub we can actually defend".
    #
    # Partitioning by has_support is what makes the ranks contiguous. Ranking over the
    # whole table and nulling the unsupported afterwards looks equivalent and is not —
    # the 1,536 unranked hubs still consume rank numbers, and the leaderboard comes out
    # numbered 27, 53, 62 with no rank 1 anywhere.
    rank_window = Window.partitionBy("has_support").orderBy(
        F.col("median_dwell_share_out").desc_nulls_last(), F.col("centre_code").asc()
    )
    hubs = hubs.withColumn(
        "friction_rank",
        F.when(F.col("has_support"), F.row_number().over(rank_window)),
    )
    return hubs, handoffs


def attribution_diagnostic(hubs: DataFrame) -> dict:
    """Is dwell an origin-side cost or a destination-side one?

    Leg-grain data cannot split a leg's idle minutes between its two ends, so the
    table credits both. This measures how much that choice matters: if outbound and
    inbound dwell were interchangeable the two per-hub series would track each other
    closely, and the ``*_out`` / ``*_in`` split would be decoration.
    """
    supported = hubs.filter("has_support AND n_legs_in > 0")
    n = supported.count()
    if n < 2:
        return {"supported_hubs_compared": n}
    return {
        "supported_hubs_compared": n,
        "corr_median_dwell_share_out_vs_in": round(
            supported.stat.corr("median_dwell_share_out", "median_dwell_share_in"), 4
        ),
        "corr_median_dwell_min_out_vs_in": round(
            supported.stat.corr("median_dwell_min_out", "median_dwell_min_in"), 4
        ),
    }


def metric_disagreement(hubs: DataFrame, top_n: int = 20) -> dict:
    """How far apart the two candidate rankings are — the evidence behind D-015."""
    supported = hubs.filter("has_support").cache()
    by_share = Window.orderBy(F.col("median_dwell_share_out").desc_nulls_last())
    by_minutes = Window.orderBy(F.col("median_dwell_min_out").desc_nulls_last())
    ranked = (
        supported.withColumn("_r_share", F.row_number().over(by_share))
        .withColumn("_r_minutes", F.row_number().over(by_minutes))
        .cache()
    )
    top_share = {r["centre_code"] for r in ranked.filter(F.col("_r_share") <= top_n).collect()}
    top_minutes = {r["centre_code"] for r in ranked.filter(F.col("_r_minutes") <= top_n).collect()}
    result = {
        "supported_hubs": supported.count(),
        "rank_correlation_share_vs_minutes": round(
            ranked.stat.corr("_r_share", "_r_minutes"), 4
        ),
        f"top_{top_n}_overlap": len(top_share & top_minutes),
        "top_n": top_n,
    }
    supported.unpersist()
    ranked.unpersist()
    return result


#: Columns written to the leaderboard CSV, in display order. Kept narrow on purpose —
#: the dashboard page and the audit read this, the full table lives in Parquet.
LEADERBOARD_COLUMNS = [
    "friction_rank",
    "centre_code",
    "centre_name",
    "city",
    "state",
    "n_legs_out",
    "n_corridors_out",
    "median_dwell_min_out",
    "p90_dwell_min_out",
    "median_dwell_share_out",
    "median_gap_ratio_out",
    "n_legs_in",
    "median_dwell_min_in",
    "median_dwell_share_in",
    "n_handoffs",
    "n_chain_breaks",
    "chain_break_rate",
    "median_unobserved_gap_min",
]


def write_leaderboard(hubs: DataFrame, path: Path) -> int:
    """Write the supported-hub leaderboard as a single tracked CSV.

    Collected to the driver and written with pandas rather than
    ``spark.write.csv`` because that produces a directory of part files, and this one
    is committed to git for Krishna's dashboard page and Lahari's ranking to read.
    """
    rows = (
        hubs.filter("has_support")
        .orderBy("friction_rank")
        .select(*LEADERBOARD_COLUMNS)
        .toPandas()
    )
    for col in ("median_dwell_share_out", "median_dwell_share_in", "chain_break_rate"):
        rows[col] = rows[col].round(4)
    for col in ("median_gap_ratio_out", "median_unobserved_gap_min"):
        rows[col] = rows[col].round(2)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(path, index=False)
    return len(rows)


def build(spark: SparkSession, input_path: Path, output_path: Path, min_support: int) -> dict:
    log.info("Reading legs from %s", input_path)
    legs = add_dwell_share(spark.read.parquet(str(input_path))).cache()
    n_legs = legs.count()
    log.info("  %s OD legs", f"{n_legs:,}")

    hubs, handoffs = build_hubs(legs, min_support)
    hubs = hubs.cache()
    n_hubs = hubs.count()
    log.info("  %s distinct hubs", f"{n_hubs:,}")

    # Every leg has exactly one origin and one destination, so the per-side counts must
    # add back to the leg count. If a join ever fans out, this catches it before the
    # number reaches a leaderboard.
    totals = hubs.agg(
        F.sum("n_legs_out").alias("out"), F.sum("n_legs_in").alias("in")
    ).collect()[0]
    if totals["out"] != n_legs or totals["in"] != n_legs:
        raise AssertionError(
            f"hub leg counts do not reconcile: outbound={totals['out']:,} "
            f"inbound={totals['in']:,} but there are {n_legs:,} legs. A join fanned out."
        )

    n_handoffs = handoffs.count()
    n_breaks = handoffs.filter("is_chain_break").count()
    supported = hubs.filter("has_support").count()

    # The leaderboard must be numbered 1..supported with no gaps. Asserted rather than
    # eyeballed: the first version of this ranked over the whole table and produced a
    # leaderboard starting at rank 27, which is invisible unless you go looking.
    ranks = hubs.filter("has_support").agg(
        F.min("friction_rank").alias("lo"),
        F.max("friction_rank").alias("hi"),
        F.countDistinct("friction_rank").alias("distinct"),
    ).collect()[0]
    if (ranks["lo"], ranks["hi"], ranks["distinct"]) != (1, supported, supported):
        raise AssertionError(
            f"friction_rank is not a dense 1..{supported} ranking over the supported hubs "
            f"(min={ranks['lo']}, max={ranks['hi']}, distinct={ranks['distinct']:,})."
        )

    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage": "3-hubs",
        "input": str(input_path),
        "output": str(output_path),
        "legs_in": n_legs,
        "hubs_out": n_hubs,
        "min_support": min_support,
        "supported_hubs": supported,
        "leg_counts_reconcile": True,
        "schema": contracts.stamp("hubs_v1"),
        "handoffs": {
            "total": n_handoffs,
            "chain_breaks": n_breaks,
            "chain_break_rate": round(n_breaks / n_handoffs, 4) if n_handoffs else None,
            "continuous_with_zero_gap": handoffs.filter(
                "NOT is_chain_break AND continuation_gap_min = 0"
            ).count(),
            "continuous": n_handoffs - n_breaks,
        },
    }

    dwell = legs.agg(
        F.expr("percentile_approx(dwell_min, 0.5)").alias("median_dwell_min"),
        F.mean("dwell_min").alias("mean_dwell_min"),
        F.expr("percentile_approx(dwell_share, 0.5)").alias("median_dwell_share"),
        F.mean("dwell_share").alias("mean_dwell_share"),
    ).collect()[0]
    report["leg_dwell"] = {k: round(float(v), 4) for k, v in dwell.asDict().items()}
    report["leg_dwell"]["corr_dwell_min_vs_wall_clock"] = round(
        legs.stat.corr("dwell_min", "start_scan_to_end_scan"), 4
    )
    report["metric_choice"] = metric_disagreement(hubs)
    report["attribution"] = attribution_diagnostic(hubs)

    log.info("Writing hub table to %s", output_path)
    # One file: 1,657 rows is a lookup table, and the dashboard and the MCP tool server
    # both read it whole. Partitioning it would only make Spark open more files.
    hubs.coalesce(1).write.mode("overwrite").parquet(str(output_path))
    (output_path / "_hub_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    leaderboard = config.BENCHMARKS_RAW_DIR / "w2_hub_dwell.csv"
    report["leaderboard_rows"] = write_leaderboard(hubs, leaderboard)
    log.info("Leaderboard (%s supported hubs) → %s", report["leaderboard_rows"], leaderboard)

    legs.unpersist()
    hubs.unpersist()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 3 — hub dwell time and hub friction")
    parser.add_argument("--input", type=Path, default=config.TRIPS_V1)
    parser.add_argument("--output", type=Path, default=config.HUBS_V1)
    parser.add_argument(
        "--min-support",
        type=int,
        default=config.MIN_HUB_SUPPORT,
        help="minimum outbound legs before a hub is ranked (D-015)",
    )
    args = parser.parse_args()

    if not args.input.exists():
        log.error("Missing %s — run `python -m src.pipeline.reconstruct` first.", args.input)
        return 1

    spark = get_spark("stage3-hubs")
    try:
        report = build(spark, args.input, args.output, args.min_support)
    finally:
        stop_spark(spark)

    log.info(
        "Done. %s legs -> %s hubs, %s ranked at >=%s outbound legs. "
        "Median leg dwell %.0f min (%.1f%% of the leg's wall clock). "
        "%s of %s handoffs are chain breaks.",
        f"{report['legs_in']:,}",
        f"{report['hubs_out']:,}",
        f"{report['supported_hubs']:,}",
        report["min_support"],
        report["leg_dwell"]["median_dwell_min"],
        report["leg_dwell"]["median_dwell_share"] * 100,
        f"{report['handoffs']['chain_breaks']:,}",
        f"{report['handoffs']['total']:,}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
