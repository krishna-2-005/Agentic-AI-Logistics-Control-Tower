"""Delay-threshold sensitivity (execution plan W5 D3-D4).

    python -m src.ml.threshold_sensitivity

D-003 moved the delay label from the blueprint's `T = 1.25` to `T = 2.00` in Week 2,
on one piece of evidence: the base rate. At 1.25, 93.6% of legs are "delayed", so a
classifier that says "delayed" to everything scores 93.6% accuracy while carrying no
information. That was the right call, but it was made in Week 1 with no models to
test it against -- the table in D-003 has a "% legs delayed" column and nothing else.

This asks the question D-003 could not yet ask: **what does each threshold do to every
classifier the project now has?** Same legs, same chronological split (D-022), same
features; only the label moves. At each of 1.15, 1.25, 1.50 (the plan's three) and 2.00
(the decided one) it re-scores:

* the majority class -- the do-nothing baseline D-003 rule 3 requires beside everything;
* OSRM, the corridor mean and the linear regressor, each thresholded (their gap
  predictions do not change with T; only the line they are measured against does);
* the **champion** GBT regressor, thresholded -- the model the stream actually runs;
* logistic regression, **refit** at each T, because a classifier trained on one label
  does not answer a question asked of another.

Why MCC is in the table
-----------------------
At `T = 1.15`, 96% of legs are positive, and the majority class -- which predicts
"delayed" for every leg -- scores an F1 near 0.98. F1 cannot see the trap D-003 was
about: it rewards the trivial classifier exactly when positives dominate. The Matthews
correlation coefficient is zero for any constant prediction whatever the base rate, so
it is the column that says whether a model knows anything at a given threshold.
Balanced accuracy is beside it for the same reason.

The label comes from `src.ml.baselines.delay_label` -- one helper, the same one the
training label, the thresholded predictions and the stream's fact events use (P-42).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from pyspark.ml import PipelineModel
from pyspark.sql import SparkSession
from sklearn.metrics import balanced_accuracy_score, matthews_corrcoef

from src.common import config, docs
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark
from src.ml.baselines import (
    CLASSIFIER_TARGET,
    FEATURES,
    TARGET,
    add_delay_label,
    corridor_mean_predictions,
    delay_label,
    evaluate_classifier,
    fit_linear_regression,
    fit_logistic_regression,
    load_features,
    majority_class_predictions,
    osrm_predictions,
    prepare_model_features,
    threshold_to_label,
    time_split,
)

log = get_logger("ml.threshold_sensitivity")

#: The plan's three, plus the decided one as the reference row.
THRESHOLDS = (1.15, 1.25, 1.50, 2.00)

#: D-003's Week 1 table, measured before any model existed -- kept so the sweep can show
#: its own base rates reproduce it rather than asserting they do.
D003_PCT_DELAYED = {1.15: 96.0, 1.25: 93.6, 1.50: 83.6, 2.00: 49.6}

OUT_CSV = config.BENCHMARKS_RAW_DIR / "w5_threshold_sensitivity.csv"
OUT_JSON = config.BENCHMARKS_RAW_DIR / "w5_threshold_sensitivity.json"
DOC_PATH = config.DOCS_DIR / "W5_lahari_stream_validation.md"

MODEL_ORDER = [
    "majority_class", "OSRM_threshold", "corridor_mean_threshold",
    "linear_regression_threshold", "champion_threshold", "logistic_regression",
]


def champion_gap_predictions(spark: SparkSession, frame: pd.DataFrame) -> np.ndarray:
    """The champion's predicted `gap_min` for every row of `frame`, in `frame`'s order.

    Scored here because Week 4 saved the champion's metrics but not its test-set
    predictions. A `_row` index rides through the transform because Spark does not
    promise `toPandas()` returns rows in the order they went in -- the same guard
    Lahari's stream-equals-batch test uses, for the same reason.
    """
    champion_path = config.MODELS_DIR / "champion"
    if not champion_path.exists():
        raise FileNotFoundError(f"No champion at {champion_path} -- run `python -m src.automation.retrain`.")
    model = PipelineModel.load(str(champion_path))
    sdf = spark.createDataFrame(frame[FEATURES].assign(_row=np.arange(len(frame))))
    scored = model.transform(sdf).select("_row", "prediction").toPandas().sort_values("_row")
    return scored["prediction"].to_numpy()


def extra_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """MCC and balanced accuracy: the two columns a constant prediction cannot game."""
    constant = len(np.unique(y_pred)) == 1
    return {
        # sklearn returns 0.0 for a constant prediction already; stated explicitly so
        # the zero reads as a property of the metric rather than an accident.
        "mcc": 0.0 if constant else round(float(matthews_corrcoef(y_true, y_pred)), 4),
        "balanced_accuracy": round(float(balanced_accuracy_score(y_true, y_pred)), 4),
        "alert_rate": round(float(np.mean(y_pred)), 4),
    }


def sweep(train: pd.DataFrame, test: pd.DataFrame, champion_test_gap: np.ndarray) -> pd.DataFrame:
    """Every model, at every threshold, scored on the same test legs."""
    linear = fit_linear_regression(train)  # a gap regressor: fit once, threshold-free
    linear_test_gap = linear.predict(test[FEATURES])
    planned = test["planned_min"].to_numpy()

    rows = []
    for threshold in THRESHOLDS:
        relabelled = train.assign(**{CLASSIFIER_TARGET: delay_label(train[TARGET], train["planned_min"], threshold)})
        y_true = delay_label(test[TARGET], test["planned_min"], threshold)
        classifier = fit_logistic_regression(relabelled)
        predictions = {
            "majority_class": majority_class_predictions(relabelled[CLASSIFIER_TARGET], len(test)),
            "OSRM_threshold": threshold_to_label(osrm_predictions(test), planned, threshold),
            "corridor_mean_threshold": threshold_to_label(corridor_mean_predictions(test), planned, threshold),
            "linear_regression_threshold": threshold_to_label(linear_test_gap, planned, threshold),
            "champion_threshold": threshold_to_label(champion_test_gap, planned, threshold),
            "logistic_regression": classifier.predict(test[FEATURES]),
        }
        for name, y_pred in predictions.items():
            rows.append({
                "threshold": threshold,
                "model": name,
                "pct_delayed_test": round(float(y_true.mean() * 100), 2),
                **evaluate_classifier(y_true, y_pred),
                **extra_metrics(y_true, y_pred),
            })
        log.info("T = %.2f: %.1f%% of test legs delayed", threshold, y_true.mean() * 100)
    return pd.DataFrame(rows)


def base_rates(pdf: pd.DataFrame) -> dict[float, float]:
    """% of *all* legs delayed at each threshold -- the figure D-003's table reports."""
    return {t: round(float(delay_label(pdf[TARGET], pdf["planned_min"], t).mean() * 100), 2) for t in THRESHOLDS}


def _pivot(results: pd.DataFrame, metric: str) -> pd.DataFrame:
    table = results.pivot(index="model", columns="threshold", values=metric).reindex(MODEL_ORDER)
    table.columns = [f"T = {t:.2f}" for t in table.columns]
    return table


def _md_table(table: pd.DataFrame, fmt: str = "{:.3f}") -> str:
    head = "| model | " + " | ".join(table.columns) + " |"
    rule = "|---|" + "---|" * len(table.columns)
    body = [
        f"| `{model}` | " + " | ".join(fmt.format(v) for v in row) + " |"
        for model, row in table.iterrows()
    ]
    return "\n".join([head, rule, *body])


def render_doc(results: pd.DataFrame, rates: dict[float, float], n_train: int, n_test: int, cutoff) -> str:
    """The generated section. Every number and every comparative sentence is computed."""
    decided = config.DELAY_THRESHOLD
    lines = [
        "## Delay-threshold sensitivity (D3-D4)",
        "",
        "*Generated by `python -m src.ml.threshold_sensitivity` -- regenerate rather than editing numbers by hand.*",
        "",
        f"Generated: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "",
        (
            f"Same {n_train + n_test:,} legs, same chronological split (D-022: {n_train:,} train, "
            f"{n_test:,} test, cut at `{cutoff}`), same features. Only the label moves. "
            "Logistic regression is refit at each threshold; the gap regressors are fit once "
            "and thresholded, because their predictions do not depend on where the line is drawn."
        ),
        "",
        "### Base rates reproduce D-003's Week 1 table",
        "",
        "| T | % of all legs delayed (this run) | D-003, Week 1 | % of test legs delayed |",
        "|---|---|---|---|",
    ]
    test_rates = results.drop_duplicates("threshold").set_index("threshold")["pct_delayed_test"]
    for t in THRESHOLDS:
        marker = " (decided)" if abs(t - decided) < 1e-9 else ""
        lines.append(f"| {t:.2f}{marker} | {rates[t]:.1f}% | {D003_PCT_DELAYED[t]:.1f}% | {test_rates[t]:.1f}% |")

    mcc = _pivot(results, "mcc")
    f1 = _pivot(results, "f1")
    lines += [
        "",
        "### MCC -- the column a constant prediction cannot game",
        "",
        "Zero for any classifier that says the same thing about every leg, whatever the base rate.",
        "",
        _md_table(mcc),
        "",
        "### F1 -- shown so the trap is visible, not because it settles anything",
        "",
        _md_table(f1),
        "",
    ]

    majority_low = results[(results["model"] == "majority_class") & (results["threshold"] == min(THRESHOLDS))].iloc[0]
    best_low = results[results["threshold"] == min(THRESHOLDS)].sort_values("mcc", ascending=False).iloc[0]
    lines.append(
        f"At T = {min(THRESHOLDS):.2f} the majority class -- \"delayed\" for every leg -- scores "
        f"F1 **{majority_low['f1']:.3f}** and MCC **{majority_low['mcc']:.3f}**. The best real model "
        f"there (`{best_low['model']}`) reaches MCC {best_low['mcc']:.3f}. That gap between the two "
        "columns is D-003's argument, now measured on models rather than inferred from a base rate."
    )

    lines += ["", "### Which model is best, at each threshold", "", "| T | best by MCC | MCC | its F1 | its alert rate |", "|---|---|---|---|---|"]
    for t in THRESHOLDS:
        best = results[results["threshold"] == t].sort_values("mcc", ascending=False).iloc[0]
        lines.append(f"| {t:.2f} | `{best['model']}` | {best['mcc']:.3f} | {best['f1']:.3f} | {best['alert_rate']:.1%} |")

    champion = results[results["model"] == "champion_threshold"].set_index("threshold")
    lines += [
        "",
        "### What each threshold would do to the alert stream",
        "",
        (
            "The streaming job flags a leg when the champion's predicted gap crosses the line "
            "(D-037), so the champion's alert rate at each T is the share of legs the Live alerts "
            "panel and the bot would receive."
        ),
        "",
        "| T | champion alert rate | precision | recall | MCC |",
        "|---|---|---|---|---|",
    ]
    for t in THRESHOLDS:
        row = champion.loc[t]
        lines.append(f"| {t:.2f} | {row['alert_rate']:.1%} | {row['precision']:.3f} | {row['recall']:.3f} | {row['mcc']:.3f} |")

    lines += [
        "",
        (
            "Full per-model, per-threshold table (accuracy, precision, recall, F1, MCC, balanced "
            "accuracy, alert rate, majority-class rate): `benchmarks/raw/w5_threshold_sensitivity.csv`."
        ),
    ]
    return "\n".join(lines)


def run(input_path: Path = config.FEATURES_V1, out_md: Path = DOC_PATH) -> dict:
    spark = get_spark("threshold-sensitivity")
    try:
        pdf = add_delay_label(load_features(spark, input_path))
        train_raw, test_raw, cutoff = time_split(pdf)
        train, test = prepare_model_features(train_raw), prepare_model_features(test_raw)
        champion_test_gap = champion_gap_predictions(spark, test)
    finally:
        stop_spark(spark)

    results = sweep(train, test, champion_test_gap)
    rates = base_rates(pdf)
    results.to_csv(OUT_CSV, index=False)
    report = {
        "thresholds": list(THRESHOLDS),
        "decided_threshold": config.DELAY_THRESHOLD,
        "legs": len(pdf),
        "n_train": len(train),
        "n_test": len(test),
        "split_cutoff": str(cutoff),
        "pct_delayed_all_legs": {str(t): v for t, v in rates.items()},
        "d003_week1_pct_delayed": {str(t): v for t, v in D003_PCT_DELAYED.items()},
        "results": results.to_dict(orient="records"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    docs.write_section(out_md, "threshold-sensitivity", render_doc(results, rates, len(train), len(test), cutoff))
    log.info("threshold sweep -> %s, %s, section in %s", OUT_CSV.name, OUT_JSON.name, out_md)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Delay-threshold sensitivity (W5 D3-D4)")
    parser.add_argument("--input", type=Path, default=config.FEATURES_V1)
    parser.add_argument("--out-md", type=Path, default=DOC_PATH)
    args = parser.parse_args()
    if not args.input.exists():
        log.error("Missing %s -- run `python -m src.pipeline.features` first.", args.input)
        return 1
    run(args.input, args.out_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
