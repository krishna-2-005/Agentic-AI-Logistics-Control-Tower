# For reviewers: claims, evidence, and how to check in ten minutes

Every claim in the paper is a macro generated from `benchmarks/results_freeze_v6.json`, which records the file each value came from and
that file's hash. To check any number: find its row below, open the file, and run the command.

## Ten-minute check

```bash
git clone <repository> && cd <repository>
pip install -r requirements.txt
python -m pytest -q -m "not spark"               # 800+ tests, no JVM, about a minute
python -m src.ml.results_freeze --verify          # recomputes every frozen number from the files in benchmarks/raw/
python -m src.report.paper_numbers --check        # every macro in the paper resolves to a frozen value
```

Rebuilding the results from the raw CSV (`make rebuild`, hours) needs the data from the source named in `DATA_LICENSE.md` and a JDK 17.

## Claims and where they are evidenced

| Claim | File | Produced by | Decision (pre-registration) |
|---|---|---|---|
| The recorded OSRM estimate is one-sided: 98.3% of 26,369 legs run over it | `w1_leg_summary.csv` | `src.pipeline` stages | D-018 |
| The standard Welch audit flags 273 slower and 512 faster corridors | `w2_corridor_audit.csv` | `src.ml.audit` | D-018 |
| Legs of one recurring service are correlated (design effect about 2); trips and days do not cluster | `b3_dependence_diagnostics.json` | `src.ml.audit_data` | D-083 |
| A cluster-aware test confirms 0 corridors; the same at 10x the permutations | `b3_audit_robust.json`, `b3_audit_robust_1e6.json` | `src.ml.audit_robust` | D-080, D-084 |
| The standard test is wrong in about 96% of its discoveries; the cluster-aware test is correctly sized but finds about 8% of corridors with a 2.7-fold overrun planted | `b9_power.json` | `src.ml.audit_power` | D-099 |
| Corridor effects persist between halves (rank correlation 0.91) | `b5_stability.json` | `src.ml.stability` | D-082 |
| Shrinkage barely stabilises top-20 lists, with a normal or a heavy-tailed prior | `b4_eb_ranking.json`, `b10_eb_t.json` | `src.ml.eb_ranking`, `src.ml.eb_t` | D-081, D-102 |
| The planning-time and buffer indices are less stable than the mean | `b11_reliability_indices.json` | `src.ml.audit_indices` | D-100 |
| The fair back-off bar scores 32.39 minutes; the old median's cold fallback was unfair | `b1_backoff_baseline.json` | `src.ml.backoff_baseline` | D-075 |
| The reported model (LightGBM, L1) scores 29.66, minus 2.74 against the bar with a day-block interval excluding zero | `b2_significance.json`, `b6_model_zoo.json` | `src.ml.significance`, `src.ml.model_zoo` | D-076, D-077 |
| It beats the bar in 4 of 4 rolling folds; the Spark model in 2 of 4 | `b2_rolling_origin_zoo.json`, `b2_rolling_origin.json` | `src.ml.rolling_origin_zoo`, `src.ml.rolling_origin` | D-076, D-098 |
| The reported model is exact through the numpy reader and the running stream on all 26,369 legs | `b13_lgbm_serving_equivalence.json`, `b13_stream_validation_lgbm.json` | `src.ml.lgbm_export`, `src.streaming.validate_v2` | D-101 |
| Exception alert precision is 58.6% as-of (72.1% was a leak); the gain over alerting on everything is significant | `b8_exception_stats.json`, `w8_replay_leakage.json` | `src.ml.exception_stats`, `src.ml.replay_leakage` | D-054, D-085 |
| Agent ablation (pilot scale) and held-out hard sets | `b7_agent_ablation.json`, `b7_hard_sets_deterministic.json` | `src.ml.agent_ablation`, `src.ml.b7_hard_sets` | D-086 to D-089 |

## What the evidence does not show

- One operator and 22 calendar days: nothing generalises beyond that network and season.
- The recorded planned time's provenance is unknown, so "planner error" means "error of this recorded column".
- The cluster-aware test is nearly blind (power study): its zero does not show corridor effects are absent.
- Agent data are synthetic; the agent ablation is a pilot; no human has labelled an agent decision yet.
- The reported model is proven servable and exact, but the deployed alert path and its measured precision use the Spark model.
- No reference is marked as read in full (`docs/references.md`): citations are verified for metadata only.

## How decisions were fixed

`docs/decisions.md` holds every experiment's pre-registration as a committed entry before the run, and an Outcome after it, including the
deviations (D-083, the hybrid p-value that failed its own calibration check in D-099, the 3-resample interval found in P-83).
