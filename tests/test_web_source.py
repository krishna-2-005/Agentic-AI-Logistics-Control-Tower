"""
Source-level checks on the site: wording, naming and the claims it must not make.

These read the TypeScript and the exported JSON as text, so a regression to an
overclaim or a stale label fails in the fast CI job without a browser.
"""

from __future__ import annotations

import json
import re

import pytest

from src.common import config

WEB = config.REPO_ROOT / "web"
SOURCES = [
    p
    for folder in ("app", "components", "lib")
    for p in (WEB / folder).rglob("*")
    if p.suffix in (".ts", ".tsx")
]
DATA = WEB / "public" / "data"


def _text(path) -> str:
    return path.read_text(encoding="utf-8")


def test_sources_were_found() -> None:
    assert len(SOURCES) > 30


def test_no_production_routing_engine_phrases_on_the_site() -> None:
    bad = {}
    for p in SOURCES:
        text = _text(p).lower()
        for phrase in ("production routing", "routing engine", "the planner", "planner wrong"):
            if phrase in text:
                bad.setdefault(p.name, []).append(phrase)
    assert not bad, f"overclaiming wording found: {bad}"


def test_no_indian_digit_grouping_anywhere() -> None:
    offenders = [p.name for p in SOURCES if "en-IN" in _text(p)]
    assert not offenders, f"en-IN grouping in {offenders}"


def test_about_page_does_not_say_no_alert_was_ever_sent() -> None:
    about = _text(WEB / "app" / "about" / "page.tsx")
    assert "No alert has ever been sent" not in about
    assert "f2_alert_channel_live.json" in about


def test_about_page_says_there_is_no_aws() -> None:
    assert "AWS" in _text(WEB / "app" / "about" / "page.tsx")


def test_one_project_name_in_title_header_and_footer() -> None:
    site = _text(WEB / "lib" / "site.ts")
    name = re.search(r'PROJECT_NAME = "([^"]+)"', site)
    assert name is not None
    layout = _text(WEB / "app" / "layout.tsx")
    nav = _text(WEB / "components" / "Nav.tsx")
    assert "PROJECT_NAME" in layout and "PROJECT_NAME" in nav
    # No page spells a second, different name for the project in its own title.
    assert "· Control Tower" not in layout
    assert name.group(1) == "Agentic AI Logistics Control Tower"


def test_alerts_page_is_labelled_a_replay_everywhere() -> None:
    nav = _text(WEB / "components" / "Nav.tsx")
    page = _text(WEB / "app" / "alerts" / "page.tsx")
    assert "Live alerts" not in nav and "Live alerts" not in page
    assert "Alert replay" in nav and "Alert replay" in page


def test_paper_page_is_in_the_navigation() -> None:
    assert "/paper/" in _text(WEB / "components" / "Nav.tsx")
    assert (WEB / "app" / "paper" / "page.tsx").exists()


def test_every_page_declares_its_own_description_and_social_image() -> None:
    for page in (WEB / "app").glob("*/page.tsx"):
        text = _text(page)
        if page.parent.name == "paper":
            assert "pageMeta(" in text
        assert "pageMeta(" in text, f"{page.parent.name} has no per-page metadata"
    assert "og.png" in _text(WEB / "lib" / "site.ts")
    assert (WEB / "public" / "og.png").exists()
    assert (WEB / "public" / "icon.svg").exists()
    assert (WEB / "app" / "not-found.tsx").exists()


def test_figures_have_alt_text_from_their_captions() -> None:
    for page in ("evidence", "paper"):
        text = _text(WEB / "app" / page / "page.tsx")
        assert "alt={`${f.title}. ${f.caption}`}" in text, page


def test_live_pages_show_the_waking_state_and_a_retry() -> None:
    states = _text(WEB / "components" / "ApiStates.tsx")
    api = _text(WEB / "lib" / "api.ts")
    assert "Waking the free server (up to ~1 min)" in api
    assert "RetryButton" in states and "ApiDownNotice" in states
    for comp in ("Predictor", "AssistantChat", "AgentConsole", "AlertFeed"):
        text = _text(WEB / "components" / f"{comp}.tsx")
        assert "WakingNotice" in text, f"{comp} has no waking state"
        assert "Retry" in text or "onRetry" in text, f"{comp} has no retry"
    # The wait window must outlast the host's boot (api-keepalive.yml allows 90 s).
    keepalive = _text(config.REPO_ROOT / ".github" / "workflows" / "api-keepalive.yml")
    assert "--max-time 90" in keepalive
    assert "WAKE_TIMEOUT_MS = 90_000" in api
    assert "timeoutMs: 12_000" not in api and "timeoutMs: 45_000" not in api


def test_glossary_covers_the_required_terms() -> None:
    text = _text(WEB / "lib" / "glossary.ts")
    for term in ("MCP", "LangGraph", "Kafka", "Spark", "MLlib", "TMS", "Parquet",
                 "Vector index", "As-of", "FDR", "q-value", "MAE", "Residual",
                 "Support floor", "OSRM", "Dwell", "Corridor", "Leg", "Back-off",
                 "Empirical Bayes"):
        assert f'term: "{term}' in text, term


# ── exported evidence labels ─────────────────────────────────────────────────

@pytest.fixture(scope="module")
def evidence() -> dict[str, dict]:
    doc = json.loads((DATA / "evidence_index.json").read_text(encoding="utf-8"))
    return {e["key"]: e for e in doc["data"]["entries"]}


def test_week4_random_forest_is_superseded_not_champion(evidence) -> None:
    for key in ("champion_model", "mae_champion", "corridors_improved"):
        label = evidence[key]["label"]
        assert "superseded (D-050)" in label, key
        assert evidence[key]["superseded"] is True
        assert "champion" not in label.lower()


def test_order_entry_success_carries_its_n(evidence) -> None:
    e = evidence["order_eval_success"]
    assert e["unit"] == "share" and e["n"] == evidence["order_eval_run"]["value"] == 50
    assert evidence["order_eval_scale_heldout"]["n"] == 200


def test_the_56_million_rows_are_labelled_as_proxy_aggregation_only(evidence) -> None:
    label = evidence["scale_rows"]["label"].lower()
    assert "proxy" in label and "aggregation" in label
