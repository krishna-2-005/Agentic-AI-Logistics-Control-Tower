# Common tasks. `make help` lists them. Uses the active Python; override with PYTHON=path/to/python.
PYTHON ?= python
export PYTHONPATH := .

.PHONY: help test test-all lint types rebuild rebuild-quick freeze verify paper numbers site clean-paper

help:  ## list the targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | sort

test:  ## fast tests (no JVM): ruff, then pytest without the spark marker
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m pytest -q -m "not spark"

test-all:  ## everything, including the tests that need a JVM and a SparkSession
	$(PYTHON) -m pytest -q

lint:  ## ruff only
	$(PYTHON) -m ruff check src tests

types:  ## mypy on the checked set in pyproject.toml
	$(PYTHON) -m mypy

rebuild:  ## every generated artefact from the raw CSV (about an hour; needs data/raw and Spark)
	bash scripts/rebuild_all.sh

rebuild-quick:  ## the batch caches and week 2-6 results only
	bash scripts/rebuild_all.sh --quick

freeze:  ## cut the next results freeze: set N, e.g. `make freeze N=6`
	$(PYTHON) -m src.ml.results_freeze --freeze --path benchmarks/results_freeze_v$(N).json

verify:  ## recompute every frozen number from the result files and report what moved
	$(PYTHON) -m src.ml.results_freeze --verify

numbers:  ## regenerate paper/numbers.tex (and the plain-text abstract) from the newest freeze
	$(PYTHON) -m src.report.paper_numbers --abstract
	$(PYTHON) -m src.report.bib_print

paper:  ## build the conference and journal PDFs (latexmk or tectonic on PATH)
	bash scripts/build_paper.sh

site:  ## re-export the site's data files from the newest freeze, then build the site
	$(PYTHON) -m src.report.export_web
	cd web && npm ci && npm run build

clean-paper:  ## remove LaTeX build products
	find paper -name '*.aux' -o -name '*.bbl' -o -name '*.blg' -o -name '*.log' -o -name '*.out' | xargs rm -f
