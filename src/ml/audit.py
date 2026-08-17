"""Stage 3 — corridor audit: where is the production planner systematically wrong?

    python -m src.ml.audit
    python -m src.ml.audit --min-support 10

Reads the OD legs cached by Stage 2 (`trips_v1`) and produces one row per corridor
with enough support to say something about, writing
`benchmarks/raw/w2_corridor_audit.csv`.

What this is testing, and what it is deliberately not testing
-------------------------------------------------------------
Week 1 established that OSRM under-predicts on **98.3% of legs** and the median leg
runs at 2.00x the planned time. So the question "is this corridor slower than the
plan?" has the same answer everywhere — yes — and a test of it would rank nothing.

The audit's claim is **localisation**, not bias: *given* that the whole network runs
over plan, which corridors run over plan by more than the network's own typical leg?
Every statistic here is therefore relative to the network baseline, never to the
planner's estimate of 1.0.

The statistic is `log_gap_ratio = log(actual_time / osrm_time)` at OD-leg grain
(D-002), computed in Stage 2. Logs rather than the raw ratio because the ratio is
right-skewed — a handful of legs run at 50x plan and would drag any corridor mean
they land in.

Compute shape
-------------
One Spark pass produces the per-corridor aggregate; the network totals come from the
same pass. Everything after that runs on the ~100-row corridor table in pandas, which
is where the tests belong: `scipy` on 100 rows is not a distributed workload and
pretending it is would only hide the aggregation that genuinely is one.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from scipy import stats
from statsmodels.stats.multitest import multipletests

from src.common import config
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark

log = get_logger("ml.audit")

#: The test statistic. Set once here so the aggregate, the tests and the writeup
#: cannot drift onto different columns.
STAT = "log_gap_ratio"

#: Family-wise false-discovery rate for the corridor tests.
ALPHA = 0.05


def load_legs(spark: SparkSession, path: Path) -> DataFrame:
    """Read `trips_v1`, keeping only legs the statistic is defined on.

    Stage 2 already guarantees `osrm_time > 0` on every published leg, so nothing is
    expected to drop here. The filter stays because the audit must not silently
    average a null away if a future Stage 2 loosens that guarantee — the count of
    dropped legs is reported.
    """
    legs = spark.read.parquet(str(path))
    usable = legs.filter(
        F.col(STAT).isNotNull() & ~F.isnan(STAT) & (F.col("osrm_time") > 0)
    )
    return usable


def network_baseline(legs: DataFrame) -> dict:
    """Network-wide totals for `STAT`, as sums so a corridor's complement subtracts.

    Returning sums rather than mean/variance is what lets every corridor's
    "rest of the network" comparison group be derived by subtraction instead of by
    re-scanning the legs once per corridor.
    """
    row = legs.agg(
        F.count("*").alias("n"),
        F.sum(STAT).alias("sum"),
        F.sum(F.col(STAT) * F.col(STAT)).alias("sumsq"),
        F.mean("gap_min").alias("mean_gap_min"),
        F.expr("percentile_approx(gap_ratio, 0.5)").alias("median_gap_ratio"),
    ).collect()[0]
    n, s, ss = row["n"], float(row["sum"]), float(row["sumsq"])
    mean = s / n
    return {
        "n": int(n),
        "sum": s,
        "sumsq": ss,
        "mean_log": mean,
        "var_log": (ss - n * mean * mean) / (n - 1),
        "mean_gap_min": float(row["mean_gap_min"]),
        "median_gap_ratio": float(row["median_gap_ratio"]),
    }


def corridor_aggregate(legs: DataFrame) -> DataFrame:
    """One row per corridor: support, gap statistics, and the sums the tests need.

    `sum_log` / `sumsq_log` are carried through deliberately — they are what the
    Welch comparison group is built from, and recomputing them later would mean a
    second pass over 26,369 legs for no gain.
    """
    return (
        legs.groupBy("corridor_id")
        .agg(
            F.count("*").alias("n_legs"),
            F.countDistinct("trip_uuid").alias("n_trips"),
            F.first("source_center").alias("source_center"),
            F.first("destination_center").alias("destination_center"),
            F.first("source_name").alias("source_name"),
            F.first("destination_name").alias("destination_name"),
            F.first("source_city").alias("source_city"),
            F.first("dest_city").alias("dest_city"),
            F.first("source_state").alias("source_state"),
            F.first("dest_state").alias("dest_state"),
            F.sum(STAT).alias("sum_log"),
            F.sum(F.col(STAT) * F.col(STAT)).alias("sumsq_log"),
            F.mean("gap_ratio").alias("mean_gap_ratio"),
            F.expr("percentile_approx(gap_ratio, 0.5)").alias("median_gap_ratio"),
            F.mean("gap_min").alias("mean_gap_min"),
            F.expr("percentile_approx(gap_min, 0.5)").alias("median_gap_min"),
            F.mean("osrm_time").alias("mean_osrm_time"),
            F.mean("actual_time").alias("mean_actual_time"),
            F.mean("osrm_distance").alias("mean_osrm_km"),
            F.mean("dwell_min").alias("mean_dwell_min"),
            F.mean(F.col("route_type").eqNullSafe("FTL").cast("double")).alias("ftl_share"),
        )
        .withColumn("mean_log", F.col("sum_log") / F.col("n_legs"))
    )


def to_pandas(agg: DataFrame, min_support: int) -> pd.DataFrame:
    """Collect the supported corridors to the driver.

    Safe by construction: the support threshold (D-004) caps this at ~100 rows out of
    2,783 corridors. `--min-support 1` would collect all of them, which is why the
    row count is logged rather than assumed.
    """
    pdf = (
        agg.filter(F.col("n_legs") >= min_support)
        .orderBy(F.col("n_legs").desc())
        .toPandas()
    )
    log.info("  %s corridors at >= %s legs", f"{len(pdf):,}", min_support)
    return pdf


def welch_against_network(pdf: pd.DataFrame, baseline: dict) -> pd.DataFrame:
    """Welch's t-test of each corridor's `log_gap_ratio` against the rest of the network.

    **The comparison group is the network, not the plan.** Testing a corridor against
    zero — "is `actual` bigger than `osrm` here?" — would return yes for essentially
    all 99 corridors, because Week 1 found the planner under-predicts on 98.3% of
    legs. That result is already known and is not localisable. What the audit needs to
    know is whether a corridor is worse *than the rest of this same biased network*,
    which is the comparison made here.

    Welch rather than Student because the two groups are wildly unbalanced (30–151
    legs against ~26,300) and there is no reason to assume equal variance. The
    comparison group's mean and variance are recovered by subtracting the corridor's
    own sums from the network totals, so no corridor is compared against itself.

    Adds, per corridor:

    * `mean_log`, `var_log` — the corridor's own moments;
    * `rest_mean_log`, `rest_var_log` — the same for every other leg in the network;
    * `excess_ratio` — `exp(mean_log - rest_mean_log)`, the ratio of this corridor's
      geometric-mean overrun to the network's. 1.0 means "as bad as everywhere else";
    * `t_stat`, `dof`, `p_value` (two-sided), `cohens_d`.
    """
    n_c = pdf["n_legs"].to_numpy(dtype=float)
    sum_c = pdf["sum_log"].to_numpy(dtype=float)
    sumsq_c = pdf["sumsq_log"].to_numpy(dtype=float)
    mean_c = sum_c / n_c
    var_c = (sumsq_c - n_c * mean_c**2) / (n_c - 1)

    n_r = baseline["n"] - n_c
    sum_r = baseline["sum"] - sum_c
    sumsq_r = baseline["sumsq"] - sumsq_c
    mean_r = sum_r / n_r
    var_r = (sumsq_r - n_r * mean_r**2) / (n_r - 1)

    if (var_c < 0).any() or (var_r < 0).any():
        raise AssertionError(
            "Negative variance from the sum-of-squares identity — the aggregate and "
            "the network totals disagree. Do not report these p-values."
        )

    se_c, se_r = var_c / n_c, var_r / n_r
    se = np.sqrt(se_c + se_r)
    t = (mean_c - mean_r) / se
    dof = (se_c + se_r) ** 2 / (se_c**2 / (n_c - 1) + se_r**2 / (n_r - 1))
    pooled_sd = np.sqrt(((n_c - 1) * var_c + (n_r - 1) * var_r) / (n_c + n_r - 2))

    out = pdf.copy()
    out["mean_log"] = mean_c
    out["var_log"] = var_c
    out["rest_mean_log"] = mean_r
    out["rest_var_log"] = var_r
    out["excess_ratio"] = np.exp(mean_c - mean_r)
    out["t_stat"] = t
    out["dof"] = dof
    out["p_value"] = 2 * stats.t.sf(np.abs(t), dof)
    out["cohens_d"] = (mean_c - mean_r) / pooled_sd
    return out


def correct_and_rank(pdf: pd.DataFrame, alpha: float = ALPHA) -> pd.DataFrame:
    """Benjamini-Hochberg correction, then rank the confirmed bottlenecks.

    99 tests at α = 0.05 expect ~5 false positives by construction, and the whole
    point of the exercise is a *ranked list of named corridors* that other people will
    act on — so an uncorrected p-value here would put roughly five invented
    bottlenecks in a top-20 table. Benjamini-Hochberg rather than Bonferroni: the
    corridors are not independent (they share hubs and vehicles), FDR is the right
    error rate for a ranking, and Bonferroni over 99 tests would cost real power for
    the smaller corridors the audit is least sure about anyway.

    **`bottleneck_rank` is assigned on `excess_ratio`, not on the p-value.** A p-value
    is a statement about how much evidence there is, and evidence grows with support:
    ranking on it would put the busiest corridors on top no matter how mild their
    overrun. Significance decides *who is on the list*; effect size decides the order.
    """
    out = pdf.copy()
    reject, q, _, _ = multipletests(out["p_value"].to_numpy(), alpha=alpha, method="fdr_bh")
    out["q_value"] = q
    out["is_significant"] = reject
    out["direction"] = np.where(out["excess_ratio"] >= 1, "worse", "better")

    bottleneck = out["is_significant"] & (out["direction"] == "worse")
    out["bottleneck_rank"] = pd.NA
    out.loc[bottleneck, "bottleneck_rank"] = (
        out.loc[bottleneck, "excess_ratio"].rank(ascending=False, method="first").astype(int)
    )
    return out.sort_values(
        ["is_significant", "excess_ratio"], ascending=[False, False]
    ).reset_index(drop=True)


def build(
    spark: SparkSession, input_path: Path, min_support: int, alpha: float = ALPHA
) -> tuple[pd.DataFrame, dict]:
    """Run the aggregation, test it, and return (audited corridors, network baseline)."""
    legs = load_legs(spark, input_path).cache()
    n_usable = legs.count()
    n_total = spark.read.parquet(str(input_path)).count()
    if n_usable != n_total:
        log.warning(
            "%s of %s legs have no usable %s and are excluded from the audit",
            f"{n_total - n_usable:,}",
            f"{n_total:,}",
            STAT,
        )

    baseline = network_baseline(legs)
    log.info(
        "Network baseline: %s legs, median gap ratio %.2fx, mean gap %.0f min",
        f"{baseline['n']:,}",
        baseline["median_gap_ratio"],
        baseline["mean_gap_min"],
    )

    agg = corridor_aggregate(legs)
    n_corridors = agg.count()
    pdf = to_pandas(agg, min_support)
    legs.unpersist()

    audited = correct_and_rank(welch_against_network(pdf, baseline), alpha)

    baseline["corridors_total"] = int(n_corridors)
    baseline["corridors_supported"] = len(audited)
    baseline["legs_covered"] = int(audited["n_legs"].sum())
    baseline["min_support"] = min_support
    baseline["alpha"] = alpha
    baseline["significant"] = int(audited["is_significant"].sum())
    baseline["bottlenecks"] = int(audited["bottleneck_rank"].notna().sum())
    baseline["faster_than_network"] = int(
        (audited["is_significant"] & (audited["direction"] == "better")).sum()
    )
    return audited, baseline


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 3 — corridor audit")
    parser.add_argument("--input", type=Path, default=config.TRIPS_V1)
    parser.add_argument(
        "--min-support",
        type=int,
        default=config.MIN_CORRIDOR_SUPPORT,
        help="minimum observed legs before a corridor is audited (D-004)",
    )
    parser.add_argument(
        "--alpha", type=float, default=ALPHA, help="false-discovery rate for the BH correction"
    )
    args = parser.parse_args()

    if not args.input.exists():
        log.error("Missing %s — run `python -m src.pipeline.reconstruct` first.", args.input)
        return 1

    config.ensure_dirs()
    spark = get_spark("stage3-audit")
    try:
        corridors, baseline = build(spark, args.input, args.min_support, args.alpha)
    finally:
        stop_spark(spark)

    out = config.BENCHMARKS_RAW_DIR / "w2_corridor_audit.csv"
    corridors.to_csv(out, index=False)
    log.info("Corridor table -> %s", out)
    log.info(
        "%s of %s corridors carry >= %s legs, covering %.1f%% of the network's legs.",
        f"{baseline['corridors_supported']:,}",
        f"{baseline['corridors_total']:,}",
        baseline["min_support"],
        baseline["legs_covered"] / baseline["n"] * 100,
    )
    log.info(
        "%s corridors differ from the network at FDR %.2f: %s worse, %s faster.",
        baseline["significant"],
        baseline["alpha"],
        baseline["bottlenecks"],
        baseline["faster_than_network"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
