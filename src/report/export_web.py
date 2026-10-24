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
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.common import config
from src.ml.stats import wilson

# ── where things come from and go ────────────────────────────────────────────

RAW = config.BENCHMARKS_RAW_DIR


def latest_freeze_path(bench_dir: Path | None = None) -> Path:
    """The newest `results_freeze_v<N>.json`, by N, so a v5 is picked up with no edit.

    The version is never hardcoded: the site, the paper and the README must quote the
    same freeze, and "the same" has to mean "the latest" without anyone remembering to
    change a constant. Sorted numerically, because v10 sorts before v9 as a string.
    """
    folder = bench_dir or config.BENCHMARKS_DIR
    found = []
    for path in folder.glob("results_freeze_v*.json"):
        match = re.fullmatch(r"results_freeze_v(\d+)\.json", path.name)
        if match:
            found.append((int(match.group(1)), path))
    if not found:
        raise FileNotFoundError(f"no results_freeze_v*.json under {folder}")
    return max(found)[1]


FREEZE_PATH = latest_freeze_path()
COORDS_PATH = config.REPO_ROOT / "src" / "dashboard" / "reference" / "centre_coords.csv"
CITY_COORDS_PATH = (
    config.REPO_ROOT / "src" / "dashboard" / "reference" / "india_city_coords.csv"
)
FIGURES_DIR = config.DOCS_DIR / "figures"
PROMPTS_DIR = config.REPO_ROOT / "src" / "agents" / "prompts"

DEFAULT_OUT = config.REPO_ROOT / "web" / "public" / "data"
DEFAULT_FIGURES_OUT = config.REPO_ROOT / "web" / "public" / "figures"

FREEZE_VERSION = "v" + FREEZE_PATH.stem.rsplit("_v", 1)[1]
FREEZE_FILE = f"benchmarks/{FREEZE_PATH.name}"

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
    frozen_at = _read_json(FREEZE_PATH).get("frozen_at")
    if frozen_at:
        return str(frozen_at)
    return datetime.fromtimestamp(0, UTC).isoformat()


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
    doc = _read_json(FREEZE_PATH)
    return {v["id"]: v for v in doc["values"]}


def _need(freeze: dict, key: str) -> Any:
    """A frozen value, or an error that names the missing key.

    There is deliberately no default. A number that falls back to a typed-in
    constant when its key goes missing is how a stale 0.9 stayed on the site next to a
    93.3% in the README; a missing key must stop the export instead.
    """
    if key not in freeze:
        raise KeyError(
            f"freeze {FREEZE_VERSION} has no value '{key}'; the site will not guess one"
        )
    return freeze[key]["value"]


def _req(mapping: dict, *path: str) -> Any:
    """Strict nested lookup into a benchmark file: raises, naming the path, if absent."""
    node: Any = mapping
    for part in path:
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"benchmark file has no '{'.'.join(path)}' (stopped at '{part}')")
        node = node[part]
    return node


def _prop(successes: int, total: int) -> dict[str, Any]:
    """A count with its Wilson 95% interval, computed here from the counts."""
    w = wilson(int(successes), int(total))
    return {
        "successes": w.successes,
        "total": w.total,
        "rate": round(w.point, 4),
        "ci_low": round(w.lower, 4),
        "ci_high": round(w.upper, 4),
    }


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
        "legs": int(_need(freeze, "legs_total")),
        "corridors": int(_need(freeze, "corridors_total")),
        "corridors_tested": int(_need(freeze, "corridors_tested")),
        "bottlenecks": int(_need(freeze, "bottlenecks")),
        "faster_corridors": int(_need(freeze, "faster_corridors")),
        "share_over_plan": _num(float((ratio > 1.0).mean()), 4),
        "median_ratio": _num(_need(freeze, "median_gap_ratio"), 2),
        "median_gap_min": _num(float(legs["gap_min"].median()), 1),
        "share_above_clip": _num(float((ratio > 8.0).mean()), 4),
        "histogram": histogram,
        "clip_at": 8.0,
        # The audit as the dependence-aware study found it (D-080, D-099, D-082): the list is a screening list.
        "audit_robust_slower": int(_need(freeze, "audit_robust_headline_slower")),
        "audit_placebo_discoveries": _num(_need(freeze, "audit_placebo_discoveries"), 0),
        "audit_welch_fdp": _num(_need(freeze, "power_welch_bh_fdp_shift_half"), 3),
        "audit_cluster_power_shift_one": _num(_need(freeze, "power_by_perm_shift_one"), 3),
        "stability_spearman": _num(_need(freeze, "stability_spearman"), 2),
    }
    return _write(
        out, "overview.json",
        _envelope("benchmarks/raw/w1_leg_summary.csv", payload),
    )


ROBUST_CSV = "b3_audit_robust_corridors.csv"
EB_CSV = "b4_eb_corridors.csv"

# The robustness and empirical-Bayes files are written by other modules. Their column
# names are matched against these candidates, so the export does not depend on one
# spelling; a file with none of them is ignored rather than guessed at.
_ROBUST_COLUMNS = ("robust", "is_robust", "robust_flag", "survives", "robust_significant")
_EB_RANK_COLUMNS = ("eb_rank", "rank_eb", "eb_bottleneck_rank", "shrunk_rank", "rank_eb_prob_floor10")


def _first_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    return next((c for c in candidates if c in df.columns), None)


def load_corridor_extras(raw_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    """Optional per-corridor columns: B3 `robust` flag and B4 `eb_rank`.

    Returns {corridor_id: {"robust": bool, "eb_rank": int}}. A file that is absent
    contributes nothing; the page then has no such column at all, instead of a column
    of dashes.
    """
    folder = raw_dir or RAW
    extras: dict[str, dict[str, Any]] = {}

    robust_path = folder / ROBUST_CSV
    if robust_path.exists():
        df = pd.read_csv(robust_path)
        col = _first_column(df, _ROBUST_COLUMNS)
        if col is None and "status" in df.columns:
            # B3's own file: `status` is robust / fragile / headline_only / not_significant (D-080).
            df = df.assign(robust=df["status"].astype(str).str.lower().eq("robust"))
            col = "robust"
        if col is not None and "corridor_id" in df.columns:
            for cid, flag in zip(df["corridor_id"], df[col], strict=True):
                if not pd.isna(flag):
                    extras.setdefault(str(cid), {})["robust"] = (
                        str(flag).strip().lower() in ("1", "true", "yes", "1.0")
                    )

    eb_path = folder / EB_CSV
    if eb_path.exists():
        df = pd.read_csv(eb_path)
        col = _first_column(df, _EB_RANK_COLUMNS)
        if col is not None and "corridor_id" in df.columns:
            for cid, rank in zip(df["corridor_id"], df[col], strict=True):
                if not pd.isna(rank):
                    extras.setdefault(str(cid), {})["eb_rank"] = int(rank)
    return extras


def _route_label(src: dict, dst: dict) -> str:
    """`Kanpur → Kanpur`, built from names or, failing that, centre codes: never `nan`."""
    def end(place: dict) -> str:
        return place.get("city") or place.get("facility") or place["code"]
    return f"{end(src)} → {end(dst)}"


def _sig(value: Any, digits: int = 3) -> float | None:
    """Significant figures rather than decimal places: q-values run to 1e-12."""
    number = _num(value)
    if number is None:
        return None
    return float(f"{number:.{digits}g}")


def _corridor_records(
    csv_path: Path,
    coords: pd.DataFrame,
    extras: dict[str, dict[str, Any]] | None = None,
) -> list[dict]:
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

    extras = extras or {}
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
            "q_value": _sig(r.get("q_value")),
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
        record = records[-1]
        record["route"] = _route_label(record["src"], record["dst"])
        record.update(extras.get(str(r["corridor_id"]), {}))
    return records


def export_corridors(out: Path) -> list[tuple[str, int]]:
    """The audit, at both support floors.

    Both are shipped because D-018 is a *result*: the 10-leg and 30-leg top-20
    lists share no corridor at all, and the site shows that by toggling between
    them rather than describing it in a caption.
    """
    coords = _coords()
    written = []

    extras = load_corridor_extras()
    ten = _corridor_records(RAW / "w2_corridor_audit.csv", coords, extras)
    written.append(_write(out, "corridors.json", _envelope(
        ["benchmarks/raw/w2_corridor_audit.csv",
         "src/dashboard/reference/centre_coords.csv"],
        ten,
        support_floor=10,
        optional_columns=sorted({k for e in extras.values() for k in e}),
        located=sum(1 for c in ten if c["src"]["lat"] and c["dst"]["lat"]),
        legend={"worse": [
            {"upto": b[0], "color": b[1], "label": b[3], "range": b[4]}
            for b in SEVERITY_BINS
        ], "better": [
            {"upto": b[0], "color": b[1], "label": b[3], "range": b[4]}
            for b in FASTER_BINS
        ]},
    )))

    thirty = _corridor_records(RAW / "w2_corridor_audit_support30.csv", coords, extras)
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

    # The site says the reported model is the served one only when the running
    # stream has been shown to reproduce it (WP-11, D-053 closed). Without that file
    # it falls back to the old caveat rather than to an unearned claim.
    served_path = RAW / "w10_stream_validation_v2.json"
    served = json.loads(served_path.read_text(encoding="utf-8")) if served_path.exists() else {}
    proven = bool(served) and served.get("identical_predictions") == served.get("legs")
    headline = {
        "model": "v2_gbt_residual_absolute_step1",
        "mae_min": _num(_need(freeze, "model_v2_mae"), 2),
        "baseline_mae_min": _num(_need(freeze, "median_bar_mae"), 2),
        "osrm_mae_min": _num(_need(freeze, "mae_osrm"), 2),
        "mean_baseline_mae_min": _num(_need(freeze, "mae_corridor_mean"), 2),
    }
    # The hierarchical back-off baseline lands in a later freeze. The key is optional
    # on purpose and only this one: when it exists the Evidence page shows the bar,
    # when it does not the page says nothing about it.
    headline["backoff_mae_min"] = _num(_need(freeze, "bar_backoff_mae"), 2)
    headline["reported_mae_min"] = _num(_need(freeze, "reported_mae"), 2)
    headline["reported_vs_bar_min"] = _num(_need(freeze, "reported_vs_bar_delta"), 2)
    headline["reported_vs_bar_ci"] = [_num(_need(freeze, "reported_vs_bar_ci_low"), 2),
                                      _num(_need(freeze, "reported_vs_bar_ci_high"), 2)]
    headline["served_vs_bar_min"] = _num(_need(freeze, "served_vs_bar_delta"), 2)
    headline["rolling_folds_reported"] = int(_need(freeze, "ro_zoo_beats_bar_folds"))
    headline["rolling_folds_served"] = int(_need(freeze, "ro_served_beats_bar_folds"))
    headline["rolling_folds_total"] = int(_need(freeze, "ro_folds"))
    if proven:
        headline.update({
            "served_model": "v2_gbt_residual_absolute_step1",
            "served_note": (
                "The live stream and the predictor run the same model the results "
                "report. Each lane's rolling history is rebuilt from events as they "
                f"arrive, and {served['identical_predictions']} of {served['legs']} "
                "sampled legs score exactly as they do in the offline evaluation."
            ),
            "stream_equals_batch": {"identical": served["identical_predictions"], "legs": served["legs"]},
        })
    else:
        headline.update({
            "served_model": "an earlier random-forest model",
            "served_note": (
                "The best model needs a rolling view of each lane's recent "
                "history, which the live service cannot build yet, so the "
                "predictor runs an earlier and slightly weaker model and names "
                "it on every answer."
            ),
        })
    payload = {"headline": headline, "slices": slices}
    sources = ["benchmarks/raw/w7_model_metrics_v2_stepsize.csv", FREEZE_FILE]
    if proven:
        sources.append("benchmarks/raw/w10_stream_validation_v2.json")
    return _write(out, "model.json", _envelope(sources, payload))


def _assistant_trivial_route(answers_path: Path) -> dict[str, Any]:
    """Always answering with the most common expected route, on the same 30 questions."""
    routes = [
        json.loads(line)["expected_route"]
        for line in answers_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    top, count = Counter(routes).most_common(1)[0]
    return {"route": top, **_prop(count, len(routes))}


def _first(arm: dict, keys: tuple[str, ...]) -> Any:
    return next((arm[k] for k in keys if k in arm and arm[k] is not None), None)


def ablation_panel(raw_dir: Path | None = None) -> dict[str, Any] | None:
    """The optional "LLM decides" ablation (B7), or None when its file is absent.

    The result file is written by another module and its schema is read defensively:
    arms may be a list of objects or a mapping name -> object, and each arm may state
    accuracy as a bare rate, as `successes`/`total`, or as an object with a Wilson
    interval. Whatever it states is carried through; what it does not state is left
    out, never invented.
    """
    path = (raw_dir or RAW) / "b7_agent_ablation.json"
    if not path.exists():
        return None
    doc = _read_json(path)
    raw_arms = doc.get("arms", doc.get("results", doc.get("conditions")))
    if isinstance(raw_arms, dict):
        arms_in = [
            {"name": k, **(v if isinstance(v, dict) else {"accuracy": v})}
            for k, v in raw_arms.items()
        ]
    elif isinstance(raw_arms, list):
        arms_in = [a for a in raw_arms if isinstance(a, dict)]
    else:
        return None

    cost_keys = ("cost_usd", "cost", "tokens", "total_tokens", "llm_calls", "calls")
    arms = []
    for arm in arms_in:
        acc = _first(arm, ("accuracy", "acc", "correct_rate", "rate"))
        entry: dict[str, Any] = {
            "name": str(_first(arm, ("name", "arm", "condition", "label")) or "arm"),
        }
        if isinstance(acc, dict):
            entry["accuracy"] = _num(_first(acc, ("rate", "value", "point")), 4)
            entry["ci_low"] = _num(_first(acc, ("ci_low", "lower", "low")), 4)
            entry["ci_high"] = _num(_first(acc, ("ci_high", "upper", "high")), 4)
            entry["n"] = _first(acc, ("total", "n"))
        else:
            entry["accuracy"] = _num(acc, 4)
            entry["ci_low"] = _num(_first(arm, ("ci_low", "accuracy_ci_low")), 4)
            entry["ci_high"] = _num(_first(arm, ("ci_high", "accuracy_ci_high")), 4)
            entry["n"] = _first(arm, ("n", "n_cases", "total", "cases"))
            ok, total = arm.get("successes"), arm.get("total")
            if entry["ci_low"] is None and ok is not None and total:
                w = _prop(ok, total)
                entry["ci_low"], entry["ci_high"] = w["ci_low"], w["ci_high"]
                if entry["accuracy"] is None:
                    entry["accuracy"] = w["rate"]
        unanimity = _first(arm, ("unanimity", "unanimous", "unanimity_rate", "agreement"))
        if isinstance(unanimity, dict):
            unanimity = _first(unanimity, ("rate", "value"))
        entry["unanimity"] = _num(unanimity, 4)
        cost = _first(arm, cost_keys)
        entry["cost"] = cost if isinstance(cost, (int, float, str)) else None
        entry["cost_unit"] = next((k for k in cost_keys if k in arm), None)
        arms.append(entry)
    if not arms:
        return None
    return {
        "file": "benchmarks/raw/b7_agent_ablation.json",
        "note": str(_first(doc, ("note", "description", "question")) or ""),
        "arms": arms,
    }


def _agree(computed: float, frozen_value: Any, what: str) -> None:
    """A card recomputed from counts must round to the number the freeze holds."""
    if abs(float(computed) - float(frozen_value)) > 6e-4:
        raise ValueError(
            f"{what}: counts give {computed} but the freeze holds {frozen_value}"
        )


def _agent_cards(freeze: dict, raw_dir: Path) -> list[dict[str, Any]]:
    """One card per agent: metric, n, Wilson interval and the trivial policy beside it.

    Every proportion is recomputed from its counts with `src.ml.stats.wilson`, and
    each value that the freeze also holds is checked against it, so the card and the
    paper cannot quote different numbers for one measurement.
    """

    def rj(name: str) -> dict:
        return _read_json(raw_dir / name)

    # Document extraction: fields, not documents.
    doc = _req(rj("w7_doc_extraction_eval.json"), "overall")
    doc_p = _prop(doc["correct"], doc["fields_in_truth"])
    _agree(doc_p["rate"], _need(freeze, "doc_extraction_accuracy"), "document accuracy")

    # Order entry: the held-out first run is the number with evidential weight.
    order = rj("w9_order_eval.json")
    held = _req(order, "held_out_first_run", "overall")
    _agree(held["rate"], _need(freeze, "order_eval_scale_heldout"), "order held-out")
    order_n = int(_need(freeze, "order_eval_scale_cases"))
    fixed = _req(order, "overall")
    always_file = _req(order, "trivial_policy_always_file")
    order50 = rj("w5_order_eval_summary.json")
    n50 = int(_need(freeze, "order_eval_run"))
    order50_p = _prop(round(float(_need(freeze, "order_eval_success")) * n50), n50)
    invented_first = _req(order, "held_out_first_run", "orders_filed_on_invented_values")

    # Exception agent, scored as-of (D-054).
    exc = rj("w8_replay_leakage.json")
    exc_as = _req(exc, "exception_agent_as_of")
    notified = int(_req(exc_as, "alerts_scored"))
    hits = sum(int(r["truly_delayed"]) for r in exc_as["by_severity"])
    exc_p = _prop(hits, notified)
    _agree(exc_p["rate"], _need(freeze, "exception_precision_as_of"), "exception precision")
    legs_replayed = int(_req(exc, "legs"))
    delayed_legs = int(_req(rj("w6_exception_eval.json"), "legs_truly_delayed"))
    exc_base = _prop(delayed_legs, legs_replayed)

    # Invoice auditor: the stratified 200 is the headline, the 60 seeded run is history.
    inv = rj("w9_invoice_eval.json")
    inv_p = _req(inv, "accuracy")
    _agree(inv_p["rate"], _need(freeze, "invoice_eval_scale_accuracy"), "invoice accuracy")
    inv_n = int(_need(freeze, "invoice_eval_scale_cases"))
    inv60 = rj("w6_invoice_eval.json")
    n60 = int(_req(inv60, "cases"))
    should_dispute = sum(int(k["n"]) for k in inv60["by_kind"] if k["expected"] == "dispute")
    inv60_recall = _prop(should_dispute - int(inv60["missed_problems"]), should_dispute)
    inv60_acc = _prop(round(float(inv60["accuracy"]) * n60), n60)

    # Assistant: route accuracy with and without the model, both on the same 30.
    llm = rj("w7_assistant_run_llm.json")
    nollm = rj("w7_assistant_run_no_llm.json")
    q_llm, q_no = int(llm["questions"]), int(nollm["questions"])
    route_llm = _prop(round(float(llm["route_accuracy"]) * q_llm), q_llm)
    route_no = _prop(round(float(nollm["route_accuracy"]) * q_no), q_no)
    _agree(route_no["rate"], _need(freeze, "assistant_route_accuracy"), "assistant route (no model)")
    ground = rj("w7_groundedness_summary.json")
    g_n = int(ground["model_written_in_scope"])
    g_p = _prop(round(float(ground["groundedness_rate_model_written"]) * g_n), g_n)
    _agree(g_p["rate"], _need(freeze, "assistant_groundedness"), "assistant groundedness")
    trivial_route = _assistant_trivial_route(raw_dir / "w7_assistant_answers_llm.jsonl")

    return [
        {
            "id": "document", "name": "Document Intelligence",
            "role": "Reads BOLs and invoices",
            "one_liner": "OCR plus a language model pull structured fields out of "
                         "scanned freight paperwork.",
            "score": {
                "value": doc_p["rate"], "label": "per-field accuracy",
                "unit": "fields", **doc_p,
                "note": f"{doc['correct']} of {doc['fields_in_truth']} fields on "
                        f"{_need(freeze, 'doc_extraction_rows')} of 40 planned documents; the "
                        "rest wait on the daily LLM quota. Fields from one document are not "
                        "independent, so the interval is optimistic.",
                "file": "benchmarks/raw/w7_doc_extraction_eval.json",
            },
            "baseline": {"label": "extract nothing", "value": 0.0,
                         "note": "a blank answer gets no field right"},
            "prompt_version": "doc_extraction/v2",
            "deterministic": "Field comparison and error detection are rules; the "
                             "model only reads the page.",
        },
        {
            "id": "order", "name": "Order Entry",
            "role": "Turns customer emails into TMS orders",
            "one_liner": "Reads a booking email, validates it, and either files the "
                         "order or asks exactly one question.",
            "score": {
                "value": held["rate"], "label": "cases correct, held-out first run",
                "unit": "emails", **_prop(held["successes"], held["total"]),
                "note": f"{order_n} authored emails, half adversarial. The first run, before "
                        f"any fix, filed {invented_first} orders on values the email never stated.",
                "file": "benchmarks/raw/w9_order_eval.json",
            },
            "baseline": {"label": "always file", "value": _req(always_file, "rate"),
                         "note": "never asks a question"},
            "also": [
                {"label": "after fixing what the first run found (not held out)",
                 "unit": "emails", **_prop(fixed["successes"], fixed["total"])},
                {"label": "earlier 50-email set", "unit": "emails", **order50_p,
                 "note": f"{order50['invented_orders']} orders filed on invented values"},
            ],
            "prompt_version": "order_entry/v1",
            "deterministic": "Validation and the decision to ask are arithmetic; "
                             "the model writes the question.",
        },
        {
            "id": "exception", "name": "Tracking & Exception",
            "role": "Watches live shipments",
            "one_liner": "Takes a delay alert off the stream, grades its severity, "
                         "notifies the customer and files a ticket.",
            "score": {
                "value": exc_p["rate"], "label": "notification precision (as-of)",
                "unit": "alerts", **exc_p,
                "note": "An earlier measurement said 72.1% and was wrong: it scored "
                        "early journeys using information that only existed later.",
                "file": "benchmarks/raw/w8_replay_leakage.json",
            },
            "baseline": {"label": "notify on every leg", "value": exc_base["rate"],
                         "note": f"{delayed_legs} of {legs_replayed} replayed legs were truly delayed"},
            "prompt_version": "exception_triage/v1",
            "deterministic": "Severity is computed from the predicted gap; the model "
                             "writes the customer sentence.",
        },
        {
            "id": "invoice", "name": "Freight Invoice Auditor",
            "role": "Approves or disputes invoices",
            "one_liner": "Checks a freight invoice against the order and the "
                         "corridor's own measured rate band.",
            "score": {
                "value": inv_p["rate"], "label": "verdicts correct, stratified set",
                "unit": "invoices", **_prop(inv_p["successes"], inv_p["total"]),
                "note": f"{inv_n} invoices, 20 of each of 10 kinds, so the rate describes "
                        "the design, not a real (mostly clean) invoice stream. "
                        f"{_need(freeze, 'invoice_eval_scale_false_disputes')} correct invoices "
                        "were wrongly disputed; all 20 misses are the one kind sitting inside "
                        "the 15% tolerance, by design. The rate band comes from the same "
                        "model that generated the test invoices.",
                "file": "benchmarks/raw/w9_invoice_eval.json",
            },
            "baseline": {
                "label": "dispute everything",
                "value": _req(inv, "trivial_policy_dispute_everything", "rate"),
                "note": "approve everything scores "
                        f"{_req(inv, 'trivial_policy_approve_everything', 'rate'):.1%}",
            },
            "also": [
                {"label": "dispute recall", "unit": "invoices that should be disputed",
                 **_prop(inv["dispute_recall"]["successes"], inv["dispute_recall"]["total"])},
                {"label": "dispute precision", "unit": "disputes raised",
                 **_prop(inv["dispute_precision"]["successes"], inv["dispute_precision"]["total"])},
                {"label": "historical 60-invoice seeded run: verdict correct",
                 "historical": True, "unit": "invoices", **inv60_acc,
                 "note": f"precision {inv60['precision']:.1%}, recall {inv60['recall']:.1%} "
                         f"({inv60['missed_problems']} problems missed). The first "
                         f"{_need(freeze, 'invoice_cases')}-invoice development run scored "
                         f"{_need(freeze, 'invoice_correct')} of {_need(freeze, 'invoice_cases')}; "
                         "both are superseded by the 200-invoice set."},
                {"label": "historical 60-invoice run: dispute recall", "historical": True,
                 "unit": "invoices that should be disputed", **inv60_recall},
            ],
            "prompt_version": "invoice_audit/v1",
            "deterministic": "The verdict is arithmetic against a rate band; the "
                             "model writes the dispute note.",
        },
        {
            "id": "assistant", "name": "Analytics Assistant",
            "role": "Answers questions about the network",
            "one_liner": "Retrieval over the project's own corridor, hub and "
                         "document index, and a refusal when the answer is not in it.",
            "score": {
                "value": route_llm["rate"], "label": "route accuracy, model phrases the answer",
                "unit": "questions", **route_llm,
                "note": f"{route_llm['successes']} of {q_llm} fixed questions. Without the "
                        f"model the route is {route_no['rate']:.1%} "
                        f"({route_no['successes']} of {q_no}).",
                "file": "benchmarks/raw/w7_assistant_run_llm.json",
            },
            "baseline": {"label": f"always route to '{trivial_route['route']}'",
                         "value": trivial_route["rate"],
                         "note": "the most common expected route among the 30 questions"},
            "also": [
                {"label": "route accuracy, no model (rules only)", "unit": "questions",
                 **route_no},
                {"label": "groundedness of model-written answers", "unit": "answers", **g_p,
                 "note": f"hand-judged; {ground['extractive_fallbacks']} provider-error "
                         "fallbacks excluded"},
                {"label": "out-of-scope questions refused", "unit": "questions",
                 **_prop(ground["out_of_scope_refused"], ground["out_of_scope_total"]),
                 "note": "refusing nothing scores 0 of 6"},
            ],
            "prompt_version": "analytics_assistant/v1",
            "deterministic": "Routing and retrieval are code; the model phrases the "
                             "answer, and can be switched off entirely.",
        },
    ]


def export_agents(out: Path, freeze: dict) -> list[tuple[str, int]]:
    """One card per agent, each with the score it actually earned.

    Every agent is reported beside the trivial policy on its own set, because
    that is the only way a number like "20 of 20" means anything.
    """
    agents = _agent_cards(freeze, RAW)

    life = _read_json(RAW / "w9_lifecycle_eval.json")
    routed = life["routing_correct"]
    top_path, top_n = max(life["path_coverage"]["distribution"].items(), key=lambda kv: kv[1])
    n_life = int(_need(freeze, "lifecycle_eval_scale_cases"))
    _agree(routed["rate"], _need(freeze, "lifecycle_eval_scale_routing"), "orchestrator routing")
    orchestrator = {
        "cases": n_life,
        "routed": _prop(routed["successes"], routed["total"]),
        "paths_exercised": int(_need(freeze, "lifecycle_eval_scale_paths")),
        "baseline": {
            "label": f"always take the most common path ({top_path})",
            "value": round(top_n / n_life, 4),
            "note": f"{top_n} of {n_life} emails deserved it",
        },
        "distribution": life["path_coverage"]["distribution"],
        "earlier_booked": int(_need(freeze, "lifecycle_booked")),
        "earlier_ticketed": int(_need(freeze, "lifecycle_ticketed")),
        "earlier_cases": int(_need(freeze, "lifecycle_cases")),
        "file": "benchmarks/raw/w9_lifecycle_eval.json",
        "note": "100 emails read by the rule extractor, the graph routing on what it "
                "found. The earlier ten-email run handed intake the true fields, so it "
                "showed the wiring, not the routing.",
    }

    data: dict[str, Any] = {"agents": agents, "orchestrator": orchestrator}
    ablation = ablation_panel()
    if ablation is not None:
        data["ablation"] = ablation

    written = [_write(out, "agents.json", _envelope(
        ["benchmarks/agent_evaluation.md", FREEZE_FILE],
        data,
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
        d = _read_json(RAW / fname)
        n_q = int(_req(d, "questions"))
        route = _prop(round(float(_req(d, "route_accuracy")) * n_q), n_q)
        payload[mode] = {
            "answered": d.get("answered"),
            "questions": n_q,
            "route_correct": route["successes"],
            "route_ci_low": route["ci_low"],
            "route_ci_high": route["ci_high"],
            "route_accuracy": _num(d.get("route_accuracy"), 4),
            "source_accuracy": _num(d.get("source_accuracy"), 4),
            "refusal_recall": _num(d.get("refusal_recall"), 4),
            "refusal_precision": _num(d.get("refusal_precision"), 4),
            "by_category": d.get("by_category"),
            "misses": d.get("misses"),
        }

    g = _read_json(RAW / "w7_groundedness_summary.json")
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
         "benchmarks/raw/w7_assistant_run_llm.json",
         "benchmarks/raw/w7_groundedness_summary.json"],
        payload,
    ))


def export_alerts_sample(out: Path) -> tuple[str, int]:
    """A recorded run, so the Alerts page is never empty.

    W-03: the live feed reads a local sink that does not exist in a deployment.
    This is the labelled fallback: the UI says "replay", never "live".
    """
    live = _read_json(RAW / "w7_kafka_live.json")
    coords = _coords()
    records = _corridor_records(RAW / "w2_corridor_audit.csv", coords)
    by_id = {r["id"]: r for r in records}

    audit = pd.read_csv(RAW / "w2_corridor_audit.csv")
    worst = audit[audit["direction"] == "worse"].nlargest(60, "excess_ratio")
    alerts: list[dict] = []
    for i, (_, r) in enumerate(worst.iterrows()):
        gap = _num(r.get("median_gap_min"), 0) or 0
        severity = (
            "critical" if gap >= 240 else
            "high" if gap >= 120 else
            "medium" if gap >= 60 else "low"
        )
        rec = by_id.get(r["corridor_id"])
        if rec is not None:
            route = rec["route"]
        else:
            route = f"{r['source_center']} → {r['destination_center']}"
        alerts.append({
            "seq": i + 1,
            "corridor_id": r["corridor_id"],
            "route": route,
            "predicted_gap_min": gap,
            "excess_ratio": _num(r.get("excess_ratio"), 2),
            "severity": severity,
            "n_legs": int(r["n_legs"]),
        })

    n_alerts = int(_req(live, "alerts"))
    channel = _read_json(RAW / "f2_alert_channel_live.json")
    delivery = [
        {
            "channel": run["channel"],
            "recorded_at": run["recorded_at"],
            "candidates": run["candidates"],
            "sent": run["sent"],
            "failed": run["failed"],
            "suppressed_by_cap": run["suppressed_cap"],
        }
        for run in channel["runs"]
    ]
    payload = {
        "recorded_at": live.get("generated_at"),
        "source": live.get("source", "kafka"),
        "is_replay": True,
        "replay_note": "A recorded run rather than a live feed.",
        "sample_note": (
            f"The table lists the {len(alerts)} worst corridors by overrun as examples "
            f"of what an alert says. It is a sample, not the {n_alerts:,} alerts the "
            "recorded run raised: those are summarised above and are not all listed here."
        ),
        "run": {
            "events": live.get("events"),
            "alerts": n_alerts,
            "events_per_second": _num(live.get("events_per_second"), 1),
            "scoring_rate_eps": _num(live.get("scoring_rate_eps"), 1),
        },
        "delivery": delivery,
        "delivered_channels": channel["channels_delivered"],
        "alerts": alerts,
    }
    return _write(out, "alerts_sample.json", _envelope(
        ["benchmarks/raw/w7_kafka_live.json", "benchmarks/raw/f2_alert_channel_live.json"],
        payload,
    ))


# Freeze values the site relabels. The freeze keeps its original wording; the public
# page says what each one now is.
RELABEL = {
    "champion_model": "Week 4 model family, superseded (D-050)",
    "mae_champion": "Week 4 random forest test MAE, superseded (D-050)",
    "corridors_improved": "Test corridors the Week 4 random forest beats OSRM on, superseded (D-050)",
    "scale_rows": "Proxy rows (NYC taxi trips) the Week 2 aggregation stage alone was run on",
}

# Shares that are only meaningful beside the number of cases behind them.
N_OF = {
    "order_eval_success": "order_eval_run",
    "order_eval_scale_heldout": "order_eval_scale_cases",
    "invoice_eval_scale_accuracy": "invoice_eval_scale_cases",
    "lifecycle_eval_scale_routing": "lifecycle_eval_scale_cases",
}


def export_evidence_index(out: Path) -> tuple[str, int]:
    """Every frozen value, so each KPI on the site can link to its source.

    This is what makes the Evidence component generated rather than typed, and
    what `tests/test_web_numbers.py` diffs the site against.
    """
    doc = _read_json(FREEZE_PATH)
    values = {v["id"]: v["value"] for v in doc["values"]}
    entries = []
    for v in doc["values"]:
        key = v["id"]
        entry = {
            "key": key,
            "label": RELABEL.get(key, _public_label(v["label"])),
            "value": _public_value(_clean(v["value"])),
            "unit": v.get("unit") or "",
            "week": v.get("week"),
            "file": f"benchmarks/raw/{v['source']}",
        }
        if key in RELABEL and "superseded" in RELABEL[key]:
            entry["superseded"] = True
        if key in N_OF:
            entry["unit"] = "share"
            entry["n"] = int(values[N_OF[key]])
        entries.append(entry)

    return _write(out, "evidence_index.json", _envelope(
        FREEZE_FILE,
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
    """Copy the paper figures (PNG for the page, PDF for the paper link) next to the site."""
    if not FIGURES_DIR.exists():
        return 0
    figures_out.mkdir(parents=True, exist_ok=True)
    n = 0
    for png in sorted(FIGURES_DIR.glob("*.png")):
        shutil.copy2(png, figures_out / png.name)
        pdf = png.with_suffix(".pdf")
        if pdf.exists():
            shutil.copy2(pdf, figures_out / pdf.name)
        n += 1
    return n


def figure_captions(readme_text: str) -> dict[str, str]:
    """`fig1_name` -> caption, from the figures README table. One source for caption and alt text."""
    captions: dict[str, str] = {}
    for line in readme_text.splitlines():
        m = re.match(r"\|\s*\[`((?:fig|b\d)[^`]+)`\]\([^)]*\)\s*\|\s*(.+?)\s*\|\s*$", line)
        if m:
            captions[m.group(1)] = m.group(2)
    return captions


def export_figure_index(out: Path) -> tuple[str, int]:
    """Captions for the Evidence and Paper pages, read from the figures README."""
    captions_path = FIGURES_DIR / "README.md"
    caption_text = (
        captions_path.read_text(encoding="utf-8")
        if captions_path.exists() else ""
    )
    captions = figure_captions(caption_text)
    figures = []
    for png in sorted(FIGURES_DIR.glob("*.png")):
        figures.append({
            "file": f"/figures/{png.name}",
            "pdf": f"/figures/{png.stem}.pdf" if png.with_suffix(".pdf").exists() else None,
            "id": png.stem,
            "title": png.stem.replace("_", " ").replace("fig", "Figure ").strip(),
            "caption": captions.get(png.stem, ""),
        })
    # The README lists each figure with its source file; keep it verbatim so the
    # page can render it rather than re-describing nine figures by hand.
    return _write(out, "figures.json", _envelope(
        "docs/figures/", {"figures": figures, "readme": caption_text},
    ))


PAPER_ABSTRACT_PATH = config.REPO_ROOT / "paper" / "abstract.txt"
CITATION_PATH = config.REPO_ROOT / "CITATION.cff"
PLACEHOLDER_ABSTRACT = (
    "The abstract is added here when the paper is finalised. Until then the numbers "
    "on every other page of this site are the ones the paper will report, each linked "
    "to the file it came from."
)


def parse_citation(text: str) -> dict[str, Any]:
    """The few CITATION.cff fields a BibTeX entry needs, without a YAML dependency.

    Handles the shapes this file uses: `key: value`, folded `key: >-` blocks and the
    `authors` list of family-names / given-names pairs.
    """
    out: dict[str, Any] = {"authors": []}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^([a-z-]+):\s*(.*)$", line)
        if m and not line.startswith(" "):
            key, val = m.group(1), m.group(2).strip()
            if val in (">-", ">", "|", "|-"):
                folded = []
                i += 1
                while i < len(lines) and (lines[i].startswith(" ") or not lines[i].strip()):
                    folded.append(lines[i].strip())
                    i += 1
                out[key] = " ".join(x for x in folded if x)
                continue
            if val:
                out[key] = val.strip("'\"")
        elif re.match(r"^\s+-?\s*family-names:\s*(.+)$", line):
            fam = re.match(r"^\s+-?\s*family-names:\s*(.+)$", line).group(1).strip()  # type: ignore[union-attr]
            given = ""
            if i + 1 < len(lines):
                g = re.match(r"^\s+given-names:\s*(.+)$", lines[i + 1])
                if g:
                    given = g.group(1).strip()
            out["authors"].append((fam, given))
        i += 1
    return out


def bibtex_from_citation(cff: dict[str, Any]) -> str:
    """A BibTeX entry built from the CITATION.cff fields, never typed into the page."""
    year = str(cff.get("date-released", ""))[:4] or "n.d."
    authors = " and ".join(f"{fam}, {given}" for fam, given in cff["authors"])
    first = cff["authors"][0][0].lower() if cff["authors"] else "anon"
    lines = [
        f"@software{{{first}{year}controltower,",
        f"  title   = {{{cff['title']}}},",
        f"  author  = {{{authors}}},",
        f"  year    = {{{year}}},",
    ]
    if cff.get("version"):
        lines.append(f"  version = {{{cff['version']}}},")
    if cff.get("repository-code"):
        lines.append(f"  url     = {{{cff['repository-code']}}},")
    lines.append("}")
    return "\n".join(lines)


def export_paper(out: Path, freeze: dict) -> tuple[str, int]:
    """Everything the Paper page shows, so the page itself holds no typed claim.

    The abstract comes from `paper/abstract.txt` when it exists; otherwise a plainly
    marked placeholder is shipped and the page says so. The preprint link stays null
    until a preprint exists.
    """
    if PAPER_ABSTRACT_PATH.exists():
        abstract = PAPER_ABSTRACT_PATH.read_text(encoding="utf-8").strip()
        placeholder = False
    else:
        abstract, placeholder = PLACEHOLDER_ABSTRACT, True
    cff = parse_citation(CITATION_PATH.read_text(encoding="utf-8"))
    docs = [
        ("Reproducibility guide", "REPRODUCIBILITY.md"),
        ("Rebuild notes", "docs/W8_mounika_reproducibility.md"),
        ("Data card", "docs/data_card.md"),
        ("Model card", "docs/model_card.md"),
        ("Decision log", "docs/decisions.md"),
    ]
    payload = {
        "title": cff["title"],
        "abstract": abstract,
        "abstract_is_placeholder": placeholder,
        "preprint_url": None,
        "bibtex": bibtex_from_citation(cff),
        "headline": {
            "bottlenecks": _need(freeze, "bottlenecks"),
            "faster_corridors": _need(freeze, "faster_corridors"),
            "model_v2_mae": _need(freeze, "model_v2_mae"),
            "median_bar_mae": _need(freeze, "median_bar_mae"),
        },
        "reproduce": {
            "command": "bash scripts/rebuild_all.sh",
            "links": [
                {"label": label, "path": path}
                for label, path in docs
                if (config.REPO_ROOT / path).exists()
            ],
        },
    }
    return _write(out, "paper.json", _envelope(
        ["CITATION.cff", "paper/abstract.txt" if not placeholder else "placeholder"],
        payload,
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
    written.append(export_paper(out_dir, freeze))

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
