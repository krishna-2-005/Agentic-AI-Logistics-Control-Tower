"""Tests for the public API (WP-04, D-072).

    pytest tests/test_api.py -q

No Spark and no model: `predict_delay` is replaced, because what is worth pinning here
is everything around it -- which routes exist, which do not, what each refuses, and
that a refusal is a 429 the site can render rather than an error.
"""

from __future__ import annotations

import gzip
import json
import os

os.environ.setdefault("API_WARM_ON_START", "0")

import pytest
from fastapi.testclient import TestClient

from src.api import app as api
from src.api.feeds import AlertReplay, read_traces
from src.api.limits import ConcurrencyGate, DailyQuota, RateLimiter

GOOD = {"corridor_id": "IND562132AAA>IND560300AAA", "osrm_time_min": 49.0, "osrm_km": 38.4,
        "route_type": "Carting", "departure_hour": 9}


def fake_prediction(*_args, **_kwargs) -> dict:
    return {"predicted_gap_min": 57.7, "predicted_total_min": 106.7, "is_delayed_predicted": True,
            "threshold_gap_min": 49.0, "cold_flags": {"corr": False, "src": False, "dst": False},
            "model_id": "v2_gbt_residual_absolute_step1", "corridor_prior_legs": 412}


@pytest.fixture
def client(monkeypatch):
    """A fresh app state per test: limits reset, the predictor marked ready."""
    monkeypatch.setattr(api, "limits", {
        "predict": RateLimiter(api.PREDICT_PER_MIN), "ask": RateLimiter(api.ASK_PER_MIN),
        "read": RateLimiter(api.READ_PER_MIN)})
    monkeypatch.setattr(api, "predict_gate", ConcurrencyGate(api.PREDICT_CONCURRENCY))
    monkeypatch.setattr(api, "llm_quota", DailyQuota(api.LLM_PER_DAY))
    monkeypatch.setattr(api.predictor, "state", "ready")
    import src.ml.predict as predict_module

    monkeypatch.setattr(predict_module, "predict_delay", fake_prediction)
    return TestClient(api.app)


# ── what exists, and what does not ───────────────────────────────────────────
def test_health_answers(client):
    response = client.get("/health")
    assert response.status_code == 200 and response.json()["status"] == "ok"


@pytest.mark.parametrize("method,path", [
    ("post", "/orders"), ("post", "/shipments"), ("post", "/exceptions"),
    ("patch", "/shipments/S1"), ("get", "/facilities"), ("get", "/orders"),
])
def test_no_tms_route_is_reachable(client, method, path):
    assert client.request(method.upper(), path, json={}).status_code in (404, 405)


def test_only_the_documented_routes_exist():
    paths = {route.path for route in api.app.routes if not route.path.startswith(("/docs", "/redoc", "/openapi"))}
    assert paths == {"/health", "/api/predict/status", "/api/predict", "/api/alerts", "/api/traces", "/api/ask"}


# ── predict ──────────────────────────────────────────────────────────────────
def test_a_prediction_names_the_model_and_the_departure(client):
    body = client.post("/api/predict", json=GOOD).json()
    assert body["model_id"] == "v2_gbt_residual_absolute_step1"
    assert body["is_delayed"] is True and body["corridor_prior_legs"] == 412
    assert body["departure"].endswith("T09:00:00")


@pytest.mark.parametrize("field,value", [
    ("corridor_id", "DROP TABLE"), ("corridor_id", "IND1>IND2"), ("osrm_time_min", -5),
    ("osrm_time_min", 1e9), ("route_type", "Truck"), ("departure_hour", 24),
])
def test_out_of_bounds_input_is_refused(client, field, value):
    assert client.post("/api/predict", json={**GOOD, field: value}).status_code == 422


def test_a_cold_model_says_so_instead_of_hanging(client, monkeypatch):
    monkeypatch.setattr(api.predictor, "state", "warming")
    monkeypatch.setattr(api.predictor, "warm_in_background", lambda: None)
    response = client.post("/api/predict", json=GOOD)
    assert response.status_code == 503 and response.json()["state"] == "warming"


def test_the_31st_prediction_in_a_minute_is_429_with_retry_after(client):
    codes = [client.post("/api/predict", json=GOOD).status_code for _ in range(api.PREDICT_PER_MIN + 1)]
    assert codes[:-1] == [200] * api.PREDICT_PER_MIN
    last = client.post("/api/predict", json=GOOD)
    assert last.status_code == 429 and int(last.headers["retry-after"]) >= 1


def test_a_third_concurrent_prediction_is_told_busy(client):
    assert api.predict_gate.try_enter() and api.predict_gate.try_enter()
    try:
        response = client.post("/api/predict", json=GOOD)
    finally:
        api.predict_gate.leave()
        api.predict_gate.leave()
    assert response.status_code == 429 and "busy" in response.json()["detail"]


def test_limits_are_per_client(client):
    for _ in range(api.PREDICT_PER_MIN):
        client.post("/api/predict", json=GOOD, headers={"x-forwarded-for": "1.1.1.1"})
    assert client.post("/api/predict", json=GOOD, headers={"x-forwarded-for": "1.1.1.1"}).status_code == 429
    assert client.post("/api/predict", json=GOOD, headers={"x-forwarded-for": "2.2.2.2"}).status_code == 200


def test_an_oversized_body_is_refused_before_it_is_read(client):
    response = client.post("/api/ask", content=b"x" * (api.MAX_BODY_BYTES + 1),
                           headers={"content-type": "application/json"})
    assert response.status_code == 413


# ── ask ──────────────────────────────────────────────────────────────────────
def test_ask_defaults_to_no_model_and_counts_no_quota(client, monkeypatch):
    from src.agents import analytics_assistant as assistant

    seen = {}

    def fake_answer(question, use_llm):
        seen["use_llm"] = use_llm
        return assistant.AssistantAnswer(question, "table", "rank 1 ...", ["w2_top20.csv"], None, "extractive")

    monkeypatch.setattr(assistant, "answer", fake_answer)
    body = client.post("/api/ask", json={"question": "worst corridors?"}).json()
    assert seen["use_llm"] is False and body["used_llm"] is False
    assert body["quota_remaining"] == api.LLM_PER_DAY


def test_the_daily_model_quota_is_enforced_and_unused_calls_are_returned(client, monkeypatch):
    from src.agents import analytics_assistant as assistant

    monkeypatch.setattr(assistant, "answer", lambda q, use_llm: assistant.AssistantAnswer(
        q, "retrieval", "x", [], 0.4, "llm" if use_llm else "extractive"))
    monkeypatch.setattr(api.limits["ask"], "limit", 100)
    used = [client.post("/api/ask", json={"question": "why?", "use_llm": True}).json()["used_llm"]
            for _ in range(api.LLM_PER_DAY + 2)]
    assert used == [True] * api.LLM_PER_DAY + [False, False]

    quota = DailyQuota(3)
    assert quota.take()
    quota.give_back()
    assert quota.remaining() == 3


def test_the_sixth_question_in_a_minute_is_429(client, monkeypatch):
    from src.agents import analytics_assistant as assistant

    monkeypatch.setattr(assistant, "answer", lambda q, use_llm: assistant.AssistantAnswer(q, "table", "a", [], None, "extractive"))
    codes = [client.post("/api/ask", json={"question": "worst corridors?"}).status_code for _ in range(api.ASK_PER_MIN + 1)]
    assert codes == [200] * api.ASK_PER_MIN + [429]


# ── the feeds ────────────────────────────────────────────────────────────────
def _feed(tmp_path, n=5):
    path, meta = tmp_path / "feed.jsonl.gz", tmp_path / "meta.json"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for i in range(n):
            handle.write(json.dumps({"corridor_id": f"C{i}", "predicted_gap_min": float(i), "severity": "high"}) + "\n")
    meta.write_text(json.dumps({"recorded_at": "2026-10-03T22:00:00+05:30"}), encoding="utf-8")
    return path, meta


def test_the_replay_releases_rows_in_order_as_time_passes(tmp_path):
    now = [0.0]
    path, meta = _feed(tmp_path)
    replay = AlertReplay(path, meta, every_s=2.0, initial=2, clock=lambda: now[0])
    assert [r["seq"] for r in replay.window()] == [2, 1]
    now[0] = 6.0
    assert [r["seq"] for r in replay.window(since=2)] == [5, 4, 3]


def test_the_replay_loops_but_seq_keeps_rising(tmp_path):
    path, meta = _feed(tmp_path, n=3)
    replay = AlertReplay(path, meta, every_s=1.0, initial=4, clock=lambda: 0.0)
    rows = replay.window()
    assert [r["seq"] for r in rows] == [4, 3, 2, 1]
    assert rows[0]["corridor_id"] == "C0"


def test_the_alerts_route_says_it_is_a_replay(client):
    body = client.get("/api/alerts").json()
    assert body["mode"] == "replay" and "no live stream" in body["note"]


def test_traces_never_echo_what_a_visitor_typed(tmp_path):
    log_file = tmp_path / "calls.jsonl"
    log_file.write_text("\n".join(json.dumps({
        "agent": "analytics_assistant", "started_at": f"2026-10-03T10:0{i}:00", "error": None,
        "inputs": {"question": "my secret question"}, "outputs": {"route": "table", "answer": "x"},
    }) for i in range(3)) + "\nnot json\n", encoding="utf-8")
    rows = read_traces(log_file, limit=2)
    assert [r["ts"] for r in rows] == ["2026-10-03T10:02:00", "2026-10-03T10:01:00"]
    assert "secret" not in json.dumps(rows) and rows[0]["event"] == "table"


# ── the browser's view ───────────────────────────────────────────────────────
def test_cors_admits_the_site_and_no_one_else(client):
    allowed = client.options("/api/alerts", headers={
        "origin": "https://control-tower-mu-rouge.vercel.app", "access-control-request-method": "GET"})
    other = client.options("/api/alerts", headers={
        "origin": "https://evil.example", "access-control-request-method": "GET"})
    assert allowed.headers.get("access-control-allow-origin") == "https://control-tower-mu-rouge.vercel.app"
    assert "access-control-allow-origin" not in other.headers


def test_rate_limiter_window_slides():
    limiter = RateLimiter(2, window_s=10)
    assert limiter.check("k", now=0) == 0 and limiter.check("k", now=1) == 0
    assert limiter.check("k", now=2) == pytest.approx(8)
    assert limiter.check("k", now=10.5) == 0
