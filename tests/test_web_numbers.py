"""
The site's numbers against the results freeze.

The point of this suite is narrow and worth stating: **a number on the public
site and the same number in the paper must not be able to drift apart.** The
export reads `benchmarks/raw/` and the freeze reads `benchmarks/raw/`, so they
agree today; what this catches is the day someone edits one path and not the
other, or hand-fixes a JSON because a page looked wrong.

Run:  pytest tests/test_web_numbers.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.common import config
from src.report import export_web

WEB_DATA = config.REPO_ROOT / "web" / "public" / "data"
FREEZE = config.BENCHMARKS_DIR / "results_freeze_v3.json"

pytestmark = pytest.mark.skipif(
    not WEB_DATA.exists(),
    reason="web data not exported yet — run python -m src.report.export_web",
)


def _load(name: str):
    return json.loads((WEB_DATA / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def frozen() -> dict[str, object]:
    doc = json.loads(FREEZE.read_text(encoding="utf-8"))
    return {v["id"]: v["value"] for v in doc["values"]}


# ── every file is present and carries its provenance ─────────────────────────

EXPECTED_FILES = [
    "overview.json",
    "corridors.json",
    "corridors_support30.json",
    "hubs.json",
    "model.json",
    "agents.json",
    "evidence_index.json",
    "prompts.json",
    "assistant_eval.json",
    "alerts_sample.json",
]


@pytest.mark.parametrize("name", EXPECTED_FILES)
def test_file_exists_and_declares_its_source(name: str) -> None:
    doc = _load(name)
    assert "data" in doc, f"{name} has no payload"
    assert doc.get("source"), f"{name} does not say where it came from"
    assert doc.get("freeze") == export_web.FREEZE_VERSION


# ── the headline numbers ─────────────────────────────────────────────────────

def test_overview_matches_freeze(frozen) -> None:
    o = _load("overview.json")["data"]
    assert o["legs"] == frozen["legs_total"]
    assert o["corridors"] == frozen["corridors_total"]
    assert o["corridors_tested"] == frozen["corridors_tested"]
    assert o["bottlenecks"] == frozen["bottlenecks"]
    assert o["faster_corridors"] == frozen["faster_corridors"]
    assert o["median_ratio"] == pytest.approx(frozen["median_gap_ratio"], abs=0.01)


def test_model_headline_matches_freeze(frozen) -> None:
    h = _load("model.json")["data"]["headline"]
    assert h["mae_min"] == pytest.approx(frozen["model_v2_mae"], abs=0.01)
    assert h["baseline_mae_min"] == pytest.approx(frozen["median_bar_mae"], abs=0.01)
    assert h["osrm_mae_min"] == pytest.approx(frozen["mae_osrm"], abs=0.01)


def test_the_served_model_is_named_as_not_the_reported_one() -> None:
    """D-053 is a caveat the site must carry, not a detail it may drop.

    The predictor page scores with the Week 4 champion while the results page
    reports a better model. If that sentence ever goes missing, the page starts
    implying it is scoring with the number printed next to it.
    """
    h = _load("model.json")["data"]["headline"]
    assert h["served_model"], "no served model named"
    assert "D-053" in h["served_note"]
    assert h["served_model"] != h["model"]


# ── the corridor audit reproduces exactly ────────────────────────────────────

def test_corridor_counts_match_the_audit(frozen) -> None:
    corridors = _load("corridors.json")["data"]
    assert len(corridors) == frozen["corridors_tested"]

    worse = sum(
        1 for c in corridors if c["is_significant"] and c["direction"] == "worse"
    )
    better = sum(
        1 for c in corridors if c["is_significant"] and c["direction"] == "better"
    )
    assert worse == frozen["bottlenecks"]
    assert better == frozen["faster_corridors"]


def test_every_corridor_is_placeable() -> None:
    """A corridor without both ends located is a line that never draws.

    This silently capped the old map at 101 of 273 bottlenecks (P-24), so it is
    asserted rather than eyeballed.
    """
    corridors = _load("corridors.json")["data"]
    unplaced = [
        c["id"]
        for c in corridors
        if not (c["src"]["lat"] and c["src"]["lon"]
                and c["dst"]["lat"] and c["dst"]["lon"])
    ]
    assert not unplaced, f"{len(unplaced)} corridors cannot be drawn: {unplaced[:5]}"


def test_support30_is_a_different_network() -> None:
    """D-018's finding, asserted: the two floors do not rank the same corridors
    differently — their top-20 lists are disjoint."""
    ten = _load("corridors.json")["data"]
    thirty = _load("corridors_support30.json")["data"]

    def top20(rows):
        sig = [r for r in rows if r["is_significant"] and r["direction"] == "worse"]
        sig.sort(key=lambda r: -r["excess_ratio"])
        return {r["id"] for r in sig[:20]}

    assert not (top20(ten) & top20(thirty)), (
        "the 10-leg and 30-leg top-20 lists now share a corridor; D-018's "
        "instability claim needs re-checking"
    )


# ── severity encoding ────────────────────────────────────────────────────────

def test_severity_never_relies_on_colour_alone() -> None:
    """W-11: every severity carries a word, so the ramp survives a colourblind
    read and a bad projector."""
    for c in _load("corridors.json")["data"]:
        sev = c["severity"]
        assert sev["label"], f"{c['id']} has a colour but no label"
        assert sev["range"], f"{c['id']} has no range text"


def test_severity_bins_are_the_tuned_ones() -> None:
    """D-058: the cut points came from the real bottleneck distribution and are
    not redesigned for the web."""
    assert [b[0] for b in export_web.SEVERITY_BINS] == [1.20, 1.50, 2.50, 99.0]
    assert [b[0] for b in export_web.FASTER_BINS] == [0.60, 0.75, 0.90, 1.00]


# ── agents ───────────────────────────────────────────────────────────────────

def test_agent_scores_match_freeze(frozen) -> None:
    agents = {a["id"]: a for a in _load("agents.json")["data"]["agents"]}

    assert agents["exception"]["score"]["value"] == pytest.approx(
        frozen["exception_precision_as_of"], abs=1e-4
    )
    assert agents["order"]["score"]["value"] == pytest.approx(
        frozen["order_eval_success"], abs=1e-4
    )
    assert agents["invoice"]["score"]["value"] == pytest.approx(
        frozen["invoice_correct"], abs=1e-4
    )
    assert agents["assistant"]["score"]["value"] == pytest.approx(
        frozen["assistant_groundedness"], abs=1e-4
    )
    assert agents["document"]["score"]["value"] == pytest.approx(
        frozen["doc_extraction_accuracy"], abs=1e-4
    )


def test_exception_agent_reports_the_asof_number(frozen) -> None:
    """D-054: the agent layer reports as-of precision. 0.7209 is the leaked
    measurement and must not reappear on the site."""
    exception = next(
        a for a in _load("agents.json")["data"]["agents"] if a["id"] == "exception"
    )
    assert exception["score"]["value"] == pytest.approx(0.5855, abs=1e-3)
    assert exception["score"]["value"] != pytest.approx(0.7209, abs=1e-3)


# ── payload size ─────────────────────────────────────────────────────────────

def test_payload_stays_shippable() -> None:
    """The whole point of the export is that a browser can hold it. 10.9 MB of
    leg summary became a 40-bin histogram; this stops that regressing."""
    total = sum(f.stat().st_size for f in WEB_DATA.glob("*.json"))
    assert total < 2_000_000, (
        f"the site's data is {total / 1024:.0f} KB — pre-aggregate further"
    )

    overview = (WEB_DATA / "overview.json").stat().st_size
    assert overview < 20_000, "overview.json should be a few KB, not a table"
