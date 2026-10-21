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
import re

import pytest

from src.common import config
from src.report import export_web

WEB_DATA = config.REPO_ROOT / "web" / "public" / "data"
RAW = config.BENCHMARKS_RAW_DIR
FREEZE = export_web.latest_freeze_path()

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
    "paper.json",
    "figures.json",
    "assistant_eval.json",
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


def test_the_served_model_claim_is_backed_by_the_stream_validation() -> None:
    """The site may say the reported model is the served one only with evidence.

    Until WP-11 the predictor ran the Week 4 champion and this test required the page
    to say so (D-053). The stream now serves v2, so the claim flipped -- and the test
    flipped with it rather than being deleted: "served" must now be backed by
    `w10_stream_validation_v2.json` showing every sampled leg identical, and the
    fallback wording must still admit the weaker model if that file ever goes away.
    """
    h = _load("model.json")["data"]["headline"]
    assert h["served_model"], "no served model named"
    validation = RAW / "w10_stream_validation_v2.json"
    if h["served_model"] == h["model"]:
        assert validation.exists(), "the site claims v2 is served with no validation file behind it"
        report = json.loads(validation.read_text(encoding="utf-8"))
        assert report["identical_predictions"] == report["legs"] >= 500
        assert h["stream_equals_batch"] == {"identical": report["legs"], "legs": report["legs"]}
    else:
        note = h["served_note"].lower()
        assert "earlier" in note or "weaker" in note, (
            "the served-model note no longer says the live model is the weaker one"
        )


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
    # The order card leads with the held-out first run on 200 emails, not the earlier
    # 50-of-50; the 50 stays on the card as a secondary row.
    assert agents["order"]["score"]["value"] == pytest.approx(
        frozen["order_eval_scale_heldout"], abs=1e-4
    )
    assert agents["order"]["score"]["total"] == frozen["order_eval_scale_cases"]
    assert any(
        row["total"] == frozen["order_eval_run"]
        and row["rate"] == pytest.approx(frozen["order_eval_success"], abs=1e-4)
        for row in agents["order"]["also"]
    )
    # The invoice card leads with the stratified 200, never "20 of 20" alone (A3).
    assert agents["invoice"]["score"]["value"] == pytest.approx(
        frozen["invoice_eval_scale_accuracy"], abs=1e-4
    )
    assert agents["invoice"]["score"]["total"] == frozen["invoice_eval_scale_cases"]
    # The assistant card leads with route accuracy (the model-phrasing run, n=30);
    # the frozen groundedness and the frozen no-model route sit on the card beside it.
    assert agents["assistant"]["score"]["total"] == 30
    also = {r["label"]: r for r in agents["assistant"]["also"]}
    assert also["groundedness of model-written answers"]["rate"] == pytest.approx(
        frozen["assistant_groundedness"], abs=1e-3
    )
    assert also["route accuracy, no model (rules only)"]["rate"] == pytest.approx(
        frozen["assistant_route_accuracy"], abs=1e-4
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


# ── freshness: nothing on the site may cite an older freeze (A6) ──────────────

def test_every_exported_file_cites_the_newest_freeze() -> None:
    newest = max(
        int(p.stem.rsplit("_v", 1)[1])
        for p in config.BENCHMARKS_DIR.glob("results_freeze_v*.json")
    )
    stale = {
        p.name: _load(p.name).get("freeze")
        for p in WEB_DATA.glob("*.json")
        if _load(p.name).get("freeze") != f"v{newest}"
    }
    assert not stale, f"exported files cite an older freeze than v{newest}: {stale}"


def test_no_exported_file_names_an_older_freeze_in_its_sources() -> None:
    newest = export_web.FREEZE_FILE
    for path in WEB_DATA.glob("*.json"):
        source = _load(path.name).get("source")
        sources = source if isinstance(source, list) else [source]
        for s in sources:
            if isinstance(s, str) and "results_freeze_v" in s:
                assert s == newest, f"{path.name} cites {s}, newest is {newest}"


# ── no placeholder text ever reaches a visitor (D1) ──────────────────────────

_PLACEHOLDER = re.compile(r"(?<![A-Za-z0-9_])(nan|NaN|undefined|null|None)(?![A-Za-z0-9_])")


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


@pytest.mark.parametrize("name", [n for n in EXPECTED_FILES if n != "prompts.json"])
def test_no_standalone_nan_or_placeholder_strings(name: str) -> None:
    # prompts.json is the project's own prompt prose and may say "None" in an
    # instruction to the model, so it is the one file not scanned for words.
    bad = [s for s in _strings(_load(name)) if _PLACEHOLDER.search(s)]
    assert not bad, f"{name} carries placeholder strings: {bad[:5]}"


def test_prompts_file_has_no_nan_as_a_value() -> None:
    bad = [s for s in _strings(_load("prompts.json")) if s.strip().lower() == "nan"]
    assert not bad


def test_alert_routes_are_names_not_nan() -> None:
    for alert in _load("alerts_sample.json")["data"]["alerts"]:
        assert " → " in alert["route"]
        assert "nan" not in alert["route"].lower().split()


def test_every_corridor_has_a_printable_route() -> None:
    for c in _load("corridors.json")["data"]:
        assert c["route"] and "nan" not in c["route"].lower().split()


# ── agents: every card shows metric, n, interval and its trivial policy (D4) ─

def test_every_agent_card_has_n_interval_and_baseline() -> None:
    agents = _load("agents.json")["data"]["agents"]
    assert {a["id"] for a in agents} == {"document", "order", "exception", "invoice", "assistant"}
    for a in agents:
        s = a["score"]
        assert s["total"] > 0 and s["unit"], a["id"]
        assert 0 <= s["ci_low"] <= s["rate"] <= s["ci_high"] <= 1, a["id"]
        assert 0 <= a["baseline"]["value"] <= 1 and a["baseline"]["label"], a["id"]


def test_orchestrator_card_is_the_100_lifecycle_run(frozen) -> None:
    o = _load("agents.json")["data"]["orchestrator"]
    assert o["cases"] == frozen["lifecycle_eval_scale_cases"] == 100
    assert o["routed"]["successes"] == o["routed"]["total"] == 100
    assert o["routed"]["rate"] == pytest.approx(frozen["lifecycle_eval_scale_routing"])
    assert o["baseline"]["label"] and o["routed"]["ci_low"] < 1


def test_invoice_card_states_the_sixty_invoice_history_not_20_of_20_alone() -> None:
    inv = next(a for a in _load("agents.json")["data"]["agents"] if a["id"] == "invoice")
    history = [r for r in inv["also"] if r.get("historical")]
    assert history, "the 60-invoice seeded run must stay on the card, labelled historical"
    text = " ".join(r["note"] for r in history if "note" in r)
    assert "100.0%" in text and "82.2%" in text
    assert inv["score"]["total"] == 200 and 0.85 < inv["score"]["ci_low"] < 0.86


def test_assistant_route_accuracy_is_shown_both_ways_with_n_30() -> None:
    a = next(a for a in _load("agents.json")["data"]["agents"] if a["id"] == "assistant")
    assert a["score"]["total"] == 30 and a["score"]["rate"] == pytest.approx(0.9333, abs=1e-4)
    no_model = next(r for r in a["also"] if "no model" in r["label"])
    assert no_model["total"] == 30 and no_model["rate"] == pytest.approx(0.9, abs=1e-4)
    ev = _load("assistant_eval.json")["data"]
    assert ev["llm"]["questions"] == ev["no_llm"]["questions"] == 30
    assert ev["llm"]["route_accuracy"] > ev["no_llm"]["route_accuracy"]


def test_alert_page_data_explains_the_sample_and_names_the_full_count() -> None:
    d = _load("alerts_sample.json")["data"]
    assert d["is_replay"] is True
    assert f"{d['run']['alerts']:,}" in d["sample_note"]
    assert "sample" in d["sample_note"]
    assert d["delivered_channels"], "the live Telegram/email delivery (D-071) must be recorded"


def test_paper_data_is_complete_and_never_claims_a_preprint_that_does_not_exist() -> None:
    p = _load("paper.json")["data"]
    assert p["abstract"].strip() and p["bibtex"].startswith("@")
    assert p["preprint_url"] is None or p["preprint_url"].startswith("http")
    assert p["reproduce"]["command"] == "bash scripts/rebuild_all.sh"
    assert p["abstract_is_placeholder"] == (not export_web.PAPER_ABSTRACT_PATH.exists())


def test_every_figure_has_a_caption_for_its_alt_text() -> None:
    figs = _load("figures.json")["data"]["figures"]
    assert len(figs) >= 9
    assert all(f["caption"] for f in figs)
