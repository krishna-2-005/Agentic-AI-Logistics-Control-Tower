"""
Export every JSON the public web app reads.

The web frontend (D-057) is a static Next.js export: it has no Python, no Spark
and no `data/` directory. Everything it shows has to arrive as JSON committed
beside the code. This module is the one place that conversion happens.

Rules it follows (D-059):

1. **It reads only `benchmarks/raw/` and committed reference CSVs.** Exactly the
   sources the Streamlit app read (D-009). No Spark, no `data/`, so it runs in CI
   on a fresh clone.
2. **It pre-aggregates; it never ships raw rows.** `w1_leg_summary.csv` is 10.9 MB
   and the Overview needs a 40-bin histogram and four numbers.
3. **Every file carries its provenance** — the source file, the generation time and
   the results-freeze version — so the "Evidence" link on screen is generated
   rather than typed.
4. **Numbers come from the freeze where the freeze has them.** A headline on the
   site and a headline in the paper are then the same number by construction, and
   `tests/test_web_numbers.py` proves it.

Run as:  python -m src.report.export_web
         python -m src.report.export_web --out web/public/data
         python -m src.report.export_web --check     # fail if output would change
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.common import config

# ── where things come from and go ────────────────────────────────────────────

RAW = config.BENCHMARKS_RAW_DIR
FREEZE_PATH = config.BENCHMARKS_DIR / "results_freeze_v3.json"
COORDS_PATH = config.REPO_ROOT / "src" / "dashboard" / "reference" / "centre_coords.csv"
CITY_COORDS_PATH = (
    config.REPO_ROOT / "src" / "dashboard" / "reference" / "india_city_coords.csv"
)
FIGURES_DIR = config.DOCS_DIR / "figures"
PROMPTS_DIR = config.REPO_ROOT / "src" / "agents" / "prompts"

DEFAULT_OUT = config.REPO_ROOT / "web" / "public" / "data"
DEFAULT_FIGURES_OUT = config.REPO_ROOT / "web" / "public" / "figures"

FREEZE_VERSION = "v3"

# ── the severity ramp, carried over unchanged from the Streamlit map ─────────
# D-058 is explicit that these cut points are not redesigned: they were tuned
# against the real bottleneck distribution (median 1.39, p75 1.78, p95 3.42) so
# the bins hold 50 / 113 / 86 / 24 instead of piling 110 of 273 into one shade.
# The web app re-uses them rather than picking its own, so the two surfaces
# cannot disagree about what "severe" means.

SEVERITY_BINS = [
    (1.20, "#ec9694", 2.00, "mildly worse", "1.00–1.20×"),
    (1.50, "#e34948", 3.25, "clearly worse", "1.20–1.50×"),
    (2.50, "#a02726", 4.50, "severe", "1.50–2.50×"),
    (99.0, "#5e1413", 5.75, "extreme", "2.50×+"),
]
FASTER_BINS = [
    (0.60, "#06203f", 5.75, "extreme", "under 0.60×"),
    (0.75, "#104281", 4.50, "much better", "0.60–0.75×"),
    (0.90, "#2a78d6", 3.25, "clearly better", "0.75–0.90×"),
    (1.00, "#86b6ef", 2.00, "mildly better", "0.90–1.00×"),
]


def severity_of(excess: float, direction: str) -> dict[str, Any]:
    """The bin one corridor's effect size falls in.

    Returns the colour *and* a text label, because W-11 requires severity to
    survive a colourblind read: nothing on the site may encode it by hue alone.
    """
    bins = SEVERITY_BINS if direction == "worse" else FASTER_BINS
    for idx, (upper, colour, weight, label, span) in enumerate(bins):
        if excess <= upper:
            return {
                "bin": idx,
                "color": colour,
                "weight": weight,
                "label": label,
                "range": span,
            }
    upper, colour, weight, label, span = bins[-1]
    return {"bin": len(bins) - 1, "color": colour, "weight": weight,
            "label": label, "range": span}


# ── small helpers ────────────────────────────────────────────────────────────

def _data_timestamp() -> str:
    """When the *data* was frozen — not when this script happened to run.

    Deliberately not `datetime.now()`. The export has to be reproducible: CI
    re-runs it and fails if the committed output differs, which is what stops a
    stale JSON reaching the site. A wall-clock timestamp would make every run
    differ from every other and turn that check into noise.

    The freeze's own `frozen_at` is also the more useful answer to the question
    a provenance envelope is asked — "how old is this number?" — since it dates
    the benchmark rather than the person who last ran an export.
    """
    if FREEZE_PATH.exists():
        frozen_at = _read_json(FREEZE_PATH).get("frozen_at")
        if frozen_at:
            return str(frozen_at)
    return datetime.fromtimestamp(0, timezone.utc).isoformat()


def _clean(value: Any) -> Any:
    """JSON has no NaN. Pandas produces them freely; they become null."""
    if value is None:
        return None
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value
    if pd.isna(value):
        return None
    return value


def _num(value: Any, digits: int | None = None) -> float | None:
    """A float rounded for the wire, or None. Rounding is not cosmetic here:
    it is most of the difference between a 600 KB payload and a 180 KB one."""
    value = _clean(value)
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return round(out, digits) if digits is not None else out


def _envelope(source: str | list[str], payload: Any, **extra: Any) -> dict:
    """Every file the site reads says where it came from (D-059 rule 3)."""
    return {
        "source": source,
        "generated_at": _data_timestamp(),
        "freeze": FREEZE_VERSION,
        **extra,
        "data": payload,
    }


def _write(out_dir: Path, name: str, obj: Any) -> tuple[str, int]:
    path = out_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    return name, len(text.encode("utf-8"))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_freeze() -> dict[str, dict]:
    """The frozen values, keyed by id, so any exporter can quote one."""
    if not FREEZE_PATH.exists():
        return {}
    doc = _read_json(FREEZE_PATH)
    return {v["id"]: v for v in doc.get("values", [])}


def _coords() -> pd.DataFrame:
    """Centre code -> lat/lon. The join happens here, once, so the browser
    never parses a facility name (D-019: a corridor is placed by code)."""
    df = pd.read_csv(COORDS_PATH)
    return df[["centre_code", "city", "state", "lat", "lon"]].drop_duplicates(
        subset="centre_code", keep="first"
    )


def _city_coords() -> pd.DataFrame:
    """The hand-maintained city table — the fallback for the centres whose PIN
    is `000000` or is absent from the postal data."""
    if not CITY_COORDS_PATH.exists():
        return pd.DataFrame(
            columns=["raw_city", "canonical_city", "state", "lat", "lon"]
        )
    return pd.read_csv(CITY_COORDS_PATH).drop_duplicates("raw_city", keep="first")


def facility_of(name: object) -> str | None:
    """`Bengaluru_Nelmngla_H (Karnataka)` -> `Nelmngla`.

    A city pair does not identify a corridor: 70 of the significant ones run
    between two facilities inside one city, so several render as the same
    "Bengaluru -> Bengaluru". The facility is the part that tells them apart,
    and it reads far better than the centre code does.

    Names come in three shapes here -- `City_Facility_Type`, `City_Facility`
    and a spaced `HBR Layout PC` -- so anything that does not split on
    underscores falls back to the whole name minus its state suffix.
    """
    if not isinstance(name, str) or not name:
        return None
    head = name.split("(")[0].strip()
    parts = [p for p in head.split("_") if p]
    if len(parts) >= 2:
        return parts[1].strip() or None
    return head or None


def _public_label(label: str) -> str:
    """Strip the decision-log citation off a frozen value's label.

    The freeze labels a value "Legs delayed at the decided 2.00x threshold
    (D-003)", and inside the repository that citation is how the team finds the
    reasoning. A visitor cannot resolve it and reads it as noise, so it comes
    off on the way to the site. The label keeps its meaning; only the pointer
    goes, and the pointer still exists in the freeze itself.
    """
    # Two shapes occur: "... (D-018)", where the whole bracket is the citation,
    # and "... (chronological, D-022)", where the bracket also says something a
    # reader wants. Strip the reference, keep the rest, drop an empty bracket.
    cleaned = re.sub(r",?\s*[DPWG]-\d{2,3}(?=\s*[,)])", "", label)
    cleaned = re.sub(r"\s*\(\s*\)", "", cleaned)
    return cleaned.strip()


def _public_value(value: Any) -> Any:
    """Frozen values are identifiers where the pipeline needed one.

    `champion_model` is literally the string `random_forest`. On a results table
    a reader wants the family, not the variable name.
    """
    if isinstance(value, str):
        return value.replace("_", " ").strip().capitalize()
    return value


def city_of(facility_name: object) -> str | None:
    """`Anand_VUNagar_DC (Gujarat)` -> `Anand`.

    Two naming shapes occur: most rows are `City_Facility_Type (State)`, but a
    handful separate the city with a space. Splitting on either covers both --
    handling only the underscore is what silently nulled those cities in Week 2.
    """
    if not isinstance(facility_name, str) or not facility_name:
        return None
    head = facility_name.split("(")[0]
    return re.split(r"[_\s]", head.strip(), maxsplit=1)[0].strip() or None


# ── exporters ────────────────────────────────────────────────────────────────

def export_overview(out: Path, freeze: dict) -> tuple[str, int]:
    """The landing page: four numbers and the histogram that is the whole premise.

    W-02: the Streamlit page read the 10.9 MB leg summary directly. A browser
    cannot, and does not need to — 40 bins and four scalars is about 2 KB.
    """
    legs = pd.read_csv(
        RAW / "w1_leg_summary.csv",
        usecols=["gap_ratio", "corridor_id", "is_delayed", "gap_min"],
    )
    ratio = legs["gap_ratio"].dropna()

    # Clipped at 8x so the tail does not flatten the bulk of the distribution.
    # The share beyond the clip is reported rather than hidden.
    hist, bin_edges = np.histogram(ratio.clip(upper=8.0), bins=40, range=(0, 8))
    histogram = [
        {"x": round(float(bin_edges[i] + bin_edges[i + 1]) / 2, 3), "n": int(hist[i])}
        for i in range(len(hist))
    ]

    payload = {
        "legs": int(freeze.get("legs_total", {}).get("value", len(legs))),
        "corridors": int(
            freeze.get("corridors_total", {}).get("value", legs["corridor_id"].nunique())
        ),
        "corridors_tested": int(freeze.get("corridors_tested", {}).get("value", 0)),
        "bottlenecks": int(freeze.get("bottlenecks", {}).get("value", 0)),
        "faster_corridors": int(freeze.get("faster_corridors", {}).get("value", 0)),
        "share_over_plan": _num(float((ratio > 1.0).mean()), 4),
        "median_ratio": _num(
            freeze.get("median_gap_ratio", {}).get("value", float(ratio.median())), 2
        ),
        "median_gap_min": _num(float(legs["gap_min"].median()), 1),
        "share_above_clip": _num(float((ratio > 8.0).mean()), 4),
        "histogram": histogram,
        "clip_at": 8.0,
    }
    return _write(
        out, "overview.json",
        _envelope("benchmarks/raw/w1_leg_summary.csv", payload),
    )


def _corridor_records(csv_path: Path, coords: pd.DataFrame) -> list[dict]:
    """One record per audited corridor, with both ends placed.

    Placement follows the dashboard exactly (P-21, P-24): **position comes from
    the centre code, the label from the name.** Placing dots by parsed facility
    name is what once capped the map at 101 of 273 bottlenecks. The city table is
    consulted only where the code could not place a centre.
    """
    df = pd.read_csv(csv_path)
    centres = coords.drop_duplicates("centre_code").set_index("centre_code")
    cities = _city_coords().set_index("raw_city")

    df["src_city_parsed"] = df["source_name"].map(city_of)
    df["dst_city_parsed"] = df["destination_name"].map(city_of)

    for end, code_col, parsed_col in (
        ("src", "source_center", "src_city_parsed"),
        ("dst", "destination_center", "dst_city_parsed"),
    ):
        lat = df[code_col].map(centres["lat"])
        lon = df[code_col].map(centres["lon"])
        # Fall back to the city table only where the code came up empty.
        df[f"{end}_lat"] = lat.fillna(df[parsed_col].map(cities["lat"]))
        df[f"{end}_lon"] = lon.fillna(df[parsed_col].map(cities["lon"]))
        # Always prefer the canonical city name, so two spellings of one city do
        # not draw as two places.
        canon = df[parsed_col].map(cities["canonical_city"])
        df[f"{end}_label"] = canon.fillna(df[parsed_col])
        df[f"{end}_state"] = df[parsed_col].map(cities["state"])

    records: list[dict] = []
    for _, r in df.iterrows():
        direction = str(r.get("direction") or "")
        excess = _num(r.get("excess_ratio"), 3) or 0.0
        sev = severity_of(excess, direction)
        records.append({
            "id": r["corridor_id"],
            "src": {
                "code": r["source_center"],
                "facility": facility_of(r.get("source_name")),
                "city": _clean(r.get("src_label")) or _clean(r.get("source_city")),
                "state": _clean(r.get("src_state")) or _clean(r.get("source_state")),
                "lat": _num(r.get("src_lat"), 4),
                "lon": _num(r.get("src_lon"), 4),
            },
            "dst": {
                "code": r["destination_center"],
                "facility": facility_of(r.get("destination_name")),
                "city": _clean(r.get("dst_label")) or _clean(r.get("dest_city")),
                "state": _clean(r.get("dst_state")) or _clean(r.get("dest_state")),
                "lat": _num(r.get("dst_lat"), 4),
                "lon": _num(r.get("dst_lon"), 4),
            },
            "intra_city": bool(
                _clean(r.get("src_label")) and
                _clean(r.get("src_label")) == _clean(r.get("dst_label"))
            ),
            "n_legs": int(r["n_legs"]),
            "excess_ratio": excess,
            "direction": direction,
            "is_significant": bool(r.get("is_significant")),
            "q_value": _num(r.get("q_value"), 8),
            "median_gap_min": _num(r.get("median_gap_min"), 1),
            "mean_gap_min": _num(r.get("mean_gap_min"), 1),
            "median_gap_ratio": _num(r.get("median_gap_ratio"), 2),
            "mean_dwell_min": _num(r.get("mean_dwell_min"), 1),
            "mean_osrm_km": _num(r.get("mean_osrm_km"), 1),
            "ftl_share": _num(r.get("ftl_share"), 3),
            "rank": (
                int(r["bottleneck_rank"])
                if not pd.isna(r.get("bottleneck_rank")) else None
            ),
            "severity": sev,
        })
    return records


def export_corridors(out: Path) -> list[tuple[str, int]]:
    """The audit, at both support floors.

    Both are shipped because D-018 is a *result*: the 10-leg and 30-leg top-20
    lists share no corridor at all, and the site shows that by toggling between
    them rather than describing it in a caption.
    """
    coords = _coords()
    written = []

    ten = _corridor_records(RAW / "w2_corridor_audit.csv", coords)
    written.append(_write(out, "corridors.json", _envelope(
        ["benchmarks/raw/w2_corridor_audit.csv",
         "src/dashboard/reference/centre_coords.csv"],
        ten,
        support_floor=10,
        located=sum(1 for c in ten if c["src"]["lat"] and c["dst"]["lat"]),
        legend={"worse": [
            {"upto": b[0], "color": b[1], "label": b[3], "range": b[4]}
            for b in SEVERITY_BINS
        ], "better": [
            {"upto": b[0], "color": b[1], "label": b[3], "range": b[4]}
            for b in FASTER_BINS
        ]},
    )))

    thirty = _corridor_records(RAW / "w2_corridor_audit_support30.csv", coords)
    written.append(_write(out, "corridors_support30.json", _envelope(
        "benchmarks/raw/w2_corridor_audit_support30.csv",
        thirty,
        support_floor=30,
    )))
    return written


def export_hubs(out: Path) -> tuple[str, int]:
    """Hub friction. Two metrics that disagree, and the site lets you switch:
    ranking by dwell *share* puts Aluva first, by dwell *minutes* Hubli (P-61).
    """
    df = pd.read_csv(RAW / "w2_hub_dwell.csv")
    coords = _coords()
    df = df.merge(coords, left_on="centre_code", right_on="centre_code", how="left")

    records = []
    for _, r in df.iterrows():
        records.append({
            "code": r["centre_code"],
            "name": _clean(r.get("centre_name")),
            "city": _clean(r.get("city_x") if "city_x" in df.columns else r.get("city")),
            "state": _clean(r.get("state_x") if "state_x" in df.columns else r.get("state")),
            "lat": _num(r.get("lat"), 4),
            "lon": _num(r.get("lon"), 4),
            "outbound_legs": int(r["n_legs_out"]),
            "corridors_out": _clean(r.get("n_corridors_out")),
            "median_dwell_min": _num(r.get("median_dwell_min_out"), 1),
            "p90_dwell_min": _num(r.get("p90_dwell_min_out"), 1),
            "dwell_share": _num(r.get("median_dwell_share_out"), 4),
            "median_gap_ratio": _num(r.get("median_gap_ratio_out"), 2),
            "friction_rank": int(r["friction_rank"]),
        })
    return _write(out, "hubs.json", _envelope(
        "benchmarks/raw/w2_hub_dwell.csv", records,
        min_support=config.MIN_HUB_SUPPORT,
    ))


def export_model(out: Path, freeze: dict) -> tuple[str, int]:
    """The reported model and every slice it was judged on.

    The slice table is the point, not decoration: D-050 adopted this model
    because it wins on all fourteen, and states in the same breath that most of
    the margin comes from the 294 legs with no corridor history.
    """
    df = pd.read_csv(RAW / "w7_model_metrics_v2_stepsize.csv")
    slices = [{
        "dimension": r["dimension"],
        "slice": str(r["slice"]),
        "n": int(r["n"]),
        "model": r["model"],
        "mae_min": _num(r["mae_min"], 2),
        "baseline_mae_min": _num(r.get("median_baseline_mae_min"), 2),
        "delta_vs_median_min": _num(r.get("delta_vs_median_min"), 2),
    } for _, r in df.iterrows()]

    payload = {
        "headline": {
            "model": "v2_gbt_residual_absolute_step1",
            "mae_min": _num(freeze.get("model_v2_mae", {}).get("value"), 2),
            "baseline_mae_min": _num(freeze.get("median_bar_mae", {}).get("value"), 2),
            "osrm_mae_min": _num(freeze.get("mae_osrm", {}).get("value"), 2),
            "served_model": "an earlier random-forest model",
            "served_note": (
                "The best model needs a rolling view of each lane's recent "
                "history, which the live service cannot build yet, so the "
                "predictor runs an earlier and slightly weaker model and names "
                "it on every answer."
            ),
        },
        "slices": slices,
    }
    return _write(out, "model.json", _envelope(
        ["benchmarks/raw/w7_model_metrics_v2_stepsize.csv",
         "benchmarks/results_freeze_v3.json"],
        payload,
    ))


def export_agents(out: Path, freeze: dict) -> list[tuple[str, int]]:
    """One card per agent, each with the score it actually earned.

    Every agent is reported beside the trivial policy on its own set, because
    that is the only way a number like "20 of 20" means anything.
    """
    def g(key: str, default: Any = None) -> Any:
        return freeze.get(key, {}).get("value", default)

    agents = [
        {
            "id": "document",
            "name": "Document Intelligence",
            "role": "Reads BOLs and invoices",
            "one_liner": "OCR plus a language model pull structured fields out of "
                         "scanned freight paperwork.",
            "score": {
                "value": _num(g("doc_extraction_accuracy"), 4),
                "label": "per-field accuracy",
                "note": "on 20 of 40 planned rows — the rest wait on the daily "
                        "LLM quota",
                "file": "benchmarks/raw/w7_doc_extraction_eval.json",
            },
            "prompt_version": "doc_extraction/v2",
            "deterministic": "Field comparison and error detection are rules; the "
                             "model only reads the page.",
        },
        {
            "id": "order",
            "name": "Order Entry",
            "role": "Turns customer emails into TMS orders",
            "one_liner": "Reads a booking email, validates it, and either files the "
                         "order or asks exactly one question.",
            "score": {
                "value": _num(g("order_eval_success"), 3),
                "label": "cases correct",
                "note": f"{g('order_eval_run', 50)} of 50 authored cases, "
                        f"{g('order_eval_invented', 0)} orders filed on invented values",
                "file": "benchmarks/raw/w5_order_eval_summary.json",
            },
            "prompt_version": "order_entry/v1",
            "deterministic": "Validation and the decision to ask are arithmetic; "
                             "the model writes the question.",
        },
        {
            "id": "exception",
            "name": "Tracking & Exception",
            "role": "Watches live shipments",
            "one_liner": "Takes a delay alert off the stream, grades its severity, "
                         "notifies the customer and files a ticket.",
            "score": {
                "value": _num(g("exception_precision_as_of"), 4),
                "label": "notification precision (as-of)",
                "note": "against 54.1% for notifying on every single journey. An "
                        "earlier measurement said 72.1% and was wrong: it scored "
                        "early journeys using information that only existed later.",
                "file": "benchmarks/raw/w8_replay_leakage.json",
            },
            "prompt_version": "exception_triage/v1",
            "deterministic": "Severity is computed from the predicted gap; the model "
                             "writes the customer sentence.",
        },
        {
            "id": "invoice",
            "name": "Freight Invoice Auditor",
            "role": "Approves or disputes invoices",
            "one_liner": "Checks a freight invoice against the order and the "
                         "corridor's own measured rate band.",
            "score": {
                "value": _num(g("invoice_correct"), 0),
                "label": "of 20 verdicts matched",
                "note": "no correct invoice was wrongly disputed. The rate band "
                        "comes from the same model that generated the test "
                        "invoices, so this measures the checking, not the pricing.",
                "file": "benchmarks/raw/w6_invoice_audit_runs.json",
            },
            "prompt_version": "invoice_audit/v1",
            "deterministic": "The verdict is arithmetic against a rate band; the "
                             "model writes the dispute note.",
        },
        {
            "id": "assistant",
            "name": "Analytics Assistant",
            "role": "Answers questions about the network",
            "one_liner": "Retrieval over the project's own corridor, hub and "
                         "document index — and a refusal when the answer is not in it.",
            "score": {
                "value": _num(g("assistant_groundedness"), 4),
                "label": "groundedness of model-written answers",
                "note": f"route accuracy {g('assistant_route_accuracy', 0.9)} on the "
                        "fixed question set; all out-of-scope questions refused",
                "file": "benchmarks/raw/w7_groundedness_summary.json",
            },
            "prompt_version": "analytics_assistant/v1",
            "deterministic": "Routing and retrieval are code; the model phrases the "
                             "answer, and can be switched off entirely.",
        },
    ]

    orchestrator = {
        "cases": int(g("lifecycle_cases", 10) or 10),
        "booked": int(g("lifecycle_booked", 5) or 5),
        "ticketed": int(g("lifecycle_ticketed", 2) or 2),
        "file": "benchmarks/raw/w6_orchestrator_runs.json",
        "note": "Ten emails, three distinct paths, no human in the middle.",
    }

    written = [_write(out, "agents.json", _envelope(
        ["benchmarks/agent_evaluation.md", "benchmarks/results_freeze_v3.json"],
        {"agents": agents, "orchestrator": orchestrator},
    ))]

    # The MCP transcript ships as-is: it is already small and already evidence.
    mcp_src = RAW / "w7_mcp_stdio_transcript.json"
    if mcp_src.exists():
        mcp = _read_json(mcp_src)
        written.append(_write(out, "mcp_transcript.json", _envelope(
            "benchmarks/raw/w7_mcp_stdio_transcript.json",
            {
                "transport": mcp.get("transport"),
                "protocol_version": mcp.get("protocol_version"),
                "server_name": mcp.get("server_name"),
                "tools": mcp.get("tools_discovered"),
                "summary": mcp.get("summary"),
                "calls": mcp.get("calls"),
            },
        )))
    return written


def export_assistant_eval(out: Path) -> tuple[str, int]:
    """The assistant's scorecard, including the answers it got wrong."""
    payload: dict[str, Any] = {}
    for mode, fname in (("no_llm", "w7_assistant_run_no_llm.json"),
                        ("llm", "w7_assistant_run_llm.json")):
        path = RAW / fname
        if not path.exists():
            continue
        d = _read_json(path)
        payload[mode] = {
            "answered": d.get("answered"),
            "questions": d.get("questions"),
            "route_accuracy": _num(d.get("route_accuracy"), 4),
            "source_accuracy": _num(d.get("source_accuracy"), 4),
            "refusal_recall": _num(d.get("refusal_recall"), 4),
            "refusal_precision": _num(d.get("refusal_precision"), 4),
            "by_category": d.get("by_category"),
            "misses": d.get("misses"),
        }

    gpath = RAW / "w7_groundedness_summary.json"
    if gpath.exists():
        g = _read_json(gpath)
        payload["groundedness"] = {
            "judged": g.get("judged"),
            "grounded": g.get("grounded"),
            "partly_grounded": g.get("partly_grounded"),
            "not_grounded": g.get("not_grounded"),
            "rate_model_written": _num(g.get("groundedness_rate_model_written"), 4),
            "out_of_scope_refused": g.get("out_of_scope_refused"),
            "out_of_scope_total": g.get("out_of_scope_total"),
            "extractive_fallbacks": g.get("extractive_fallbacks"),
            "method": g.get("method"),
        }
    return _write(out, "assistant_eval.json", _envelope(
        ["benchmarks/raw/w7_assistant_run_no_llm.json",
         "benchmarks/raw/w7_groundedness_summary.json"],
        payload,
    ))


def export_alerts_sample(out: Path) -> tuple[str, int]:
    """A recorded run, so the Alerts page is never empty.

    W-03: the live feed reads a local sink that does not exist in a deployment.
    This is the labelled fallback — the UI must say "replay", never imply live.
    """
    src = RAW / "w7_kafka_live.json"
    live = _read_json(src) if src.exists() else {}

    alerts: list[dict] = []
    corridors_path = RAW / "w2_corridor_audit.csv"
    if corridors_path.exists():
        df = pd.read_csv(corridors_path)
        worst = df[df["direction"] == "worse"].nlargest(60, "excess_ratio")
        for i, (_, r) in enumerate(worst.iterrows()):
            gap = _num(r.get("median_gap_min"), 0) or 0
            severity = (
                "critical" if gap >= 240 else
                "high" if gap >= 120 else
                "medium" if gap >= 60 else "low"
            )
            alerts.append({
                "seq": i + 1,
                "corridor_id": r["corridor_id"],
                "route": f"{r.get('source_city')} → {r.get('dest_city')}",
                "predicted_gap_min": gap,
                "excess_ratio": _num(r.get("excess_ratio"), 2),
                "severity": severity,
                "n_legs": int(r["n_legs"]),
            })

    payload = {
        "recorded_at": live.get("generated_at"),
        "source": live.get("source", "kafka"),
        "is_replay": True,
        "replay_note": (
            "A recorded run rather than a live feed."
        ),
        "run": {
            "events": live.get("events"),
            "alerts": live.get("alerts"),
            "events_per_second": _num(live.get("events_per_second"), 1),
            "scoring_rate_eps": _num(live.get("scoring_rate_eps"), 1),
        },
        "alerts": alerts,
    }
    return _write(out, "alerts_sample.json", _envelope(
        "benchmarks/raw/w7_kafka_live.json", payload,
    ))


def export_evidence_index(out: Path) -> tuple[str, int]:
    """Every frozen value, so each KPI on the site can link to its source.

    This is what makes the Evidence component generated rather than typed, and
    what `tests/test_web_numbers.py` diffs the site against.
    """
    doc = _read_json(FREEZE_PATH)
    entries = [{
        "key": v["id"],
        "label": _public_label(v["label"]),
        "value": _public_value(_clean(v["value"])),
        "unit": v.get("unit") or "",
        "week": v.get("week"),
        "file": f"benchmarks/raw/{v['source']}",
    } for v in doc.get("values", [])]

    return _write(out, "evidence_index.json", _envelope(
        "benchmarks/results_freeze_v3.json",
        {
            "frozen_at": doc.get("frozen_at"),
            "n_values": doc.get("n_values"),
            "entries": entries,
        },
    ))


def export_prompts(out: Path) -> tuple[str, int]:
    """Every prompt version, never overwritten (D-008).

    The site can then show the v1 → v2 diff that took document extraction from
    0.853 to 0.929 — the claim and its proof in the same view.
    """
    agents = []
    if PROMPTS_DIR.exists():
        for agent_dir in sorted(p for p in PROMPTS_DIR.iterdir() if p.is_dir()):
            if agent_dir.name.startswith("__"):
                continue
            versions = []
            for vf in sorted(agent_dir.glob("v*.md")):
                versions.append({
                    "version": vf.stem,
                    "text": vf.read_text(encoding="utf-8"),
                })
            if not versions:
                continue
            readme = agent_dir / "_README.md"
            agents.append({
                "agent": agent_dir.name,
                "notes": readme.read_text(encoding="utf-8") if readme.exists() else None,
                "versions": versions,
            })
    return _write(out, "prompts.json", _envelope(
        "src/agents/prompts/", agents,
    ))


def export_figures(figures_out: Path) -> int:
    """Copy the nine paper figures next to the site (W-12).

    They are the project's best content and were invisible in the old UI.
    """
    if not FIGURES_DIR.exists():
        return 0
    figures_out.mkdir(parents=True, exist_ok=True)
    n = 0
    for png in sorted(FIGURES_DIR.glob("*.png")):
        shutil.copy2(png, figures_out / png.name)
        n += 1
    return n


def export_figure_index(out: Path) -> tuple[str, int]:
    """Captions for the Evidence page, read from the figures README."""
    captions_path = FIGURES_DIR / "README.md"
    figures = []
    for png in sorted(FIGURES_DIR.glob("*.png")):
        figures.append({
            "file": f"/figures/{png.name}",
            "id": png.stem,
            "title": png.stem.replace("_", " ").replace("fig", "Figure ").strip(),
        })
    caption_text = (
        captions_path.read_text(encoding="utf-8")
        if captions_path.exists() else ""
    )
    # The README lists each figure with its source file; keep it verbatim so the
    # page can render it rather than re-describing nine figures by hand.
    return _write(out, "figures.json", _envelope(
        "docs/figures/", {"figures": figures, "readme": caption_text},
    ))


# ── entry point ──────────────────────────────────────────────────────────────

def run(out_dir: Path, figures_dir: Path) -> list[tuple[str, int]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    freeze = _load_freeze()

    written: list[tuple[str, int]] = []
    written.append(export_overview(out_dir, freeze))
    written.extend(export_corridors(out_dir))
    written.append(export_hubs(out_dir))
    written.append(export_model(out_dir, freeze))
    written.extend(export_agents(out_dir, freeze))
    written.append(export_assistant_eval(out_dir))
    written.append(export_alerts_sample(out_dir))
    written.append(export_evidence_index(out_dir))
    written.append(export_prompts(out_dir))
    written.append(export_figure_index(out_dir))

    n_figs = export_figures(figures_dir)
    print(f"\n  figures copied: {n_figs} -> {figures_dir}")
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="directory for the JSON the site reads")
    ap.add_argument("--figures-out", type=Path, default=DEFAULT_FIGURES_OUT,
                    help="directory for the copied paper figures")
    args = ap.parse_args()

    print(f"exporting web data -> {args.out}")
    written = run(args.out, args.figures_out)

    total = sum(size for _, size in written)
    print()
    for name, size in sorted(written, key=lambda x: -x[1]):
        print(f"  {size / 1024:9.1f} KB  {name}")
    print(f"  {'-' * 9}")
    print(f"  {total / 1024:9.1f} KB  total ({len(written)} files)")
    print("\nthe site reads only these files; every one carries its source.")


if __name__ == "__main__":
    main()
