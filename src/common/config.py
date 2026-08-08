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
FEATURES_V1 = PROCESSED_DIR / "features_v1"

# ── Raw dataset facts (asserted by src.common.check_env) ─────────────────────
RAW_SHA256 = "ca654e6233912172cfde4c11fa5f194fa0b635961c0816b46b13dd71c06e78ed"
RAW_BYTES = 55_617_128
RAW_ROWS = 144_867  # data rows, excluding the header
RAW_COLUMNS = 24

# ── Domain constants ─────────────────────────────────────────────────────────
# A segment is "delayed" when realised time exceeds the OSRM estimate by this
# factor. Agreed by Lahari + Mounika, Week 1 D3 — see docs/decisions.md D-003.
# Sensitivity to 1.15 / 1.25 / 1.5 is tested in Week 5 (Lahari).
DELAY_THRESHOLD = 1.25

# Corridors with fewer than this many observed trips are excluded from the audit;
# their gap statistics are too noisy to test. See docs/decisions.md D-004.
MIN_CORRIDOR_SUPPORT = 30

# Route types present in the data.
ROUTE_TYPES = ("FTL", "Carting")

# ── Environment-driven settings ──────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.0-flash")

TMS_BASE_URL = os.getenv("TMS_BASE_URL", "http://localhost:8000")
TMS_DB_PATH = REPO_ROOT / os.getenv("TMS_DB_PATH", "data/tms.sqlite")

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
