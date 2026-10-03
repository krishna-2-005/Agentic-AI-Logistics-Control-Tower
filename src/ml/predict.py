"""What-if delay prediction (execution plan W4 D5, served model switched by WP-11) -- the
one place the dashboard starts a SparkSession, per D-034's documented exception to D-009.

    python -m src.ml.predict --corridor IND208012AAA>IND209304AAA \
        --planned-min 593 --planned-km 19.8 --route-type FTL \
        --departure "2018-09-20 14:30"

Scores with the model the paper reports -- the v2 residual GBT (D-050) -- and says so on
every answer (`model_id`). Until WP-11 this page ran the Week 4 champion, because the
v2 features need history a snapshot lookup cannot give (D-053).

**History is strictly as of the departure asked about.** Every leg that had *finished*
by then is folded, in event-time order, through `src.streaming.state` -- the same state
the streaming job keeps, so the two cannot disagree about what a corridor's history
was. This replaces the Week 4 simplification of reading each key's newest snapshot
whatever the date, which handed a departure inside the data window history from after
it. For a departure after the window (the intended use, "what if I ship this today")
all legs count, and the trailing 7-day mean is honestly empty: nothing is known about
the last week.
"""

from __future__ import annotations

import argparse
from datetime import datetime

import pandas as pd

from src.common import config
from src.common.logging_setup import get_logger
from src.common.spark import get_spark
from src.ml.baselines import HISTORY_PREFIXES
from src.streaming.schema import fact_event, temporal_features
from src.streaming.state import HistoryBook, epoch_us, sort_key

log = get_logger("ml.predict")

#: The model every answer names. Restated from `src.ml.serving` so this module's
#: Spark-free half imports without loading a model; a test pins the two together.
MODEL_ID = "v2_gbt_residual_absolute_step1"


#: Every leg's fact event, in D-020 order -- read once per process. The legs are the
#: frozen `features_v1` cache, so re-reading them through Spark on every form submission
#: cost ~40 seconds an answer and bought nothing.
_FACTS: list[dict] | None = None
_MODEL = None


def load_facts(spark) -> list[dict]:
    global _FACTS
    if _FACTS is None:
        from src.streaming.producer import load_legs

        legs = load_legs(spark=spark)
        _FACTS = sorted((fact_event(row) for _, row in legs.iterrows()), key=sort_key)
    return _FACTS


def history_as_of(facts: list[dict], query: dict) -> dict:
    """The query's 26 history features from every leg finished by its event time.

    `facts` must be in `sort_key` order; folding stops at the first fact after the query,
    which is also where a fact at the query's own instant stops counting (D-020).
    """
    cutoff = epoch_us(query["event_time"])
    book = HistoryBook()
    for fact in facts:
        if epoch_us(fact["event_time"]) > cutoff:
            break
        book.apply_fact(fact)
    return book.read(query)


def base_row(route_type: str, planned_min: float, planned_km: float, departure: datetime) -> dict:
    """The half of a what-if row that has nothing to do with history.

    The three temporal fields come from `src.streaming.schema.temporal_features` -- the
    one place Spark's day-of-week convention (Sunday = 1) is reproduced. Until Week 5
    this built `created_dayofweek` from `departure.weekday()` (Monday = 0), so every
    what-if prediction since Week 4 was made on a day-of-week from a different scale
    than the one the champion learned (P-46). Split out so it can be tested without a
    SparkSession, like `build_result` below.
    """
    return {
        "planned_min": float(planned_min),
        "planned_km": float(planned_km),
        **temporal_features(departure),
        "is_ftl": int(route_type == "FTL"),
    }


def predict_delay(
    corridor_id: str,
    source_center: str,
    destination_center: str,
    route_type: str,
    planned_min: float,
    planned_km: float,
    departure: datetime,
) -> dict:
    """One what-if prediction from the served v2 model. Returns predicted gap/total
    minutes, the D-003 delay call, which history keys were cold and which model answered
    -- so the page can say "this corridor has no history yet" rather than silently
    predicting off zeros that look identical to "this corridor is normally on time."
    """
    from src.ml import serving

    global _MODEL
    # The session and the model stay warm between answers. Starting a JVM and loading
    # 200 trees was most of every answer's wait; a what-if page in a live demo is used
    # several times in a row, and the process exiting is what stops Spark.
    spark = get_spark("what-if-predict")
    if _MODEL is None:
        _MODEL = serving.load_model()
    query = {
        "kind": "query", "leg_id": "what-if", "event_time": departure.isoformat(),
        "corridor_id": corridor_id, "source_center": source_center,
        "destination_center": destination_center,
        "route_type": route_type, **base_row(route_type, planned_min, planned_km, departure),
    }
    row = {**query, **history_as_of(load_facts(spark), query)}
    scored = serving.score(spark, _MODEL, pd.DataFrame([row])).iloc[0]

    cold_flags = {p: bool(scored[f"{p}_is_cold"]) for p in HISTORY_PREFIXES}
    return build_result(float(scored["predicted_gap_min"]), planned_min, cold_flags)


def build_result(predicted_gap_min: float, planned_min: float, cold_flags: dict,
                 model_id: str = MODEL_ID) -> dict:
    """The part of a prediction that has nothing to do with Spark -- split out so it
    can be tested (`tests/test_predict.py`) without a SparkSession or a real
    model on disk.
    """
    threshold_gap = (config.DELAY_THRESHOLD - 1) * planned_min
    return {
        "predicted_gap_min": round(predicted_gap_min, 1),
        "predicted_total_min": round(planned_min + predicted_gap_min, 1),
        "is_delayed_predicted": predicted_gap_min > threshold_gap,
        "threshold_gap_min": round(threshold_gap, 1),
        "cold_flags": cold_flags,
        "model_id": model_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corridor", required=True, help="corridor_id, e.g. IND208012AAA>IND209304AAA")
    parser.add_argument("--source", help="source_center; parsed from --corridor if omitted")
    parser.add_argument("--destination", help="destination_center; parsed from --corridor if omitted")
    parser.add_argument("--planned-min", type=float, required=True)
    parser.add_argument("--planned-km", type=float, required=True)
    parser.add_argument("--route-type", choices=["FTL", "Carting"], default="FTL")
    parser.add_argument("--departure", required=True, help="'YYYY-MM-DD HH:MM'")
    args = parser.parse_args()

    source = args.source or args.corridor.split(">")[0]
    destination = args.destination or args.corridor.split(">")[1]
    # Naive, matching D-013's timestamp convention -- every timestamp in this
    # project (trip_creation_time included) is naive local time, never tz-aware.
    departure = datetime.strptime(args.departure, "%Y-%m-%d %H:%M")  # noqa: DTZ007

    result = predict_delay(
        args.corridor, source, destination, args.route_type,
        args.planned_min, args.planned_km, departure,
    )
    log.info(
        "%s: predicted gap %.1f min (total %.1f min), delayed=%s, cold=%s",
        result["model_id"], result["predicted_gap_min"], result["predicted_total_min"],
        result["is_delayed_predicted"], result["cold_flags"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
