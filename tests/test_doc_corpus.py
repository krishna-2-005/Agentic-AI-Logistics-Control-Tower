"""Tests for the Week 3 synthetic document corpus.

    pytest tests/test_doc_corpus.py -q

Reads only the committed `benchmarks/raw/w2_corridor_audit.csv` — no Spark, no live
data — the same D-009 discipline the dashboard tests follow.
"""

from __future__ import annotations

import random
import re

import pytest

from src.agents.doc_corpus import labels, seed_errors
from src.agents.doc_corpus.generate import run
from src.agents.doc_corpus.records import ConsignmentRecord, generate_records
from src.common import config

PROMPT_V1 = config.REPO_ROOT / "src" / "agents" / "prompts" / "doc_extraction" / "v1.md"


# ── Records ─────────────────────────────────────────────────────────────────────
def test_generate_records_is_deterministic():
    a = generate_records(20, seed=7)
    b = generate_records(20, seed=7)
    assert [r.corridor_id for r in a] == [r.corridor_id for r in b]
    assert [r.freight_charge for r in a] == [r.freight_charge for r in b]
    assert [r.shipper_name for r in a] == [r.shipper_name for r in b]


def test_generate_records_different_seeds_differ():
    a = generate_records(20, seed=1)
    b = generate_records(20, seed=2)
    assert [r.corridor_id for r in a] != [r.corridor_id for r in b]


def test_records_draw_real_corridors():
    """Corridor and centre codes must be ones the audit actually tested (D-018's
    1,130), never invented pairs — the whole point of building on real data."""
    import pandas as pd

    audited = set(pd.read_csv(records_csv())["corridor_id"])
    for r in generate_records(15, seed=3):
        assert r.corridor_id in audited


def records_csv():
    return config.BENCHMARKS_RAW_DIR / "w2_corridor_audit.csv"


def test_route_type_is_ftl_or_carting():
    for r in generate_records(15, seed=4):
        assert r.route_type in ("FTL", "Carting")


# ── Label schema ─────────────────────────────────────────────────────────────────
def test_label_schema_matches_doc_extraction_prompt():
    """The corpus's label schema must never drift from what the extraction prompt
    actually asks for — that drift would make Week 4's eval harness compare two
    different shapes and call it a score."""
    assert PROMPT_V1.exists(), "doc_extraction/v1.md moved or was renamed"
    text = PROMPT_V1.read_text(encoding="utf-8")
    prompt_fields = set(re.findall(r"\| `(\w+)` \|", text))
    assert prompt_fields == set(labels.LABEL_FIELDS)


def test_bol_label_has_no_amount_totals():
    rec = generate_records(1, seed=5)[0]
    label = labels.bol_label(rec)
    assert label["other_charges"] is None
    assert label["total_amount"] is None
    assert label["freight_charge"] is not None


def test_invoice_label_totals_are_internally_consistent_before_seeding():
    for rec in generate_records(10, seed=6):
        label = labels.invoice_label(rec)
        assert label["total_amount"] == pytest.approx(
            label["freight_charge"] + label["other_charges"], abs=0.01
        )


# ── Seeded errors ─────────────────────────────────────────────────────────────────
def _labels_for(records: list[ConsignmentRecord]):
    return (
        {r.seq: labels.bol_label(r) for r in records},
        {r.seq: labels.invoice_label(r) for r in records},
    )


def test_zero_error_rate_leaves_every_document_clean():
    records = generate_records(15, seed=9)
    bol, invoice = _labels_for(records)
    applied = seed_errors.apply_seeded_errors(records, bol, invoice, seed=9, error_rate=0.0)
    assert all(types == [] for types in applied.values())
    for r in records:
        assert invoice[r.seq]["total_amount"] == pytest.approx(
            invoice[r.seq]["freight_charge"] + invoice[r.seq]["other_charges"], abs=0.01
        )


def test_seeded_errors_are_reproducible():
    records = generate_records(30, seed=11)
    bol1, invoice1 = _labels_for(records)
    applied1 = seed_errors.apply_seeded_errors(records, bol1, invoice1, seed=11, error_rate=0.3)

    bol2, invoice2 = _labels_for(records)
    applied2 = seed_errors.apply_seeded_errors(records, bol2, invoice2, seed=11, error_rate=0.3)

    assert applied1 == applied2
    assert invoice1 == invoice2


def test_corridor_mismatch_changes_destination_not_origin():
    records = generate_records(5, seed=12)
    rec = records[0]
    bol = labels.bol_label(rec)
    invoice = labels.invoice_label(rec)
    ok = seed_errors._apply_one(
        "corridor_mismatch", rec, {r.seq: r for r in records}, bol, invoice, [], random.Random(0)
    )
    assert ok
    assert invoice["destination_centre_code"] != rec.dest_center
    assert invoice["origin_centre_code"] == rec.source_center  # unchanged
    assert bol["destination_centre_code"] == rec.dest_center  # BOL untouched


def test_duplicate_document_number_reuses_a_prior_number():
    records = generate_records(3, seed=13)
    rec = records[0]
    bol = labels.bol_label(rec)
    invoice = labels.invoice_label(rec)
    ok = seed_errors._apply_one(
        "duplicate_document_number", rec, {r.seq: r for r in records}, bol, invoice,
        ["INV0009999"], random.Random(0),
    )
    assert ok
    assert invoice["document_number"] == "INV0009999"


def test_duplicate_document_number_fails_gracefully_with_no_history():
    records = generate_records(1, seed=14)
    rec = records[0]
    bol, invoice = labels.bol_label(rec), labels.invoice_label(rec)
    ok = seed_errors._apply_one(
        "duplicate_document_number", rec, {rec.seq: rec}, bol, invoice, [], random.Random(0)
    )
    assert ok is False


def test_ocr_confusion_flips_exactly_one_documented_character_class():
    corrupted = seed_errors._corrupt_one_char("IND282002AAD", random.Random(1))
    assert corrupted is not None
    assert len(corrupted) == len("IND282002AAD")
    diffs = [(a, b) for a, b in zip("IND282002AAD", corrupted) if a != b]
    assert len(diffs) == 1
    original, new = diffs[0]
    assert seed_errors._CONFUSIONS[original] == new


def test_missing_field_nulls_a_previously_populated_field():
    records = generate_records(1, seed=15)
    rec = records[0]
    bol = labels.bol_label(rec)
    invoice = labels.invoice_label(rec)
    assert invoice["freight_charge"] is not None
    ok = seed_errors._apply_one(
        "missing_field", rec, {rec.seq: rec}, bol, invoice, [], random.Random(2)
    )
    assert ok
    nullable = ("weight_kg", "pieces", "freight_charge", "other_charges", "total_amount")
    assert any(bol[f] is None for f in nullable) or any(invoice[f] is None for f in nullable)


# ── End-to-end generation ─────────────────────────────────────────────────────────
def test_full_pipeline_writes_expected_files(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.csv"
    demo_dir = tmp_path / "demo_samples"
    monkeypatch.setattr("src.agents.doc_corpus.generate.MANIFEST_CSV", manifest_path)
    monkeypatch.setattr(config, "DEMO_SAMPLE_DOCUMENTS_DIR", demo_dir)

    output_dir = tmp_path / "documents"
    rows = run(count=12, seed=21, error_rate=0.4, output_dir=output_dir, demo_samples=5)

    assert len(rows) == 12
    for row in rows:
        for key in ("bol_pdf", "bol_label_json", "bol_scan_jpg",
                    "invoice_pdf", "invoice_label_json", "invoice_scan_jpg"):
            assert (output_dir / row[key]).exists(), row[key]

    assert manifest_path.exists()
    assert demo_dir.exists()
    assert (demo_dir / "MANIFEST.md").exists()
    assert len(list(demo_dir.glob("*.pdf"))) <= 10  # GIT_RULES §3
    assert any(r["error_types"] for r in rows)  # 40% rate on 12 docs should seed at least one


def test_demo_sample_step_skips_untouched_when_nothing_qualifies(tmp_path, monkeypatch):
    """--demo-samples 0 (or an all-clean run with nothing to curate) must not touch
    the real repo's demo/sample_documents/ — a test importing this module should never
    be able to write into the working tree outside tmp_path."""
    demo_dir = tmp_path / "demo_samples"
    monkeypatch.setattr(config, "DEMO_SAMPLE_DOCUMENTS_DIR", demo_dir)

    from src.agents.doc_corpus.generate import _copy_demo_samples

    _copy_demo_samples(manifest_rows=[], output_dir=tmp_path, demo_samples=5)
    assert not demo_dir.exists()
