"""Guards for the consistency fixes (upgrade Phase A): wording that was corrected must stay corrected.

    pytest tests/test_consistency.py -q

Each test reads committed documents, not code. They fail the day someone reintroduces a claim that a
file already contradicts (an overclaim about the data, a closed caveat, a number quoted from the wrong split).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "benchmarks" / "raw"

#: Current-state documents. Weekly write-ups (docs/W*), the decision log and the problem log are
#: dated records of what was believed then, and are deliberately not policed here.
CURRENT_DOCS = [
    "README.md", "docs/paper_draft.md", "docs/data_card.md", "docs/model_card.md",
    "docs/RELEASE_v1.0.md", "docs/demo_script.md", "docs/references.md",
    "benchmarks/final_tables.md", *[str(p.relative_to(ROOT)) for p in (ROOT / "paper").glob("**/*.tex")],
]


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", CURRENT_DOCS)
def test_the_planned_time_is_never_called_a_production_engine(rel):
    # The dataset has an `osrm_time` column and nothing about how the carrier used it (A7).
    text = _text(rel).lower()
    assert "production routing" not in text and "production planner" not in text, rel


@pytest.mark.parametrize("rel", CURRENT_DOCS)
def test_the_scale_claim_names_the_stage_and_the_proxy_data(rel):
    text = _text(rel).lower()
    assert "pipeline runs unchanged" not in text, rel


@pytest.mark.parametrize("rel", CURRENT_DOCS)
def test_the_reported_model_is_not_described_as_unserved(rel):
    # D-070 closed D-053; w10_stream_validation_v2.json is the authoritative evidence (A1).
    text = _text(rel).lower()
    assert "not yet the one the streaming job serves" not in text, rel
    assert "not yet served by the stream" not in text, rel


def test_document_extraction_leads_with_one_overall_number_and_its_n():
    # A2: overall 97.9% over 280 fields; clean and noisy are labelled as splits of it.
    doc = json.loads((RAW / "w7_doc_extraction_eval.json").read_text(encoding="utf-8"))["overall"]
    table = _text("benchmarks/final_tables.md")
    assert f"{doc['correct']} of {doc['fields_in_truth']} fields" in table
    assert "overall (clean + noisy)" in table
    readme = _text("README.md")
    assert "97.9% [95.4-99.0]" in readme and f"{doc['correct']} of {doc['fields_in_truth']} fields" in readme


def test_the_week_6_invoice_row_is_labelled_historical():
    readme = _text("README.md")
    assert "Week 6 development corpus" in readme.split("Freight Invoice Auditor v1", 1)[1][:200]


def test_the_data_card_says_what_the_planned_time_column_is_and_is_not():
    card = _text("docs/data_card.md")
    assert "OSRM estimate recorded in" in card and "What we cannot know" in card
