"""Tests for Lahari's Order Entry evaluation set and harness (execution plan W5 D5).

    pytest tests/test_order_eval.py -q

No LLM: `process_email` is replaced with a stub wherever a run is exercised, because a
real call costs one of twenty a day (D-032). What is pinned is the set's own contract,
the scoring rules, and the two behaviours that keep a multi-day run honest -- a quota
refusal is never recorded as a result, and only Gemini is allowed to run it.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.agents.order_agent import OrderOutcome
from src.agents.order_corpus import generate_emails
from src.ml import order_eval as ev


@pytest.fixture(scope="module")
def cases():
    return ev.build_eval_set()


# ── the set ──────────────────────────────────────────────────────────────────
def test_fifty_cases_five_per_template(cases):
    assert len(cases) == 50
    counts = pd.Series([c.variant for c in cases]).value_counts()
    assert set(counts.index) == set(ev.TEMPLATES) and (counts == 5).all()


def test_any_twenty_case_prefix_covers_every_template(cases):
    # A 20-a-day run takes a prefix; it must not spend a day on three templates.
    assert {c.variant for c in cases[:len(ev.TEMPLATES)]} == set(ev.TEMPLATES)


def test_the_set_is_deterministic():
    a, b = ev.build_eval_set(), ev.build_eval_set()
    assert [(c.seq, c.body) for c in a] == [(c.seq, c.body) for c in b]


def test_no_case_shares_a_seq_or_body_with_krishnas_corpus(cases):
    # D-028's builder/judge split: the agent is scored on emails it was never built against.
    builder = generate_emails(count=12, seed=42)
    assert not {c.seq for c in cases} & {e.seq for e in builder}
    assert not {c.body for c in cases} & {e.body for e in builder}


def test_ground_truth_never_holds_what_the_email_withholds(cases):
    for case in cases:
        if case.expected_missing:
            assert case.expected_missing not in case.expected_fields


def test_missing_two_withholds_both_and_expects_the_weight_question(cases):
    for case in (c for c in cases if c.variant == "missing_two"):
        assert case.expected_missing == "weight_kg"
        assert "route_type" not in case.expected_fields


def test_every_email_is_signed_by_a_person_not_the_company(cases):
    # Prompt rule 6 is tested by every case: the customer is the company.
    for case in cases:
        assert case.expected_fields["customer_name"] in case.body
        assert any(name in case.body for name in ev.SIGNATORIES)


def test_the_tonnes_case_expects_the_converted_figure(cases):
    for case in (c for c in cases if c.variant == "tonnes"):
        stated = float(case.body.split("Total load is ")[1].split(" tonnes")[0])
        assert case.expected_fields["weight_kg"] == pytest.approx(stated * 1000, abs=0.1)


def test_the_correction_case_expects_the_corrected_weight(cases):
    for case in (c for c in cases if c.variant == "correction"):
        assert f"{case.expected_fields['weight_kg']} kg, not" in case.body


def test_numbers_in_words():
    assert ev.number_in_words(1) == "one"
    assert ev.number_in_words(12) == "twelve"
    assert ev.number_in_words(40) == "forty"
    assert ev.number_in_words(47) == "forty-seven"
    assert ev.number_in_words(150) == "150"


# ── scoring ──────────────────────────────────────────────────────────────────
def test_weight_is_matched_within_tolerance_and_pieces_exactly():
    assert ev.field_matches("weight_kg", 3723.4, 3723.0)
    assert not ev.field_matches("weight_kg", 3800.0, 3723.0)
    assert ev.field_matches("pieces", 6, 6) and ev.field_matches("pieces", 6.0, 6)
    assert not ev.field_matches("pieces", 6.5, 6)
    assert not ev.field_matches("pieces", True, 1)  # a bool is not a count
    assert ev.field_matches("origin_centre", " ind244901aab ", "IND244901AAB")
    assert not ev.field_matches("weight_kg", None, 100.0)


def _case(cases, template):
    return next(c for c in cases if c.variant == template)


def test_a_correct_filing_succeeds(cases):
    case = _case(cases, "clean_table")
    verdict = ev.score_case(case, {"action": "file", "order": dict(case.expected_fields), "validation_errors": []})
    assert verdict["success"] and not verdict["mismatched_fields"]


def test_a_filing_with_one_wrong_field_fails_and_names_it(cases):
    case = _case(cases, "clean_table")
    order = dict(case.expected_fields, pieces=case.expected_fields["pieces"] + 1)
    verdict = ev.score_case(case, {"action": "file", "order": order})
    assert not verdict["success"] and verdict["mismatched_fields"] == "pieces"


def test_asking_about_the_right_field_succeeds_and_the_wrong_one_does_not(cases):
    case = _case(cases, "missing_two")
    assert ev.score_case(case, {"action": "clarify", "missing_field": "weight_kg"})["success"]
    # route_type is also missing, but rule 2 says weight first.
    assert not ev.score_case(case, {"action": "clarify", "missing_field": "route_type"})["success"]


def test_filing_when_it_should_have_asked_is_an_invented_order(cases):
    verdict = ev.score_case(_case(cases, "weight_range"), {"action": "file", "order": {}})
    assert verdict["invented_order"] and not verdict["success"]


def test_asking_when_it_should_have_filed_is_a_needless_question(cases):
    verdict = ev.score_case(_case(cases, "tonnes"), {"action": "clarify", "missing_field": "weight_kg"})
    assert verdict["needless_question"] and not verdict["success"]


def test_an_extraction_failure_is_counted_as_one(cases):
    verdict = ev.score_case(_case(cases, "tonnes"), {"action": None, "error": "non-JSON"})
    assert verdict["extraction_failed"] and not verdict["success"]


def test_the_summary_rates(cases):
    file_case, ask_case = _case(cases, "clean_table"), _case(cases, "no_service")
    scores = pd.DataFrame([
        {**ev.score_case(file_case, {"action": "file", "order": dict(file_case.expected_fields)}), "ran_on": "2026-09-11"},
        {**ev.score_case(ask_case, {"action": "file", "order": {}}), "ran_on": "2026-09-11"},
    ])
    summary = ev.summarise(scores, 50)
    assert summary["n_run"] == 2 and summary["success_rate"] == 0.5
    assert summary["invented_orders"] == 1 and summary["clarification_rate"] == 0.0


def test_a_partial_run_says_so_in_the_report(cases):
    case = _case(cases, "clean_table")
    scores = pd.DataFrame([{
        **ev.score_case(case, {"action": "file", "order": dict(case.expected_fields)}),
        "ran_on": "2026-09-11", "model": "gemini-3.6-flash",
    }])
    text = ev.render_doc(scores, ev.summarise(scores, 50))
    assert "Partial: 1 of 50" in text and "not run yet" in text


# ── the run's two honesty rules ──────────────────────────────────────────────
def test_quota_errors_are_recognised():
    assert ev.is_quota_error("429 RESOURCE_EXHAUSTED: GenerateRequestsPerDay")
    assert ev.is_quota_error("You exceeded your current quota")
    assert not ev.is_quota_error("returned non-JSON")
    assert not ev.is_quota_error(None)


def test_only_gemini_may_run_the_eval(tmp_path, monkeypatch):
    monkeypatch.setattr(ev.config, "LLM_PROVIDER", "anthropic")
    with pytest.raises(RuntimeError, match="gemini only"):
        ev.run(1, tmp_path / "set.json", tmp_path / "runs.jsonl")


def _stub(outcomes):
    calls = iter(outcomes)

    def fake(email, prompt, dry_run=False):
        assert dry_run, "the eval must never POST"
        action, error = next(calls)
        return OrderOutcome(
            seq=email.seq, variant=email.variant, expected_action=email.expected_action,
            expected_missing=email.expected_missing, action=action, error=error,
        )
    return fake


def test_a_quota_refusal_stops_the_run_and_is_not_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(ev.config, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(ev, "process_email", _stub([("file", None), (None, "429 RESOURCE_EXHAUSTED"), ("file", None)]))
    runs = tmp_path / "runs.jsonl"
    assert ev.run(5, tmp_path / "set.json", runs) == 1
    assert len(ev.load_runs(runs)) == 1


def test_a_run_resumes_where_it_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(ev.config, "LLM_PROVIDER", "gemini")
    runs = tmp_path / "runs.jsonl"
    monkeypatch.setattr(ev, "process_email", _stub([("file", None)] * 3))
    ev.run(3, tmp_path / "set.json", runs)
    monkeypatch.setattr(ev, "process_email", _stub([("clarify", None)] * 2))
    ev.run(2, tmp_path / "set.json", runs)
    done = ev.load_runs(runs)
    assert sorted(done) == [5001, 5002, 5003, 5004, 5005]
    record = json.loads(runs.read_text(encoding="utf-8").splitlines()[0])
    assert record["provider"] == "gemini" and record["ran_on"]
