"""The public API (WP-04, D-072): the four live pages of the site, and nothing else.

    uvicorn src.api.app:app --port 7860

Six routes, all read-only in effect:

==========================  ===========================================================
GET  /health                liveness, and whether the predictor is warm
GET  /api/predict/status    cold / warming / ready / unavailable
POST /api/predict           the served v2 model (D-070), as of today at the given hour
GET  /api/alerts?since=     the v2 stream's recorded alerts, replayed (labelled as such)
GET  /api/traces            the newest agent calls, trimmed to what the console shows
POST /api/ask               the analytics assistant; extractive unless asked, LLM capped
==========================  ===========================================================

**The TMS is not in this process.** Not behind a key, not bound to localhost -- absent.
The public container imports no TMS route, so every TMS path is a 404 from the public URL
and there is no write route for a key to protect. The agents that need the TMS run from
the repository, where the TMS does (D-072).

Abuse controls (`src.api.limits`): 30 predictions a minute per client and two in flight
at once across everyone, 5 questions a minute per client, 10 language-model answers a day
across everyone, bounded inputs, a 4 KB body cap. A refusal is a 429 with `Retry-After`
and a reason, which the site renders as "busy" rather than as an error.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.api.feeds import AlertReplay, read_traces
from src.api.limits import IST, ConcurrencyGate, DailyQuota, RateLimiter
from src.common import config

log = logging.getLogger("api")

MAX_BODY_BYTES = 4096
CORS_ORIGINS = [o.strip() for o in os.environ.get(
    "API_CORS_ORIGINS",
    "https://control-tower-mu-rouge.vercel.app,"
    "https://control-tower-git-dev-kuchurusaikrishnareddy-2388s-projects.vercel.app,"
    "http://localhost:3000,http://127.0.0.1:3000",
).split(",") if o.strip()]
TRACE_PATH = config.DATA_DIR / "traces" / "agent_calls.jsonl"

PREDICT_PER_MIN, ASK_PER_MIN, READ_PER_MIN = 30, 5, 120
PREDICT_CONCURRENCY, LLM_PER_DAY = 2, 10


# ── request and response shapes ──────────────────────────────────────────────
class PredictRequest(BaseModel):
    corridor_id: str = Field(pattern=r"^IND[0-9A-Z]{6,12}>IND[0-9A-Z]{6,12}$", max_length=40)
    osrm_time_min: float = Field(gt=0, le=10_000)
    osrm_km: float = Field(gt=0, le=5_000)
    route_type: Literal["FTL", "Carting"]
    departure_hour: int = Field(ge=0, le=23)


class PredictResponse(BaseModel):
    predicted_gap_min: float
    predicted_total_min: float
    is_delayed: bool
    threshold_gap_min: float
    model_id: str
    model_note: str
    cold_start: bool
    cold_flags: dict[str, bool]
    corridor_prior_legs: int | None
    departure: str


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=300)
    use_llm: bool = False


# ── state shared by the routes ───────────────────────────────────────────────
class Predictor:
    """The warm-up state of the model, so the page can say "warming" instead of hanging."""

    def __init__(self) -> None:
        self.state = "cold"
        self.detail = ""
        self._lock = threading.Lock()

    def warm(self) -> None:
        with self._lock:
            if self.state in ("warming", "ready"):
                return
            self.state, self.detail = "warming", "starting Spark and loading the v2 model"
        started = time.monotonic()
        try:
            from src.ml.predict import warm

            warm()
        except Exception as exc:  # noqa: BLE001 -- reported on /status, not raised into a thread
            self.state, self.detail = "unavailable", f"{type(exc).__name__}: {exc}"[:200]
            log.exception("predictor failed to warm")
            return
        self.state, self.detail = "ready", f"warmed in {time.monotonic() - started:.0f}s"

    def warm_in_background(self) -> None:
        threading.Thread(target=self.warm, name="predictor-warm", daemon=True).start()


predictor = Predictor()
alert_replay = AlertReplay()
limits = {
    "predict": RateLimiter(PREDICT_PER_MIN),
    "ask": RateLimiter(ASK_PER_MIN),
    "read": RateLimiter(READ_PER_MIN),
}
predict_gate = ConcurrencyGate(PREDICT_CONCURRENCY)
llm_quota = DailyQuota(LLM_PER_DAY)


def client_key(request: Request) -> str:
    """The visitor's address as the proxy saw it. Hugging Face terminates TLS in front of
    the container, so `request.client` is the proxy; the first `X-Forwarded-For` hop is
    the visitor. Hashed, so the limiter's table and the logs hold no addresses."""
    forwarded = request.headers.get("x-forwarded-for", "")
    address = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return hashlib.sha256(address.encode()).hexdigest()[:16]


def too_many(reason: str, retry_after: float) -> JSONResponse:
    seconds = max(1, round(retry_after))
    return JSONResponse(status_code=429, headers={"Retry-After": str(seconds)},
                        content={"detail": reason, "retry_after": seconds})


def limited(request: Request, bucket: str) -> JSONResponse | None:
    wait = limits[bucket].check(client_key(request))
    if wait:
        return too_many(f"rate limit: {limits[bucket].limit} per minute on this route", wait)
    return None


# ── the app ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if os.environ.get("API_WARM_ON_START", "1") == "1":
        predictor.warm_in_background()
    yield


app = FastAPI(
    title="Agentic AI Logistics Control Tower API",
    version="1.0",
    description="Read-only API behind the public site's four live pages. Source: "
                "github.com/krishna-2-005/Agentic-AI-Logistics-Control-Tower",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST"],
    allow_headers=["content-type"], max_age=600,
)


@app.middleware("http")
async def guard_and_log(request: Request, call_next):
    """Refuse oversized bodies before reading them; log every request as one JSON line."""
    started = time.monotonic()
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        response = JSONResponse(status_code=413, content={"detail": f"body over {MAX_BODY_BYTES} bytes"})
    else:
        response = await call_next(request)
    log.info(json.dumps({
        "ts": datetime.now(IST).isoformat(timespec="milliseconds"),
        "method": request.method, "path": request.url.path, "status": response.status_code,
        "latency_ms": round((time.monotonic() - started) * 1000, 1), "client": client_key(request),
    }))
    return response


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "predictor": predictor.state, "alerts_recorded": len(alert_replay.rows)}


@app.get("/api/predict/status")
def predict_status() -> dict:
    return {"state": predictor.state, "detail": predictor.detail}


@app.post("/api/predict", response_model=PredictResponse,
          responses={429: {"description": "rate limited or busy"}, 503: {"description": "model not ready"}})
def predict(body: PredictRequest, request: Request):
    refused = limited(request, "predict")
    if refused:
        return refused
    if predictor.state != "ready":
        predictor.warm_in_background()
        return JSONResponse(status_code=503, headers={"Retry-After": "15"},
                            content={"detail": f"the model is {predictor.state}", "state": predictor.state})
    if not predict_gate.try_enter():
        return too_many(f"busy: {PREDICT_CONCURRENCY} predictions already running", 2)
    try:
        from src.ml.predict import MODEL_ID, predict_delay

        source, destination = body.corridor_id.split(">")
        departure = datetime.now(IST).replace(hour=body.departure_hour, minute=0, second=0,
                                              microsecond=0, tzinfo=None)
        result = predict_delay(body.corridor_id, source, destination, body.route_type,
                               body.osrm_time_min, body.osrm_km, departure)
    finally:
        predict_gate.leave()
    return PredictResponse(
        predicted_gap_min=result["predicted_gap_min"],
        predicted_total_min=result["predicted_total_min"],
        is_delayed=result["is_delayed_predicted"],
        threshold_gap_min=result["threshold_gap_min"],
        model_id=result.get("model_id", MODEL_ID),
        model_note="the v2 residual GBT the results report (D-050), history as of the departure",
        cold_start=result["cold_flags"].get("corr", False),
        cold_flags=result["cold_flags"],
        corridor_prior_legs=result.get("corridor_prior_legs"),
        departure=departure.isoformat(),
    )


@app.get("/api/alerts")
def alerts(request: Request, since: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    refused = limited(request, "read")
    if refused:
        return refused
    rows = alert_replay.window(since, limit)
    return {
        "mode": "replay",
        "note": "Alerts from a recorded run of the v2 stream over the 2018 data, released in "
                "event-time order. This container runs no live stream.",
        "recorded_at": alert_replay.meta.get("recorded_at"),
        "alerts": rows,
        "rollup": alert_replay.rollup(rows),
        "generated_at": datetime.now(IST).isoformat(timespec="seconds"),
    }


@app.get("/api/traces")
def traces(request: Request, agent: str | None = Query(None, max_length=40, pattern=r"^[a-z_]+$"),
           limit: int = Query(50, ge=1, le=200)):
    refused = limited(request, "read")
    if refused:
        return refused
    return {"traces": read_traces(TRACE_PATH, agent, limit)}


@app.post("/api/ask")
def ask(body: AskRequest, request: Request):
    refused = limited(request, "ask")
    if refused:
        return refused
    from src.agents.analytics_assistant import answer

    use_llm = body.use_llm and llm_quota.take()
    try:
        result = answer(body.question, use_llm=use_llm)
    except Exception as exc:
        if use_llm:
            llm_quota.give_back()
        log.exception("assistant failed")
        raise HTTPException(status_code=500, detail="the assistant failed on this question") from exc
    if use_llm and result.draft_source != "llm":
        llm_quota.give_back()  # the model was not reached; the extractive route answered
    return {
        "answer": result.answer,
        "route": result.route,
        "sources": [{"label": s} for s in result.sources],
        "used_llm": result.draft_source == "llm",
        "llm_requested": body.use_llm,
        "quota_remaining": llm_quota.remaining(),
    }
