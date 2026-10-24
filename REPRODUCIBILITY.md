# Reproducibility

How to regenerate every number in the paper, on what, and how long it takes. Everything here was measured on the
reference machine; where a figure is an estimate it says so.

## Reference environment

| | |
|---|---|
| Machine | Intel Core i7-13700H (14 cores, 20 logical), 15.7 GB RAM, one SSD |
| OS | Windows 11 Home (10.0.26200), Git Bash for the shell scripts |
| Python | 3.13.5 in a virtualenv outside the repository |
| JDK | OpenJDK 17.0.20 (Eclipse Temurin), `JAVA_HOME` set; a Hadoop `winutils` shim on `PATH` for Spark on Windows |
| Key libraries | PySpark 4.0.4, numpy 2.5.1, pandas 2.3.3, scikit-learn 1.9.1, LightGBM 4.7.0, XGBoost 3.4.1, SciPy 1.18.0, statsmodels 0.14.6 (`requirements.lock` has the full list) |
| LaTeX | Tectonic (XeTeX) for the manuscripts; `latexmk` also works |
| Data | `data/raw/delhivery_data.csv` from the Kaggle dataset named in `DATA_LICENSE.md`; not in the repository |

## One command each

| To | Run | Needs |
|---|---|---|
| run the fast tests | `make test` | Python; Spark tests skip without PySpark |
| run everything | `make test-all` | JDK 17, the data |
| regenerate every result | `make rebuild` (`bash scripts/rebuild_all.sh`) | JDK 17, the data |
| check nothing moved | `python -m src.ml.results_freeze --verify` | the result files |
| cut a new freeze | `make freeze N=6` | the result files |
| regenerate the paper's numbers | `make numbers` | the newest freeze |
| build both manuscripts | `make paper` | `latexmk` or `tectonic` |
| re-export and build the site | `make site` | Node 20+, `pnpm` or `npm` |

## What the freeze is

`benchmarks/results_freeze_v6.json` records every number the paper and README print, the file it came from and the first 16
hex digits of that file's SHA-256. `results_freeze --verify` recomputes each value from the files on disk and fails on any
difference; `src/report/paper_numbers.py` turns the same file into `paper/numbers.tex`, and a test fails if a manuscript uses a
macro the freeze does not define or if `numbers.tex` is stale. The expected freeze digest is the one printed in the first
comment line of `paper/numbers.tex` (`sha256 <16 hex digits>`).

## Runtime per stage

The first block is from a fresh clone before the upgrade pass (`benchmarks/raw/w8_fresh_clone_rebuild.json`, 4,258 s in total);
the second is the upgrade pass's stages, measured one by one on the reference machine while other work was running, so treat them
as upper bounds.

| Stage | Command | Time |
|---|---|---|
| clean, reconstruct, hubs, features, contracts | `src.pipeline.*` | about 2 min |
| corridor audit, baselines | `src.ml.audit`, `src.ml.baselines` | under 30 s |
| champion model (Week 4) | `src.automation.retrain` | 28 min |
| features v2, model sprint v2, adopted model | `src.pipeline.features_v2`, `src.ml.models_v2`, `src.ml.models_v2_stepsize` | 39 min |
| back-off baseline | `src.ml.backoff_baseline` | minutes (pandas only; not timed separately) |
| Spark residual model over back-off (v3) | `src.ml.models_v3` | about 70 min |
| model zoo and feature ablation | `src.ml.model_zoo` | about 20 min (the linear median regression is 4 min of it) |
| significance study | `src.ml.significance` | 40 s |
| rolling origin, Spark folds | `src.ml.rolling_origin` | about 2.5 h (four folds, two refits each; see the note) |
| rolling origin, reported model | `src.ml.rolling_origin_zoo` | 3 s |
| dependence diagnostics, audit (10^5 permutations) | `src.ml.audit_data`, `src.ml.audit_robust` | 10 s, 62 s |
| audit at 10^6 permutations | `src.ml.audit_robust --permutations 1000000 --placebo 0 --suffix _1e6` | 8 min |
| empirical-Bayes ranking, stability | `src.ml.eb_ranking`, `src.ml.stability` | 4 s, 9 min |
| exception statistics, hard sets, figures | `src.ml.exception_stats`, `src.ml.b7_hard_sets`, `src.report.figures_*` | under 2 min |

A full `make rebuild` is therefore about **six hours** on this machine, dominated by Spark model fits; `--quick` stops before the
model stages. This is an estimate summed from stage timings; it has not been re-measured as one clean-clone run since the upgrade.

## Known nondeterminism and how it is controlled

| Source | Control |
|---|---|
| Permutation tests, bootstraps, placebo | fixed seeds in each module (`20260801`, `20260802`, ...) and recorded in each result file |
| Gradient-boosted models | `random_state` / `seed` fixed; MLlib is deterministic for a fixed partitioning and seed on one machine; the numpy tree reader reproduces MLlib to the last bit (`w10_gbt_local_equivalence.json`) |
| Floating-point summation order | the numpy reader uses the same four-lane summation as Spark; results across machines with different BLAS may differ in the last digits. `--verify` compares exactly (no tolerance), so a rebuild elsewhere can report a moved value that is a rounding difference; read the `was` and `now` before treating it as a regression |
| Spark local scratch directory | `data/spark-tmp` is cleaned by some tests; a long Spark run should set `SPARK_LOCAL_DIR` elsewhere (this killed one rolling-origin run during the upgrade) |
| LLM calls (agent ablation, assistant, extraction) | every model call is cached by prompt hash under `data/b7_cache`; `--cache-only` rebuilds the result files with no calls; the cache is not committed, so a fresh clone keeps the committed result files |
| Free-tier quotas | the ablation is resumable across days; extraction rows 21 to 40 are not run (P-75) |

## What is not reproduced here

The Zenodo archive and its DOI (HUMAN_ACTIONS 6.8), the live Telegram and email receipts (masked evidence only), the Vercel and
Render deployments, and anything that needs a human (second labeller, user test, phone photographs).
