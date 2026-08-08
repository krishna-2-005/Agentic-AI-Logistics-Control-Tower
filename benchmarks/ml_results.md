# ML results — model vs OSRM

**Owner: Lahari.** Populated Week 3 (baselines) and Week 4 (the beat-OSRM headline).

Every number here must be reproducible by a named script in `src/ml/`, from the cached
Parquet, with the raw output landing in `benchmarks/raw/`. A number that cannot be
regenerated does not go in the report or the paper (GIT_RULES §4).

## Status: awaiting Week 3

## The baseline to beat

Established Week 1 at OD-leg grain (`docs/W1_lahari_eda.md`), on 26,369 legs:

| Baseline | MAE (min) | Notes |
|---|---|---|
| OSRM production estimate | _pending W3_ | `osrm_time` as the prediction of `actual_time` |
| Corridor mean | _pending W3_ | past-only mean per corridor |
| Linear regression | _pending W3_ | |
| Random Forest | _pending W4_ | |
| GBT | _pending W4_ | |

OSRM under-predicts on **98.3%** of legs; the median leg runs **2.00×** plan, mean
absolute gap **110 min**. Because the error is this one-sided, a model that merely
learns the bias should beat OSRM comfortably — so **the report must state the corridor
mean baseline too**, or the headline is unimpressive under scrutiny.

## Required alongside every classifier metric

The majority-class rate. See D-003: at the blueprint's 1.25 threshold the positive
class is 93.6% of legs, so accuracy alone is meaningless.

## Ablations (Week 4)

- drop corridor-history features
- drop temporal features
- FTL vs Carting separately
