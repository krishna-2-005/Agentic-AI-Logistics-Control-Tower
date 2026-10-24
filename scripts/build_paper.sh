#!/usr/bin/env bash
# Build both manuscripts from the newest results freeze.
#   scripts/build_paper.sh            # regenerate paper/numbers.tex, then compile both
#   scripts/build_paper.sh --check    # only verify numbers.tex and the macros the text uses
# Uses latexmk (TeX Live / MiKTeX) when present, otherwise tectonic. Run from anywhere.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"
export PYTHONPATH=.

if [[ "${1:-}" == "--check" ]]; then
  "$PY" -m src.report.paper_numbers --check
  exit $?
fi

"$PY" -m src.report.paper_numbers
"$PY" -m src.report.paper_numbers --check
"$PY" -m src.report.bib_print

compile() {
  local dir="$1" file="${2:-main}"
  if command -v latexmk >/dev/null 2>&1; then
    (cd "$dir" && latexmk -pdf -interaction=nonstopmode -halt-on-error "$file.tex")
  elif command -v tectonic >/dev/null 2>&1; then
    (cd "$dir" && tectonic -X compile "$file.tex")
  else
    echo "need latexmk or tectonic on PATH" >&2
    exit 1
  fi
}

compile paper/conference
compile paper/conference anon   # double-blind variant: no names, affiliations or repository links
compile paper/journal
echo "built paper/conference/{main,anon}.pdf and paper/journal/main.pdf"
