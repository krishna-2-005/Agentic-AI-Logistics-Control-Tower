"""Tests for the Freight Invoice Auditor (execution plan W6 D5).

    pytest tests/test_invoice_auditor.py -q

No LLM and no TMS. Every verdict this auditor reaches is arithmetic, so every verdict
is testable without either -- which is the argument for building it that way.
"""

from __future__ import annotations

import pytest

from src.agents import invoice_auditor as ia


def _case(**overrides) -> ia.InvoiceCase:
    base = {
        "seq": 1, "kind": "clean", "corridor_id": "INDA>INDB", "route_type": "FTL",
        "weight_kg": 4000.0, "pieces": 3, "external_invoice_number": "INV-000001",
        "freight_charge": 1000.0, "other_charges": 100.0, "total_amount": 1100.0,
    }
    base.update(overrides)
    return ia.InvoiceCase(**base)


# ── the bands ───────────────────────────────────────────────────────────────
def test_the_ftl_band_is_the_corpus_rate_model_with_tolerance():
    low, high = ia.freight_band("FTL", 4000.0, 100.0)
    assert low == pytest.approx(100 * 28 * (1 - ia.BAND_TOLERANCE), rel=1e-6)
    assert high == pytest.approx(100 * 45 * (1 + ia.BAND_TOLERANCE), rel=1e-6)


def test_the_carting_band_adds_handling_to_a_per_tonne_rate():
    low, high = ia.freight_band("Carting", 500.0, 100.0)
    assert low == pytest.approx((100 * 0.5 * 6 + 500 * 2) * (1 - ia.BAND_TOLERANCE), rel=1e-6)
    assert high == pytest.approx((100 * 0.5 * 10 + 500 * 4) * (1 + ia.BAND_TOLERANCE), rel=1e-6)


# ── the checks ──────────────────────────────────────────────────────────────
def test_a_clean_invoice_is_approved():
    findings = ia.audit_invoice(_case(), corridor_km=30.0, seen_numbers=set())
    assert findings == [] and ia.verdict_for(findings) == "approve"


def test_the_arithmetic_check_gives_both_numbers():
    findings = ia.audit_invoice(_case(total_amount=1500.0), 30.0, set())
    codes = {f.code for f in findings}
    assert "total_mismatch" in codes
    detail = next(f.detail for f in findings if f.code == "total_mismatch")
    assert "1,100.00" in detail and "1,500.00" in detail


def test_a_rounding_difference_is_not_a_dispute():
    # A supplier is not disputed over half a paisa.
    assert ia.audit_invoice(_case(total_amount=1100.009), 30.0, set()) == []


def test_an_overcharge_is_caught_and_quotes_the_band():
    findings = ia.audit_invoice(_case(freight_charge=9000.0, other_charges=900.0, total_amount=9900.0), 30.0, set())
    assert any(f.code == "rate_above_band" for f in findings)
    assert "band" in next(f.detail for f in findings if f.code == "rate_above_band")


def test_an_undercharge_is_flagged_for_confirmation_not_accusation():
    findings = ia.audit_invoice(_case(freight_charge=100.0, other_charges=10.0, total_amount=110.0), 30.0, set())
    assert any(f.code == "rate_below_band" for f in findings)


def test_other_charges_outside_the_billed_band_are_caught():
    findings = ia.audit_invoice(_case(other_charges=500.0, total_amount=1500.0), 30.0, set())
    assert any(f.code == "other_charges_out_of_band" for f in findings)


def test_other_charges_at_the_band_edges_are_fine():
    for share in (ia.OTHER_CHARGES_SHARE[0], ia.OTHER_CHARGES_SHARE[1]):
        other = round(1000.0 * share, 2)
        findings = ia.audit_invoice(_case(other_charges=other, total_amount=1000.0 + other), 30.0, set())
        assert not any(f.code == "other_charges_out_of_band" for f in findings), share


def test_a_repeated_invoice_number_is_caught():
    findings = ia.audit_invoice(_case(), 30.0, {"INV-000001"})
    assert any(f.code == "duplicate_invoice_number" for f in findings)


def test_a_foreign_currency_is_caught():
    assert any(f.code == "unexpected_currency" for f in ia.audit_invoice(_case(currency="USD"), 30.0, set()))


def test_an_unaudited_corridor_is_not_a_dispute():
    # "We cannot check this" must never become "this is wrong": the supplier would be
    # paying for our own lack of corridor history.
    findings = ia.audit_invoice(_case(freight_charge=99999.0, other_charges=9999.9, total_amount=109998.9),
                                corridor_km=None, seen_numbers=set())
    assert not any(f.code.startswith("rate_") for f in findings)


def test_several_problems_are_all_reported():
    findings = ia.audit_invoice(_case(freight_charge=9000.0, other_charges=4000.0, total_amount=999.0), 30.0,
                                {"INV-000001"})
    assert len({f.code for f in findings}) >= 3


# ── the seeded corpus ───────────────────────────────────────────────────────
def test_every_kind_appears_before_the_weighted_draw_fills_the_rest():
    cases = ia.build_cases(len(ia.CASE_WEIGHTS), seed=7)
    assert {c.kind for c in cases} == set(ia.CASE_WEIGHTS)


def test_the_corpus_is_deterministic():
    a, b = ia.build_cases(12, seed=3), ia.build_cases(12, seed=3)
    assert [(c.seq, c.kind, c.total_amount) for c in a] == [(c.seq, c.kind, c.total_amount) for c in b]


def test_ground_truth_matches_the_kind():
    for case in ia.build_cases(25, seed=7):
        assert case.expected_finding == ia.FINDING_FOR_KIND.get(case.kind)
        assert case.expected_verdict == ("approve" if case.kind == "clean" else "dispute")


def test_a_duplicate_case_actually_repeats_an_earlier_number():
    cases = ia.build_cases(25, seed=7)
    numbers_before = set()
    for case in cases:
        if case.kind == "duplicate_number":
            assert case.external_invoice_number in numbers_before
        numbers_before.add(case.external_invoice_number)


def test_the_first_case_cannot_be_a_duplicate():
    # Nothing precedes it to duplicate; the generator downgrades it to clean rather than
    # silently emitting a "duplicate" that is unique.
    assert ia.build_cases(1, seed=99)[0].kind != "duplicate_number"


# ── wording never changes a verdict ─────────────────────────────────────────
def test_no_prompt_means_no_call(monkeypatch):
    monkeypatch.setattr(ia, "get_llm", lambda: pytest.fail("--no-draft must not call the model"))
    _, source = ia.draft_note(_case(), [ia.Finding("total_mismatch", "x")], None)
    assert source == "template"


def test_a_failed_draft_still_disputes(monkeypatch):
    class Boom:
        def invoke(self, _):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(ia, "get_llm", lambda: Boom())
    text, source = ia.draft_note(_case(), [ia.Finding("total_mismatch", "parts do not sum")], ia.load_prompt("invoice_audit"))
    assert source == "template" and "parts do not sum" in text


def test_the_template_note_carries_every_finding():
    findings = [ia.Finding("total_mismatch", "sums wrong"), ia.Finding("rate_above_band", "too dear")]
    note = ia.template_note(_case(), findings)
    assert "sums wrong" in note and "too dear" in note


# ── end to end, no model, no TMS ────────────────────────────────────────────
def test_a_batch_run_matches_the_seeded_truth(tmp_path):
    summary = ia.run(count=20, seed=7, draft=False, post=False, out_path=tmp_path / "runs.json")
    assert summary["cases"] == 20
    assert summary["correct_verdicts"] == 20
    assert summary["drafted_by_llm"] == 0
