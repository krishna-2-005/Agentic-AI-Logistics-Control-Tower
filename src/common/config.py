"""Single source of truth for paths, dataset facts, and environment settings.

Every script imports from here rather than hardcoding a path. If a location has to
move, it moves once.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Paths ────────────────────────────────────────────────────────────────────
# config.py -> common -> src -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / ".env")

DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
DOCS_DIR = REPO_ROOT / "docs"
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
BENCHMARKS_RAW_DIR = BENCHMARKS_DIR / "raw"
DEMO_DIR = REPO_ROOT / "demo"
MODELS_DIR = DATA_DIR / "models"

RAW_CSV = RAW_DIR / "delhivery_data.csv"

# Versioned Spark outputs. Bump the suffix rather than overwriting when the schema
# changes — teammates' in-flight work keeps reading the version it was built against.
CLEAN_V1 = PROCESSED_DIR / "clean_v1"
TRIPS_V1 = PROCESSED_DIR / "trips_v1"
HUBS_V1 = PROCESSED_DIR / "hubs_v1"
FEATURES_V1 = PROCESSED_DIR / "features_v1"

# ── Raw dataset facts (asserted by src.common.check_env) ─────────────────────
RAW_SHA256 = "ca654e6233912172cfde4c11fa5f194fa0b635961c0816b46b13dd71c06e78ed"
RAW_BYTES = 55_617_128
RAW_ROWS = 144_867  # data rows, excluding the header
RAW_COLUMNS = 24

# ── Domain constants ─────────────────────────────────────────────────────────
# A leg is "delayed" when realised time exceeds the OSRM estimate by this factor.
# Raised from the blueprint's 1.25 at the Week 2 sync — see docs/decisions.md D-003.
# At 1.25 the label was true of 93.6% of legs, because the median leg on this network
# already runs at 2.00x plan; a classifier could score 93.6% knowing nothing. 2.00
# splits the legs 49.6 / 50.4. Classification is the secondary framing either way:
# the headline is regression on `gap_min`, which has no threshold at all.
# Sensitivity across 1.10 - 2.00 is in benchmarks/raw/w1_delay_threshold_sensitivity.csv.
DELAY_THRESHOLD = 2.00

# Corridors with fewer than this many observed legs are excluded from the audit.
# Lowered from 30 at the Week 2 sync — see docs/decisions.md D-018, which supersedes
# D-004's provisional floor. The floor was set before any significance test existed;
# with one, re-running the whole audit at each threshold showed 30 legs was not
# trading power for coverage but removing the finding: 18.9% of legs covered and a
# worst corridor at 1.92x, against 78.6% and 13.9x at 10 legs, with the significant
# share unchanged (71% vs 70%). Welch is valid at n = 10 and the comparison group is
# the whole 26,369-leg network either way.
MIN_CORRIDOR_SUPPORT = 10

# Hubs with fewer than this many outbound legs are not ranked on the friction
# leaderboard, for the same reason. 30 legs leaves 121 of 1,657 facilities — see
# docs/decisions.md D-015.
MIN_HUB_SUPPORT = 30

# Route types present in the data.
ROUTE_TYPES = ("FTL", "Carting")

# ── Environment-driven settings ──────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.0-flash")

TMS_BASE_URL = os.getenv("TMS_BASE_URL", "http://localhost:8000")
TMS_DB_PATH = REPO_ROOT / os.getenv("TMS_DB_PATH", "data/tms.sqlite")
# Empty means the mock TMS serves unauthenticated. Set it and every endpoint except
# /health requires an X-API-Key header — see src/tms/app.py.
TMS_API_KEY = os.getenv("TMS_API_KEY", "")

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC_TRIPS = os.getenv("KAFKA_TOPIC_TRIPS", "delhivery.trips")
KAFKA_TOPIC_ALERTS = os.getenv("KAFKA_TOPIC_ALERTS", "delhivery.alerts")
STREAM_SOURCE = os.getenv("STREAM_SOURCE", "kafka")

CHROMA_PERSIST_DIR = REPO_ROOT / os.getenv("CHROMA_PERSIST_DIR", "data/chroma_db")

SPARK_DRIVER_MEMORY = os.getenv("SPARK_DRIVER_MEMORY", "4g")
SPARK_LOCAL_DIR = REPO_ROOT / os.getenv("SPARK_LOCAL_DIR", "data/spark-tmp")


def ensure_dirs() -> None:
    """Create the generated-output directories. Safe to call repeatedly."""
    for path in (PROCESSED_DIR, BENCHMARKS_RAW_DIR, MODELS_DIR, SPARK_LOCAL_DIR):
        path.mkdir(parents=True, exist_ok=True)
