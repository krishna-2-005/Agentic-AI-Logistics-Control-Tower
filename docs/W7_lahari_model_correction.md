# W7 · Lahari — the model correction sprint, and closing the evaluation gaps

Week 7 opened under execution plan v3.1, which reopened the Week 4 result for exactly
three days (D-048) because a Random Forest was losing to a per-corridor average and that
points at a defect, not a limit. It ends with a model that beats the right baseline by
6.5% on every slice, and with a clear account of why the Week 4 number was what it was.

```bash
python -m src.ml.ml_diagnostics          # D1: the four diagnostics, before any model change
python -m src.ml.models_v2               # D2: residual target, absolute loss, on feature table v2
python -m src.ml.models_v2_stepsize      # D3: the step-size fix, chosen on validation
python -m src.ml.order_eval --run --report   # D4: the last order-entry cases (G-02)
python -m src.ml.experiments_appendix    # D5: every reported number, to a command
```

## 1. The diagnostics found three wrong things, not one (D1, D-048)

v3.1 predicted a categorical-as-numeric bug. There isn't one: the feature assembly has no
`StringIndexer` and no corridor key in the vector at all, so `maxBins` cannot be the
problem. Reading the code ruled out the most likely explanation in ten minutes. What the
diagnostics did find:

**The bar was wrong.** The table is graded on MAE, and MAE is minimised by the median, so
the fair baseline was never the corridor *mean* (36.13). The per-corridor as-of median
scores **33.04** — stronger than either Week 4 model. Reporting against the mean would
have been choosing the comparison after seeing the result, so every Week 7 number is
reported against 33.04.

**The objective was wrong.** MLlib's Random Forest is squared-loss only. sklearn's
`HistGradientBoostingRegressor` on the same 27 features moved 5.1 minutes between squared
and absolute loss (34.70 → 29.59). The features were never the limit.

**The as-of reconstruction was wrong, in my own diagnostic.** My first version derived a
leg's finish time as departure plus `actual_time`, which agreed with Stage 4 on only 95.2%
of legs. `actual_time` is *moving* time; it excludes dwell. Joining the real `od_end_time`
brought agreement to 100% (P-52, and Mounika carried the same fix into the stream, where
facts were being published a median 49.6 minutes early). The median baseline itself moved
from 33.06 to 33.04 — the fix bought a provably identical history, not a better headline,
which is the only reason to trust the 33.04.

## 2. Residual learning, and a result that looked better than it was (D2-D3)

The model learns `gap_min − corridor median` and the prediction is baseline plus
correction, so a model that learns nothing reproduces the baseline exactly.

First run, GBT with `lossType="absolute"`, `stepSize=0.05`: **32.52 min**, which clears the
33.04 bar by 1.6% and returns "adopt" from the pre-registered rule. It was not a result to
adopt, and the slice table said why: the entire margin came from 294 legs on corridors the
training set had never seen. **On every corridor with history it was 1 to 2 minutes worse
than looking the median up in a table.** The v3.1 rule only checks well-observed corridors
for its second outcome, not its first, so the rule could not see this. That gap in the rule
is recorded in D-049 rather than patched after the fact.

**Why it underperformed, read out of the saved model.** MLlib's absolute-loss GBT fits its
first tree on the raw target with squared error (leaf values −1,382 to +2,605 minutes) and
every later tree on the *sign* of the error, with leaf values in [−1, 1] scaled by
`stepSize`. At 0.05, the 199 corrective trees can move a prediction by **9.95 minutes in
total**. The objective the sprint was built around was barely switched on.

## 3. The fix, chosen before it was scored (D-049, D-050)

The temptation was to try step sizes and report the best test score. That is selection on
the test set. Instead, D-049 was written and committed first: cut the training split
chronologically again, fit at `stepSize` ∈ {0.05, 0.3, 1.0} on the earlier part, score on
the later part, refit the winner on the full training split, score it **once** on test, and
adopt it whatever that score is.

| stepSize | correction cap | validation MAE | test MAE |
|---|---|---|---|
| corridor median | — | **29.89** | 33.04 |
| 0.05 | 9.95 min | 31.55 | 32.52 |
| 0.3 | 59.7 min | 30.51 | — |
| **1.0** | 199 min | **30.17** | **30.90** |

Two things are worth saying about this table. The ordering confirms the mechanism: more
allowed correction, better fit. And **on validation every step size loses to the median**,
which is why the rule mattered — a run that stopped there would have concluded the opposite
of what the held-out test split says.

**On test the adopted model wins on all fourteen slices**, which the 0.05 model did not:

| slice | n | corridor median | v2 GBT (step 1.0) |
|---|---|---|---|
| corridor unseen in training | 294 | 111.18 | **75.92** |
| 1-9 prior legs | 1,548 | 31.79 | **31.76** |
| 10-29 | 2,723 | 26.26 | **26.07** |
| ≥30 | 709 | 29.45 | **28.95** |
| FTL | 2,594 | 39.10 | **36.48** |
| Carting | 2,680 | 27.18 | **25.51** |
| **overall** | 5,274 | 33.04 | **30.90** |

**Where the gain really is.** −35 minutes on the 294 unseen-corridor legs is −1.97 of the
−2.14 overall. On corridors with history the model beats the lookup by 0.02 to 0.51
minutes. Both belong in the same sentence: this model is a large improvement exactly where
a lookup table has nothing to say, and a small one everywhere else. The sklearn reference
still reaches 29.52, so 30.90 is not the ceiling — it is what the MLlib configuration
reaches, and MLlib is the reported model by the plan's own rule.

**The serving champion did not move** (D-050). A residual model is baseline plus
correction, and the streaming job carries the corridor *mean* in its history snapshots, not
the median. Repointing the champion without that lookup would serve the correction alone.

## 4. G-02 closed: 50 of 50 order-entry cases

The last two cases ran on the fifth quota day. **50 of 50 succeeded**: five of five on
every one of the ten templates, clarification recall and precision both 1.00, no order
filed on an invented value, no needless question. The reading in D-040 is unchanged by the
larger sample, which is itself mildly reassuring — a perfect score that survives a 25%
bigger set is less likely to be luck. It is still templated email, and still a ceiling
rather than a verdict.

## 5. One evaluation table, and every number traceable (D4-D5)

`benchmarks/agent_evaluation.md` now covers all five agents plus the orchestrator in one
table, each row carrying its test set, prompt version, model, and **the trivial policy on
the same set** — "always file" for order entry, "notify every leg" for the exception agent,
"dispute everything" for the invoice auditor. Two rows are still owed and say what they
wait on rather than borrowing an older number.

`benchmarks/experiments_appendix.md` is generated from the frozen results: 31 reported
numbers, each with the cache file it is read from and the command that regenerates that
cache, and zero gaps. It is generated rather than written, because a hand-kept list of
numbers drifts from the numbers — which is exactly how the MCP tool list went stale
this week (P-57).

**Groundedness judging is defined but not yet run.** The method is fixed in
`agent_evaluation.md` before the answers exist: for each model-phrased answer, every number
in it must appear in its retrieved context, nothing may be claimed the context does not
support, and an out-of-scope question must get the refusal sentence. It waits on Krishna's
model-phrased run, which waits on quota.

Decisions logged: D-048 (the diagnostics and the unfreeze), D-049 (the procedure, before it
ran), D-050 (the adoption). Problems: P-52 (finish time), P-55 (two JVM failures in the
sprint).
