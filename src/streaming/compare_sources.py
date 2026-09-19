"""Does the source change the answer? Kafka alerts against the file-source alerts (G-05).

    python -m src.streaming.compare_sources

The Kafka path and the file path share everything after `readStream` — the history join,
`prepare_model_features`, the model, the threshold. If that is true in fact and not only in
the code, replaying the same legs through either source must alert on the **same legs with
the same predicted gaps**. This checks exactly that, against the 1,347-alert file-source run
the Exception agent's Week 6 evaluation was built on (`w6_exception_eval_cases.csv`).

Run it after `src.streaming.job --kafka` has drained a replay of the same legs into the
alert sink.
"""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger
from src.dashboard.alerts import load_alerts

log = get_logger("streaming.compare_sources")

FILE_RUN = config.BENCHMARKS_RAW_DIR / "w6_exception_eval_cases.csv"
OUT = config.BENCHMARKS_RAW_DIR / "w7_kafka_source_equivalence.json"


def run() -> dict:
    feed = load_alerts()
    kafka = feed.alerts if hasattr(feed, "alerts") else feed
    file_run = pd.read_csv(FILE_RUN)
    kafka_legs, file_legs = set(kafka["leg_id"]), set(file_run["leg_id"])
    shared = sorted(kafka_legs & file_legs)
    k = kafka.set_index("leg_id")["predicted_gap_min"]
    f = file_run.set_index("leg_id")["predicted_gap_min"]
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kafka_alerts": len(kafka_legs),
        "file_source_alerts": len(file_legs),
        "identical_leg_sets": kafka_legs == file_legs,
        "only_in_kafka": len(kafka_legs - file_legs),
        "only_in_file": len(file_legs - kafka_legs),
        "max_abs_predicted_gap_difference_min": float((k.loc[shared] - f.loc[shared]).abs().max())
        if shared else None,
        "file_run": FILE_RUN.name,
    }
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info("kafka vs file: %s", summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
