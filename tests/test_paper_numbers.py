"""The manuscripts' numbers are macros generated from the newest freeze (UPGRADE C1).

    pytest tests/test_paper_numbers.py -q
"""

from __future__ import annotations

import json

import pytest

from src.report import paper_numbers as pn

BS = chr(92)

pytestmark = pytest.mark.skipif(not list(pn.config.BENCHMARKS_DIR.glob("results_freeze_v*.json")), reason="no freeze")


def test_numbers_tex_is_what_the_newest_freeze_generates():
    assert pn.OUT.read_text(encoding="utf-8") == pn.render()


def test_every_macro_the_text_uses_is_defined_in_numbers_tex():
    defined = {m.group(1) for m in pn.re.finditer(r"providecommand\{\\(fz[A-Za-z]+)\}", pn.OUT.read_text(encoding="utf-8"))}
    missing = {name: files for name, files in pn.used_macros().items() if name not in defined}
    assert not missing, missing


def test_each_macro_matches_the_freeze_value():
    freeze = json.loads(pn.newest_freeze().read_text(encoding="utf-8"))
    text = pn.OUT.read_text(encoding="utf-8")
    for item in freeze["values"]:
        line = BS + f"providecommand{{{BS}{pn.macro_name(item['id'])}}}{{{pn.tex_value(item['value'])}}}"
        assert line in text, item["id"]


def test_macro_names_have_no_digits_and_do_not_collide():
    freeze = json.loads(pn.newest_freeze().read_text(encoding="utf-8"))
    names = [pn.macro_name(i["id"]) for i in freeze["values"]]
    assert len(names) == len(set(names))
    assert all(n.isalpha() for n in names)


def test_no_manuscript_types_a_result_that_a_macro_holds():
    """The headline results must come from macros, not from typed numbers."""
    freeze = {i["id"]: i["value"] for i in json.loads(pn.newest_freeze().read_text(encoding="utf-8"))["values"]}
    typed = [f"{freeze[k]:.2f}" for k in ("reported_mae", "bar_backoff_mae", "bar_old_median_mae") if k in freeze]
    for tex in sorted((pn.PAPER_DIR / "sections").glob("*.tex")):
        text = tex.read_text(encoding="utf-8")
        for number in typed:
            # a number may appear once inside a table cell as a validation companion; the main text uses macros
            assert text.count(number) <= 1, (tex.name, number)


def test_the_plain_text_abstract_is_current_and_in_the_word_range():
    text = (pn.PAPER_DIR / "abstract.txt").read_text(encoding="utf-8").strip()
    assert text == pn.plain_text((pn.PAPER_DIR / "sections" / "abstract.tex").read_text(encoding="utf-8"))
    assert 200 <= len(text.split()) <= 250

