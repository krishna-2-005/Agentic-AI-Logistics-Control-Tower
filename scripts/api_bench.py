"""Measure the public API from outside it (WP-04 acceptance).

    python scripts/api_bench.py --base https://<space>.hf.space

Writes two files under benchmarks/raw/:

* `f1_api_latency.json` -- 20 warm predictions, one at a time, timed at the client:
  p50/p95/max in milliseconds, including the network. Spaced a little over the rate
  limit's pace so the limiter is not what is being measured.
* `f1_api_load_test.json` -- 200 requests from this one client as fast as 8 threads can
  send them, across the routes. Passes when the limiter answers with 429s and the server
  answers with no 5xx: overload must be refused, never crash.

Also records that the TMS is not reachable: a POST to each TMS write route must be a
404 or 405 from the public URL.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import httpx

RAW = Path(__file__).resolve().parents[1] / "benchmarks" / "raw"
BODY = {"corridor_id": "IND562132AAA>IND560300AAA", "osrm_time_min": 49.0, "osrm_km": 38.4,
        "route_type": "Carting", "departure_hour": 9}
TMS_WRITES = ["/orders", "/shipments", "/exceptions"]


def nearest_rank(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[max(1, min(len(ordered), round(pct / 100 * len(ordered)))) - 1]


def wait_ready(client: httpx.Client, timeout_s: float = 600) -> float:
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        try:
            state = client.get("/api/predict/status").json().get("state")
        except (httpx.HTTPError, ValueError):
            state = None
        if state == "ready":
            return time.monotonic() - started
        if state == "unavailable":
            raise SystemExit("the predictor failed to warm: see /api/predict/status")
        time.sleep(5)
    raise SystemExit("the predictor never became ready")


def latency(client: httpx.Client, n: int = 20) -> dict:
    client.post("/api/predict", json=BODY)  # one unmeasured call: warm is the claim
    samples, statuses = [], Counter()
    for _ in range(n):
        started = time.perf_counter()
        response = client.post("/api/predict", json=BODY)
        samples.append((time.perf_counter() - started) * 1000)
        statuses[response.status_code] += 1
        time.sleep(2.1)
    return {
        "requests": n, "status_codes": dict(statuses),
        "p50_ms": round(nearest_rank(samples, 50), 1), "p95_ms": round(nearest_rank(samples, 95), 1),
        "max_ms": round(max(samples), 1), "mean_ms": round(statistics.mean(samples), 1),
        "model_id": response.json().get("model_id") if response.status_code == 200 else None,
    }


def load_test(base: str, n: int = 200) -> dict:
    plan = [("POST", "/api/predict", BODY)] * 120 + [("GET", "/api/alerts", None)] * 60 + \
           [("POST", "/api/ask", {"question": "which corridors are the worst bottlenecks?"})] * 20
    plan = plan[:n]

    def fire(item):
        method, path, body = item
        try:
            with httpx.Client(base_url=base, timeout=60) as c:
                return path, c.request(method, path, json=body).status_code
        except httpx.HTTPError as exc:
            return path, f"error:{type(exc).__name__}"

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fire, plan))
    by_route: dict[str, Counter] = {}
    for path, status in results:
        by_route.setdefault(path, Counter())[str(status)] += 1
    every = Counter(str(s) for _, s in results)
    server_errors = sum(v for k, v in every.items() if k.startswith("5") and k != "503")
    return {
        "requests": len(results), "threads": 8, "wall_s": round(time.monotonic() - started, 1),
        "status_codes": dict(every), "by_route": {k: dict(v) for k, v in by_route.items()},
        "rate_limited_429": every.get("429", 0), "server_errors_5xx": server_errors,
        "transport_errors": sum(v for k, v in every.items() if k.startswith("error")),
        "passed": every.get("429", 0) > 0 and server_errors == 0,
        "note": "503 is the predictor saying it is warming, which the site renders; it is not counted as a failure",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True)
    parser.add_argument("--out-dir", type=Path, default=RAW)
    args = parser.parse_args()
    base = args.base.rstrip("/")
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")

    with httpx.Client(base_url=base, timeout=120) as client:
        health = client.get("/health")
        warmed_after_s = wait_ready(client)
        tms = {path: client.post(path, json={}).status_code for path in TMS_WRITES}
        measured = latency(client)

    report = {"generated_at": stamp, "base_url": base, "health_status": health.status_code,
              "health": health.json() if health.status_code == 200 else None,
              "ready_after_s": round(warmed_after_s, 1), "tms_write_routes": tms,
              "tms_unreachable": all(code in (404, 405) for code in tms.values()), **measured}
    (args.out_dir / "f1_api_latency.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

    time.sleep(61)  # let the latency run's minute expire, so the load test starts clean
    load = {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "base_url": base, **load_test(base)}
    (args.out_dir / "f1_api_load_test.json").write_text(json.dumps(load, indent=2), encoding="utf-8")
    print(json.dumps(load, indent=2))
    return 0 if load["passed"] and report["tms_unreachable"] else 1


if __name__ == "__main__":
    sys.exit(main())
