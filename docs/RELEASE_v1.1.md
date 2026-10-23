# v1.1 — release notes

**Agentic AI Logistics Control Tower**, the upgrade pass (decisions D-075 to D-098). v1.1 does not add features to
v1.0; it re-examines its two headline results at the strength the data support and puts the work in publishable form.

## What changed, in one paragraph

Two v1.0 claims got weaker and are reported that way. The corridor audit's **273 slower / 512 faster** corridors are now a
*screening list*: legs of one recurring service are correlated, a placebo with meaningless corridor labels returns about 680
"discoveries", and a cluster-aware permutation test confirms **0** at its pre-registered strictness (also at ten times the
permutations); corridor effects do persist between halves of the period (rank correlation 0.91). The model's margin over its
baseline fell from 6.5% to 4.6% once the baseline lost an unfair 0.0-minute cold-start fallback, and the validation cut did
not favour the served model over that baseline. The reported model is now a single-node LightGBM chosen on validation by a
rule fixed in advance: **29.66 min** against a back-off bar of **32.39** (−2.74, day-block 95% interval [−3.41, −2.11]), winning on
all 13 slices and in 4 of 4 rolling-origin folds. The Spark model that the stream and the API serve is unchanged (30.90, −1.49 on the headline split) and beats the bar in only 2 of 4 rolling-origin folds, so it is described as no worse than the bar and better on cold legs.

## Numbers that moved

| | v1.0 | v1.1 | Why |
|---|---|---|---|
| Slower / faster corridors (headline) | 273 / 512 | 0 / 0 confirmed; 273 / 512 as a screening list | dependence-aware audit (D-080, D-083, D-084) |
| The bar the model is judged against | per-corridor median, 33.04 | hierarchical back-off median, 32.39 | the old median predicted 0.0 min on cold corridors (D-075) |
| Reported model, test MAE | 30.90 (Spark v2) | 29.66 (LightGBM L1), with a 95% interval [27.86, 31.12] | reporting rule over a model zoo (D-077); the Spark model is still served |
| Margin over the bar | 6.5% (2.14 min) | 8.4% (2.74 min) reported; 4.6% (1.49 min) served | |
| Top-20 stability across support floors | disjoint at floors 10 and 30 | overlap 0.15 (empirical Bayes) vs 0.10 (raw) across all pairs | shrinkage helps little; the cause is eligibility (D-081) |
| Exception agent precision | 58.6%, no interval | 58.6% [56.2, 60.9]; +4.45 points over alerting on every leg, significant by a valid paired test | D-085 |
| Invoice auditor headline | 20 / 20 | 90.0% [85.1, 93.4] on 200 stratified invoices | the 20 were a development corpus |
| Order entry headline | 50 / 50 | 85.0% [79.4, 89.3] on 200 held-out emails; 70% on a new held-out hard set | |
| Website figures | stale and inconsistent in places | one freeze (v5), enforced by tests | Phase D |

## New

- **Pre-registered studies** in `docs/decisions.md` (a dated, committed entry before each run): back-off bar, significance and
  rolling origin, model zoo and feature ablation, dependence-aware audit, empirical-Bayes ranking, temporal stability, exception
  statistics, the agent ablation, and two sensitivity runs. Each has an Outcome paragraph, including where a result disagreed
  with the plan.
- **Two manuscripts** in `paper/conference/` (Springer LNCS, 16 pages with references) and `paper/journal/` (about 27 pages), sharing
  `paper/sections/` and `paper/refs.bib` (90 verified entries). Every number is a macro generated from `results_freeze_v5.json`.
- **`REPRODUCIBILITY.md`**, `Makefile`, `scripts/build_paper.sh`, `docs/install.md`, `.gitleaks.toml`, a complete `.env.example`.
- **Site:** a Paper page, a corridors table with the audit status and empirical-Bayes rank, cold-start handling, and an
  Evidence page tied to the newest freeze.

## Not done, and why (see `docs/UPGRADE_REPORT.md`)

- The agent ablation ran at **pilot scale** (18 order cases, 8 each for invoice and exception triage) because the free-tier
  daily token cap bound; it is resumable.
- Nothing that needs a person: a second labeller, phone photographs, a user test, the venue choice, the Zenodo DOI
  (`docs/HUMAN_ACTIONS.md` section 6).
- Mobile Lighthouse performance below 90 on most pages (the map-heavy ones especially).

## Cutting the release (human steps)

1. Merge the upgrade PR into `dev`, then `dev` into `main`.
2. `git tag v1.1.0 && git push origin v1.1.0`; publish a GitHub release with these notes.
3. With Zenodo's GitHub integration switched on for the repository, the release is archived and a DOI issued; add the DOI to
   `CITATION.cff` (`identifiers`) and to the paper's reproducibility statement.
4. Redeploy the site (Vercel rebuilds on the push to `main`) and the API (Render is a manual deploy: see `deploy/api/README.md`).
