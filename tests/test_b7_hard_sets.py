"""B7 hard sets: deterministic, balanced, and authored apart from the agents' rules (D-028)."""

import ast
from collections import Counter
from pathlib import Path

from src.ml import b7_hard_sets as hs


def test_order_set_is_deterministic_and_balanced():
    a, b = hs.build_order_hard(), hs.build_order_hard()
    assert [x.body for x in a] == [x.body for x in b]
    assert len(a) == 100
    assert set(Counter(x.template for x in a).values()) == {10}
    actions = Counter(x.expected_action for x in a)
    assert actions["file"] == 20 and actions["clarify"] == 80
    assert all(x.expected_missing for x in a if x.expected_action == "clarify")
    assert len({x.body for x in a}) == len(a)


def test_invoice_boundary_set_is_deterministic_and_balanced():
    a, b = hs.build_invoice_boundary(), hs.build_invoice_boundary()
    assert [x.freight_charge for x in a] == [x.freight_charge for x in b]
    assert len(a) == 100 and set(Counter(x.kind for x in a).values()) == {10}
    verdicts = Counter(x.expected_verdict for x in a)
    assert verdicts["approve"] == verdicts["dispute"] == 50
    assert len({x.external_invoice_number for x in a}) == 100


def test_invoice_edges_sit_on_the_stated_side():
    for c in hs.build_invoice_boundary():
        share = c.other_charges / c.freight_charge
        if c.kind == "share_high_inside":
            assert hs.SHARE_HIGH < share < hs.SHARE_HIGH + hs.SHARE_SLACK
        if c.kind == "share_high_outside":
            assert share > hs.SHARE_HIGH + hs.SHARE_SLACK
        if c.kind == "total_off_two_paise":
            assert abs(c.total_amount - c.freight_charge - c.other_charges) > hs.TOTAL_TOLERANCE
        if c.kind == "total_off_half_paisa":
            assert abs(c.total_amount - c.freight_charge - c.other_charges) < hs.TOTAL_TOLERANCE


def test_expected_fields_never_contain_unstated_values():
    for o in hs.build_order_hard():
        if o.expected_action == "file":
            assert set(o.expected_fields) == {"customer_name", "origin_centre", "dest_centre",
                                              "route_type", "pieces", "weight_kg"}


def test_builder_does_not_import_the_agents_rules():
    tree = ast.parse(Path(hs.__file__).read_text(encoding="utf-8"))
    top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = {getattr(n, "module", None) or "" for n in top_level}
    assert not any("order_rules" in m or "invoice_auditor" in m for m in names)
