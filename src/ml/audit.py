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
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from scipy import stats
from statsmodels.stats.multitest import multipletests

from src.common import config, docs
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark

log = get_logger("ml.audit")

#: The test statistic. Set once here so the aggregate, the tests and the writeup
#: cannot drift onto different columns.
STAT = "log_gap_ratio"

#: Family-wise false-discovery rate for the corridor tests.
ALPHA = 0.05

#: Support thresholds the audit is re-run at, so the floor's cost is a table rather
#: than an assertion. This sweep is what settled D-018; 10 is now the decided floor.
SUPPORT_GRID = (10, 20, 30, 50, 100)

#: The old D-004 floor, kept as a robustness view rather than dropped. D-018 lowered
#: the audited set to 10 legs on the evidence that 30 was removing the finding, but
#: the high-support table is the one whose top rows carry no winner's curse — with 99
#: tests rather than 1,130, the largest effect size is far less likely to be a lucky
#: sample. Both are written; the report leads with the decided set and cites this one
#: beside it. `w2_corridor_audit_support30.csv`.
ROBUSTNESS_SUPPORT = 30


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


def audit_at(agg_pdf: pd.DataFrame, baseline: dict, min_support: int, alpha: float) -> pd.DataFrame:
    """The whole audit at one support threshold.

    The BH correction is re-run inside this function rather than sliced out of a
    single big correction, because the family of tests *is* the set of corridors that
    passed the threshold. Correcting over 578 corridors and then filtering to the 99
    would give the 99 different q-values than testing them alone — a threshold is a
    decision about what to test, not a filter applied after testing.
    """
    kept = agg_pdf[agg_pdf["n_legs"] >= min_support].reset_index(drop=True)
    return correct_and_rank(welch_against_network(kept, baseline), alpha)


def support_sensitivity(
    agg_pdf: pd.DataFrame, baseline: dict, thresholds: tuple[int, ...], alpha: float
) -> pd.DataFrame:
    """What the audit would have said at other support thresholds — D-004's revisit.

    D-004 fixed the minimum at 30 legs in Week 1 *in the abstract*, before any
    significance test existed, and asked to be revisited once one did. The trade-off
    is real in both directions: a lower threshold covers far more of the network but
    tests corridors with too few legs to detect anything, so it can easily find fewer
    bottlenecks while claiming broader coverage. This table is what that argument
    should be settled on.
    """
    rows = []
    for t in thresholds:
        audited = audit_at(agg_pdf, baseline, t, alpha)
        bottlenecks = audited["bottleneck_rank"].notna()
        rows.append(
            {
                "min_support": t,
                "corridors_tested": len(audited),
                "pct_of_corridors": round(len(audited) / baseline["corridors_total"] * 100, 1),
                "legs_covered": int(audited["n_legs"].sum()),
                "pct_of_legs": round(audited["n_legs"].sum() / baseline["n"] * 100, 1),
                "median_legs_per_corridor": float(audited["n_legs"].median()),
                "significant": int(audited["is_significant"].sum()),
                "bottlenecks": int(bottlenecks.sum()),
                "pct_tests_significant": round(audited["is_significant"].mean() * 100, 1),
                "max_excess_ratio": round(float(audited.loc[bottlenecks, "excess_ratio"].max()), 3)
                if bottlenecks.any()
                else None,
            }
        )
    return pd.DataFrame(rows)


def top_bottlenecks(audited: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """The ranked table the report and the India map both read.

    Facility names carry a `Bangalore_Nelmngla_H (Karnataka)` shape; the city columns
    are used instead so the table is readable and the map can join on them.
    """
    cols = [
        "bottleneck_rank",
        "corridor_id",
        "source_center",
        "destination_center",
        "source_city",
        "dest_city",
        "source_state",
        "dest_state",
        "n_legs",
        "median_gap_ratio",
        "excess_ratio",
        "mean_gap_min",
        "median_gap_min",
        "mean_osrm_time",
        "mean_actual_time",
        "mean_osrm_km",
        "mean_dwell_min",
        "ftl_share",
        "t_stat",
        "p_value",
        "q_value",
        "cohens_d",
    ]
    ranked = audited[audited["bottleneck_rank"].notna()].sort_values("bottleneck_rank")
    return ranked.head(n)[cols].reset_index(drop=True)


W2_DOC_HEADER = """# W2 · Lahari — corridor audit and hub friction ranking

Week 2 deliverable: the statistical audit of the production planner at corridor grain,
the ranked bottleneck table, and the confirmation of the hub-friction ranking metric
Stage 3 left open.

Both sections are generated — regenerate rather than editing numbers by hand:

```bash
python -m src.ml.audit                   # both sections, plus the benchmarks CSVs
python -m src.ml.audit --min-support 10  # the coverage view (see the threshold section)
```
"""


def _corridor_label(row: pd.Series) -> str:
    """`Bhiwandi -> Mumbai`, falling back to the centre code when the city is null."""
    src = row["source_city"] if isinstance(row["source_city"], str) else row["source_center"]
    dst = row["dest_city"] if isinstance(row["dest_city"], str) else row["destination_center"]
    return f"{src} -> {dst}"


def hub_ranking(
    spark: SparkSession, hubs_path: Path, corridors: pd.DataFrame, top_n: int = 20
) -> tuple[pd.DataFrame, dict]:
    """Confirm the hub-friction ranking metric against the corridor audit — D-015.

    Stage 3 emits two friction metrics per hub and ranks on `dwell_share`, leaving the
    choice for this analysis to confirm. Both metrics are internal to the dwell
    columns, so comparing them to each other settles nothing; the question is which
    one agrees with a measurement taken from a **different** column.

    The corridor audit is that measurement. `excess_ratio` is built from `actual_time`
    and `osrm_time`; `dwell_min` is built from `start_scan_to_end_scan − actual_time`.
    Neither contains the other, so a hub whose friction metric tracks the overrun of
    the corridors leaving it is measuring something real about the hub.

    Two diagnostics decide it:

    * **friction vs corridor overrun** — Spearman correlation of each metric with the
      mean `excess_ratio` of the corridors departing that hub. Higher is better.
    * **friction vs leg length** — the same correlation against the mean *planned*
      minutes of those corridors, which is the confound D-015 raised. Near zero is
      better: a metric that mostly ranks hubs by how long their legs happen to be is
      not measuring friction.
    """
    hubs = (
        spark.read.parquet(str(hubs_path))
        .filter("has_support")
        .toPandas()
        .sort_values("friction_rank")
        .reset_index(drop=True)
    )

    by_source = corridors.groupby("source_center").agg(
        audited_corridors_out=("corridor_id", "size"),
        mean_excess_ratio_out=("excess_ratio", "mean"),
        mean_planned_min_out=("mean_osrm_time", "mean"),
    )
    joined = hubs.join(by_source, on="centre_code", how="inner")

    def rho(a: str, b: str) -> float:
        return round(float(stats.spearmanr(joined[a], joined[b]).statistic), 4)

    share_top = set(hubs.nsmallest(top_n, "friction_rank")["centre_code"])
    minutes_top = set(hubs.nlargest(top_n, "median_dwell_min_out")["centre_code"])

    diagnostics = {
        "supported_hubs": len(hubs),
        "hubs_matched_to_audited_corridors": len(joined),
        "rank_corr_share_vs_minutes": round(
            float(
                stats.spearmanr(hubs["median_dwell_share_out"], hubs["median_dwell_min_out"]).statistic
            ),
            4,
        ),
        "top_n": top_n,
        "top_n_overlap": len(share_top & minutes_top),
        "share_vs_corridor_overrun": rho("median_dwell_share_out", "mean_excess_ratio_out"),
        "minutes_vs_corridor_overrun": rho("median_dwell_min_out", "mean_excess_ratio_out"),
        "share_vs_planned_leg_length": rho("median_dwell_share_out", "mean_planned_min_out"),
        "minutes_vs_planned_leg_length": rho("median_dwell_min_out", "mean_planned_min_out"),
    }

    cols = [
        "friction_rank",
        "centre_code",
        "city",
        "state",
        "n_legs_out",
        "n_corridors_out",
        "median_dwell_share_out",
        "median_dwell_min_out",
        "p90_dwell_min_out",
        "median_dwell_share_in",
        "median_dwell_min_in",
        "median_gap_ratio_out",
        "chain_break_rate",
    ]
    return hubs.head(top_n)[cols].reset_index(drop=True), diagnostics


#: City labels the dataset spells more than one way. Only used to *count* cities in
#: the prose below — never to key anything, which is the corridor centre pair (D-002).
#: The audit hit this the honest way: a count written as `source_city == "Bengaluru"`
#: silently missed every row the file spells `Bangalore`, and reported a cluster at
#: half its real size.
CITY_ALIASES = {
    "Bangalore": "Bengaluru",
    "BLR": "Bengaluru",
    "HBR": "Bengaluru",
    "BOM": "Mumbai",
    "Bombay": "Mumbai",
    "LowerParel": "Mumbai",
    "CCU": "Kolkata",
    "Calcutta": "Kolkata",
    "MAA": "Chennai",
    "Madras": "Chennai",
    "AMD": "Ahmedabad",
    "Amd": "Ahmedabad",
    "Amdavad": "Ahmedabad",
    "GGN": "Gurgaon",
    "Gurugram": "Gurgaon",
    "Del": "Delhi",
    "Janakpuri": "Delhi",
    "FBD": "Faridabad",
    "GZB": "Ghaziabad",
    "PNQ": "Pune",
    "Muzaffrpur": "Muzaffarpur",
}

#: Duplicated, knowingly: `src/dashboard/reference/india_city_coords.csv` carries the
#: same aliases plus coordinates, and the two lists can drift. Merging them means a
#: shared reference table neither the audit nor the dashboard owns, which is a Week 3
#: refactor across two members' areas rather than a Week 2 patch — raised as an open
#: item so it is a decision rather than an oversight.


def _canon_city(s: pd.Series) -> pd.Series:
    return s.replace(CITY_ALIASES)


def _both_directions_note(slow: pd.DataFrame, faster: pd.DataFrame) -> str:
    """Name a city pair that is in both tables, if one still is.

    The point being made is that the corridor key is the centre pair and not the city
    pair, so it needs a live example rather than a remembered one — the example that
    carried this paragraph before D-018 was `Delhi -> Gurgaon`, which was true of the
    30-leg tables and is not something to assume of any other family.
    """
    def pairs(df):
        return set(zip(_canon_city(df["source_city"]), _canon_city(df["dest_city"])))

    shared = sorted(p for p in pairs(slow) & pairs(faster) if all(isinstance(x, str) for x in p))
    if not shared:
        return (
            "**The centre codes are load-bearing in both tables.** City labels are for reading; "
            "the corridor key is the centre pair (D-002), and any rollup to city level has to "
            "average the pairs it covers rather than pick one.\n"
        )
    named = ", ".join(f"`{a} -> {b}`" for a, b in shared[:3])
    n = len(shared)
    plural = "" if n == 1 else "s"
    return (
        f"**The centre codes are load-bearing in both tables.** {n} city pair{plural} "
        f"appear{'s' if n == 1 else ''} in the bottleneck table *and* here — {named} — "
        "different facility pairs serving "
        "the same two cities, one of them among the worst corridors in the network and one among "
        "the best. City labels are for reading; the corridor key is the centre pair (D-002), and "
        "any rollup to city level has to average the pairs it covers rather than pick one.\n"
    )


def _faster_cluster_note(faster: pd.DataFrame) -> str:
    """Where the planner is reliably right, counted over canonical city names."""
    counts = _canon_city(faster["source_city"]).value_counts()
    if counts.empty:
        return ""
    city, n = counts.index[0], int(counts.iloc[0])
    share = n / len(faster) * 100
    return (
        f"{n} of the {len(faster):,} start in {city}, the largest single origin, and the top "
        f"three origins ({', '.join(counts.index[:3])}) carry "
        f"{int(counts.iloc[:3].sum())} between them. That is a real cluster but a modest one — "
        f"{share:.0f}% of the faster set from one city — so the reading is that the planner is "
        "calibrated in a handful of places rather than in one. Week 4's error analysis should "
        "check whether the model inherits that or corrects it.\n"
    )


def _bottlenecks(audited: pd.DataFrame) -> pd.DataFrame:
    """Every significantly-slower corridor, in rank order."""
    return audited[audited["bottleneck_rank"].notna()].sort_values("bottleneck_rank")


def _places(top: pd.DataFrame, n: int = 4) -> str:
    """The states a ranked table actually sits in, most-represented first.

    The characterisation of a top-N table is the sentence most likely to be carried
    over from a previous run and quietly stop being true — which is exactly what
    happened to this one when D-018 moved the floor. Counting is cheap; remembering
    is not reliable.
    """
    counts = top["source_state"].value_counts().head(n)
    parts = [f"{state} ({int(c)})" for state, c in counts.items()]
    return ", ".join(parts)


def _geography_shift(top: pd.DataFrame, robust_top: pd.DataFrame, b: dict) -> str:
    """How the ranked table changes between the decided floor and the old one.

    Worth a paragraph rather than a footnote: the two tables do not merely differ in
    length, they describe different parts of the country, and a reader who knows the
    Week 1 version of this section would otherwise carry the old reading forward.
    """
    kept = len(set(top["corridor_id"]) & set(robust_top["corridor_id"]))
    intra_new = int((top["source_city"] == top["dest_city"]).sum())
    intra_old = int((robust_top["source_city"] == robust_top["dest_city"]).sum())
    if kept == 0:
        overlap = "The two top tables share no corridor at all."
    else:
        overlap = f"The two top tables share {kept} corridor{'' if kept == 1 else 's'}."
    return (
        "**Lowering the floor changed which India the table is describing, and that is a "
        f"finding rather than a side effect.** The {b['robustness_support']}-leg table was a "
        f"metro table — {_places(robust_top)} — with {intra_old} of its {len(robust_top)} rows "
        "beginning and ending in the same city, and it read as a story about urban congestion. "
        f"The {b['min_support']}-leg table is mostly not that: {_places(top)}, with "
        f"{intra_new} of {len(top)} intra-city, and its entries are district feeders between "
        f"towns rather than legs inside a metro. {overlap}\n"
        "\nBoth readings are true of the thing each was measured on, and neither replaces the "
        "other. What the busy core suffers from is city traffic; what the network's worst "
        "corridors suffer from is something else, on thin-support routes the high-support view "
        "could not see at all. Week 4's error analysis should not assume one model explains "
        f"both, and the {b['robustness_support']}-leg table stays in `benchmarks/raw/` so the "
        "metro claim keeps its own evidence.\n"
    )


def render_audit(
    audited: pd.DataFrame, robust: pd.DataFrame, sensitivity: pd.DataFrame, baseline: dict
) -> str:
    """The corridor-audit section of the weekly document.

    `robust` is the same audit at the old D-004 floor. It is passed in rather than
    recomputed because the interesting sentence about the bottleneck table is not what
    is in it but how it differs from the high-support view — and a claim about that
    difference has to be measured, not remembered from the previous run.
    """
    o: list[str] = []
    top = top_bottlenecks(audited)
    robust_top = top_bottlenecks(robust)
    faster = audited[audited["is_significant"] & (audited["direction"] == "better")]
    b = baseline

    o.append("# Corridor audit\n")
    o.append(
        "*Generated by `python -m src.ml.audit` — regenerate rather than editing numbers "
        "by hand.*\n"
    )
    o.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    o.append("## 1. The question the audit can actually answer\n")
    o.append(
        f"Week 1 measured the planner's error and found it one-sided: OSRM under-predicts on "
        f"98.3% of legs and the median leg runs at {b['median_gap_ratio']:.2f}x plan, "
        f"{b['mean_gap_min']:.0f} minutes over on average. **That already answers “is the "
        "planner wrong?” — everywhere, yes.** Testing each corridor against the plan would "
        f"return the same verdict {b['corridors_supported']:,} times and rank nothing.\n"
    )
    o.append(
        "So the audit asks the localisation question instead: *given* a network that runs at "
        "twice its plan, which corridors run over by more than this network's own typical leg? "
        "Every test below compares a corridor against **the other 26,000-odd legs**, never "
        "against the planner's 1.0. The effect size that comes out — `excess_ratio` — reads as "
        "“this corridor's typical overrun is N times the network's typical overrun”, so "
        "1.0 means ordinary and 1.5 means half again as bad as an already-bad network.\n"
    )
    o.append("| Choice | Value | Why |")
    o.append("|---|---|---|")
    o.append("| Grain | OD leg | D-002 — the trip columns are cumulative within a leg |")
    o.append(
        "| Statistic | `log(actual_time / osrm_time)` | the raw ratio is right-skewed "
        f"(up to {audited['median_gap_ratio'].max():.1f}x at a corridor's median) |"
    )
    o.append(
        "| Test | Welch t-test, corridor vs rest of network | unequal n "
        f"({int(audited['n_legs'].min())}–{int(audited['n_legs'].max())} against ~26,300), no "
        "equal-variance assumption |"
    )
    o.append(
        f"| Correction | Benjamini-Hochberg, FDR {b['alpha']:.2f} | "
        f"{b['corridors_supported']} simultaneous tests would otherwise carry about "
        f"{b['corridors_supported'] * b['alpha']:.0f} invented bottlenecks into a top-20 table |"
    )
    o.append(
        f"| Minimum support | {b['min_support']} legs | D-018 — D-004's floor of "
        f"{b['robustness_support']} legs, revisited on the evidence in §4 |"
    )
    o.append("")

    o.append("## 2. What the audit found\n")
    o.append("| Result | Value |")
    o.append("|---|---|")
    o.append(f"| Corridors in the network | {b['corridors_total']:,} |")
    o.append(
        f"| Corridors with >= {b['min_support']} legs (tested) | "
        f"**{b['corridors_supported']:,}** "
        f"({b['corridors_supported'] / b['corridors_total'] * 100:.1f}%) |"
    )
    o.append(
        f"| Legs those corridors cover | {b['legs_covered']:,} of {b['n']:,} "
        f"({b['legs_covered'] / b['n'] * 100:.1f}%) |"
    )
    o.append(
        f"| Differ from the network at FDR {b['alpha']:.2f} | **{b['significant']:,}** of "
        f"{b['corridors_supported']:,} "
        f"({b['significant'] / b['corridors_supported'] * 100:.0f}%) |"
    )
    o.append(f"| — significantly **slower** (bottlenecks) | **{b['bottlenecks']}** |")
    o.append(f"| — significantly **faster** | **{b['faster_than_network']}** |")
    o.append(
        f"| Worst corridor's excess ratio | {top['excess_ratio'].max():.2f}x the network's "
        "typical overrun |"
    )
    o.append("")
    o.append(
        f"**The error localises.** {b['significant']:,} of {b['corridors_supported']:,} tested "
        "corridors are distinguishable from the network baseline after correction, which is the "
        "result the rest of the project stands on: a systematic planner error that varies by "
        "corridor is one a model can learn and an agent can act on. Had the gap been uniform "
        "noise, Week 4's per-corridor claim would have had nothing to say.\n"
    )
    o.append(
        f"**It localises in both directions, and the report has to say so.** "
        f"{b['faster_than_network']:,} corridors are significantly *faster* than the network — the "
        "planner is not uniformly optimistic by a varying amount, it is differently wrong in "
        "different places. Calling this a “bottleneck audit” and showing only the slow "
        "half would misdescribe what was measured.\n"
    )

    o.append(f"### Top {len(top)} bottlenecks\n")
    o.append(
        "Ranked on **effect size, not p-value**. A p-value grows with support, so ranking on it "
        "would put the busiest corridors on top however mild their overrun. Significance decides "
        "who is on the list; `excess_ratio` decides the order.\n"
    )
    o.append(
        f"**Read the leg column before the effect size.** With {b['corridors_supported']:,} "
        "corridors tested (D-018), the single largest `excess_ratio` in the family is by "
        "construction the likeliest of all of them to be a lucky sample — winner's curse, and it "
        "bites hardest at exactly the rows a reader looks at first. Every row therefore prints "
        f"the legs it rests on, and a corridor sitting near the {int(b['min_support'])}-leg floor "
        "is a weaker claim than one resting on a hundred legs however large its ratio. The "
        f"{b['robustness_support']}-leg set in "
        f"`benchmarks/raw/w2_corridor_audit_support{b['robustness_support']}.csv` is the "
        f"comparison view — {b['robustness_corridors']} corridors, "
        f"{b['robustness_bottlenecks']} bottlenecks, worst "
        f"{b['robustness_max_excess']:.2f}x — small enough a family that its top rows carry no "
        "curse worth naming.\n"
    )
    o.append(
        "| # | Corridor | Centres | Legs | Median actual/plan | Excess vs network | "
        "Mean gap (min) | Planned (min) | q |"
    )
    o.append("|---|---|---|---|---|---|---|---|---|")
    for _, r in top.iterrows():
        o.append(
            f"| {int(r['bottleneck_rank'])} | {_corridor_label(r)} | `{r['corridor_id']}` "
            f"| {int(r['n_legs'])} | {r['median_gap_ratio']:.2f}x "
            f"| **{r['excess_ratio']:.2f}x** | {r['mean_gap_min']:.0f} "
            f"| {r['mean_osrm_time']:.0f} | {r['q_value']:.1e} |"
        )
    o.append("")
    o.append(
        f"The table is short-haul: the median entry is a "
        f"{top['mean_osrm_time'].median():.0f}-minute planned leg over "
        f"{top['mean_osrm_km'].median():.0f} km, and across all {b['bottlenecks']:,} bottlenecks "
        f"the median is {_bottlenecks(audited)['mean_osrm_km'].median():.0f} km. Short legs "
        "overrun proportionally more (§3), so a ranking on a ratio finds them, and the headline "
        "is a claim about the network's short legs rather than about long-haul planning.\n"
    )
    o.append(_geography_shift(top, robust_top, b))

    o.append(f"### The {len(faster)} corridors the planner over-estimates\n")
    o.append("| Corridor | Centres | Legs | Median actual/plan | Excess vs network | q |")
    o.append("|---|---|---|---|---|---|")
    for _, r in faster.nsmallest(5, "excess_ratio").iterrows():
        o.append(
            f"| {_corridor_label(r)} | `{r['corridor_id']}` | {int(r['n_legs'])} "
            f"| {r['median_gap_ratio']:.2f}x | {r['excess_ratio']:.2f}x | {r['q_value']:.1e} |"
        )
    o.append("")
    o.append(_both_directions_note(_bottlenecks(audited), faster))
    o.append(_faster_cluster_note(faster))

    o.append("## 3. What the ranking is not\n")
    corr_km = audited["excess_ratio"].corr(audited["mean_osrm_km"], method="spearman")
    corr_n = audited["excess_ratio"].corr(audited["n_legs"], method="spearman")
    corr_ftl = audited["excess_ratio"].corr(audited["ftl_share"], method="spearman")
    o.append(
        "Three checks that the order is not an artefact of something else, Spearman over the "
        f"{b['corridors_supported']} tested corridors:\n"
    )
    o.append("| `excess_ratio` vs | rho | Reading |")
    o.append("|---|---|---|")
    o.append(f"| planned distance (km) | {corr_km:+.2f} | short corridors overrun proportionally more |")
    o.append(f"| legs observed | {corr_n:+.2f} | it is not a traffic ranking |")
    o.append(f"| FTL share | {corr_ftl:+.2f} | nor a route-type ranking |")
    o.append("")

    o.append("## 4. The support threshold — D-004 revisited\n")
    o.append(
        f"D-004 fixed the minimum at {b['robustness_support']} legs in Week 1, in the abstract, "
        "before any significance test existed — and asked to be revisited once one did. "
        "Re-running the whole audit at each threshold (aggregate, Welch, and a fresh BH "
        "correction over whatever family the threshold defines) gives this:\n"
    )
    o.append(
        "| Min legs | Corridors tested | % of corridors | % of legs covered | Significant | "
        "Bottlenecks | Worst excess ratio |"
    )
    o.append("|---|---|---|---|---|---|---|")
    for _, r in sensitivity.iterrows():
        if int(r["min_support"]) == b["min_support"]:
            mark = " **(D-018 — decided)**"
        elif int(r["min_support"]) == b["robustness_support"]:
            mark = " *(D-004, superseded)*"
        else:
            mark = ""
        worst = f"{r['max_excess_ratio']:.2f}x" if pd.notna(r["max_excess_ratio"]) else "—"
        o.append(
            f"| {int(r['min_support'])}{mark} | {int(r['corridors_tested']):,} "
            f"| {r['pct_of_corridors']:.1f}% | {r['pct_of_legs']:.1f}% "
            f"| {int(r['significant']):,} | {int(r['bottlenecks']):,} | {worst} |"
        )
    o.append("")
    row10 = sensitivity[sensitivity["min_support"] == SUPPORT_GRID[0]].iloc[0]
    row30 = sensitivity[sensitivity["min_support"] == b["robustness_support"]].iloc[0]
    o.append(
        f"**The threshold was not costing coverage so much as costing the finding.** At "
        f"{int(row30['min_support'])} legs the audit speaks for {row30['pct_of_legs']:.1f}% of "
        f"the network's legs and its worst corridor runs {row30['max_excess_ratio']:.2f}x the "
        f"network's overrun. At {int(row10['min_support'])} legs it speaks for "
        f"{row10['pct_of_legs']:.1f}% of legs, finds {int(row10['bottlenecks']):,} bottlenecks "
        f"instead of {int(row30['bottlenecks'])}, and the worst runs "
        f"**{row10['max_excess_ratio']:.1f}x**. The corridors that are genuinely broken are "
        f"mostly rare corridors, and a {int(row30['min_support'])}-leg floor removed them "
        "before the test ran.\n"
    )
    o.append(
        f"The share of tests that come back significant barely moves "
        f"({row10['pct_tests_significant']:.0f}% at {int(row10['min_support'])} legs against "
        f"{row30['pct_tests_significant']:.0f}% at {int(row30['min_support'])}), so the looser "
        "threshold is not buying significance with noise: Welch is valid at n = 10 and the "
        "comparison group is the whole 26,369-leg network either way.\n"
    )
    o.append(
        f"**Decided at the Week 2 sync — D-018: the audited set moves to "
        f"{int(row10['min_support'])} legs, and every ranked row prints the legs it rests on.** "
        f"`config.MIN_CORRIDOR_SUPPORT` is {b['min_support']}, so the table above and every "
        "number in this document are the audit at that floor. D-004 is superseded rather than "
        "overturned: its reasoning — that ranking 2,783 mostly-singleton corridors ranks noise — "
        "still holds, and a floor is still needed. What the sweep showed is that it was set one "
        "notch too high to see the thing it was built to find.\n"
    )
    o.append(
        f"**What the decision costs, kept in view.** Winner's curse at the top of a "
        f"{b['corridors_supported']:,}-test family is real, and it is why the leg count is now "
        "printed in every ranked row and why the "
        f"{b['robustness_support']}-leg set is still written to "
        f"`benchmarks/raw/w2_corridor_audit_support{b['robustness_support']}.csv` rather than "
        "dropped. A claim that survives both tables is worth putting in the paper; one that "
        "appears only at the top of the loose table is a lead, not a result. The two framings "
        "also answer different questions — *how bad does this network get* is the "
        f"{b['min_support']}-leg table, *what is reliably true of its busy core* is the "
        f"{b['robustness_support']}-leg one — and the report carries both.\n"
    )

    o.append("## 5. What this hands on\n")
    n_null_city = int(audited["source_city"].isna().sum() + audited["dest_city"].isna().sum())
    o.append(
        f"- **Krishna's India map** reads `benchmarks/raw/w2_corridor_audit.csv` — "
        "`bottleneck_rank` and `excess_ratio` for the colour scale, city columns to read by. "
        f"**{n_null_city} of the {len(audited) * 2} city fields in the audited set are still "
        "null**, because a facility named `Mumbai Hub (Maharashtra)` does not match the "
        "`City_Facility_Type (State)` shape Stage 1's city parser expects. The map no longer "
        "inherits them — it re-derives the city from the raw facility name with a parser that "
        "splits on either separator (P-21) — but the null is still in this cache, and anything "
        "else joining on these columns will hit it. Fixing it at source means a new `clean_v2` "
        "under D-016's versioning rule, which is Week 3 work, not a Week 2 patch.\n"
        "- **Week 3 features** get per-corridor `excess_ratio` as corridor history — but computed "
        "past-only inside the training window. The value in this table is fitted on the whole "
        "period and is a *reporting* number; using it as a feature as it stands would leak.\n"
        f"- **Week 4's per-corridor claim** has {b['bottlenecks']} named slow corridors and "
        f"{b['faster_than_network']} fast ones to be evaluated on separately. “Beats OSRM "
        "overall” is a much weaker sentence than “beats OSRM where OSRM is worst”.\n"
        "- **Week 6's Invoice Auditor** can ask what a leg on a named corridor should have taken: "
        "`mean_actual_time` per corridor is in `w2_corridor_audit.csv`, now covering "
        f"{b['legs_covered'] / b['n'] * 100:.1f}% of the network's legs rather than 18.9%, so far "
        "fewer invoices will fall on a corridor the auditor has no history for.\n"
    )
    return "\n".join(o)


def render_hub_ranking(hubs: pd.DataFrame, diag: dict) -> str:
    """The hub-ranking section — the confirmation D-015 asked for."""
    o: list[str] = []
    o.append("# Hub friction ranking\n")
    o.append(
        "Stage 3 emits two friction metrics per hub and ranks on `dwell_share = dwell_min / "
        "start_scan_to_end_scan`, leaving the choice for the audit to confirm (D-015). The two "
        f"rankings genuinely disagree — Spearman {diag['rank_corr_share_vs_minutes']:.2f}, "
        f"sharing {diag['top_n_overlap']} of the top {diag['top_n']} hubs — so which one is "
        "picked changes the leaderboard and cannot be left implicit.\n"
    )

    o.append("## Confirming it against a column neither metric contains\n")
    o.append(
        "Comparing the two dwell metrics to each other settles nothing: both are built from the "
        "same two columns. The corridor audit is an independent measurement — `excess_ratio` "
        "comes from `actual_time` and `osrm_time`, dwell comes from `start_scan_to_end_scan − "
        "actual_time` — so each metric can be scored against the corridors leaving the hub. Over "
        f"the {diag['hubs_matched_to_audited_corridors']} supported hubs that appear as an origin "
        "in the audited set:\n"
    )
    o.append("| Spearman rho | `dwell_share` | `dwell_min` | Wanted |")
    o.append("|---|---|---|---|")
    o.append(
        f"| vs mean corridor `excess_ratio` | {diag['share_vs_corridor_overrun']:+.2f} "
        f"| {diag['minutes_vs_corridor_overrun']:+.2f} | high |"
    )
    o.append(
        f"| vs mean **planned** leg minutes | {diag['share_vs_planned_leg_length']:+.2f} "
        f"| {diag['minutes_vs_planned_leg_length']:+.2f} | near zero |"
    )
    o.append("")
    o.append(
        f"**D-015 confirmed: rank on `dwell_share`.** Raw dwell minutes correlate "
        f"{diag['minutes_vs_planned_leg_length']:+.2f} with how long a hub's legs are *planned* "
        "to take — a column neither dwell metric is built from, so this is D-015's suspected "
        "confound measured from outside rather than argued. A leaderboard on raw minutes would "
        "substantially be a leaderboard of hubs that happen to serve long legs. `dwell_share` "
        f"runs {diag['share_vs_planned_leg_length']:+.2f} against the same column, which is what "
        "a roughly fixed per-leg hub cost looks like when it is spread over legs of different "
        "lengths.\n"
    )
    o.append(
        "**And a second finding, which deserves its own line in the report: hub friction is not "
        "corridor friction.** Neither metric tracks the overrun of the corridors leaving the hub "
        f"({diag['share_vs_corridor_overrun']:+.2f} and "
        f"{diag['minutes_vs_corridor_overrun']:+.2f}). Time a shipment spends idle at a facility "
        "and the planner being wrong about the road between facilities are close to independent "
        "here. Two consequences: the India map and the hub leaderboard are two separate claims "
        "and must not be presented as one, and Week 3 should carry hub friction as its own "
        "feature rather than assume corridor history already contains it.\n"
    )

    o.append(f"## Top {len(hubs)} hubs by dwell share\n")
    o.append(
        "| # | Hub | City | State | Legs out | Dwell share (out) | Dwell min (out) | p90 min |"
    )
    o.append("|---|---|---|---|---|---|---|---|")
    for _, r in hubs.iterrows():
        city = r["city"] if isinstance(r["city"], str) else r["centre_code"]
        o.append(
            f"| {int(r['friction_rank'])} | `{r['centre_code']}` | {city} | {r['state']} "
            f"| {int(r['n_legs_out'])} | **{r['median_dwell_share_out']:.0%}** "
            f"| {r['median_dwell_min_out']:.0f} | {r['p90_dwell_min_out']:.0f} |"
        )
    o.append("")
    o.append(
        "Read the share column as *the fraction of a typical leg's wall clock the shipment spent "
        f"stationary at this hub before departing*. The top hub sits at "
        f"{hubs['median_dwell_share_out'].max():.0%} — most of that leg's elapsed time is dwell, "
        "not movement. Raw minutes stay in the table beside it because they are what a customer "
        "actually waits, and the report needs both framings.\n"
    )
    return "\n".join(o)


def build(
    spark: SparkSession, input_path: Path, min_support: int, alpha: float = ALPHA
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Run the aggregation and the tests.

    Returns `(audited, coverage, robust, sensitivity, baseline)` — `audited` at the
    decided support threshold (D-018: 10 legs), `coverage` the same audit at the
    loosest threshold on the grid, which is what the hub linkage correlates over, and
    `robust` the old 30-leg set kept as the no-winner's-curse comparison.
    """
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
    # Collected once at the loosest threshold the sensitivity table asks about, so the
    # threshold sweep is a filter on the driver rather than five more Spark jobs.
    agg_pdf = to_pandas(agg, min(SUPPORT_GRID + (min_support,)))
    legs.unpersist()

    baseline["corridors_total"] = int(n_corridors)
    audited = audit_at(agg_pdf, baseline, min_support, alpha)
    coverage = audit_at(agg_pdf, baseline, SUPPORT_GRID[0], alpha)
    robust = audit_at(agg_pdf, baseline, ROBUSTNESS_SUPPORT, alpha)
    sensitivity = support_sensitivity(agg_pdf, baseline, SUPPORT_GRID, alpha)

    baseline["corridors_supported"] = len(audited)
    baseline["legs_covered"] = int(audited["n_legs"].sum())
    baseline["min_support"] = min_support
    baseline["alpha"] = alpha
    baseline["significant"] = int(audited["is_significant"].sum())
    baseline["bottlenecks"] = int(audited["bottleneck_rank"].notna().sum())
    baseline["faster_than_network"] = int(
        (audited["is_significant"] & (audited["direction"] == "better")).sum()
    )
    # Quoted beside the headline so the winner's-curse caveat is a number, not a worry.
    baseline["robustness_support"] = ROBUSTNESS_SUPPORT
    baseline["robustness_corridors"] = len(robust)
    baseline["robustness_bottlenecks"] = int(robust["bottleneck_rank"].notna().sum())
    baseline["robustness_max_excess"] = float(robust["excess_ratio"].max())
    return audited, coverage, robust, sensitivity, baseline


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 3 — corridor audit")
    parser.add_argument("--input", type=Path, default=config.TRIPS_V1)
    parser.add_argument("--hubs", type=Path, default=config.HUBS_V1)
    parser.add_argument(
        "--out-md", type=Path, default=config.DOCS_DIR / "W2_lahari_corridor_audit.md"
    )
    parser.add_argument(
        "--min-support",
        type=int,
        default=config.MIN_CORRIDOR_SUPPORT,
        help="minimum observed legs before a corridor is audited (D-018)",
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
        corridors, coverage, robust, sensitivity, baseline = build(
            spark, args.input, args.min_support, args.alpha
        )
        hubs, hub_diag = hub_ranking(spark, args.hubs, coverage)
    finally:
        stop_spark(spark)

    raw = config.BENCHMARKS_RAW_DIR
    corridors.to_csv(raw / "w2_corridor_audit.csv", index=False)
    top = top_bottlenecks(corridors)
    top.to_csv(raw / "w2_top20_bottlenecks.csv", index=False)
    robust.to_csv(raw / f"w2_corridor_audit_support{ROBUSTNESS_SUPPORT}.csv", index=False)
    sensitivity.to_csv(raw / "w2_support_sensitivity.csv", index=False)
    hubs.to_csv(raw / "w2_hub_friction_top20.csv", index=False)
    baseline["hub_metric_check"] = hub_diag
    log.info("Corridor tables, support sweep and hub leaderboard -> %s", raw)

    docs.write_section(
        args.out_md, "corridor-audit", render_audit(corridors, robust, sensitivity, baseline),
        header=W2_DOC_HEADER,
    )
    docs.write_section(
        args.out_md, "hub-ranking", render_hub_ranking(hubs, hub_diag), header=W2_DOC_HEADER
    )
    log.info("Audit writeup -> %s (sections: corridor-audit, hub-ranking)", args.out_md)

    # The prose quotes these; the JSON is what makes each quoted number traceable
    # without re-running Spark. `sum`/`sumsq` are dropped as intermediates.
    report = {k: v for k, v in baseline.items() if k not in ("sum", "sumsq")}
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    (raw / "w2_audit_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
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
    worst = top.iloc[0]
    log.info(
        "Worst corridor: %s -> %s, %.2fx the network's typical overrun over %s legs "
        "(q = %.2g).",
        worst["source_city"],
        worst["dest_city"],
        worst["excess_ratio"],
        f"{int(worst['n_legs']):,}",
        worst["q_value"],
    )
    log.info(
        "Hub metric (D-015): dwell share tracks corridor overrun at rho %.2f vs %.2f "
        "for raw minutes, over %s hubs.",
        hub_diag["share_vs_corridor_overrun"],
        hub_diag["minutes_vs_corridor_overrun"],
        hub_diag["hubs_matched_to_audited_corridors"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
