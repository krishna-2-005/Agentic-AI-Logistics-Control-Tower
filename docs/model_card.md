# Model card: v2 residual GBT (`v2_gbt_residual_absolute_step1`)

**What this is.** The delay model the paper reports and the system serves: the stream, the
what-if predictor and the public API all score with it (D-050, D-070). Every number below is
read from a committed file, named in brackets; `tests/test_cards.py` checks them against
those files. The data underneath is described in `docs/data_card.md`.

**Owner:** Lahari (model and evaluation); serving by Mounika.

---

## What it predicts

For one road-freight leg, at the moment the leg is **created**, the model predicts
**`gap_min`: how many minutes past its planned (OSRM) time the leg will run**.

It does this as a **residual**: prediction = the corridor's as-of median gap + the model's
correction. The median alone is the strongest simple baseline (D-048); the model learns
when and by how much to depart from it.

## Intended use

* **Ranking and flagging legs likely to run late,** so an operator looks at them first. The
  stream raises an alert when the prediction crosses 2.0× the planned time (D-003).
* **What-if questions** on the public predictor: how late would this leg run from this hub at
  this hour.
* **A research artefact** for the paper's claim that a residual over a per-corridor median
  improves prediction, most of all where the corridor has no history.

**Not intended for:** promising delivery times to customers, pricing, or any network other
than the one it was trained on (see "Failure modes").

## Training data and split `[w3_baseline_report.json]`, `[w7_model_v2_stepsize_report.json]`

| | |
|---|---|
| data | Delhivery legs created 12 September to 3 October 2018 (`docs/data_card.md`) |
| split | **chronological**, not random (D-022): the first 80% of legs by creation time train, the rest test |
| train / test | **21,095** / **5,274** legs, cut on 28 September 2018 |
| model selection | a second chronological cut inside train: 16,876 legs fit, 4,219 scored |

## Model

| | |
|---|---|
| algorithm | Spark MLlib gradient-boosted trees, trained on the residual over the corridor median |
| loss | **absolute** (MAE is the reported metric, D-024) |
| trees, depth | 200, depth 6 |
| step size | **1.0**, chosen on the validation cut from {0.05, 0.3, 1.0} before the test set was scored (D-049) |
| features | **38**: 6 known at creation (planned minutes and km, hour, day of week, weekend, FTL); 18 as-of history statistics for the corridor and both hubs; 3 cold-start flags; 8 v2 history features (corridor median, p90, IQR, std, 7-day mean and count, dwell by hub and part of day); 3 flags for missing v2 history |
| leakage rule | every history feature uses only legs **finished before** this leg was created (D-020), verified at 100% agreement against an independent recomputation `[w7_ml_diagnostics.json]` |

## Performance on the held-out test split (5,274 legs) `[w7_model_metrics_v2_stepsize.csv]`

Mean absolute error in minutes, lower is better:

| | MAE |
|---|---|
| **this model** | **30.90** |
| corridor median (the fair baseline) | 33.04 |
| OSRM's own plan (context only: it has no history) | 107.09 |

### By slice: where the gain is

| slice | legs | median baseline | **this model** | change |
|---|---|---|---|---|
| corridor **unseen** in training | 294 | 111.18 | **75.92** | **−35.26** |
| corridor with 1–9 legs | 1,548 | 31.79 | 31.76 | −0.02 |
| corridor with 10–29 legs | 2,723 | 26.26 | 26.07 | −0.19 |
| corridor with ≥ 30 legs | 709 | 29.45 | 28.95 | −0.51 |
| FTL | 2,594 | 39.10 | 36.48 | −2.61 |
| Carting | 2,680 | 27.18 | 25.51 | −1.68 |
| short (< 33 km) | 1,960 | 18.30 | 18.20 | −0.10 |
| medium (33–67 km) | 1,760 | 26.87 | 24.63 | −2.24 |
| long (≥ 67 km) | 1,554 | 58.63 | 54.04 | −4.59 |
| night | 1,537 | 33.99 | 31.54 | −2.45 |
| morning | 650 | 43.74 | 40.43 | −3.31 |
| afternoon | 647 | 37.16 | 36.35 | −0.81 |
| evening | 2,440 | 28.51 | 26.52 | −1.98 |

**It wins on all fourteen slices, but read where.** Most of the overall gain comes from the
294 legs on corridors the model never saw in training. On corridors with history it beats a
median lookup by a fraction of a minute. That is a real gain and a small one.

**And on validation it did not win.** On the validation cut, every step size lost to the
median (best 30.17 against 29.89) `[w7_model_v2_stepsize_report.json]`. The step size was
chosen there; adoption was judged on test by a rule fixed beforehand (D-049, D-050). Both
facts are reported because the second qualifies the first.

## Serving, and proof it is the same model

| check | result |
|---|---|
| the running stream against batch, on every leg | **26,369 of 26,369 identical**, 500 of 500 in the acceptance sample `[w10_stream_validation_v2.json]` |
| the stream's own predictions on the test split | MAE **30.90**, the reported figure `[w10_stream_validation_v2.json]` |
| the public API's numpy reader against Spark, on every leg | **26,369 of 26,369 identical** `[w10_gbt_local_equivalence.json]` |
| warm prediction latency, public API | p50 292 ms, p95 345 ms `[f1_api_latency.json]` |

## Failure modes, and what to do about them

1. **Cold-start corridors.** With no corridor history the prediction rests on route, distance,
   hour and hub history. That is where the model helps most and is least certain; every
   answer carries cold-start flags, and the predictor says "no history yet".
2. **One carrier, three weeks.** Trained on 22 days of one operator's network. It has seen no
   season, no festival peak and no other network. Do not transfer it.
3. **The served history ends in October 2018.** For "today", the public predictor reads each
   corridor's history as it stood at the end of the data; the 7-day window is empty and is
   flagged as such (D-073).
4. **Replay evaluations can leak the future.** Scoring replayed events against end-of-data
   history inflated an alert precision from 58.6% to 72.1% (D-054) `[w8_replay_leakage.json]`.
   This model is served on event-time state, which is as-of by construction (D-070), but any
   new evaluation must keep every join as-of the replayed event.
5. **Optimiser settings can disable the chosen loss.** MLlib's absolute-loss GBT fits its
   first tree with squared error and every later tree to the *sign* of the error, scaled by
   the step size. At 0.05, the 199 corrective trees could move a prediction by **at most
   9.95 minutes in total**, so the absolute loss was barely switched on (D-049, paper §5.4).
   Re-tune the step size on validation if the model is retrained.
6. **The delay threshold is a policy, not a quality dial.** Moving it from 1.15× to 2.0× changes
   how many legs are alerted far more than how well (`w5_threshold_sensitivity.csv`).

## Regenerate

```bash
python -m src.pipeline.features_v2          # the v2 feature table
python -m src.ml.models_v2_stepsize         # select on validation, score on test, save
python -m src.streaming.validate_v2         # stream equals batch, every leg
python -m src.ml.gbt_local --verify         # the API's reader equals Spark
```
