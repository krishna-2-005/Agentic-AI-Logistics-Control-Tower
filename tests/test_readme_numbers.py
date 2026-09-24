"""
The README's numbers against the results freeze.

The README is the only thing most visitors read, and it is the file most likely
to drift: every week added a row, and nothing recomputed the old ones. It has
already been wrong once in the direction that matters least to a reader and most
to a reviewer -- it advertised a *worse* project than the repository contained,
reporting a superseded 36.9-minute model for weeks after the 30.90-minute one was
adopted.

`tests/test_web_numbers.py` protects the site this way. This does the same for
the README, so neither surface can quietly disagree with the paper.

Run:  pytest tests/test_readme_numbers.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.common import config

README = config.REPO_ROOT / "README.md"
FREEZE = config.BENCHMARKS_DIR / "results_freeze_v3.json"


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def frozen() -> dict[str, object]:
    doc = json.loads(FREEZE.read_text(encoding="utf-8"))
    return {v["id"]: v["value"] for v in doc["values"]}


def _appears(text: str, value: str) -> bool:
    """Is this number in the README, allowing thousands separators?

    A bare `in` check is too loose -- "273" matches inside "12273" -- so the
    match is bounded by non-digit context on both sides.
    """
    pattern = rf"(?<![\d.]){re.escape(value)}(?![\d])"
    return re.search(pattern, text) is not None


# ── the numbers the README states, each tied to its frozen id ────────────────
#
# Only numbers the README actually claims are listed. Adding a row here is the
# cost of adding a number to the README, which is the point.

CLAIMS = [
    ("bottlenecks", "273", "corridors significantly slower"),
    ("faster_corridors", "512", "corridors significantly faster"),
    ("corridors_tested", "1,130", "corridors tested"),
    ("legs_total", "26,369", "legs in the feature table"),
    ("model_v2_mae", "30.90", "the reported model's MAE"),
    ("median_bar_mae", "33.04", "the per-corridor median baseline"),
    ("mae_osrm", "107.1", "OSRM's own MAE"),
    ("mae_champion", "36.9", "the superseded Week 4 champion, kept as the correction story"),
    ("scale_rows", "56,353,613", "rows in the scale appendix"),
    ("stream_events", "52,738", "events replayed"),
    ("stream_produced_eps", "886", "producer events/sec"),
    ("stream_scoring_eps", "740", "saturated scoring rate"),
    ("order_eval_run", "50", "order entry cases"),
    ("invoice_correct", "20", "invoice verdicts matched"),
]


@pytest.mark.parametrize("key,shown,what", CLAIMS)
def test_readme_number_is_in_the_freeze(readme, frozen, key, shown, what) -> None:
    """Every headline number in the README appears, and the freeze agrees."""
    assert key in frozen, f"{key} is not a frozen value; the freeze moved under the README"
    assert _appears(readme, shown), (
        f"the README no longer states {shown} ({what}). If the number changed, "
        f"update the README and this row together."
    )


def test_the_frozen_value_matches_what_the_readme_prints(frozen) -> None:
    """The freeze's own values, rendered the way the README renders them."""
    checks = {
        "bottlenecks": "273",
        "faster_corridors": "512",
        "corridors_tested": "1,130",
        "legs_total": "26,369",
        "scale_rows": "56,353,613",
        "stream_events": "52,738",
    }
    for key, shown in checks.items():
        assert f"{int(frozen[key]):,}" == shown, (
            f"{key} is {frozen[key]:,} in the freeze but the README prints {shown}"
        )

    assert f"{float(frozen['model_v2_mae']):.2f}" == "30.90"
    assert f"{float(frozen['median_bar_mae']):.2f}" == "33.04"


# ── the caveats, which are claims too ────────────────────────────────────────

def test_the_as_of_alert_precision_is_the_one_reported(readme) -> None:
    """D-054: the agent layer reports 58.6%, not the leaked 72.1%.

    The leaked figure may appear *as* the correction -- that is the honest way to
    report it -- but it must never stand alone as the result.
    """
    assert "58.6" in readme, "the as-of exception precision is missing from the README"
    if "72.1" in readme:
        window_start = readme.find("72.1")
        window = readme[max(0, window_start - 400):window_start + 400]
        assert any(w in window for w in ("leak", "D-054", "as-of", "first published")), (
            "72.1% appears in the README without the replay leak beside it"
        )


def test_closed_caveats_are_not_still_claimed(readme) -> None:
    """A caveat that has been closed and left in place understates the project.

    Kafka has met a live broker and the MCP server has been driven over stdio;
    both sentences were true once and are not any more.
    """
    stale = [
        "has never reached a live broker",
        "never met a broker",
        "has not been driven by an MCP client",
        "the MCP server has never",
    ]
    found = [s for s in stale if s.lower() in readme.lower()]
    assert not found, f"the README still carries closed caveats: {found}"


def test_open_caveats_are_still_stated(readme) -> None:
    """The reverse failure: dropping a limitation that is still true.

    G-07 (no real alert sent) and D-053 (reported model is not the served model)
    are both open. Removing either would make the README describe a better
    project than the repository contains.
    """
    lowered = readme.lower()
    assert "d-053" in lowered or "not yet served" in lowered, (
        "the served-vs-reported model gap (D-053) is no longer stated"
    )
    assert "unconfigured" in lowered or "g-07" in lowered, (
        "the alert channel caveat (G-07) is no longer stated"
    )


def test_no_pending_placeholders_remain(readme) -> None:
    """`_pending W7_` rows shipped in the results table for two weeks after their
    evidence files existed."""
    assert "_pending" not in readme, "the README results table still has a pending row"


def test_the_live_url_is_the_first_thing_a_visitor_sees(readme) -> None:
    """G-08 closed. The URL is the point of closing it."""
    head = readme[:1200]
    assert "control-tower-mu-rouge.vercel.app" in head, (
        "the production URL is not near the top of the README"
    )
