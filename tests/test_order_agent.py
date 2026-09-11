"""Tests for the Order Entry Agent (execution plan W5 D1-D2).

    pytest tests/test_order_agent.py -q

No LLM and no HTTP: `extract_order` costs a call against a 20-a-day free tier (D-032)
and `post_order` needs a running TMS, so both are exercised by the CLI instead. What
is pinned here is `validate_order` -- the layer whose whole job is catching a bad
extraction before it becomes a 422 -- and the corpus's ground-truth invariants that
Lahari's D5 scoring will depend on.
"""

from __future__ import annotations

from src.agents import order_agent as agent
from src.agents.order_corpus import (
    CLARIFY_FIELD,
    VARIANT_WEIGHTS,
    build_email,
    generate_emails,
)


def _order(**overrides) -> dict:
    base = {
        "customer_name": "Bolpur Distributors",
        "origin_centre": "IND731204AAB",
        "dest_centre": "IND731301AAA",
        "route_type": "FTL",
        "pieces": 3,
        "weight_kg": 1817.7,
    }
    base.update(overrides)
    return base


# ── validate_order: the happy path ───────────────────────────────────────────
def test_a_complete_order_has_no_problems():
    assert agent.validate_order(_order()) == []


def test_no_order_at_all_is_a_problem():
    assert agent.validate_order(None) == ["no order object returned"]
    assert agent.validate_order({}) == ["no order object returned"]


# ── validate_order: the things a model actually gets wrong ───────────────────
def test_missing_required_field_is_named():
    problems = agent.validate_order(_order(weight_kg=None))
    assert any("weight_kg is missing" in p for p in problems)


def test_centre_code_shape_is_enforced():
    # D-002 keys every corridor on IND + 6 digits + 3 letters. A city name here is the
    # exact failure the prompt's rule 3 tells the model to ask about instead.
    problems = agent.validate_order(_order(origin_centre="Bolpur"))
    assert any("not IND + 6 digits + 3 letters" in p for p in problems)


def test_identical_origin_and_destination_is_rejected_before_the_round_trip():
    # The TMS returns 422 for this; catching it here means the log says which email,
    # not which HTTP call.
    problems = agent.validate_order(_order(dest_centre="IND731204AAB"))
    assert any("same centre" in p for p in problems)


def test_route_type_must_be_one_of_the_two_real_ones():
    problems = agent.validate_order(_order(route_type="Express"))
    assert any("route_type" in p for p in problems)


def test_zero_or_negative_pieces_is_rejected():
    assert any("pieces" in p for p in agent.validate_order(_order(pieces=0)))
    assert any("pieces" in p for p in agent.validate_order(_order(pieces=-2)))


def test_pieces_must_be_a_whole_number():
    assert any("pieces" in p for p in agent.validate_order(_order(pieces=2.5)))


def test_a_bool_is_not_a_valid_number():
    # `True` is an int in Python and would otherwise sail through `pieces >= 1`.
    assert any("pieces" in p for p in agent.validate_order(_order(pieces=True)))
    assert any("weight_kg" in p for p in agent.validate_order(_order(weight_kg=True)))


def test_zero_or_negative_weight_is_rejected():
    assert any("weight_kg" in p for p in agent.validate_order(_order(weight_kg=0)))
    assert any("weight_kg" in p for p in agent.validate_order(_order(weight_kg=-1.0)))


def test_several_problems_are_all_reported_not_just_the_first():
    # An agent that gets three fields wrong should produce three lines to fix, not one
    # exception that hides the other two.
    problems = agent.validate_order(_order(pieces=0, weight_kg=-1, route_type="Express"))
    assert len(problems) >= 3


# ── the corpus contract Lahari's D5 scoring depends on ───────────────────────
def test_every_variant_is_represented_when_the_corpus_is_big_enough():
    emails = generate_emails(count=len(VARIANT_WEIGHTS), seed=42)
    assert {e.variant for e in emails} == set(VARIANT_WEIGHTS)


def test_the_corpus_is_deterministic_in_its_seed():
    a = generate_emails(count=8, seed=7)
    b = generate_emails(count=8, seed=7)
    assert [(e.seq, e.variant, e.body) for e in a] == [(e.seq, e.variant, e.body) for e in b]


def test_clean_emails_expect_filing_and_the_rest_expect_a_question():
    for email in generate_emails(count=10, seed=42):
        expected = "file" if email.variant == "clean" else "clarify"
        assert email.expected_action == expected


def test_a_clarify_variant_names_the_field_its_question_must_be_about():
    for email in generate_emails(count=10, seed=42):
        if email.expected_action == "clarify":
            assert email.expected_missing == CLARIFY_FIELD[email.variant]


def test_ground_truth_omits_whatever_the_variant_removed_from_the_email():
    # An agent must never be scored wrong for declining to invent a value nobody wrote.
    for email in generate_emails(count=10, seed=42):
        if email.expected_missing:
            assert email.expected_missing not in email.expected_fields


def test_external_ref_is_stable_and_unique_per_email():
    emails = generate_emails(count=6, seed=42)
    refs = [e.external_ref for e in emails]
    assert len(set(refs)) == len(refs)
    assert refs == [f"W5-ORD-{e.seq:04d}" for e in emails]


def test_a_clean_email_states_every_required_field():
    from src.agents.doc_corpus.records import generate_records

    record = generate_records(1, seed=42)[0]
    body = build_email(record, "clean").body
    assert record.source_center in body
    assert record.dest_center in body
    assert record.route_type in body
    assert str(record.pieces) in body
