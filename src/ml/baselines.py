"""Stage 5 — baselines: OSRM, the past-only corridor mean, and linear regression.

    python -m src.ml.baselines

Reads the frozen, leak-free feature table (`features_v1`, Stage 4) and fills in the
first three rows of the "baseline to beat" table in `benchmarks/ml_results.md`: how
far off the production planner already is, how much of that gap a corridor's own past
mean already explains, and what a linear model over the rest of the as-of features
buys on top of that. Random Forest and GBT are Week 4.

Grain and target
-----------------
One row per OD leg (D-002), 26,369 legs. Every model here predicts
`gap_min = actual_time - planned_min` rather than `actual_time` directly — the same
quantity Stage 4 refuses to leak a feature about — so a model's implied prediction of
`actual_time` is always `planned_min + predicted gap_min`, and MAE in minutes on one is
MAE in minutes on the other. Minutes rather than `log_gap_ratio` because that is what
the report table asks for.

D-005 promised a time-based split; this is where it gets fixed
----------------------------------------------------------------
D-005 (Week 1) decided the split would be on `trip_creation_time` rather than the
dataset's own `data` column, and left the exact cut to whichever week first trains
something. That is this week — see D-020. `time_split()` below is the one function
Week 4 must import rather than reimplement: a "beats these baselines" claim only means
something if the Week 4 model was trained on the same legs and scored on the same
held-out ones.

Cold start, and why the cold legs are never dropped
-----------------------------------------------------
11.09% of legs are a corridor's first sighting (`corr_n_prior == 0`) and carry no
corridor-mean feature at all — Stage 4's `_feature_report.json` calls this out
directly. Dropping them from the corridor-mean baseline's evaluation would shrink its
test set and its apparent error together, which is a free win from throwing away
exactly the legs the baseline cannot help with. They stay in every evaluated set. The
corridor-mean baseline falls back to OSRM's own prediction (zero gap) on a leg it has
no history for; the linear model gets an explicit `{corr,src,dst}_is_cold` indicator
per key alongside a zero-filled mean, so "no history yet" is a feature rather than a
silently wrong zero — see D-021.

Compute shape
-------------
One Spark read of the ~26K-row feature table, collected once. Everything after that —
the split, the two hand-built baselines, the OLS fit — runs in pandas/scikit-learn,
which is where it belongs: 26,369 rows is not a distributed workload, and scikit-learn
would not distribute it even if it were (`requirements.txt` calls this out: "sanity
baselines... alongside MLlib").
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from pyspark.sql import SparkSession
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from src.common import config, docs
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark

log = get_logger("ml.baselines")

#: What every model predicts. Never `actual_time` directly — see module docstring.
TARGET = "gap_min"

#: Fraction of legs, ordered by `trip_creation_time`, held out for training. D-020
#: fixes this at Week 3 per D-005. Week 4 must import this constant (or the function
#: below) rather than pick its own cut.
TIME_SPLIT_FRAC = 0.80

#: One as-of history triple per key Stage 4 accumulated over — corridor, source hub,
#: destination hub. Order matches `src.pipeline.features.as_of_history`'s output.
HISTORY_PREFIXES = ("corr", "src", "dst")
HISTORY_STATS = (
    "n_prior",
    "mean_log_ratio",
    "std_log_ratio",
    "mean_gap_min",
    "last_log_ratio",
    "hours_since_last",
)
#: Null on a cold leg (`{p}_n_prior == 0`) for every stat except `std_log_ratio`, which
#: is also null on a single-observation leg (`n_prior == 1`) — variance needs two
#: points. `n_prior` itself is never null (D-021).
COLD_ONLY_NULL_STATS = ("mean_log_ratio", "mean_gap_min", "last_log_ratio", "hours_since_last")

FEATURES = [
    "planned_min",
    "planned_km",
    "created_hour",
    "created_dayofweek",
    "created_is_weekend",
    "is_ftl",
] + [f"{p}_{s}" for p in HISTORY_PREFIXES for s in HISTORY_STATS] + [
    f"{p}_is_cold" for p in HISTORY_PREFIXES
]


def load_features(spark: SparkSession, path: Path) -> pd.DataFrame:
    """Read `features_v1` and collect it — 26,369 rows, one Spark pass."""
    sdf = spark.read.parquet(str(path))
    pdf = sdf.toPandas()
    log.info("%s feature rows, %s columns", f"{len(pdf):,}", len(pdf.columns))
    return pdf.sort_values("trip_creation_time").reset_index(drop=True)


def time_split(pdf: pd.DataFrame, frac: float = TIME_SPLIT_FRAC) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    """Chronological train/test split on `trip_creation_time` — D-020.

    Not a random split: a random split would score a model on legs that are, in wall
    clock, mixed in among the ones it trained on, which is not how the model would
    ever be deployed. The cut is a quantile of `trip_creation_time` rather than a
    fixed calendar date so the split fraction — the thing Week 4 actually needs to
    match — is invariant to the extract's exact date range.

    Every as-of feature in `features_v1` is already computed relative to each leg's
    own `trip_creation_time` (Stage 4), so this split cannot leak future corridor
    history into the training set regardless of where the cut falls — the cut only
    decides which legs the *models built here* are fitted and scored on.
    """
    cutoff = pdf["trip_creation_time"].quantile(frac)
    train = pdf[pdf["trip_creation_time"] <= cutoff].reset_index(drop=True)
    test = pdf[pdf["trip_creation_time"] > cutoff].reset_index(drop=True)
    return train, test, cutoff


def prepare_model_features(pdf: pd.DataFrame) -> pd.DataFrame:
    """Add `is_ftl` and per-key cold-start handling; return a copy safe for sklearn.

    `LinearRegression` cannot take a null, and a silent `fillna(0)` on
    `corr_mean_log_ratio` would tell the model "this corridor runs exactly on plan"
    for every corridor it has never seen — the opposite of not knowing. So every
    filled column is paired with an `{p}_is_cold` indicator carrying the fact that was
    actually observed (D-021): nothing here is knowable, not that it is knowable and
    zero.
    """
    out = pdf.copy()
    out["is_ftl"] = (out["route_type"] == "FTL").astype(int)
    for p in HISTORY_PREFIXES:
        cold = out[f"{p}_n_prior"] == 0
        out[f"{p}_is_cold"] = cold.astype(int)
        for s in HISTORY_STATS:
            if s == "n_prior":
                continue
            col = f"{p}_{s}"
            fill_mask = cold if s in COLD_ONLY_NULL_STATS else out[col].isna()
            assert not (out[col].isna() & ~fill_mask).any(), (
                f"{col} is null outside the documented cold/single-observation case — "
                "the null-handling policy above no longer matches Stage 4's output."
            )
            out[col] = out[col].fillna(0.0)
    return out


def cold_start_summary(pdf: pd.DataFrame) -> dict:
    return {f"pct_{p}_cold": round(float((pdf[f"{p}_n_prior"] == 0).mean() * 100), 2) for p in HISTORY_PREFIXES}


def evaluate(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """MAE in minutes, plus RMSE and R2 for a fuller diagnostic than the headline needs."""
    return {
        "n": len(y_true),
        "mae_min": round(float(mean_absolute_error(y_true, y_pred)), 2),
        "rmse_min": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 2),
        "r2": round(float(r2_score(y_true, y_pred)), 4),
    }


def osrm_predictions(pdf: pd.DataFrame) -> np.ndarray:
    """The planner's own estimate: zero predicted gap, i.e. `actual = planned`."""
    return np.zeros(len(pdf))


def corridor_mean_predictions(pdf: pd.DataFrame) -> np.ndarray:
    """Past-only mean gap per corridor (Stage 4), falling back to OSRM when cold.

    `corr_mean_gap_min` is already the leak-free quantity D-005 and Stage 4 exist to
    produce — nothing is refit here. A cold leg (11.09% of the table) has no corridor
    mean to fall back on, so it falls back to the OSRM baseline's own prediction
    (zero gap) rather than, say, the network mean, which would be a second baseline
    smuggled in under this one's name.
    """
    cold = pdf["corr_n_prior"] == 0
    return np.where(cold, 0.0, pdf["corr_mean_gap_min"].fillna(0.0))


def fit_linear_regression(train: pd.DataFrame) -> LinearRegression:
    model = LinearRegression()
    model.fit(train[FEATURES], train[TARGET])
    return model


def coefficient_table(model: LinearRegression) -> pd.DataFrame:
    return (
        pd.DataFrame({"feature": FEATURES, "coefficient": model.coef_})
        .assign(abs_coef=lambda d: d["coefficient"].abs())
        .sort_values("abs_coef", ascending=False)
        .drop(columns="abs_coef")
        .reset_index(drop=True)
        .assign(intercept=lambda d: [model.intercept_] + [None] * (len(d) - 1))
    )


W3_DOC_HEADER = """# W3 · Lahari — baselines

Week 3 deliverable: the first three rows of `benchmarks/ml_results.md`'s "baseline to
beat" table, and the time-based split D-005 deferred to this week.

Regenerate rather than editing numbers by hand:

```bash
python -m src.ml.baselines
```

Reads `data/processed/features_v1` (Stage 4, Mounika) and writes
`benchmarks/raw/w3_baseline_metrics.csv`, `w3_linreg_coefficients.csv`,
`w3_baseline_report.json`, and this section.
"""


def render_doc(train: pd.DataFrame, test: pd.DataFrame, cutoff: pd.Timestamp, metrics: pd.DataFrame, coefs: pd.DataFrame, cold: dict) -> str:
    o: list[str] = []
    o.append("# Baselines\n")
    o.append(
        "*Generated by `python -m src.ml.baselines` — regenerate rather than editing "
        "numbers by hand.*\n"
    )
    o.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")

    o.append("## 1. What is being predicted, and on what split\n")
    o.append(
        f"Every model predicts `gap_min = actual_time - planned_min` at OD-leg grain "
        f"(D-002), on the {len(train) + len(test):,}-leg `features_v1` table (Stage 4). "
        "MAE in minutes on `gap_min` is MAE in minutes on `actual_time`, since "
        "`planned_min` is known and identical for every model.\n"
    )
    o.append(
        f"**The split is chronological, not random — D-020, closing D-005.** Legs with "
        f"`trip_creation_time` on or before **{cutoff.floor('s')}** are training "
        f"({len(train):,} legs, {len(train) / (len(train) + len(test)) * 100:.0f}%); "
        f"everything after is held out ({len(test):,} legs). Every model here is fitted "
        "on train and scored on test only; train-set numbers are reported beside test "
        "purely as an overfitting check. **Week 4 must reuse `src.ml.baselines.time_split` "
        "rather than define its own cut** — a \"beats these baselines\" claim is only "
        "true if both were scored on the same held-out legs.\n"
    )

    o.append("## 2. Cold start — D-021\n")
    o.append(
        f"A leg is a corridor's/hub's first sighting on "
        f"{cold['pct_corr_cold']:.1f}% / {cold['pct_src_cold']:.1f}% / "
        f"{cold['pct_dst_cold']:.1f}% of legs (corridor / source hub / destination hub) "
        "and carries no as-of mean for that key (Stage 4). These legs are **never "
        "dropped** — the corridor-mean baseline falls back to OSRM's own prediction "
        "(zero gap) on them, and the linear model is given an explicit `is_cold` "
        "indicator per key alongside a zero-filled mean, so \"unknown\" is a feature "
        "rather than a silently wrong zero.\n"
    )

    o.append("## 3. Results\n")
    o.append("| Model | Split | n | MAE (min) | RMSE (min) | R2 |")
    o.append("|---|---|---|---|---|---|")
    for _, r in metrics.iterrows():
        bold = "**" if r["split"] == "test" else ""
        o.append(
            f"| {r['model']} | {r['split']} | {int(r['n']):,} | {bold}{r['mae_min']:.1f}{bold} "
            f"| {r['rmse_min']:.1f} | {r['r2']:.3f} |"
        )
    o.append("")

    osrm_test = metrics[(metrics["model"] == "OSRM") & (metrics["split"] == "test")].iloc[0]
    corr_test = metrics[(metrics["model"] == "corridor_mean") & (metrics["split"] == "test")].iloc[0]
    lin_test = metrics[(metrics["model"] == "linear_regression") & (metrics["split"] == "test")].iloc[0]
    o.append(
        f"**The corridor mean alone recovers {(1 - corr_test['mae_min'] / osrm_test['mae_min']) * 100:.0f}% "
        f"of OSRM's error** ({osrm_test['mae_min']:.1f} -> {corr_test['mae_min']:.1f} min MAE) "
        "using nothing but Stage 4's past-only per-corridor average — the number Week 4's "
        "Random Forest and GBT have to clear is this one, not OSRM's, or the headline "
        "overstates what a model contributes on top of a mean anyone could compute.\n"
    )
    o.append(
        "*Caveat to carry into the report, per Week 1's finding:* OSRM's error is "
        "one-sided (98.3% of legs under-predicted), so any model that learns the bias "
        "beats it easily — the corridor mean is the baseline that actually tests "
        "whether Week 4's models learn something beyond \"add the corridor's usual "
        "gap\", and both numbers belong in the report together "
        "(`docs/W1_lahari_data_dictionary_and_eda.md`).\n"
    )

    o.append("### The linear model does not clear the corridor mean — D-022\n")
    o.append(
        f"The full-feature linear regression scores {lin_test['mae_min']:.1f} min MAE on "
        f"test, **worse than the {corr_test['mae_min']:.1f} min corridor mean**, despite a "
        f"better RMSE ({lin_test['rmse_min']:.1f} vs {corr_test['rmse_min']:.1f}) and a "
        f"better R2 ({lin_test['r2']:.3f} vs {corr_test['r2']:.3f}). This is not a bug — OLS "
        "minimises squared error, which is exactly RMSE and R2's objective and not MAE's. "
        "The two metrics rank these two models in opposite order, which is why "
        "**D-022 fixes MAE, not RMSE or R2, as the metric Week 4 is judged on** — it is "
        "the metric `benchmarks/ml_results.md` was already tracking, and it is the one a "
        "reader means by \"average error in minutes\".\n"
    )
    o.append(
        "**Why squared error buys RMSE at MAE's expense here, specifically.** The audited "
        "network has corridors running up to 13.9x its own typical overrun (D-018) — "
        "genuine heavy-tailed outliers, not noise. A single set of global OLS coefficients "
        "has to spend some of its fit reducing squared error on those few extreme legs, "
        "which nudges predictions for the ordinary legs in between just enough to raise "
        "MAE over the whole set. The corridor mean cannot make this trade: each corridor "
        "gets its own local average, so an extreme corridor's history only ever biases "
        "predictions for that corridor, never for a calmer one sharing a global "
        "coefficient. **A model that is provably better by RMSE can be worse by the "
        "metric the report actually leads with**, and Week 4 evaluating both is now a "
        "requirement rather than a nice-to-have.\n"
    )

    o.append("## 4. Linear regression — largest coefficients\n")
    o.append(
        "Unstandardised OLS coefficients — read as minutes of `gap_min` per unit of "
        "the feature, holding the rest fixed. Not causal; a sanity check on what the "
        "model actually leans on.\n"
    )
    o.append("| Feature | Coefficient (min / unit) |")
    o.append("|---|---|")
    for _, r in coefs.head(10).iterrows():
        o.append(f"| `{r['feature']}` | {r['coefficient']:+.3f} |")
    o.append("")
    o.append(f"Intercept: {coefs['intercept'].iloc[0]:.2f} min. Full table in `benchmarks/raw/w3_linreg_coefficients.csv`.\n")

    o.append("## 5. What this hands on\n")
    o.append(
        "- **Week 4's Random Forest and GBT** are trained and scored with "
        "`src.ml.baselines.time_split(frac=0.80)` on this same `features_v1` table, "
        "and are compared against the corridor-mean row above, not only OSRM.\n"
        "- **The ablations** (`benchmarks/ml_results.md`) drop the corridor-history "
        "block or the temporal block from `FEATURES` here and refit — both blocks "
        "already exist as named prefixes, nothing new to build.\n"
        "- **The majority-class rate** (D-003) has nothing to attach to yet — every "
        "model here is a regressor on `gap_min`. It is reported the moment a "
        "classifier metric appears in this document, per D-003, not before.\n"
    )
    return "\n".join(o)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 5 — baselines")
    parser.add_argument("--input", type=Path, default=config.FEATURES_V1)
    parser.add_argument("--out-md", type=Path, default=config.DOCS_DIR / "W3_lahari_baselines.md")
    parser.add_argument("--split-frac", type=float, default=TIME_SPLIT_FRAC)
    args = parser.parse_args()

    if not args.input.exists():
        log.error("Missing %s — run `python -m src.pipeline.features` first.", args.input)
        return 1

    config.ensure_dirs()
    spark = get_spark("stage5-baselines")
    try:
        pdf = load_features(spark, args.input)
    finally:
        stop_spark(spark)

    train_raw, test_raw, cutoff = time_split(pdf, args.split_frac)
    train = prepare_model_features(train_raw)
    test = prepare_model_features(test_raw)
    cold = cold_start_summary(pdf)

    rows = []
    for split_name, split in (("train", train), ("test", test)):
        osrm_metrics = evaluate(split[TARGET].to_numpy(), osrm_predictions(split))
        corr_metrics = evaluate(split[TARGET].to_numpy(), corridor_mean_predictions(split))
        rows.append({"model": "OSRM", "split": split_name, **osrm_metrics})
        rows.append({"model": "corridor_mean", "split": split_name, **corr_metrics})
    model = fit_linear_regression(train)
    for split_name, split in (("train", train), ("test", test)):
        lin_metrics = evaluate(split[TARGET].to_numpy(), model.predict(split[FEATURES]))
        rows.append({"model": "linear_regression", "split": split_name, **lin_metrics})
    metrics = pd.DataFrame(rows)
    coefs = coefficient_table(model)

    raw = config.BENCHMARKS_RAW_DIR
    metrics.to_csv(raw / "w3_baseline_metrics.csv", index=False)
    coefs.to_csv(raw / "w3_linreg_coefficients.csv", index=False)

    report = {
        "legs": len(pdf),
        "split_frac": args.split_frac,
        "split_cutoff": str(cutoff),
        "n_train": len(train),
        "n_test": len(test),
        **cold,
        "metrics": rows,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (raw / "w3_baseline_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("Baseline tables -> %s", raw)

    docs.write_section(args.out_md, "baselines", render_doc(train, test, cutoff, metrics, coefs, cold), header=W3_DOC_HEADER)
    log.info("Baselines writeup -> %s (section: baselines)", args.out_md)

    osrm_test = metrics[(metrics["model"] == "OSRM") & (metrics["split"] == "test")].iloc[0]
    corr_test = metrics[(metrics["model"] == "corridor_mean") & (metrics["split"] == "test")].iloc[0]
    lin_test = metrics[(metrics["model"] == "linear_regression") & (metrics["split"] == "test")].iloc[0]
    log.info(
        "Test MAE (min): OSRM %.1f, corridor mean %.1f, linear regression %.1f, over %s legs.",
        osrm_test["mae_min"], corr_test["mae_min"], lin_test["mae_min"], f"{int(osrm_test['n']):,}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
