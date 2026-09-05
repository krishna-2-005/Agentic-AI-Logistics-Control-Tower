# ML results — model vs OSRM

**Owner: Lahari.** Populated Week 3 (baselines) and Week 4 (the beat-OSRM headline).

Every number here must be reproducible by a named script in `src/ml/`, from the cached
Parquet, with the raw output landing in `benchmarks/raw/`. A number that cannot be
regenerated does not go in the report or the paper (GIT_RULES §4).

## Status: Week 4 D1-D2 done (D3-D4 ablations, D5 doc-eval harness pending)

Source: `python -m src.ml.baselines` (Week 3) and `python -m src.ml.models` (Week 4) →
`docs/W3_lahari_baselines.md`, `docs/W4_lahari_beat_osrm.md`,
`benchmarks/raw/w3_baseline_metrics.csv`, `w3_linreg_coefficients.csv`,
`w3_classifier_metrics.csv`, `w3_baseline_report.json`, `w4_model_metrics.csv`,
`w4_classifier_metrics.csv`, `w4_corridor_gains.csv`, `w4_feature_importances.csv`,
`w4_cv_report.json`, `w4_model_report.json`. Computed on the frozen `features_v1` table
(Stage 4, Mounika), chronological split fixed by D-022: 21,095 train legs
(`trip_creation_time` <= 2018-09-28 23:12:35 UTC) / 5,274 test legs, reported below.

## The baseline to beat

Established Week 1 at OD-leg grain (`docs/W1_lahari_data_dictionary_and_eda.md`), on
26,369 legs, all MAE figures on the D-022 test split:

| Baseline | MAE (min) | Notes |
|---|---|---|
| OSRM production estimate | **107.1** | `osrm_time` as the prediction of `actual_time` |
| Corridor mean | **36.1** | past-only mean per corridor (Stage 4), falls back to OSRM when cold (D-023) |
| Linear regression | 41.2 | full as-of feature set; beats OSRM but **not** the corridor mean — see below |
| Random Forest (MLlib, tuned) | **36.9** | best of the two Week 4 models on MAE — still **not** the corridor mean, by 0.8 min |
| GBT (MLlib, tuned) | 38.3 | |

**Neither Week 4 model clears the corridor mean, and that is reported as it stands.**
Random Forest is the stronger of the two (36.9 vs GBT's 38.3 min MAE) and both comfortably
clear OSRM and the linear regressor, but the number D-024 says this project is judged on
is the corridor mean's 36.1, and a tuned tree ensemble trailing a single per-corridor
average by 0.8 min is a real, reportable result rather than a headline to round away.
Per-corridor, Random Forest still improves 1,369 of 1,646 test corridors over OSRM
(83%) — the network-wide MAE is not hiding a model that only helps a handful of
corridors. Full reasoning, the per-split table, feature importances, and the extended
delay-classifier table: `docs/W4_lahari_beat_osrm.md`.

OSRM under-predicts on **98.3%** of legs; the median leg runs **2.00×** plan, mean
absolute gap **110 min**. As expected, a model that merely learns the bias beats OSRM
comfortably — **the corridor mean alone recovers 66% of OSRM's error**, which is the
number Week 4's Random Forest and GBT actually have to clear, not OSRM's 107.1.

**The linear model does not clear the corridor mean, and that is the headline result
of this baseline — D-024.** 41.2 min MAE against the corridor mean's 36.1, despite a
*better* RMSE (96.8 vs 101.7) and R2 (0.811 vs 0.791). OLS minimises squared error, not
MAE, and the audited network's heavy-tailed corridors (up to 13.9× per D-018) let a
single global coefficient set trade a little bias on ordinary legs for less squared
error on the extreme ones — a trade the corridor mean's per-corridor local averages
never have to make. **D-024 fixes MAE as the metric Week 4 is judged and ranked on**,
not RMSE or R2, since the two disagree here on which of these two models is better.
Full reasoning and the per-split train/test table: `docs/W3_lahari_baselines.md` §3.

## Delay classifier v1 — `is_delayed`, D-025

`is_delayed` (`actual_time > 2.00x planned_min`, D-003) is 49.7% positive over all
26,369 legs — the whole reason D-003 moved the threshold off the blueprint's 1.25,
where it was 93.6% and accuracy alone would have meant nothing. Every classifier
metric below is reported beside the majority-class rate, per D-003, permanently.

| Model | Split | Accuracy | Precision | Recall | F1 | Majority rate |
|---|---|---|---|---|---|---|
| Majority class | test | 0.511 | 0.000 | 0.000 | 0.000 | 0.511 |
| OSRM (thresholded) | test | 0.511 | 0.000 | 0.000 | 0.000 | 0.511 |
| Corridor mean (thresholded) | test | 0.746 | 0.704 | **0.831** | 0.762 | 0.511 |
| Linear regression (thresholded) | test | 0.727 | 0.699 | 0.774 | 0.735 | 0.511 |
| **Logistic regression (delay classifier v1)** | test | **0.768** | **0.761** | 0.767 | **0.764** | 0.511 |
| Random Forest (thresholded) | test | 0.720 | 0.654 | 0.904 | 0.759 | 0.511 |
| GBT (thresholded) | test | 0.744 | 0.686 | 0.880 | **0.771** | 0.511 |

`OSRM` and the majority class make the same degenerate call — never predict
"delayed" — because OSRM's own estimate never disagrees with itself by 2x.
Thresholding GBT's own regression prediction reaches 0.771 F1, edging out logistic
regression's 0.764 (delay classifier v1) — a byproduct of the regression fit, not a
separately tuned classifier, and reported to complete D-025's table rather than to
replace v1. This is a different ranking from the MAE table above (Random Forest wins
there, not GBT) for the same reason D-024/P-28 already found MAE and RMSE can rank two
models in opposite orders: a thresholded classification score and a continuous
prediction are different objectives. Full table, train-split numbers, and the
precision/recall trade-off between the corridor mean and the fitted classifier:
`docs/W3_lahari_baselines.md` §5, `docs/W4_lahari_beat_osrm.md` §4.

## Ablations (Week 4, D3-D4)

Source: `python -m src.ml.models --ablations` → `docs/W4_lahari_beat_osrm.md` §6,
`benchmarks/raw/w4_ablations.csv`. Each model refit at its D1-D2 tuned hyperparameter
point (no fresh CV search per ablation — D-027), same D-022 test split.

| Model | Ablation | Features | Test MAE (min) | Cost vs full |
|---|---|---|---|---|
| Random Forest | full | 27 | **36.89** | — |
| Random Forest | drop corridor-history | 20 | 40.19 | **+3.30** |
| Random Forest | drop temporal | 24 | 37.00 | +0.11 |
| GBT | full | 27 | **38.28** | — |
| GBT | drop corridor-history | 20 | 40.71 | **+2.43** |
| GBT | drop temporal | 24 | 39.00 | +0.72 |

**The corridor-history block is worth far more than the temporal block, on both
models** — dropping it costs 2.4–3.3 min MAE, against 0.1–0.7 min for dropping
`created_hour`/`created_dayofweek`/`created_is_weekend`. This confirms D1-D2's
feature-importance ranking (`corr_mean_gap_min` top-3 for both models) against an
actual held-out cost rather than the fitted model's internal split statistics alone —
the two agree here, which was not guaranteed.

**Not done, and not asked for by the execution plan's actual D3-D4 line** (only
"drop corridor-history, drop temporal" is specified there): a separate FTL-vs-Carting
ablation was listed here speculatively at the Week 3 close and is left as an open idea
rather than implemented, so as not to silently claim a result nothing computed.

## Document-extraction evaluation harness (Week 4 D5 — pending)

Field-level accuracy/F1 on Krishna's Document Intelligence Agent (`week4-krishna-doc-agent`)
against the Week 3 labelled corpus — the first Layer 2 (agent) evaluation number, once
his agent has run over the corpus.
