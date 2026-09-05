"""Tests for the document-extraction evaluation harness (execution plan W4 D5).

    pytest tests/test_doc_eval.py -q

Never touches Spark, never calls an LLM, never re-runs OCR -- exactly the point of
keeping this harness separate from `src.agents.document_agent` (module docstring).
"""

from __future__ import annotations

import json

from src.ml import doc_eval


# ── score_document ───────────────────────────────────────────────────────────
def test_exact_match_is_all_true_positives():
    true = dict.fromkeys(doc_eval.LABEL_FIELDS, "x")
    result = doc_eval.score_document(dict(true), true)
    assert result["exact_match"] is True
    assert result["tp"] == len(doc_eval.LABEL_FIELDS)
    assert result["fp"] == 0
    assert result["fn"] == 0


def _all_null(**overrides) -> dict:
    """Every `LABEL_FIELDS` key explicit and null except the ones under test --
    avoids the footgun of a missing key and a genuinely-null field both reading as
    `None` from `.get()`, which made the field count easy to miscompute by hand.
    """
    base = dict.fromkeys(doc_eval.LABEL_FIELDS, None)
    base.update(overrides)
    return base


def test_correctly_returned_null_is_neither_hit_nor_miss():
    true = _all_null(document_type="BOL")
    predicted = _all_null(document_type="BOL")
    result = doc_eval.score_document(predicted, true)
    # every field matches (14 null-null pairs + the one real value) -- but only the
    # non-null field counts toward precision/recall's true-positive count.
    assert result["fields_correct"] == len(doc_eval.LABEL_FIELDS)
    assert result["tp"] == 1
    assert result["fp"] == 0
    assert result["fn"] == 0


def test_wrong_non_null_value_is_both_fp_and_fn():
    true = _all_null(document_number="LR0000001")
    predicted = _all_null(document_number="LROOOOOO1")
    result = doc_eval.score_document(predicted, true)
    # the 14 null-null fields still match; only document_number disagrees
    assert result["fields_correct"] == len(doc_eval.LABEL_FIELDS) - 1
    assert result["tp"] == 0
    assert result["fp"] == 1
    assert result["fn"] == 1


def test_hallucinated_value_on_a_null_field_is_a_pure_false_positive():
    true = _all_null()
    predicted = _all_null(total_amount="1234.00")
    result = doc_eval.score_document(predicted, true)
    assert result["tp"] == 0
    assert result["fp"] == 1
    assert result["fn"] == 0


def test_missed_extraction_is_a_pure_false_negative():
    true = _all_null(total_amount="1234.00")
    predicted = _all_null()
    result = doc_eval.score_document(predicted, true)
    assert result["tp"] == 0
    assert result["fp"] == 0
    assert result["fn"] == 1


# ── _prf1 ─────────────────────────────────────────────────────────────────────
def test_prf1_handles_all_zero_counts_without_dividing_by_zero():
    precision, recall, f1 = doc_eval._prf1(tp=0, fp=0, fn=0)
    assert (precision, recall, f1) == (0.0, 0.0, 0.0)


def test_prf1_perfect_score():
    precision, recall, f1 = doc_eval._prf1(tp=10, fp=0, fn=0)
    assert (precision, recall, f1) == (1.0, 1.0, 1.0)


# ── score_predictions_file / score_null_baseline ────────────────────────────
def _write_label(tmp_path, name: str, fields: dict) -> None:
    (tmp_path / name).write_text(json.dumps(fields), encoding="utf-8")


def _write_predictions(tmp_path, filename: str, prompt_version: str, predictions: list[dict]) -> None:
    (tmp_path / filename).write_text(
        json.dumps({"prompt_version": prompt_version, "n_documents": len(predictions), "predictions": predictions}),
        encoding="utf-8",
    )


def test_score_predictions_file_end_to_end(tmp_path):
    true_fields = _all_null(document_number="LR0000001")
    _write_label(tmp_path, "doc1.json", true_fields)

    wrong_fields = dict(true_fields)
    wrong_fields["document_number"] = "LROOOOOO1"  # wrong
    _write_label(tmp_path, "doc2.json", true_fields)

    predictions_path = tmp_path / "preds.json"
    _write_predictions(
        tmp_path, "preds.json", "v1",
        [
            {"seq": 1, "doc_type": "BOL", "label_json": "doc1.json", "predicted_fields": dict(true_fields)},
            {"seq": 2, "doc_type": "BOL", "label_json": "doc2.json", "predicted_fields": wrong_fields},
            {"seq": 3, "doc_type": "BOL", "label_json": "doc1.json", "predicted_fields": None, "error": "boom"},
        ],
    )

    result = doc_eval.score_predictions_file(predictions_path, tmp_path)

    assert result["n_attempted"] == 3
    assert result["n_scored"] == 2  # the None prediction is excluded, not scored as wrong
    assert result["coverage"] == round(2 / 3, 3)
    assert result["exact_match_documents"] == 1
    assert result["tp"] == 1  # doc1's document_number
    assert result["fp"] == 1  # doc2's wrong document_number
    assert result["fn"] == 1  # doc2's document_number, counted as missed too


def test_score_null_baseline_never_scores_a_true_positive(tmp_path):
    true_fields = dict.fromkeys(doc_eval.LABEL_FIELDS, None)
    true_fields["document_type"] = "BOL"
    _write_label(tmp_path, "doc1.json", true_fields)
    _write_predictions(
        tmp_path, "preds.json", "v1",
        [{"seq": 1, "doc_type": "BOL", "label_json": "doc1.json", "predicted_fields": {}}],
    )

    baseline = doc_eval.score_null_baseline(tmp_path / "preds.json", tmp_path)

    assert baseline["tp"] == 0
    assert baseline["fp"] == 0
    assert baseline["fn"] == 1  # the one non-null true field
    assert baseline["precision"] == 0.0
    assert baseline["f1"] == 0.0
