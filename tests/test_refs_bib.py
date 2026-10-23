"""Structural checks on the shared bibliography (pure python, no LaTeX needed)."""
from __future__ import annotations

import re
from pathlib import Path

BIB = Path(__file__).resolve().parents[1] / "paper" / "refs.bib"
ENTRY_START = re.compile(r"^@(\w+)\s*\{\s*([^,\s]+)\s*,", re.M)


def _entries() -> list[tuple[str, str, str]]:
    """Return (type, key, body) for every entry; fails on unbalanced braces."""
    text = BIB.read_text(encoding="utf-8")
    out = []
    starts = list(ENTRY_START.finditer(text))
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        chunk = text[m.start():end]
        # drop comment lines (they may hold stray braces) before counting
        code = "\n".join(ln for ln in chunk.splitlines() if not ln.lstrip().startswith("%"))
        body = code[code.index("{") :].rstrip()
        depth = 0
        for ch in body:
            depth += ch == "{"
            depth -= ch == "}"
            assert depth >= 0, f"extra closing brace in {m.group(2)}"
        assert depth == 0, f"unbalanced braces in {m.group(2)}"
        assert body.endswith("}"), f"entry {m.group(2)} does not end with a closing brace"
        out.append((m.group(1).lower(), m.group(2), body))
    return out


def _field(body: str, name: str) -> str | None:
    m = re.search(rf"^\s*{name}\s*=\s*", body, re.M | re.I)
    return body[m.end() : m.end() + 1] if m else None


def test_bib_exists_and_has_enough_entries():
    assert len(_entries()) >= 50


def test_no_duplicate_keys():
    keys = [k.lower() for _, k, _ in _entries()]
    assert len(keys) == len(set(keys))


def test_every_entry_has_required_fields_and_a_verification_note():
    for _, key, body in _entries():
        assert _field(body, "title"), f"{key}: no title"
        assert _field(body, "author") or _field(body, "editor"), f"{key}: no author/editor"
        assert re.search(r"^\s*year\s*=\s*\{?\d{4}", body, re.M), f"{key}: no year"
        note = re.search(r"^\s*note\s*=\s*\{(.*)\}\s*,?\s*$", body, re.M | re.S)
        assert note, f"{key}: no note"
        assert re.search(r"verified \d{4}-\d{2}-\d{2}", note.group(1)), f"{key}: note lacks a verified date"
        assert re.search(r"https?://|10\.\d{4,}/", note.group(1)), f"{key}: note lacks a URL or DOI"


def test_cite_keys_follow_surname_year_word():
    for _, key, _ in _entries():
        assert re.fullmatch(r"[a-z]+\d{4}[a-z0-9]+", key), key


def test_core_and_journal_tags_present():
    text = BIB.read_text(encoding="utf-8")
    core = len(re.findall(r"keywords\s*=\s*\{core\}", text))
    assert 25 <= core <= 40
