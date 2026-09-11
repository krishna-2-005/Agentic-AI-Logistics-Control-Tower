# ruff: noqa: DTZ001 -- `event_time` is naive by design (a bare 2018 dataset timestamp,
# see src/dashboard/alerts.py), so the fixtures that stand in for it are naive too.
"""Tests for the alert-sink reader and the alert bot (execution plan W5 D3-D4 and D5).

    pytest tests/test_alerts_panel.py -q

No Spark, no Streamlit, no network. The Live alerts page and the bot both read the sink
through `src.dashboard.alerts`, so pinning that reader pins both. The bot's channels are
exercised through the file channel only -- the one that actually runs here -- plus the
start-up refusal of an unconfigured one, which is the behaviour that matters when no
Telegram or SMTP account exists (D-039).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd
import pytest

from src.agents import alert_bot as bot
from src.dashboard import alerts as reader


def _alert(alert_id: str = "a1", **overrides) -> dict:
    record = {
        "alert_id": alert_id,
        "leg_id": f"trip-{alert_id}|20180912000016|INDA>INDB",
        "trip_uuid": f"trip-{alert_id}",
        "corridor_id": "IND462022AAA>IND209304AAA",
        "source_center": "IND462022AAA",
        "destination_center": "IND209304AAA",
        "event_time": "2018-09-12T00:00:16.535741",
        "route_type": "FTL",
        "planned_min": 100.0,
        "planned_km": 120.0,
        "predicted_gap_min": 150.0,
        "predicted_total_min": 250.0,
        "threshold_gap_min": 100.0,
        "delay_threshold": 2.0,
        "corr_is_cold": 0,
        "src_is_cold": 0,
        "dst_is_cold": 0,
        "emit_time": "2026-09-09T15:47:26+05:30",
        "alert_time": "2026-09-09T15:47:27.382715+05:30",
        "latency_ms": 1382.7,
        "batch_id": 0,
    }
    record.update(overrides)
    return record


def _write(directory, batch_id: int, rows: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"alerts_{batch_id:06d}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )


# ── the reader ───────────────────────────────────────────────────────────────
def test_a_missing_sink_is_an_empty_feed_not_an_error(tmp_path):
    feed = reader.load_alerts(tmp_path / "nowhere")
    assert feed.empty and feed.files == 0
    assert feed.seconds_since_last_alert is None


def test_every_batch_file_is_read(tmp_path):
    _write(tmp_path, 0, [_alert("a1"), _alert("a2")])
    _write(tmp_path, 1, [_alert("a3")])
    feed = reader.load_alerts(tmp_path)
    assert len(feed.alerts) == 3 and feed.files == 2


def test_a_replayed_batch_does_not_double_count(tmp_path):
    # The alert schema promises a re-emitted batch carries the same alert_id; this is
    # where that promise is cashed rather than trusted.
    _write(tmp_path, 0, [_alert("a1")])
    _write(tmp_path, 1, [_alert("a1")])
    assert len(reader.load_alerts(tmp_path).alerts) == 1


def test_a_malformed_line_costs_that_line_not_the_panel(tmp_path):
    _write(tmp_path, 0, [_alert("a1")])
    with (tmp_path / "alerts_000000.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    assert len(reader.load_alerts(tmp_path).alerts) == 1


def test_a_file_from_a_different_job_version_is_named_not_rendered(tmp_path):
    _write(tmp_path, 0, [{"alert_id": "a1", "corridor_id": "X"}])
    with pytest.raises(ValueError, match="missing"):
        reader.load_alerts(tmp_path)


def test_the_historical_clock_is_not_shifted_by_the_local_offset(tmp_path):
    # event_time is a bare 2018 timestamp. Reading it as UTC and converting would move
    # every historical time by the machine's offset -- five and a half hours here.
    _write(tmp_path, 0, [_alert("a1")])
    event_time = reader.load_alerts(tmp_path).alerts.loc[0, "event_time"]
    assert event_time.tzinfo is None
    assert (event_time.hour, event_time.minute) == (0, 0)


def test_the_wall_clock_keeps_its_offset(tmp_path):
    _write(tmp_path, 0, [_alert("a1")])
    assert reader.load_alerts(tmp_path).alerts.loc[0, "alert_time"].tzinfo is not None


def test_mixed_timestamp_precision_parses(tmp_path):
    # One whole-second event_time among microsecond ones: P-09 and P-38's trap.
    _write(tmp_path, 0, [_alert("a1"), _alert("a2", event_time="2018-09-12T00:23:34")])
    assert reader.load_alerts(tmp_path).alerts["event_time"].notna().all()


def test_staleness_is_measured_on_the_wall_clock(tmp_path):
    _write(tmp_path, 0, [_alert("a1")])
    feed = reader.load_alerts(tmp_path)
    feed.read_at = feed.latest_alert_time + timedelta(minutes=10)
    assert feed.seconds_since_last_alert == pytest.approx(600.0)


def test_severity_is_excess_over_the_legs_own_threshold():
    frame = pd.DataFrame([
        {"predicted_gap_min": 430.0, "threshold_gap_min": 400.0},  # long haul, +30
        {"predicted_gap_min": 70.0, "threshold_gap_min": 40.0},    # short run, +30
        {"predicted_gap_min": 100.0, "threshold_gap_min": 20.0},   # short run, +80
    ])
    assert list(reader.excess_min(frame)) == [30.0, 30.0, 80.0]


def test_corridor_rollup_puts_the_noisiest_corridor_first():
    frame = pd.DataFrame([
        _alert("a1", corridor_id="C1"), _alert("a2", corridor_id="C2"), _alert("a3", corridor_id="C2"),
    ])
    rollup = reader.corridor_rollup(frame)
    assert list(rollup["corridor_id"]) == ["C2", "C1"]
    assert list(rollup["alerts"]) == [2, 1]


def test_summary_counts_an_alert_cold_if_any_key_was_cold(tmp_path):
    _write(tmp_path, 0, [_alert("a1", src_is_cold=1, dst_is_cold=1), _alert("a2")])
    assert reader.summary(reader.load_alerts(tmp_path))["cold_alerts"] == 1


def test_summary_of_nothing_says_none_rather_than_zero(tmp_path):
    stats = reader.summary(reader.load_alerts(tmp_path))
    assert stats["alerts"] == 0 and stats["worst_excess_min"] is None


# ── the bot's policy ─────────────────────────────────────────────────────────
def _frame(*rows: dict) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


def test_the_shortlist_is_worst_first_and_capped():
    alerts = _frame(
        _alert("low", predicted_gap_min=110.0),
        _alert("high", predicted_gap_min=500.0),
        _alert("mid", predicted_gap_min=200.0),
    )
    picked, seen, capped = bot.shortlist(alerts, set(), top=2)
    assert list(picked["alert_id"]) == ["high", "mid"]
    assert (seen, capped) == (0, 1)


def test_the_shortlist_never_resends_a_seen_alert():
    alerts = _frame(_alert("a1", predicted_gap_min=500.0), _alert("a2"))
    picked, seen, _ = bot.shortlist(alerts, {"a1"}, top=10)
    assert list(picked["alert_id"]) == ["a2"] and seen == 1


def test_the_message_names_shipment_corridor_and_delay_with_its_scale():
    row = pd.Series(_alert("a1")).copy()
    row["event_time"] = datetime(2018, 9, 12, 0, 0)
    row["alert_time"] = datetime(2026, 9, 9, 15, 47, 27)
    message = bot.format_message(row, 1, 3)
    assert "IND462022AAA>IND209304AAA" in message
    assert "trip-a1" in message
    assert "planned 100 min" in message and "+150 min" in message
    assert "+50 past the 100 min threshold" in message
    assert "[1/3]" in message
    assert "cold start" not in message


def test_the_message_warns_when_the_prediction_had_no_history():
    row = pd.Series(_alert("a1", corr_is_cold=1)).copy()
    row["event_time"] = datetime(2018, 9, 12)
    row["alert_time"] = datetime(2026, 9, 9)
    assert "no history yet for the corridor" in bot.format_message(row)


def test_an_unconfigured_channel_refuses_before_sending_anything():
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        bot.TelegramChannel(token="", chat_id="").check()
    with pytest.raises(RuntimeError, match="SMTP_HOST"):
        channel = bot.EmailChannel()
        channel.host = ""
        channel.check()


def test_a_run_sends_then_remembers_then_moves_on(tmp_path):
    sink, state, log_file = tmp_path / "alerts", tmp_path / "state.json", tmp_path / "out.log"
    _write(sink, 0, [_alert(f"a{i}", predicted_gap_min=100.0 + i) for i in range(5)])
    bot.CHANNELS["file"] = lambda: bot.FileChannel(log_file)
    try:
        first = bot.run("file", top=2, alerts_dir=sink, state_path=state)
        second = bot.run("file", top=2, alerts_dir=sink, state_path=state)
    finally:
        bot.CHANNELS["file"] = bot.FileChannel
    assert (first.sent, second.sent) == (2, 2)
    assert second.suppressed_seen == 2
    assert log_file.read_text(encoding="utf-8").count("DELAY PREDICTED") == 4
    assert len(bot.load_seen(state)) == 4


def test_a_dry_run_sends_nothing_and_remembers_nothing(tmp_path):
    sink, state = tmp_path / "alerts", tmp_path / "state.json"
    _write(sink, 0, [_alert("a1")])
    result = bot.run("telegram", top=5, dry_run=True, alerts_dir=sink, state_path=state)
    assert result.sent == 0 and len(result.messages) == 1
    assert not state.exists()


def test_a_corrupt_state_file_does_not_stop_the_bot(tmp_path):
    state = tmp_path / "state.json"
    state.write_text("{broken", encoding="utf-8")
    assert bot.load_seen(state) == set()
