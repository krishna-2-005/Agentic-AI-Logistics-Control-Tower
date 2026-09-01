"""Write a generated section into a shared weekly document.

`GIT_RULES.md` §2 gives each member **one document per week**, but a member's week is
usually produced by more than one script: Lahari's Week 1 doc is the column profile
from ``src.pipeline.data_dictionary`` plus the EDA from ``src.ml.eda``. Letting each
script own a whole file is what produced two Week 1 files for one member.

So each script owns a *section* instead, delimited by HTML comments that survive
Markdown rendering:

    <!-- section: data-dictionary -->
    ...generated content...
    <!-- /section: data-dictionary -->

Re-running a script replaces its own section and leaves everything else — including
any prose a human added between sections — untouched.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Canonical order of the generated sections. A section being appended for the first
#: time is inserted at its position here rather than at the end, so the document reads
#: the same regardless of which script happened to run first.
SECTION_ORDER = ["data-dictionary", "eda", "corridor-audit", "hub-ranking", "baselines", "beat-osrm"]


def _markers(section_id: str) -> tuple[str, str]:
    return f"<!-- section: {section_id} -->", f"<!-- /section: {section_id} -->"


def demote_headings(body: str) -> str:
    """Shift every heading down one level so the document keeps a single ``#``.

    Each generator renders a standalone document with its own ``# Title``. Pasted into
    a shared file that already has one, the result is three top-level headings and a
    table of contents that reads as three documents.

    Fenced code blocks are skipped — a shell comment inside a ``` block is a comment,
    not an H1, and demoting it would corrupt a command a teammate copy-pastes.
    """
    out, in_fence = [], False
    for line in body.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and re.match(r"^#{1,5} ", line):
            line = "#" + line
        out.append(line)
    return "\n".join(out)


def write_section(path: Path, section_id: str, body: str, header: str = "") -> Path:
    """Insert or replace ``section_id`` in ``path``.

    Args:
        path: the shared weekly document. Created with ``header`` if absent.
        section_id: must appear in :data:`SECTION_ORDER`.
        body: the generated Markdown, without the markers. Its headings are demoted
            one level; see :func:`demote_headings`.
        header: document title and preamble, used only when creating the file.

    Returns the path written, so callers can log it.
    """
    if section_id not in SECTION_ORDER:
        raise ValueError(
            f"Unknown section {section_id!r}. Add it to SECTION_ORDER so its position "
            "in the document is decided once, here, rather than by run order."
        )

    open_tag, close_tag = _markers(section_id)
    block = f"{open_tag}\n{demote_headings(body).strip()}\n{close_tag}\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else header

    pattern = re.compile(
        rf"{re.escape(open_tag)}.*?{re.escape(close_tag)}\n?", re.DOTALL
    )
    if pattern.search(existing):
        updated = pattern.sub(block, existing)
    else:
        updated = _insert_in_order(existing, section_id, block)

    path.write_text(updated, encoding="utf-8")
    return path


def _insert_in_order(document: str, section_id: str, block: str) -> str:
    """Place a new section before the first section that outranks it."""
    for later in SECTION_ORDER[SECTION_ORDER.index(section_id) + 1 :]:
        later_open, _ = _markers(later)
        if later_open in document:
            head, sep, tail = document.partition(later_open)
            return f"{head.rstrip()}\n\n{block}\n{sep}{tail}"
    return f"{document.rstrip()}\n\n{block}"
