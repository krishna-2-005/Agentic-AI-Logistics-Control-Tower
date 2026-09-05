"""Tests for the stream event schema (execution plan W4 D5).

    pytest tests/test_stream_schema.py -q

Never touches Spark or Kafka -- `query_event`/`fact_event` are pure functions over a
`pandas.Series`, and the schema itself is validated as plain JSON Schema.
"""

from __future__ import annotations

import pandas as pd
import pytest

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
        "is_delayed": 1,
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


def test_fact_event_time_is_od_start_plus_actual_time():
    row = _row()  # od_start 2018-09-12T00:02:09, planned_min=46, gap_min=101 -> actual_time=147 min
    event = schema.fact_event(row)
    assert event["event_time"] == "2018-09-12T02:29:09"


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
