#!/usr/bin/env bash
# Rebuild every generated artefact from the raw CSV, in dependency order (W8 reproducibility).
#
#   bash scripts/rebuild_all.sh            # everything, ~40 minutes on a laptop
#   bash scripts/rebuild_all.sh --quick    # stop before the Week 7 model sprint
#
# Precondition: data/raw/delhivery_data.csv (see data/README.md) and a working Spark
# environment (python -m src.common.check_env).
#
# Why a script and not a README section: the README's run order stopped at Stage 3 and the
# audit. Stage 4, the champion model, the Week 7 models, the document corpus and the vector
# index were only ever named as fix hints inside `boot --check`, so a newcomer following the
# README top to bottom could not rebuild what the dashboard and agents read. Each step below
# is the command its own module documents; nothing here is a second implementation.
#
# The last step is the one that makes this a test rather than a build: `results_freeze
# --verify` recomputes every frozen number from the files this run just wrote and reports
# anything that moved.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PYTHON="${PYTHON:-python}"
QUICK="${1:-}"

step() {
  local name="$1"; shift
  local started=$SECONDS
  echo "==> ${name}"
  "$PYTHON" "$@"
  echo "    ${name}: $((SECONDS - started))s"
}

[ -f data/raw/delhivery_data.csv ] || { echo "missing data/raw/delhivery_data.csv -- see data/README.md" >&2; exit 1; }

# Stage 1-4: the batch caches.
step "stage 1 clean"        -m src.pipeline.clean --input data/raw/delhivery_data.csv --output data/processed/clean_v1
step "stage 2 reconstruct"  -m src.pipeline.reconstruct --validate
step "stage 3 hubs"         -m src.pipeline.hubs
step "stage 4 features"     -m src.pipeline.features
step "contracts"            -m src.pipeline.contracts --keys

# Week 2-4 results that everything downstream reads.
step "corridor audit"       -m src.ml.audit
step "baselines"            -m src.ml.baselines
step "champion model"       -m src.automation.retrain

# Week 3 document corpus and the Week 6 vector index.
step "document corpus"      -m src.agents.doc_corpus.generate
step "vector index"         -m src.common.vectordb --build

# The mock TMS.
step "tms seed"             -m src.tms.seed

if [ "$QUICK" != "--quick" ]; then
  # Week 7: feature table v2 and the model sprint the paper reports (D-048 to D-050).
  step "features v2"        -m src.pipeline.features_v2
  step "model sprint v2"    -m src.ml.models_v2
  step "adopted model"      -m src.ml.models_v2_stepsize
fi

# Reported, not fatal: a fresh clone has no LLM key, which boot correctly lists as missing
# while every agent still runs with --no-llm.
echo "==> preflight"
"$PYTHON" -m src.common.boot --check || echo "    preflight listed missing items (an LLM key is optional)"
step "results verify"       -m src.ml.results_freeze --verify
echo "==> rebuild complete in ${SECONDS}s"
