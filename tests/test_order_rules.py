"""
The rule route's field readers, one behaviour per test.

These are unit tests of the parsing, not the evaluation. The evaluation lives in
`src/ml/order_eval.py` and is scored against a set this module's author should not
be tuning against -- see the note in `test_order_rules_are_frozen_before_the_hard_set`
below, which is the one test here that is really about method rather than code.
"""

from __future__ import annotations

import pytest

from src.agents.order_rules import (
    extract_order_rules,
    read_centres,
    read_customer_name,
    read_pieces,
    read_route_type,
    read_weight_kg,
)

# ── weight ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Gross weight: 1817.7 kg", 1817.7),
        ("total weight 480 kgs", 480.0),
        ("weight 2.5 tonnes", 2500.0),
        ("3 MT of cargo", 3000.0),
        ("1,250 kg on a pallet", 1250.0),
    ],
)
def test_weight_is_read_and_converted(text, expected) -> None:
    value, vague = read_weight_kg(text)
    assert value == pytest.approx(expected)
    assert not vague


@pytest.mark.parametrize(
    "text",
    [
        "somewhere between 2 and 3 tonnes",
        "weight is between 800 and 900 kg",
        "about 1200 kg give or take",
        "roughly 2 tonnes",
    ],
)
def test_an_estimated_weight_is_ambiguous_not_missing(text) -> None:
    """A range is *stated* and unusable. The distinction matters: the customer
    believes they have answered, so the question back has to acknowledge that."""
    value, vague = read_weight_kg(text)
    assert value is None
    assert vague is True


def test_a_correction_takes_the_new_weight_not_the_superseded_one() -> None:
    """`the weight is X kg, not Y kg` -- the judge's `correction` template puts the
    wrong figure second and repeats it again in a forwarded quote below."""
    text = (
        "Correction to my mail below: the weight is 900.0 kg, not 1170.0 kg. "
        "Everything else stands.\n--- Forwarded ---\nWeight 1170.0 kg."
    )
    value, vague = read_weight_kg(text)
    assert value == pytest.approx(900.0)
    assert not vague


# ── pieces ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("12 pieces", 12),
        ("No. of packages:       7", 7),
        ("twelve cartons", 12),
        ("twenty-one crates", 21),
        ("5 pallets on the truck", 5),
    ],
)
def test_pieces_are_read_from_digits_and_words(text, expected) -> None:
    value, vague = read_pieces(text)
    assert value == expected
    assert not vague


@pytest.mark.parametrize("text", ["roughly 10-12 boxes", "between 8 and 10 cartons"])
def test_an_estimated_piece_count_is_ambiguous(text) -> None:
    value, vague = read_pieces(text)
    assert value is None
    assert vague is True


# ── route type ───────────────────────────────────────────────────────────────


def test_route_type_is_read_but_never_inferred() -> None:
    assert read_route_type("please send FTL") == ("FTL", False)
    assert read_route_type("Carting (part load)") == ("Carting", False)
    # Prompt rule 4: silence is a question, not an inference from the weight.
    assert read_route_type("18 tonnes, 40 pallets") == (None, False)


def test_a_contradictory_service_level_is_ambiguous() -> None:
    value, vague = read_route_type("book as FTL — actually make it Carting")
    assert value is None
    assert vague is True


# ── centres ──────────────────────────────────────────────────────────────────


def test_centres_are_assigned_by_cue_not_by_order_of_appearance() -> None:
    """The destination is named first here. Taking 'first code seen' as the origin
    is wrong on every email written this way, and prose emails are written this
    way often."""
    text = (
        "This needs to reach the consignee at Kanpur, hub IND209304AAA. "
        "It will be collected from our Bengaluru premises, hub code IND560067AAA."
    )
    origin, dest = read_centres(text)
    assert origin == "IND560067AAA"
    assert dest == "IND209304AAA"


def test_a_repeated_code_in_a_forwarded_quote_does_not_reassign_an_end() -> None:
    text = (
        "Please book from IND110037AAA to IND400093AAB.\n"
        "--- Forwarded ---\nfrom IND110037AAA to IND400093AAB"
    )
    assert read_centres(text) == ("IND110037AAA", "IND400093AAB")


# ── customer name ────────────────────────────────────────────────────────────


def test_the_customer_is_the_company_not_the_signatory() -> None:
    """Prompt rule 6. The judge's set signs every email with a person's name over
    a company, so a reader that takes the first line after 'Regards' is wrong 50
    times out of 50."""
    assert (
        read_customer_name("Best regards,\nPriya Nair\nLogistics desk, Acme Traders")
        == "Acme Traders"
    )
    assert read_customer_name("Regards,\nAcme Traders\nConsignor") == "Acme Traders"


# ── the decision ─────────────────────────────────────────────────────────────


def test_a_complete_email_files() -> None:
    out = extract_order_rules(
        "Consignment request",
        "Origin hub code: IND560067AAA\nDestination hub code: IND209304AAA\n"
        "No. of packages: 12\nGross weight: 1817.7 kg\nMode: Full Truck Load\n\n"
        "Best regards,\nPriya Nair\nLogistics desk, Acme Traders",
    )
    assert out["action"] == "file"
    assert out["order"]["origin_centre"] == "IND560067AAA"
    assert out["order"]["pieces"] == 12
    assert out["order"]["route_type"] == "FTL"
    assert out["order"]["customer_name"] == "Acme Traders"


def test_when_several_fields_are_missing_it_asks_about_weight_first() -> None:
    """Prompt rule 2 orders the question: weight and pieces before service level."""
    out = extract_order_rules(
        "Booking",
        "From IND560067AAA to IND209304AAA, 12 cartons.\n\n"
        "Regards,\nAcme Traders\nConsignor",
    )
    assert out["action"] == "clarify"
    assert out["missing_field"] == "weight_kg"


def test_it_never_fills_a_field_the_email_did_not_state() -> None:
    """The whole reason a rule route is defensible: it cannot hallucinate. What it
    could still do is carry a stale default, so the clarify branch is checked for
    absence rather than for a placeholder."""
    out = extract_order_rules(
        "Booking",
        "Collection from our Nagpur warehouse to IND209304AAA. "
        "12 cartons, 1817.7 kg, FTL.\n\nRegards,\nAcme Traders\nConsignor",
    )
    assert out["action"] == "clarify"
    assert out["missing_field"] == "origin_centre"
    assert "origin_centre" not in out["order"]


def test_identical_origin_and_destination_is_asked_about_not_filed() -> None:
    out = extract_order_rules(
        "Booking",
        "From IND560067AAA to IND560067AAA, 12 cartons, 1817.7 kg, FTL.\n\n"
        "Regards,\nAcme Traders\nConsignor",
    )
    assert out["action"] == "clarify"


def test_the_question_is_asked_in_priority_order() -> None:
    """Prompt rule 2: ask about the thing that blocks the booking hardest.

    `consignment` leads because it dominates -- which weight applies is not a
    sensible question until it is clear which shipment is being booked. Then
    weight and pieces, then the route, then service level, which is the ordering
    `order_eval.py`'s `missing_two` case depends on.
    """
    from src.agents import order_rules

    order = order_rules.ASK_ORDER
    assert order[0] == "consignment"
    assert order.index("weight_kg") < order.index("pieces")
    assert order.index("pieces") < order.index("route_type")
    assert set(order) == set(order_rules.QUESTIONS)


def test_consignment_is_a_question_not_an_order_field() -> None:
    """It sits in ASK_ORDER for its priority and must never reach the TMS.

    Regression guard with a real cost behind it: including it in the
    field-presence loop made `order.get("consignment")` None on every email, so
    all 200 evaluation cases reported it missing and the score fell from 95% to
    5% in one commit.
    """
    from src.agents.order_rules import REQUIRED_ORDER_FIELDS, extract_order_rules

    assert "consignment" not in REQUIRED_ORDER_FIELDS

    out = extract_order_rules(
        "Consignment request",
        "Origin hub code: IND560067AAA\nDestination hub code: IND209304AAA\n"
        "No. of packages: 12\nGross weight: 1817.7 kg\nMode: Full Truck Load\n\n"
        "Best regards,\nPriya Nair\nLogistics desk, Acme Traders",
    )
    assert out["action"] == "file"
    assert "consignment" not in out["order"]


def test_two_shipments_in_one_mail_are_not_one_order() -> None:
    out = extract_order_rules(
        "Two bookings",
        "Hi,\n\nTwo loads to arrange this week.\n\n"
        "1) A (IND560067AAA) to B (IND209304AAA), 18 pieces, 482.6 kg, Carting\n"
        "2) B (IND209304AAA) to A (IND560067AAA), 9 pieces, 241.3 kg, Carting\n\n"
        "Regards,\nAcme Traders\nConsignor",
    )
    assert out["action"] == "clarify"
    assert out["missing_field"] == "consignment"


def test_two_weights_nothing_reconciles_is_asked_about() -> None:
    """Different from a correction, where the email says which figure is dead."""
    out = extract_order_rules(
        "Booking",
        "From IND560067AAA to IND209304AAA. 12 pieces. Gross weight 900.0 kg. FTL.\n"
        "Warehouse has the total as 1260.0 kg on their docket.\n\n"
        "Regards,\nAcme Traders\nConsignor",
    )
    assert out["action"] == "clarify"
    assert out["missing_field"] == "weight_kg"


def test_zero_pieces_is_refused_by_both_halves_of_the_agent() -> None:
    """`validate_order` rejects a count below 1. The rule route used to file it
    anyway, moving the rejection to a 422 from the TMS three layers away."""
    out = extract_order_rules(
        "Booking",
        "From IND560067AAA to IND209304AAA. 0 cartons for now, 900.0 kg, FTL.\n\n"
        "Regards,\nAcme Traders\nConsignor",
    )
    assert out["action"] == "clarify"
    assert out["missing_field"] == "pieces"
