# Reviewer simulation of the conference draft

*Self-review, UPGRADE_PLAN C6. Three reviews written by the authors in the voice of the reviewers the paper will
meet: a statistician, a transport researcher and an ML/systems reviewer. They are not independent reviews, and the
scores are the authors' guess at what a hostile but fair reader would give, not a prediction of any venue's outcome.
Each weakness is marked **Fixed** (what changed), **Answered** (stated in the paper's limits) or **Open**.*

## Review 1: the statistician

**Summary.** The paper shows that a standard corridor audit is over-optimistic under dependence, replaces it with a
cell-permutation test, finds nothing survives, and reports that corridor effects nonetheless persist. It then compares
models with day-block intervals. I like the placebo and the pre-registration discipline. Score: **6 / 10 (weak accept)**.

| # | Weakness | Status |
|---|---|---|
| S1 | The strictest variant (BY over permutation p-values) could not reject anything at 10^5 permutations, so "0 of 273" says nothing | **Fixed.** Stated in the audit section; a ten-fold finer run (D-084, pre-registered before it ran) lowers the p floor below the BY threshold and still rejects nothing |
| S2 | A zero result is not evidence of absence; no power analysis for the permutation test | **Answered, Open.** The paper calls the 273 a screening list and says the data cannot separate corridor from service effects. A simulation that injects known corridor effects into the placebo and measures detection would settle the power question; it was not run |
| S3 | The global-null permutation is conservative when real effects exist in the pool | **Answered.** Stated in threats to validity |
| S4 | Six calendar days of test legs means six bootstrap blocks | **Answered.** Said in the results and in the limits; the 6-hour-block and Diebold-Mariano intervals are given beside it and agree for the reported model |
| S5 | The reported model was chosen on validation among about 14 candidates; winner's curse | **Answered.** The rule was fixed before fitting (D-077); the test split was scored once; rolling-origin folds (D-098) are a second, independent check: the model wins 4 of 4 |
| S6 | Slice-level wins are multiple comparisons | **Fixed.** Holm correction over 14 comparisons reported: the reported model keeps 14 of 14, the served model drops from 10 to 6 |
| S7 | The empirical-Bayes model assumes normal log ratios and a common variance | **Open.** The log ratio is heavy-tailed; REML was compared with a moment estimator (they agree except at the highest floor) but no t-distributed random effect was fitted |
| S8 | The bootstrap interval in the first EB write-up came from 3 resamples | **Fixed.** Found while citing it; rerun at 200 resamples; the lower end moved from 0.037 to 0.006 (still above zero). Logged as P-83 |

## Review 2: the transport researcher

**Summary.** An interesting use of operational data, but the object studied is a recorded number of unknown origin on 22 days
of one carrier's network, and the "corridor" is a pair of facilities. The contribution to the reliability literature is a
testing recipe, not a finding about freight. Score: **5 / 10 (borderline)**.

| # | Weakness | Status |
|---|---|---|
| T1 | The planned time's provenance is unknown; "planner error" may be "column error" | **Answered.** The data section says what the column is and is not, and the paper makes no claim about the carrier's planning system |
| T2 | 22 days, one season, one operator | **Answered.** Threats to validity; the persistence result is explicitly within the 22 days and not independent replication |
| T3 | The standard reliability indices (planning-time index, buffer index) are not computed for comparison | **Open.** The related work cites them as descriptive; a comparison table would strengthen the link to the transport literature |
| T4 | A corridor is not a road; two services on one pair may take different roads | **Answered.** Stated under construct validity; the service-cell finding is partly an answer, since service is what clusters |
| T5 | What can an operator do with a screening list that confirms nothing? | **Answered.** The paper recommends reporting the whole ranking with intervals and the floor; operational use is not evaluated and is not claimed |
| T6 | No cost model: is 2.7 minutes of 32 meaningful? | **Open.** The gain is 8% of MAE and concentrated on cold legs (a 46-minute improvement there); no operational value is estimated |

## Review 3: the ML and systems reviewer

**Summary.** The evaluation hygiene is better than most (as-of features, leakage found and reported, a fair baseline,
model zoo under an identical budget). But the model that is reported is not the model that is served, the
streaming system is out of the conference version, and the agent claims rest on synthetic data. Score: **6 / 10 (weak accept)**.

| # | Weakness | Status |
|---|---|---|
| M1 | The reported model (single-node LightGBM) is not the served model (Spark MLlib) | **Answered.** Said in the abstract-level results, the table and the threats; the paper does not claim they are the same. The serving chain was not re-validated for LightGBM, by decision (D-075 rule 4: v2 stays served) |
| M2 | A small tuning budget (three learning rates) for every library | **Answered.** Stated; the close candidates (29.66 to 29.75) could reorder with a larger search |
| M3 | No neural or sequence model baseline (DeeprETA-type) | **Open.** Not feasible without trajectories; cited as related |
| M4 | The agent ablation is a pilot (18, 8 and 8 cases) and the rule agents' 100% on the 200-email set is not held out | **Fixed / Answered.** The paper says "pilot", states the 100% is not held out, and reports the new held-out hard set (70%). The full pre-registered 40 cases per agent were not run (token cap) |
| M5 | Everything about the agents is synthetic | **Answered.** Said in the context section and the limits |
| M6 | Rolling origin covers only Spark in the first version | **Fixed.** D-098 adds the reported model on the same folds |
| M7 | The leak found in the replay may exist elsewhere | **Answered.** Threats to validity say any replay-based measurement inherits the risk; a stream-equals-batch test on features alone would not catch it |
| M8 | No ablation of the as-of rule (what does leakage buy?) | **Open.** The replay leak (72.1% against 58.6%) is the only quantified instance |

## What this review changed

Fixed in the paper: the permutation-resolution caveat and its finer run (S1), the Holm-corrected slice wins (S6), the
single-node rolling-origin folds (M6), the false 3-resample interval (S8), and the removal of every claim that the 273 corridors
are confirmed. Left open, in order of how much they would help: a power simulation for the permutation test (S2), a
comparison with planning-time and buffer indices (T3), a heavy-tailed random-effects model (S7), and an operational value
estimate (T6). None of the open items changes a headline number; each would change how a reader weighs one.
