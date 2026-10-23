"""Kappa and the blank human-task sheets (B7). No label here comes from a person."""

import csv

import pytest

from src.ml import human_sheets as hs
from src.ml.groundedness import cohen_kappa


def test_cohen_kappa_perfect_and_chance():
    assert cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"])["kappa"] == 1.0
    # observed 0.5, both label a half the time -> expected 0.5 -> kappa 0
    assert cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"])["kappa"] == 0.0


def test_cohen_kappa_hand_computed():
    # 10 items. a: 7 yes / 3 no ; b: 6 yes / 4 no ; both yes 5, both no 2 -> p_o = 0.7
    first = ["y"] * 7 + ["n"] * 3
    second = ["y"] * 5 + ["n"] * 2 + ["y"] + ["n"] * 2
    # b yes = 5 + 1 = 6. p_e = 0.7*0.6 + 0.3*0.4 = 0.54 ; kappa = (0.7-0.54)/0.46
    out = cohen_kappa(first, second)
    assert out["kappa"] == pytest.approx((0.7 - 0.54) / 0.46, abs=1e-4)
    assert out["observed_agreement"] == 0.7


def test_cohen_kappa_undefined_and_validation():
    assert cohen_kappa(["a", "a"], ["a", "a"])["kappa"] is None
    with pytest.raises(ValueError):
        cohen_kappa(["a"], ["a", "b"])


def test_order_pool_is_fixed_and_hides_labels(tmp_path):
    a, b = hs.order_email_pool(), hs.order_email_pool()
    assert [x["email_id"] for x in a] == [x["email_id"] for x in b]
    assert len(a) == 150 and len({x["body"] for x in a}) == 150
    assert {x["intended"] for x in a} <= {"ask", "infer"}
    path = tmp_path / "sheet.csv"
    assert hs.build_order_sheet(path) == 150
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert all(r["label"] == "" for r in rows)
    assert "intended" not in rows[0] and "expected" not in " ".join(rows[0])


def test_order_agreement_rejects_blank_and_bad_labels(tmp_path):
    pool = hs.order_email_pool()

    def write(name, label):
        p = tmp_path / name
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["email_id", "subject", "body", "label", "field_if_ask", "note"])
            for item in pool:
                w.writerow([item["email_id"], "", "", label(item), "", ""])
        return str(p)

    good = write("a.csv", lambda i: i["intended"])
    blank = write("b.csv", lambda i: "" if i["email_id"] == "E001" else i["intended"])
    wrong = write("c.csv", lambda i: "maybe")
    with pytest.raises(ValueError):
        hs.order_agreement(good, blank)
    with pytest.raises(ValueError):
        hs.order_agreement(good, wrong)
    out = hs.order_agreement(good, good)
    assert out["labeller_a_vs_b"]["kappa"] == 1.0 and out["labeller_a_vs_intended"]["observed_agreement"] == 1.0
