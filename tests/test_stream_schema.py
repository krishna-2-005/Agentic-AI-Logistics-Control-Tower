"""Tests for the stream event schema (execution plan W4 D5).

    pytest tests/test_stream_schema.py -q

Never touches Spark or Kafka -- `query_event`/`fact_event` are pure functions over a
`pandas.Series`, and the schema itself is validated as plain JSON Schema.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.common import config
from src.streaming import schema


@pytest.fixture(scope="module")
def json_schema():
    return schema.load_schema()


def test_schema_file_is_a_valid_json_schema(json_schema):
    import jsonschema as js

    js.Draft202012Validator.check_schema(json_schema)


def _row(**overrides) -> pd.Series:
    base = {
        "leg_id": "trip-abc|20180912000209|IND583101AAA>IND583201AAA",
        "trip_uuid": "trip-abc",
        "corridor_id": "IND583101AAA>IND583201AAA",
        "source_center": "IND583101AAA",
        "destination_center": "IND583201AAA",
        "trip_creation_time": pd.Timestamp("2018-09-12T00:00:00"),
        "route_type": "FTL",
        "planned_min": 46.0,
        "planned_km": 63.6461,
        "created_hour": 0,
        "created_dayofweek": 4,
        "created_is_weekend": 0,
        "gap_min": 101.0,
        "log_gap_ratio": 1.1617911902896414,
        # Moving time is 147 min (planned 46 + gap 101), so start + moving time would be
        # 02:29:09. The real finish is later because the leg also dwelt at the hub (P-52).
        "od_end_time": pd.Timestamp("2018-09-12T03:11:40"),
        # Deliberately the WRONG value: `features_v1` carries a stale `is_delayed`
        # computed at the 1.25x threshold D-003 rejected (P-42), and `fact_event` must
        # ignore whatever is in the column and recompute. A fixture holding the right
        # answer could not tell the two behaviours apart.
        "is_delayed": 0,
    }
    base.update(overrides)
    return pd.Series(base)


def test_query_event_validates_against_the_schema(json_schema):
    event = schema.query_event(_row())
    schema.validate_event(event, json_schema)
    assert event["kind"] == "query"
    assert "gap_min" not in event  # a query event never carries an outcome column


def test_fact_event_validates_against_the_schema(json_schema):
    event = schema.fact_event(_row())
    schema.validate_event(event, json_schema)
    assert event["kind"] == "fact"
    assert "planned_min" not in event  # a fact event never carries a predictor


def test_fact_event_time_is_the_real_finish_not_start_plus_moving_time():
    # P-52: start + actual_time (02:29:09) excludes dwell and publishes the fact early.
    event = schema.fact_event(_row())
    assert event["event_time"] == "2018-09-12T03:11:40"


def test_a_fact_event_without_a_finish_time_is_refused():
    with pytest.raises(ValueError, match="od_end_time"):
        schema.fact_event(_row(od_end_time=pd.NaT))


def test_a_replay_with_a_leg_that_lost_its_finish_time_is_refused():
    frame = pd.DataFrame({"leg_id": ["a", "b"], "od_end_time": [pd.Timestamp("2018-09-12"), pd.NaT]})
    with pytest.raises(ValueError, match="1 legs"):
        schema.require_od_end_time(frame)


def test_a_document_missing_a_required_query_field_fails_validation(json_schema):
    event = schema.query_event(_row())
    del event["planned_min"]
    with pytest.raises(Exception, match="planned_min"):
        schema.validate_event(event, json_schema)


def test_an_unknown_field_fails_validation(json_schema):
    event = schema.query_event(_row())
    event["not_a_real_field"] = 1
    with pytest.raises(Exception, match="not_a_real_field|[Aa]dditional"):
        schema.validate_event(event, json_schema)


def test_fact_event_recomputes_the_delay_label_and_ignores_the_stale_column():
    # gap_min 101 against planned_min 46: the leg took 147 of a planned 46 minutes,
    # 3.2x plan, delayed at any threshold the project has ever considered. The row says
    # 0 because that is what the stale parquet column says.
    assert schema.fact_event(_row())["is_delayed"] == 1


def test_a_leg_just_under_the_threshold_is_not_delayed():
    # 2.00x means gap > planned. 45 against 46 is 1.98x -- late, not "delayed" by
    # D-003's rule, and the boundary is where a re-derivation of the label goes wrong.
    assert schema.fact_event(_row(gap_min=45.0, is_delayed=1))["is_delayed"] == 0
    assert schema.fact_event(_row(gap_min=47.0, is_delayed=0))["is_delayed"] == 1


def test_the_delay_label_follows_config_rather_than_a_hardcoded_two():
    # If DELAY_THRESHOLD moves -- Lahari's D3-D4 sweeps it -- the event must move with
    # it, not keep a 2.00 baked in at the moment this was written.
    threshold_gap = (config.DELAY_THRESHOLD - 1) * 46.0
    assert schema.fact_event(_row(gap_min=threshold_gap + 1))["is_delayed"] == 1
    assert schema.fact_event(_row(gap_min=threshold_gap - 1))["is_delayed"] == 0


def test_the_stale_column_is_not_even_loaded():
    # Not reading it is what stops it being used by accident.
    assert "is_delayed" not in schema.EXAMPLE_COLUMNS
