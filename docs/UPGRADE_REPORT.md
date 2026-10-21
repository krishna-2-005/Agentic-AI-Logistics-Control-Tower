# Upgrade report

What the upgrade pass (`docs/UPGRADE_PLAN.md`, local brief) changed, which numbers moved and why, what is still open, and an
honest score against its section 8. Written 2026-10-21 on branch `wo-12-mounika-consistency`; the four track branches
(`wo-12-mounika-audit-stats`, `-refs-venues`, `-agent-study`, `-website`) are merged into it, so one PR carries everything.

## 1. The short version

The pass made two of v1.0's headline results **weaker** and reported them that way, added the statistics and the baselines a
reviewer would ask for, and put the work in two LaTeX manuscripts whose every number is generated from a frozen results file.

| Headline | v1.0 said | The upgrade found |
|---|---|---|
| Corridor audit | 273 slower and 512 faster corridors | A **screening list**. Legs of one recurring service are correlated (design effect about 2); on placebo data with meaningless corridor labels the same procedure finds about 680 "discoveries"; the cluster-aware test confirms **0** at its pre-registered strictness (and at ten times the permutations). Corridor effects **do persist** between halves of the period (rank correlation 0.91) |
| Support-floor instability | disjoint top-20 lists at floors 10 and 30 | Empirical-Bayes ranking is only slightly more stable (0.15 vs 0.10 mean overlap); the cause is who is eligible, not noise |
| Model vs its baseline | 30.90 vs 33.04, a 6.5% margin | The baseline's 0.0-minute cold fallback was unfair. Against a hierarchical back-off bar (32.39) the served Spark model's margin is 4.6% and **not robust** (2 of 4 rolling folds); the reported model (LightGBM, chosen on validation by a pre-registered rule) scores 29.66, −2.74 vs the bar [−3.41, −2.11], 4 of 4 folds |
| Exception agent | 58.6% precision | 58.6% [56.2, 60.9]; +4.45 points over alerting on every leg, significant by a valid paired test; the lowest severity grade is worse than alerting on everything |
| Agents | 50/50, 20/20 on small sets | 85.0% [79.4, 89.3] (order, 200 held-out), 90.0% [85.1, 93.4] (invoice, 200); a pilot ablation of letting a model decide found it behind the rules on orders (87.8% vs 100%, not held out; the rules score 70% on a new held-out hard set) |

## 2. What was done, by phase

**Phase A (consistency).** The wording that called OSRM a "production planner", the not-yet-served claim, the extraction headline
(97.9% over 280 fields with its n), the Week-6 invoice label and the data card's "what we cannot know" paragraph were fixed and are
guarded by `tests/test_consistency.py`. The site exporter now raises on a missing number instead of defaulting, uses the newest
freeze, and describes the live alert run and the no-AWS decision (A3–A6).

**Phase B (research).** Every experiment was pre-registered as a committed `DECIDED` entry before it ran; each has an Outcome.

| | Decision | Result |
|---|---|---|
| B1 back-off bar | D-075 | bar 32.39 vs old median 33.04; shrinkage (k) harmful; v3 model over back-off loses on validation; v2 stays served |
| B2 intervals, rolling origin | D-076, D-098 | day-block, 6-hour-block, paired and Diebold-Mariano intervals; Holm; four folds; reported model 4 of 4, served 2 of 4 |
| B3 dependence-aware audit | D-080, D-083, D-084 | trips and days do not cluster; the recurring service does (plan's assumption was wrong, logged); 0 / 0 headline; sensitivity at 10^6 permutations |
| B4 empirical Bayes | D-081 | pre-registered hypothesis "shrinkage removes the floor effect" not supported |
| B5 stability | D-082 | rank correlation 0.91; 97.7% of first-half slower corridors slower again |
| B6 model zoo, ablation | D-077 | LightGBM/XGBoost/HistGBR within 0.1 min of each other; reported by the rule; feature groups that matter: time, hub history, dispersion and dwell |
| B7 agent ablation, hard sets | D-086 to D-089 | **pilot scale only** (18 / 8 / 8 cases) because the free-tier token cap bound; hard sets held out |
| B8 exception statistics | D-085 | valid paired test; Cochran-Armitage trend; low grade below the trivial policy |

**Phase C (paper).** `paper/conference/` (Springer LNCS, 16 pages including 32 references) and `paper/journal/` (elsarticle, 27 pages,
63 references; the journal-only sections (streaming, scale, agent study, extended related work, reproducibility, appendix) are 31% of the
journal text and 46% of the conference text by word count, so the "at least 30% new" floor is met only narrowly). Shared sections in `paper/sections/`; numbers are macros from `paper/numbers.tex`, generated from
`benchmarks/results_freeze_v5.json` (168 values) and checked by tests; `paper/refs.bib` has 90 entries, each with a verification note
(`docs/references.md`: all `[metadata checked]`, none `[read]`); `docs/venues.md`; `docs/reviewer_simulation.md`; seven new figures
from code (forest plot, architecture, folds, agent ablation, and the audit-track figures); abstract 208 words. **Three title options**
(default first): *Localising Systematic Route-Estimate Error in Road Freight: Dependence-Aware Corridor Auditing and Residual Prediction*;
*Dependence-Aware Localisation of Route-Estimate Error in a National Freight Network*; *Shrinkage, Dependence and Baselines: An Honest
Evaluation of Corridor-Level Routing Error and Delay Prediction in Road Freight*.

**Phase D (site).** D1–D12 and A3–A6 done by the website track (no `nan` anywhere, en-US grouping, superseded rows labelled, agent cards with
n, interval and trivial baseline, alert replay explained, corridors table with search/filter/pagination, a Paper page, cold-start states,
Lighthouse accessibility mostly 100). After the merge the corridors page also shows each corridor's audit status and empirical-Bayes rank.
A browser check of every page passes; the site builds.

**Phase E (repo).** README shortened with a 90-second path, results with intervals, BibTeX; `docs/install.md`; Spark test modules skip
without PySpark (E2); mypy covers `src/common`, `src/agents`, `src/ml`, `src/api` with 11 modules excluded for stated reasons (E3); `Makefile`
(E4); `docs/RELEASE_v1.1.md`, `CITATION.cff` with a DOI placeholder, Zenodo steps in `HUMAN_ACTIONS` (E5); `REPRODUCIBILITY.md` (E6);
`.gitleaks.toml` (history of 329 commits scans clean), complete `.env.example`, `requirements.txt` and lock (E7); badges point at `main` (E8).

## 3. Numbers that moved

See `docs/RELEASE_v1.1.md` for the table of moved numbers. Not repeated here.

## 4. Deviations from the plan, and problems found

* **D-083:** the plan assumed trip or day clustering; measured, neither exists, the recurring service does. The cluster unit became the (corridor, service) cell.
* **D-084:** the strictest audit variant could not reject at 10^5 permutations (resolution), found after seeing the result; a ten-fold finer run was pre-registered before it ran and changes nothing.
* **D-098:** the plan's folds covered only the Spark models; the reported single-node model was added after it was named.
* **P-83:** the empirical-Bayes bootstrap interval quoted in the first write-up came from 3 resamples, not 200 (a smoke run had overwritten the file); caught while citing it, rerun, the interval's lower end moved from 0.037 to 0.006.
* **P-84:** a long Spark run was killed by a test run that cleans the shared scratch directory.
* The refs track found that D-052's conference date belongs to a different "ICCCI" (a networking conference): D-097, P-82. The 20 February 2027 date is withdrawn.

## 5. Scorecard

| Aspect | Score | Why not higher |
|---|---|---|
| Code and engineering | **8** | 824 fast tests, ruff and mypy clean, every new module tested, rebuild includes the new stages. The 50 Spark-marked tests also pass locally. Not 9: GitHub CI has not run on this branch, the lock was updated by hand for two packages and not re-compiled |
| Reproducibility | **8** | Freeze v5 verified (168 values unchanged), macros, `REPRODUCIBILITY.md`, DOI steps prepared. Not 9: the full-rebuild runtime (about six hours) is an estimate summed from stage timings, not a re-measured clean-clone run, and there is no DOI yet |
| Statistical rigour | **8.5** | Dependence-aware audit, EB, stability, intervals and Holm on every comparison, rules pre-registered and logged, deviations logged. Open: a power simulation for the permutation test, a heavy-tailed random-effects model; day-block intervals rest on six blocks |
| ML results | **8** | Fair bar, zoo under an identical budget, rolling origin, ablation, reporting rule applied. The honest finding is that the served model's margin is not robust, and the reported model is not what is served; no neural baseline |
| Agent layer | **6.5** | Hard sets and 200-case sets with Wilson intervals, human-task protocols prepared. The B7 ablation is a **pilot** (token cap), extraction rows 21–40 not run, kappa waits for a person |
| Novelty and contribution | **7** | Contributions rewritten around what Phase B showed; the general findings are real (dependence inflates a standard audit; shrinkage does not fix floors; two evaluation traps) but modest, and several are negative |
| Paper | **7.5** | LaTeX in LNCS and elsarticle, 32 / 63 references, equations and an algorithm box, threats, reviewer simulation, no TODOs. Not 9: no reference is marked `[read]` (a human pass is owed), the venue and its template are not chosen or verified, the conference version is 16 pages not 12–15, no outside review |
| Website | **7.5** | D1–D12 done, tests enforce consistency, Paper page built. Mobile Lighthouse performance is below 90 on most pages; the site has not been redeployed (needs the merge) |
| Repo presentation | **8** | README concise, release notes, citation metadata, badges on `main`. The tag, the release and the DOI are human steps |

## 6. Open items, in order of value

1. **People:** venue and template choice, author order, the `[read]` pass on eight core references, a second labeller (groundedness, 150 order emails), phone photographs, the user test, the Zenodo DOI, an arXiv endorsement (`docs/HUMAN_ACTIONS.md` section 6).
2. **Quota:** resume the agent ablation across 3–4 days (`python -m src.ml.agent_ablation --llm-verdict`) and extraction rows 21–40, then re-cut the freeze.
3. **Analysis:** a power simulation for the permutation test; a comparison with planning-time and buffer indices; a heavy-tailed random-effects model; put the reported single-node model through the streaming and serving chain if it is to be the served one (D-075 rule 4).
4. **Site:** improve mobile performance on the map pages; redeploy after the merge.
5. **Process:** merge the PR into `dev`, then `dev` into `main`, tag `v1.1.0`.

## 7. How this was checked

Fast tests: `pytest -m "not spark"` (824 passed). Lint and types: `ruff check src tests`, `mypy`. Freeze: `results_freeze --verify`
(168 unchanged). Paper: both manuscripts compile with Tectonic; `paper_numbers --check` and the macro tests pass. Site: `tsc`, `next build`
and `tests/e2e_site_check.py` pass. Secrets: `gitleaks detect` on all 329 commits reports none (the digests in the freezes are allow-listed).
Spark-marked tests: `pytest -m spark` (50 passed, 80 s).
