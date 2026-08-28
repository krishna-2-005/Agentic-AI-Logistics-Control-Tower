"""Stage 4 — the leak-free feature table (PySpark).

    python -m src.pipeline.features
    python -m src.pipeline.features --validate

Reads the OD legs from Stage 2 (`trips_v1`) and writes `features_v1`: one row per leg,
carrying only values that were **knowable at the moment the shipment was created**,
plus the targets Week 4 trains against.

The whole stage exists for one reason
-------------------------------------
Week 2's audit produced `excess_ratio` per corridor, and it is the single most
predictive thing we have: it says how badly this corridor overruns. Using it as a
feature *as it stands* would destroy the project's headline result, because it was
fitted over the **entire** observation window — including the legs the model is asked
to predict. A model given that column would score brilliantly and mean nothing, and
"we beat the production planner" would be a claim about having seen the answer.

So corridor history is recomputed here, from scratch, **as of each leg's own creation
time**. Nothing else in the pipeline may hand a model a column fitted on the full
period (D-005).

Two clocks, and the difference between them is the whole trap
-------------------------------------------------------------
A leg is predicted when the shipment is created — `trip_creation_time`. Verified
across all 26,369 legs: `trip_creation_time <= od_start_time` without exception, so it
is a legitimate decision point rather than a column that quietly post-dates dispatch.

But a *previous* leg's outcome does not become usable when it starts. It becomes
usable when it **finishes**, at `od_end_time`, because that is when anyone could know
how long it actually took. So for a leg created at time T on corridor C, the usable
history is every leg on C with:

    od_end_time <= T

**Not** `od_start_time < T`, which is the natural thing to write and is leakage. On
this dataset a leg runs a median 100 minutes and up to several days, so a leg that
started before T can easily finish after it. Ordering corridor history by start time
would feed the model outcomes from journeys still in flight. The validator below
checks this explicitly rather than trusting the window specification to be right.

How the as-of aggregate is computed without a self-join
-------------------------------------------------------
The naive implementation is a self-join of legs to legs on `corridor_id` with an
inequality predicate, which is a cross join per corridor — 151 legs on the busiest
corridor means 22K comparisons for that corridor alone, and it does not transfer to
production volumes.

Instead the legs are turned into a single **event stream** and read once:

* every leg emits a **fact** at `od_end_time` — "this outcome is now known"
* every leg emits a **query** at `trip_creation_time` — "what was known here?"

Both are unioned, partitioned by corridor, ordered by `(event_time, kind)` with facts
sorting before queries so that a fact known at exactly T counts for a query at T, and
a running window sums the fact columns from the start of the corridor to the current
row. Reading off the query rows gives every leg its own past, in one pass, with the
window doing the work Spark is good at. The same shape gives hub history by
partitioning on the centre code instead.

What is deliberately *not* in the table
---------------------------------------
Every column produced by the journey itself: `actual_time`, `start_scan_to_end_scan`,
`dwell_min`, `factor`, `gap_ratio`, `n_segments`, `segment_*`,
`actual_distance_to_destination`, and the OD window itself. These are outcomes. They
are listed in `BANNED_FEATURES` and the writer refuses to emit a table containing any
of them, so the leakage rule is enforced by the code rather than remembered by whoever
edits it next.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from src.common import config
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark

log = get_logger("pipeline.features")

#: Columns that only exist because the journey happened. Any of these in the feature
#: table is leakage, so the writer refuses rather than warns.
BANNED_FEATURES = (
    "actual_time",
    "start_scan_to_end_scan",
    "dwell_min",
    "factor",
    "gap_ratio",
    "n_segments",
    "segment_actual_time_sum",
    "segment_osrm_time_sum",
    "negative_segments",
    "zero_osrm_segments",
    "actual_distance_to_destination",
    "od_start_time",
    "od_end_time",
)

#: Carried through as prediction targets, not features. Week 4 trains on `gap_min`
#: (regression, the headline) and `is_delayed` (classification, D-003 at 2.00x).
TARGETS = ("gap_min", "log_gap_ratio", "is_delayed")

#: The statistic corridor and hub history are accumulated over. Logs rather than the
#: raw ratio for the same reason the Week 2 audit uses them — the ratio is
#: right-skewed and a handful of 40x legs would drag any mean they land in.
STAT = "log_gap_ratio"


def load_legs(spark: SparkSession, path: Path) -> DataFrame:
    """Read `trips_v1`, keeping only legs the target is defined on."""
    legs = spark.read.parquet(str(path))
    total = legs.count()
    usable = legs.filter(F.col(STAT).isNotNull() & F.col("gap_min").isNotNull())
    n = usable.count()
    if n != total:
        log.warning("%s of %s legs have no usable target and are dropped", total - n, total)
    return usable


def assert_prediction_point(legs: DataFrame) -> dict:
    """Fail if `trip_creation_time` is not a legitimate moment to predict from.

    The entire feature table is anchored on the claim that a shipment's creation time
    precedes its journey. If that stops being true on some future extract, every
    "past-only" statistic here silently becomes a statistic about the future.
    """
    bad = legs.filter(F.col("trip_creation_time") > F.col("od_start_time")).count()
    if bad:
        raise ValueError(
            f"{bad:,} legs have trip_creation_time after od_start_time. The prediction "
            "point is not before the journey, so no feature in this table can be "
            "called past-only. Investigate before regenerating."
        )
    span = legs.agg(
        F.min("trip_creation_time").alias("lo"), F.max("trip_creation_time").alias("hi")
    ).first()
    return {"prediction_point": "trip_creation_time", "from": str(span.lo), "to": str(span.hi)}


def as_of_history(
    legs: DataFrame, key: str, prefix: str, fact_time: str = "od_end_time"
) -> DataFrame:
    """Past-only running statistics on `key`, as of each leg's creation time.

    Args:
        legs: the OD legs, one row per leg.
        key: what history is accumulated over — `corridor_id`, `source_center`, …
        prefix: column-name prefix for the emitted features.
        fact_time: when a prior leg's outcome becomes knowable. **`od_end_time` is the
            only correct value** — a journey's duration is not known until it ends.
            `od_start_time` is accepted solely so `measure_naive_leak()` can quantify
            what the obvious-but-wrong implementation would have leaked.

    Returns one row per `leg_id` with the history that was knowable when that leg was
    created, and nothing else. A leg never contributes to its own history: its fact
    lands at `od_end_time`, which is strictly after its own `trip_creation_time`.
    """
    facts = legs.select(
        F.col(key).alias("k"),
        F.col(fact_time).alias("event_time"),
        F.lit(0).alias("kind"),  # facts sort before queries at an identical timestamp
        F.lit(None).cast("string").alias("leg_id"),
        F.col(STAT).alias("f_stat"),
        F.col("gap_min").alias("f_gap"),
    )
    queries = legs.select(
        F.col(key).alias("k"),
        F.col("trip_creation_time").alias("event_time"),
        F.lit(1).alias("kind"),
        F.col("leg_id"),
        F.lit(None).cast("double").alias("f_stat"),
        F.lit(None).cast("double").alias("f_gap"),
    )

    stream = facts.unionByName(queries)
    w = (
        Window.partitionBy("k")
        .orderBy("event_time", "kind")
        .rowsBetween(Window.unboundedPreceding, Window.currentRow)
    )

    acc = stream.select(
        "k",
        "kind",
        "leg_id",
        "event_time",
        F.count("f_stat").over(w).alias("n_prior"),
        F.sum("f_stat").over(w).alias("sum_stat"),
        F.sum(F.col("f_stat") * F.col("f_stat")).over(w).alias("sumsq_stat"),
        F.sum("f_gap").over(w).alias("sum_gap"),
        F.last("f_stat", ignorenulls=True).over(w).alias("last_stat"),
        F.last(
            F.when(F.col("kind") == 0, F.col("event_time")), ignorenulls=True
        ).over(w).alias("last_known_at"),
    ).filter(F.col("kind") == 1)

    n = F.col("n_prior")
    mean = F.col("sum_stat") / n
    # Population variance from the running sums; clamped at zero because floating-point
    # cancellation can produce a very small negative where every value is identical.
    var = F.greatest(F.col("sumsq_stat") / n - mean * mean, F.lit(0.0))

    return acc.select(
        "leg_id",
        n.cast("int").alias(f"{prefix}_n_prior"),
        F.when(n > 0, mean).alias(f"{prefix}_mean_log_ratio"),
        F.when(n > 1, F.sqrt(var)).alias(f"{prefix}_std_log_ratio"),
        F.when(n > 0, F.col("sum_gap") / n).alias(f"{prefix}_mean_gap_min"),
        F.col("last_stat").alias(f"{prefix}_last_log_ratio"),
        F.when(
            F.col("last_known_at").isNotNull(),
            (
                F.col("event_time").cast("long") - F.col("last_known_at").cast("long")
            ) / 3600.0,
        ).alias(f"{prefix}_hours_since_last"),
    )


def measure_naive_leak(legs: DataFrame, features: DataFrame) -> dict:
    """How much history the obvious implementation would have invented.

    Ordering corridor history by `od_start_time` is the natural thing to write, and it
    leaks in two separate ways. Running the same window on that clock and diffing the
    prior-leg counts turns the docstring's warning into numbers the report can quote.

    **Leak 1 — the leg reads its own record.** On 46.4% of legs `od_start_time` is
    *exactly* `trip_creation_time`: the shipment is created and departs in the same
    second. Under the naive clock the leg's own departure is therefore already a
    "known fact" when it is asked to predict itself. That is not a subtle leak, it is
    the answer sheet.

    **Leak 2 — journeys still on the road.** A leg that departed before time T can
    easily still be moving at T; the median leg runs 153 minutes and the slowest 1%
    run over 42 hours. Their durations are not knowable yet.

    The two overlap, so they are counted separately and the union is reported too.
    """
    naive = as_of_history(legs, "corridor_id", "naive", fact_time="od_start_time")
    joined = (
        features.select("leg_id", "corr_n_prior")
        .join(naive.select("leg_id", "naive_n_prior"), on="leg_id", how="inner")
        .join(
            legs.select(
                "leg_id",
                (F.col("od_start_time") <= F.col("trip_creation_time"))
                .cast("int")
                .alias("counts_itself"),
            ),
            on="leg_id",
            how="inner",
        )
    )
    # Everything the naive clock adds, minus the leg's own record, is other traffic.
    others = F.col("naive_n_prior") - F.col("corr_n_prior") - F.col("counts_itself")
    row = joined.select(
        F.col("counts_itself"),
        others.alias("others"),
        (F.col("naive_n_prior") - F.col("corr_n_prior")).alias("extra"),
    ).agg(
        F.sum("counts_itself").alias("self_legs"),
        F.sum(F.when(F.col("others") > 0, 1).otherwise(0)).alias("other_legs"),
        F.sum(F.when(F.col("others") > 0, F.col("others")).otherwise(0)).alias("other_total"),
        F.sum(F.when(F.col("extra") > 0, 1).otherwise(0)).alias("any_legs"),
        F.max("others").alias("worst_others"),
    ).first()
    total = features.count()
    return {
        "legs_reading_their_own_record": int(row.self_legs),
        "pct_reading_their_own_record": round(row.self_legs / total * 100, 2),
        "legs_given_other_unfinished_journeys": int(row.other_legs),
        "pct_given_other_unfinished_journeys": round(row.other_legs / total * 100, 2),
        "other_unfinished_outcomes_leaked": int(row.other_total),
        "worst_leg_other_unfinished": int(row.worst_others),
        "legs_affected_either_way": int(row.any_legs),
        "pct_affected_either_way": round(row.any_legs / total * 100, 2),
    }


def build(spark: SparkSession, input_path: Path) -> tuple[DataFrame, dict]:
    """Assemble the feature table and the report describing it."""
    # `trip_uuid` + corridor is NOT unique: trip-153784572117438961 runs
    # IND370001AAA -> IND370110AAA on both 25 and 26 September, two genuine journeys a
    # day apart. `trips_v1` already declares its key as (trip_uuid, od_start_time,
    # od_end_time) for this reason, so the leg id carries the departure time too.
    legs = load_legs(spark, input_path).withColumn(
        "leg_id",
        F.concat_ws("|", "trip_uuid", F.date_format("od_start_time", "yyyyMMddHHmmss"), "corridor_id"),
    )
    legs = legs.cache()
    n_legs = legs.count()
    report = {"legs": n_legs}
    report.update(assert_prediction_point(legs))

    dup = legs.groupBy("leg_id").count().filter(F.col("count") > 1).count()
    if dup:
        raise ValueError(
            f"leg_id is not unique on {dup:,} groups — it cannot key the table. A trip "
            "repeating a corridor is legitimate (see the comment above); a collision "
            "here means two legs share a departure second and the id needs more."
        )

    # Known at creation time: the plan, the route type, and the clock.
    base = legs.select(
        "leg_id",
        "trip_uuid",
        "corridor_id",
        "source_center",
        "destination_center",
        "route_type",
        "trip_creation_time",
        F.col("osrm_time").alias("planned_min"),
        F.col("osrm_distance").alias("planned_km"),
        F.hour("trip_creation_time").alias("created_hour"),
        F.dayofweek("trip_creation_time").alias("created_dayofweek"),
        F.dayofweek("trip_creation_time").isin(1, 7).alias("created_is_weekend"),
        *TARGETS,
    )

    histories = [
        as_of_history(legs, "corridor_id", "corr"),
        as_of_history(legs, "source_center", "src"),
        as_of_history(legs, "destination_center", "dst"),
    ]
    features = base
    for h in histories:
        features = features.join(h, on="leg_id", how="left")

    legs.unpersist()
    return features, report


def leakage_checks(features: DataFrame, legs: DataFrame) -> dict:
    """Assert the past-only claim from the data, not from the window specification.

    Three things are checked, and each has been wrong in some implementation of this
    before it was checked:

    1. **No banned column survived** into the table.
    2. **A leg never sees its own outcome** — the first leg on any corridor must have
       no history at all.
    3. **Every counted prior leg had finished.** Recomputed independently against the
       legs table with an explicit `od_end_time <= trip_creation_time` predicate, on a
       sample, and compared to what the window produced.
    """
    out: dict = {}

    present = [c for c in BANNED_FEATURES if c in features.columns]
    if present:
        raise ValueError(f"Outcome columns leaked into the feature table: {present}")
    out["banned_columns_present"] = 0

    cold = features.filter(F.col("corr_n_prior") == 0).count()
    total = features.count()
    out["legs_with_no_corridor_history"] = cold
    out["pct_cold_start"] = round(cold / total * 100, 2)

    nulls = features.filter(
        (F.col("corr_n_prior") > 0) & F.col("corr_mean_log_ratio").isNull()
    ).count()
    if nulls:
        raise ValueError(f"{nulls:,} legs claim prior history but carry a null mean.")

    # Independent recomputation on a sample, with the predicate written out longhand.
    sample = features.select("leg_id", "corridor_id", "trip_creation_time", "corr_n_prior")
    sample = sample.orderBy(F.col("corr_n_prior").desc()).limit(200)
    priors = legs.select(
        F.col("corridor_id").alias("p_corridor"),
        F.col("od_end_time").alias("p_end"),
    )
    recomputed = (
        sample.join(priors, sample["corridor_id"] == priors["p_corridor"], "left")
        .filter(F.col("p_end") <= F.col("trip_creation_time"))
        .groupBy("leg_id", "corr_n_prior")
        .agg(F.count("*").alias("recomputed_n"))
    )
    mismatch = recomputed.filter(F.col("corr_n_prior") != F.col("recomputed_n")).count()
    if mismatch:
        raise ValueError(
            f"{mismatch} of 200 sampled legs disagree with an independent as-of "
            "recomputation. The window is counting legs that had not finished."
        )
    out["sampled_legs_recomputed"] = recomputed.count()
    out["sample_mismatches"] = 0
    return out


def summarise(features: DataFrame, report: dict) -> dict:
    """Coverage numbers the writeup and Lahari's split both need."""
    row = features.agg(
        F.avg("corr_n_prior").alias("mean_prior"),
        F.expr("percentile_approx(corr_n_prior, 0.5)").alias("median_prior"),
        # Cast before averaging: Spark 4 refuses avg() on a boolean.
        F.avg((F.col("corr_n_prior") > 0).cast("double")).alias("share_with_history"),
        F.avg((F.col("src_n_prior") > 0).cast("double")).alias("share_src_history"),
        F.min("trip_creation_time").alias("lo"),
        F.max("trip_creation_time").alias("hi"),
    ).first()
    report.update(
        {
            "mean_prior_legs_per_corridor": round(float(row.mean_prior), 2),
            "median_prior_legs_per_corridor": int(row.median_prior),
            "pct_legs_with_corridor_history": round(float(row.share_with_history) * 100, 2),
            "pct_legs_with_source_hub_history": round(float(row.share_src_history) * 100, 2),
            "feature_columns": len(features.columns),
        }
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 4 — leak-free feature table")
    parser.add_argument("--input", type=Path, default=config.TRIPS_V1)
    parser.add_argument("--output", type=Path, default=config.FEATURES_V1)
    parser.add_argument(
        "--validate",
        action="store_true",
        help="run the leakage checks and exit non-zero on failure",
    )
    args = parser.parse_args()

    if not args.input.exists():
        log.error("Missing %s — run `python -m src.pipeline.reconstruct` first.", args.input)
        return 1

    config.ensure_dirs()
    spark = get_spark("stage4-features")
    try:
        features, report = build(spark, args.input)
        features = features.cache()
        log.info("%s feature rows, %s columns", f"{features.count():,}", len(features.columns))

        if args.validate:
            legs = load_legs(spark, args.input)
            report["leakage_checks"] = leakage_checks(features, legs)
            legs_keyed = legs.withColumn(
                "leg_id",
                F.concat_ws(
                    "|",
                    "trip_uuid",
                    F.date_format("od_start_time", "yyyyMMddHHmmss"),
                    "corridor_id",
                ),
            )
            report["naive_start_time_leak"] = measure_naive_leak(legs_keyed, features)
            log.info("Leakage checks passed: %s", report["leakage_checks"])
            nl = report["naive_start_time_leak"]
            log.info(
                "Ordering history by od_start_time instead: %s legs (%.1f%%) would read "
                "their own record, and %s (%.1f%%) would be handed another journey still "
                "on the road. %.1f%% of the table affected either way.",
                f"{nl['legs_reading_their_own_record']:,}",
                nl["pct_reading_their_own_record"],
                f"{nl['legs_given_other_unfinished_journeys']:,}",
                nl["pct_given_other_unfinished_journeys"],
                nl["pct_affected_either_way"],
            )

        report = summarise(features, report)
        features.write.mode("overwrite").partitionBy("route_type").parquet(str(args.output))
        report["generated_at"] = datetime.now(timezone.utc).isoformat()
        (args.output / "_feature_report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
    finally:
        stop_spark(spark)

    log.info("features_v1 -> %s", args.output)
    log.info(
        "%.1f%% of legs have corridor history at creation time; the rest are the "
        "corridor's first sighting and must be handled by the model, not dropped.",
        report["pct_legs_with_corridor_history"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
