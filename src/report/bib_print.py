"""Write `paper/refs_print.bib`: `paper/refs.bib` without the verification notes.

    python -m src.report.bib_print
    python -m src.report.bib_print --check     # exit 1 if refs_print.bib is stale

Every entry in `refs.bib` carries a `note = {verified <date>: <url or doi>}` so that a reader can see where
each reference was checked (decision D-096). Bibliography styles print `note` fields, which would put the
verification trail into the reference list of the manuscripts. The manuscripts therefore cite
`refs_print.bib`, which is this module's output; the notes stay in `refs.bib`.
"""

from __future__ import annotations

import argparse
import re

from src.common import config

SOURCE = config.REPO_ROOT / "paper" / "refs.bib"
OUT = config.REPO_ROOT / "paper" / "refs_print.bib"
NOTE = re.compile(r"^\s*note\s*=\s*\{verified\b", re.IGNORECASE)


def strip_notes(text: str) -> str:
    """Drop `note` fields that start with `verified`, brace-balanced, wherever they sit in an entry."""
    out: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if NOTE.match(line):
            depth = line.count("{") - line.count("}")
            while depth > 0:
                i += 1
                depth += lines[i].count("{") - lines[i].count("}")
            i += 1
            continue
        out.append(line)
        i += 1
    cleaned = "\n".join(out) + "\n"
    # an entry whose last field was the note now ends with a trailing comma, which BibTeX accepts
    return cleaned


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    cleaned = strip_notes(SOURCE.read_text(encoding="utf-8"))
    if args.check:
        return 0 if OUT.exists() and OUT.read_text(encoding="utf-8") == cleaned else 1
    OUT.write_text(cleaned, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
