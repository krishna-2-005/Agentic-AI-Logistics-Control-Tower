"""Tests for the document-extraction evaluation (execution plan v3.1, G-01).

    pytest tests/test_eval_extraction.py -q

No LLM and no OCR run: the scoring rules, the corpus wiring, the subsample and the two
honesty rules (a cached document is never paid for twice; a quota refusal is never a
score) are what is pinned here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.common import config
from src.ml import eval_extraction as ev

DOCS = config.DOCUMENTS_DIR
needs_corpus = pytest.mark.skipif(
    not any(DOCS.glob("*.json")), reason="document corpus not generated"
)


# ── the field spec matches the real labels ──────────────────────────────────
@needs_corpus
def test_field_spec_covers_exactly_the_label_keys():
    for doc_type, suffix in (("BOL", "bol"), ("INVOICE", "invoice")):
        label = json.loads((DOCS / f"w3_00001_{suffix}.json").read_text(encoding="utf-8"))
        assert set(ev.FIELD_SPEC[doc_type]) == set(label), doc_type


def test_both_types_share_the_fifteen_field_schema():
    assert ev.FIELD_SPEC["BOL"] == ev.FIELD_SPEC["INVOICE"]
    assert len(ev.FIELD_SPEC["BOL"]) == 15


# ── scoring ─────────────────────────────────────────────────────────────────
def test_a_perfect_extraction_scores_every_present_field():
    truth = {"document_number": "LR0000001", "weight_kg": 6932.4, "other_charges": None}
    tally, errors = ev.score_document("BOL", truth, dict(truth))
    assert tally.correct == 2 and not errors  # the null is correctly absent, not scored


def test_filling_a_field_the_document_does_not_carry_is_a_hallucination():
    # A BOL's label has null total_amount: the printed BOL does not show one.
    tally, errors = ev.score_document("BOL", {"total_amount": None}, {"total_amount": 1793.1})
    assert tally.hallucinated == 1 and errors[0]["outcome"] == "hallucinated"


def test_a_missing_field_is_missed_not_wrong():
    tally, _ = ev.score_document("BOL", {"pieces": 3}, {"pieces": None})
    assert tally.missed == 1 and tally.wrong == 0


def test_codes_ignore_case_and_punctuation():
    assert ev.values_match("code", "IND209625AAA", "ind-209625-aaa")
    assert not ev.values_match("code", "IND209625AAA", "IND2O9625AAA")  # an OCR 0/O confusion


def test_money_parses_printed_amounts():
    assert ev.values_match("money", 1678.71, "INR 1,678.71")
    assert not ev.values_match("money", 1678.71, "1,678.70")


def test_facility_names_tolerate_small_ocr_noise():
    assert ev.values_match("text", "Farrukhbad_Pnchlght_D (Uttar Pradesh)",
                           "Farrukhbad_Pnchight_D (Uttar Pradesh)")


# ── the corpus and the subsample ────────────────────────────────────────────
@needs_corpus
def test_each_consignment_yields_two_documents_in_two_splits():
    corpus = ev.load_corpus(DOCS, consignments=3)
    assert len(corpus) == 3 * 2 * 2
    clean = [d for d in corpus if d["split"] == "clean"]
    noisy = [d for d in corpus if d["split"] == "noisy"]
    assert all(d["path"].suffix == ".pdf" for d in clean)
    assert all(d["path"].suffix == ".jpg" for d in noisy)


@needs_corpus
def test_the_subsample_is_deterministic_and_keeps_seeded_errors():
    import csv

    rows = list(csv.DictReader(ev.MANIFEST.open(encoding="utf-8")))
    a = ev.select_consignments(rows, 20, seed=16)
    b = ev.select_consignments(rows, 20, seed=16)
    assert [r["seq"] for r in a] == [r["seq"] for r in b]
    assert len(a) == 20
    assert any(r["error_types"].strip() for r in a), "a subsample with no seeded errors would test nothing"


def test_no_subsample_means_every_consignment():
    rows = [{"seq": str(i), "error_types": ""} for i in range(5)]
    assert ev.select_consignments(rows, None, seed=1) == rows


# ── the two honesty rules ───────────────────────────────────────────────────
class _Prompt:
    label = "doc_extraction/test"


def _doc(tmp_path: Path) -> dict:
    return {"doc_id": "w3_09999_bol", "split": "clean", "path": tmp_path / "x.pdf",
            "doc_type": "BOL", "truth": {}, "seq": 9999, "error_types": ""}


def test_a_cached_extraction_is_never_paid_for_twice(tmp_path, monkeypatch):
    doc = _doc(tmp_path)
    key = f"{doc['doc_id']}|clean|pdf-text|{_Prompt.label}"
    cache = {key: {"key": key, "fields": {"pieces": 2}}}
    monkeypatch.setattr(ev, "document_text", lambda *a: pytest.fail("a cached document must not be re-read"))
    assert ev.run_extraction(doc, "tesseract", _Prompt(), cache) == {"pieces": 2}


def test_cache_only_returns_none_rather_than_calling(tmp_path):
    assert ev.run_extraction(_doc(tmp_path), "tesseract", _Prompt(), {}, cache_only=True) is None


def test_a_quota_refusal_raises_instead_of_being_scored(tmp_path, monkeypatch):
    import src.agents.document_agent as agent

    monkeypatch.setattr(ev, "document_text", lambda *a: "text")
    monkeypatch.setattr(agent, "extract_fields",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("429 RESOURCE_EXHAUSTED")))
    with pytest.raises(ev.QuotaExhausted):
        ev.run_extraction(_doc(tmp_path), "tesseract", _Prompt(), {}, cache_path=tmp_path / "c.jsonl")
    assert not (tmp_path / "c.jsonl").exists(), "a refused call must not be cached"


def test_a_successful_extraction_is_cached_before_it_is_scored(tmp_path, monkeypatch):
    import src.agents.document_agent as agent

    monkeypatch.setattr(ev, "document_text", lambda *a: "some text")
    monkeypatch.setattr(agent, "extract_fields", lambda *a, **k: {"pieces": 4})
    cache_path = tmp_path / "c.jsonl"
    cache: dict = {}
    assert ev.run_extraction(_doc(tmp_path), "tesseract", _Prompt(), cache, cache_path=cache_path) == {"pieces": 4}
    assert ev.load_cache(cache_path)
    assert len(cache) == 1
