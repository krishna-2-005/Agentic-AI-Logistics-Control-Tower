"""How much does a replay's end-of-data history flatter the stream's alerts? (W8, D-053)

    python -m src.ml.replay_leakage --legs 2000

The streaming job joins each query to the **latest** history snapshot per key
(`job.latest_history`). On a live stream that is right: history up to now. On a replay of
past legs it is not — the snapshot is the state at the *end* of the data, so an early
replayed leg is scored against legs that finished after it, possibly including its own
outcome. Every alert-quality number measured on a replay (the Exception agent's precision
among them) inherits that.

This scores the same replayed legs two ways with the same champion model:

* **as-of** — the history columns exactly as `features_v1` holds them for that leg: only
  legs that had finished before it was created (D-020). What a live system would have known.
* **snapshot** — the event fields from the leg, the history from `job.latest_history`, which
  is what the replay actually did.

and compares each against what really happened. The difference is the leak.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime

import numpy as np
import pandas as pd
from pyspark.ml import PipelineModel

from src.common import config
from src.common.logging_setup import get_logger
from src.common.spark import get_spark, stop_spark
from src.ml.baselines import (
    FEATURES,
    HISTORY_PREFIXES,
    TARGET,
    delay_label,
    load_features,
    prepare_model_features,
)

log = get_logger("ml.replay_leakage")

OUT = config.BENCHMARKS_RAW_DIR / "w8_replay_leakage.json"


def _predict(spark, model: PipelineModel, frame: pd.DataFrame) -> np.ndarray:
    data = frame[FEATURES].copy()
    data["_row"] = np.arange(len(data))
    out = model.transform(spark.createDataFrame(data)).select("_row", "prediction").toPandas()
    return out.sort_values("_row")["prediction"].to_numpy()


def _alert_metrics(pred_gap: np.ndarray, frame: pd.DataFrame) -> dict:
    truth = delay_label(frame[TARGET].to_numpy(), frame["planned_min"].to_numpy()).astype(bool)
    alerted = delay_label(pred_gap, frame["planned_min"].to_numpy()).astype(bool)
    tp = int((alerted & truth).sum())
    return {
        "mae_min": round(float(np.mean(np.abs(pred_gap - frame[TARGET].to_numpy()))), 2),
        "alerts": int(alerted.sum()),
        "precision": round(tp / int(alerted.sum()), 4) if alerted.any() else None,
        "recall": round(tp / int(truth.sum()), 4) if truth.any() else None,
    }


def _grade(pred_gap: np.ndarray, frame: pd.DataFrame) -> dict:
    """Alerts as the stream would write them, then the Exception agent's grade and score."""
    from src.ml.exception_eval import grade_alerts, score

    threshold_gap = (config.DELAY_THRESHOLD - 1.0) * frame["planned_min"].to_numpy()
    alerted = pred_gap > threshold_gap
    alerts = frame.loc[alerted, ["leg_id", "corridor_id", "source_center", "destination_center",
                                 "corr_is_cold", "src_is_cold", "dst_is_cold"]].copy()
    alerts["alert_id"] = "replay-" + alerts["leg_id"]
    alerts["predicted_gap_min"] = np.round(pred_gap[alerted], 1)
    alerts["threshold_gap_min"] = np.round(threshold_gap[alerted], 1)
    truth = delay_label(frame[TARGET].to_numpy(), frame["planned_min"].to_numpy()).astype(int)
    facts = dict(zip(frame["leg_id"], truth, strict=True))
    scored = score(grade_alerts(alerts.reset_index(drop=True)), facts)
    return {k: scored[k] for k in ("alerts_scored", "notification_precision", "recall_of_all_delayed",
                                   "by_severity", "policies")}


def run(legs: int = 2000) -> dict:
    from src.streaming.job import KEY_COLUMN, latest_history

    champion = config.MODELS_DIR / "champion"
    spark = get_spark("replay-leakage")
    try:
        pdf = load_features(spark, config.FEATURES_V1).sort_values("trip_creation_time").reset_index(drop=True)
        replay = pdf.head(legs).copy()

        # As-of: the feature table's own history for each leg.
        as_of = prepare_model_features(replay.copy())

        # Snapshot: overwrite every history column with the end-of-data snapshot for its key.
        snap = replay.copy()
        for prefix in HISTORY_PREFIXES:
            key = KEY_COLUMN[prefix]
            history = latest_history(spark, prefix).toPandas()
            cols = [c for c in history.columns if c != key]
            snap = snap.drop(columns=[c for c in cols if c in snap.columns]).merge(history, on=key, how="left")
            snap[f"{prefix}_n_prior"] = snap[f"{prefix}_n_prior"].fillna(0)
        snapshot = prepare_model_features(snap)

        model = PipelineModel.load(str(champion))
        pred_as_of = _predict(spark, model, as_of)
        pred_snapshot = _predict(spark, model, snapshot)
    finally:
        stop_spark(spark)

    severity_as_of = _grade(pred_as_of, as_of)
    severity_snapshot = _grade(pred_snapshot, snapshot)

    n_prior_as_of = as_of["corr_n_prior"].to_numpy()
    n_prior_snap = snapshot["corr_n_prior"].to_numpy()
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "legs": len(as_of),
        "legs_replayed_first": "the earliest legs by creation time, as the producer replays them",
        "model": "data/models/champion (the served model)",
        "as_of": _alert_metrics(pred_as_of, as_of),
        "snapshot": _alert_metrics(pred_snapshot, snapshot),
        "median_corridor_history_legs": {"as_of": float(np.median(n_prior_as_of)),
                                         "snapshot": float(np.median(n_prior_snap))},
        "legs_cold_as_of_but_warm_in_snapshot": int(((n_prior_as_of == 0) & (n_prior_snap > 0)).sum()),
        "mean_abs_prediction_shift_min": round(float(np.mean(np.abs(pred_snapshot - pred_as_of))), 2),
        # The Exception agent's own grading and scoring, run on each alert set. The snapshot
        # half should reproduce w6_exception_eval.json; the as-of half is what it would have
        # measured without the leak.
        "exception_agent_as_of": severity_as_of,
        "exception_agent_snapshot": severity_snapshot,
    }
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info("as-of %s | snapshot %s", summary["as_of"], summary["snapshot"])
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure the replay's end-of-data history leak")
    parser.add_argument("--legs", type=int, default=2000)
    args = parser.parse_args()
    print(json.dumps(run(args.legs), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
