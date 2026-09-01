# ML results — model vs OSRM

**Owner: Lahari.** Populated Week 3 (baselines) and Week 4 (the beat-OSRM headline).

Every number here must be reproducible by a named script in `src/ml/`, from the cached
Parquet, with the raw output landing in `benchmarks/raw/`. A number that cannot be
regenerated does not go in the report or the paper (GIT_RULES §4).

## Status: Week 3 done, awaiting Week 4

Source: `python -m src.ml.baselines` → `docs/W3_lahari_baselines.md`,
`benchmarks/raw/w3_baseline_metrics.csv`, `w3_linreg_coefficients.csv`,
`w3_classifier_metrics.csv`, `w3_baseline_report.json`. Computed on the frozen
`features_v1` table (Stage 4, Mounika), chronological split fixed by D-022: 21,095
train legs (`trip_creation_time`
<= 2018-09-28 23:12:35 UTC) / 5,274 test legs, reported below.

## The baseline to beat

Established Week 1 at OD-leg grain (`docs/W1_lahari_data_dictionary_and_eda.md`), on
26,369 legs, all MAE figures on the D-022 test split:

| Baseline | MAE (min) | Notes |
|---|---|---|
| OSRM production estimate | **107.1** | `osrm_time` as the prediction of `actual_time` |
| Corridor mean | **36.1** | past-only mean per corridor (Stage 4), falls back to OSRM when cold (D-023) |
| Linear regression | 41.2 | full as-of feature set; beats OSRM but **not** the corridor mean — see below |
| Random Forest | _pending W4_ | |
| GBT | _pending W4_ | |

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

`OSRM` and the majority class make the same degenerate call — never predict
"delayed" — because OSRM's own estimate never disagrees with itself by 2x. Full
table, train-split numbers, and the precision/recall trade-off between the corridor
mean and the fitted classifier: `docs/W3_lahari_baselines.md` §5.

## Ablations (Week 4)

- drop corridor-history features
- drop temporal features
- FTL vs Carting separately
- Week 4 must reuse `src.ml.baselines.time_split(frac=0.80)` rather than define its own
  cut, and must report MAE against the corridor-mean baseline above, not only OSRM
  (D-024).
- Week 4's Random Forest and GBT owe the same classifier table above too, scored with
  `add_delay_label` / `threshold_to_label` rather than a redefined `is_delayed` — the
  fitted classifier to clear is logistic regression's 0.764 F1, not the majority
  class's 0.000.
