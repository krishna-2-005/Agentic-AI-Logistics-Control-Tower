# Problems log

Every problem that cost us real time, what actually caused it, and how it was fixed.

**Why this file exists.** Three of us work on three machines against one dataset, and
most of what slowed us down was not hard — it was invisible. A pipeline that runs
cleanly and produces wrong numbers costs more than one that crashes. Writing these
down means the next person who hits one recognises it in a minute instead of a day,
and the viva answer to *"what went wrong?"* is this file rather than a shrug.

Add an entry the day you hit the problem, while you still remember what you tried.
Decisions that came out of a problem live in [`decisions.md`](decisions.md); this file
is the symptom and the diagnosis.

**Format:** symptom → cause → fix → what it cost.

---

## Environment and setup

### P-01 · `winget install` for JDK 17 hangs forever
**Week 1 · Mounika · resolved**

- **Symptom.** `winget install EclipseAdoptium.Temurin.17.JDK` produced no output and
  never returned in a non-interactive shell.
- **Cause.** The MSI needs UAC elevation. The prompt is invisible in a
  non-interactive terminal, so the install waits on a click nobody can see.
- **Fix.** The portable Temurin **zip** — extract, set `JAVA_HOME`, add to `PATH`.
  No elevation, no prompt. Commands are in the README.
- **Cost.** ~1 hour, mostly spent assuming the download was slow.

### P-02 · pip silently builds NumPy and PySpark from source
**Week 1 · Mounika · resolved**

- **Symptom.** `pip install -r requirements.txt` ran for a very long time, then failed
  on a machine with no C compiler.
- **Cause.** We are on **Python 3.13**, and the obvious "stable" pins
  (`numpy==1.26.4`, `pandas==2.2.2`, `pyarrow==15`, `scipy==1.13.1`, `pyspark==3.5.1`)
  have **no cp313 wheels**. pip falls back to a source build without saying so.
- **Fix.** Repin to the floors that do have cp313 wheels; PySpark 4.0 is the first
  release supporting 3.13. Check before changing any pin:
  `pip download <pkg>==<ver> --no-deps --only-binary=:all:`
- **Cost.** ~3 hours across two machines. Recorded as D-012.

### P-03 · `--only-binary=:all:` cannot install PySpark
**Week 2 · Mounika · resolved**

- **Symptom.** `ERROR: Could not find a version that satisfies the requirement
  pyspark<4.1,>=4.0 (from versions: none)` — while the same flag worked for every
  other package.
- **Cause.** PySpark publishes an **sdist**, not a wheel. `--only-binary=:all:`
  refuses sdists, so it saw no installable version at all. The error says "no
  versions", which reads like the package does not exist.
- **Fix.** Install PySpark without the flag; keep it for everything else. It is a pure
  Python sdist, so there is no compiler involved.
- **Cost.** ~20 minutes. Directly contradicts the P-02 advice, which is exactly why
  both are written down.

### P-04 · Spark reads Parquet on Windows but cannot write it
**Week 1 · Mounika · resolved**

- **Symptom.** Reads fine; `df.write.parquet(...)` throws inside
  `RawLocalFileSystem.setPermission`.
- **Cause.** Hadoop's Windows file-system code calls `getWinUtilsPath`. Without
  `winutils.exe` and `hadoop.dll` present there is nothing to call.
- **Fix.** Put both in `C:\hadoop\bin` and set `HADOOP_HOME=C:\hadoop`.
- **Cost.** ~40 minutes. Note these are unsigned third-party binaries — standard
  practice for Spark on Windows, recorded in D-012 so everyone knows what is on their
  machine.

### P-05 · A virtualenv inside OneDrive thrashes sync
**Week 1 · Mounika · resolved**

- **Symptom.** The machine crawled and OneDrive sat permanently "syncing" after
  creating a venv.
- **Cause.** A venv containing PySpark is several GB of small files, and the repo
  folder was inside a synced directory.
- **Fix.** Virtualenv lives outside the synced folder, e.g.
  `%USERPROFILE%\venvs\control-tower`.
- **Cost.** ~30 minutes plus sync quota.

### P-06 · The cached Parquet came from a machine that no longer existed
**Week 2 · Mounika · resolved**

- **Symptom.** `data/processed/` was full and looked healthy, but nothing would run:
  no venv, no `pyspark`, and `java -version` exited with code 9 and printed nothing.
- **Cause.** The caches had been built on a different machine — visible in the
  absolute paths inside `_reconstruction_report.json`. The Oracle `javapath` stub was
  on `PATH` with no JRE behind it, so Java *looked* installed.
- **Fix.** Rebuild the environment from D-012 and re-run the whole pipeline. Stage 1
  reproduced 144,867 rows and Stage 2 all 26,369 legs, so the caches were genuine.
- **Cost.** ~1 hour. The lesson kept: `python -m src.common.check_env` before trusting
  anything on a machine you have not run on before.

---

## Data traps — the expensive ones

These are the problems that do **not** raise. Each was found by running code and
checking a number, never by reading the file.

### P-07 · Missing names are the literal string `nan`, and pandas and Spark disagree
**Week 1 · Lahari + Mounika · resolved**

- **Symptom.** The pandas profile reported 554 missing facility names. Spark reported
  **zero** on the same file.
- **Cause.** The publisher wrote the three-character text `nan`. pandas coerces that
  to `NaN` on read; Spark reads it as an ordinary string.
- **Fix.** Stage 1 converts textual null sentinels explicitly and reports the count per
  column.
- **Cost.** Would have put a facility in a city called "nan" on the India map and
  polluted every group-by on city. Recorded as D-010.
- **Carry:** any pandas number compared against a Spark number must account for this.

### P-08 · `segment_factor` carries a `-1` sentinel, not a ratio
**Week 1 · Lahari · resolved**

- **Symptom.** Segment-level ratios had a long negative tail that made no physical
  sense.
- **Cause.** On the 2,347 rows where `segment_osrm_time == 0`, the publisher wrote
  exactly `-1.0` instead of dividing by zero.
- **Fix.** Stage 1 recomputes the column and nulls it where OSRM time is zero, flagging
  those rows `is_zero_osrm_segment`.
- **Cost.** Caught before it reached a model. **A sentinel that looks like a number is
  worse than an infinity** — an infinity is loud, `-1` survives every mean, join and
  model fit without complaint.

### P-09 · One timestamp column is mixed precision
**Week 1 · Mounika · resolved**

- **Symptom.** Stage 1 threw part-way through parsing under Spark 4's ANSI mode.
- **Cause.** `cutoff_timestamp` is second-precision on 141,438 rows and microsecond on
  3,429 (2.37%). A fixed format fails on the minority.
- **Fix.** One explicit format with an optional fraction,
  `yyyy-MM-dd HH:mm:ss[.SSSSSS]`, for all four timestamp columns. Explicit rather than
  inferred, so a genuinely new shape still stops the pipeline. Recorded as D-013.
- **Cost.** ~1 hour, and it was ANSI mode throwing that made it visible at all — a
  lenient parser would have nulled 3,429 rows silently.

### P-10 · A backfill that was written for a problem that does not exist
**Week 1 · Mounika · resolved**

- **Symptom.** The facility-name backfill recovered **0** names, after the Week 1
  writeup had already claimed names were recoverable.
- **Cause.** The premise was never checked. All 554 missing names belong to 14 centre
  codes, and none of those codes carries a name on *any* row anywhere in the file.
- **Fix.** Keep the step (correct, free, and it reports the count so "0 recovered" is
  asserted rather than assumed), and recover the **state** from the PIN embedded in
  the centre code instead. City is left null rather than guessed. Recorded as D-011,
  superseding the original claim.
- **Cost.** A wrong sentence in a writeup, caught by running the code.

### P-11 · Leg totals came from the wrong row on 1,861 legs
**Week 2 · Mounika · resolved**

- **Symptom.** Stage 2 disagreed with the independent pandas oracle on 80 legs.
- **Cause.** Both implementations picked each leg's final row by `max(actual_time)`.
  On 1,861 legs (7.1%) the trailing segments add **zero** minutes, so several rows tie
  on `actual_time` while carrying different `osrm_time` and `osrm_distance`. The
  maximum does not identify a single row, and pandas `idxmax()` breaks the tie by
  taking the *first*.
- **Fix.** Stage 1 now emits `source_row_index` (asserted unique), and Stage 2 takes
  the genuinely last row by file order. Checked against the raw file: the last-row rule
  agreed with the true final scan 80/80 on the disputed legs, the oracle's rule 0/80.
  Recorded as D-014.
- **Cost.** ~3 hours. **No reported number moved** — the value was in learning that
  two independent implementations can agree on a headline and still both be wrong
  about which row they read.

---

## Method problems — the analysis was wrong, not the code

### P-12 · The blueprint's delay threshold labels 93.6% of legs "delayed"
**Week 1 · Lahari · resolved at the Week 2 sync (D-003)**

- **Symptom.** At `T = 1.25`, 24,687 of 26,369 legs are positive.
- **Cause.** The median leg already runs at **2.00×** plan. On this network a 25%
  overrun is the norm, not an exception.
- **Fix.** All three moves adopted (D-003): `T = 2.00` (49.6% / 50.4%), lead with
  regression on `gap_min` where there is no threshold at all, and report the
  majority-class baseline next to every accuracy figure, permanently.
- **Cost.** None — caught before any model was trained. It was left `OPEN` for a week
  precisely so it could not be resolved by accident, and closing it moved exactly one
  column: `is_delayed` on 11,594 of 26,369 legs. No other number in the Week 1 tables
  changed.
- **Risk if missed:** a classifier scoring 93.6% accuracy while carrying zero
  information, and a Week 6 Exception Agent that flags every shipment.
- **Carry:** `BLUEPRINT_THRESHOLD = 1.25` is now pinned as a literal in `src/ml/eda.py`
  rather than read from config. The Week 1 finding *is* the 1.25 number; had that
  sentence read `config.DELAY_THRESHOLD` it would have silently rewritten itself into a
  sentence about 2.00 the moment the decision landed, deleting the evidence for the
  decision it caused.

### P-13 · The obvious hub-dwell metric measures nothing
**Week 2 · Mounika · resolved**

- **Symptom.** Between-leg dwell — arrival at a hub to departure on the next leg — came
  out as **0 minutes on 85%** of all handoffs.
- **Cause.** The publisher closes one leg's OD window at the instant it opens the next,
  so on a continuous handoff there is structurally no gap. Every non-zero gap turned
  out to be a **chain break**: the next leg starts at a *different* facility (13.5% of
  handoffs), which is unobserved movement, not a shipment resting.
- **Fix.** Measure dwell *within* the leg (`start_scan_to_end_scan − actual_time`,
  median 49 min) and keep the between-leg gap under honest names —
  `chain_break_rate`, `median_unobserved_gap_min`. Recorded as D-015.
- **Cost.** ~2 hours of rework. Had the aggregation been written before the
  measurement, the hub leaderboard would have ranked facilities by how close they sit
  to a missing leg — and it would have looked completely plausible.

### P-14 · Two hub rankings that disagree, and no stated choice
**Week 2 · Mounika · resolved**

- **Symptom.** Ranking hubs by median dwell **minutes** and by dwell **share** gave top
  20s that overlap on only 8 hubs (rank correlation 0.49).
- **Cause.** Raw dwell minutes correlate 0.54 with the leg's wall clock, so that
  ranking is partly just "which hubs have long legs".
- **Fix.** Emit both; rank on the scale-free `dwell_share`; state the choice in D-015
  so the leaderboard is not silently one of two defensible answers.
- **Cost.** ~40 minutes, and it removes a question the viva panel would certainly ask.

---

### P-22 · A generated document kept its old conclusions after the data under it changed
**Week 2 · Lahari · resolved**

- **Symptom.** Closing D-018 moved the audit's support floor from 30 legs to 10 and
  `python -m src.ml.audit` regenerated the writeup cleanly, no error. The new top-20
  table was Kanpur, Phulpur → Allahabad, Malvan → Sawantwadi and three corridors into
  Muzaffarpur — and the paragraph directly beneath it still read *"Mumbai/Bhiwandi,
  Delhi/Gurgaon, intra-Hyderabad, intra-Kolkata — metro and metro-fringe corridors"*.
  The document contradicted its own table, in confident prose, on the page.
- **Cause.** The generator interpolates every *number* from the run and hard-codes every
  *characterisation*. That split is invisible while the data is stable and it is exactly
  backwards: the numbers were never going to be wrong, and the sentences describing them
  were the ones with no mechanism keeping them true. Three claims had gone stale at once
  — the geography of the top table, the "`Delhi -> Gurgaon` appears in both tables"
  example, and the corridor count in §1 that still said 99.
- **Fix.** Every claim about the data is now computed. `_places()` counts the states a
  ranked table actually sits in, `_geography_shift()` compares the decided floor's table
  against the old one, `_both_directions_note()` finds a city pair that is genuinely in
  both tables instead of naming a remembered one, and `_faster_cluster_note()` counts
  the largest origin rather than asserting it. Where a sentence cannot be computed it
  must be about the *method*, which does not change when the data does.
- **Cost.** ~40 minutes, and it produced the best finding of the week as a side effect:
  once the geography was measured rather than remembered, the two floors turned out to
  share **no corridor at all** in their top-20s, and the 30-leg metro reading and the
  10-leg district-feeder reading are two different claims (D-018). Nobody would have
  noticed that from prose written once and carried forward.
- **Carry:** a generated document is only as trustworthy as its least-computed sentence.
  When a run's inputs change, read the prose, not just the tables.

### P-23 · A city-alias list that exists in two places, and drifted
**Week 2 · Lahari + Krishna · resolved, with the root cause carried to Week 3**

- **Symptom.** The audit's prose reported the corridors that are in both the bottleneck
  and the faster tables as `BLR -> Bengaluru`, `Bengaluru -> BLR`, `Bengaluru ->
  Bengaluru` — three spellings of one city pair. Separately, the count of faster
  corridors leaving Bengaluru read 17 when the real figure was 35: the code compared
  `source_city == "Bengaluru"` and the file also spells it `Bangalore` (48 rows) and
  `BLR` (5).
- **Cause.** Two alias tables. `src/dashboard/reference/india_city_coords.csv` carries
  the map's aliases, and the audit had none at all until it needed to count cities. The
  10-leg floor pulled in `BLR`, `BOM`, `CCU` and `GZB`, which were in neither.
- **Fix.** `CITY_ALIASES` in `src/ml/audit.py` for the prose counts, the four missing
  codes added to the coordinates table for the map, and both marked in comments as
  duplicates of each other.
- **Cost.** ~30 minutes. **The fix is a patch, not a solution, and it is written down as
  one:** two lists holding the same truth will drift again, and the next drift will show
  up as a silently missing dot rather than an obviously wrong sentence. Merging them
  needs a shared reference table that neither the audit nor the dashboard owns — carried
  into Week 3 with both owners named rather than left as a comment nobody reads. It is
  the same trap as D-002's warning about city names, arriving in the tooling instead of
  the data.

### P-20 · A map of the worst corridors that could not show the worst corridors
**Week 2 · Krishna · resolved**

- **Symptom.** The India map was built to plan — corridors as great-circle lines
  coloured by delay severity — and rendered a mostly empty map of India whose only
  visible lines were the long *fast* corridors.
- **Cause.** 19 of the 34 bottlenecks start and end in the same city and 33 of 34 span
  under 50 km; the median span is **0 km**. As lines at national zoom the worst
  corridors in the network are marks of zero length. Lahari's audit had already said
  the table was short-haul and urban — the form contradicted a finding that was
  already written down.
- **Fix.** Map cities, not routes: audited corridors roll up to the city they leave
  from, bubble size is corridor count, colour is the worst effect size, and a line is
  drawn only for corridors that genuinely cross a distance.
- **Cost.** ~45 minutes and one rebuild. Cheap because it was caught by rendering the
  thing and looking at it, which is worth doing before any chart is called done.

---

### P-21 · 27 of 99 audited corridors were silently missing from the map
**Week 2 · Krishna · resolved**

- **Symptom.** Only 72 of the 99 audited corridors could be placed on the map. Nothing
  errored — an unplaceable corridor is simply a dot that never appears.
- **Cause.** Two failures behind one symptom. Ahmedabad is written `AMD`, `Amd` and
  `Amdavad`, and Gurugram `GGN`, none of which were in the coordinate table. Separately,
  `city_of()` split facility names on `_` only, so the nine facilities named
  `Mumbai Hub (Maharashtra)` — city separated by a space — returned the whole string.
  Those nine are the same rows Lahari's audit reported as **19 null city fields**: one
  bug surfacing in two places.
- **Fix.** 11 alias rows added to `india_city_coords.csv`; `city_of()` now splits on
  either separator. The map re-derives cities from the raw facility names rather than
  reading the audit's city columns, so it does not inherit the nulls. **99 of 99 now
  resolve**, and the page reports coverage and names anything unmapped so this fails
  loudly next time.
- **Cost.** ~30 minutes. The silent half is the expensive part: a missing dot looks
  exactly like a corridor that was never bad.

---

### P-24 · Widening the audit silently emptied two thirds of the map
**Week 2 · Krishna · resolved**

- **Symptom.** D-018 lowered the support floor from 30 legs to 10 and the audited set
  went from 99 corridors to 1,130. The map page ran without a single error and reported
  a healthy-looking picture. It was drawing **101 of the 273 bottlenecks.** Nothing was
  red, nothing was logged, and the missing 172 looked exactly like corridors that had
  never been bad.
- **Cause.** Placement went through a hand-maintained table of 59 city names. That table
  had been built against the 30-leg audited set, which was metro-heavy — Mumbai,
  Bhiwandi, Delhi, Hyderabad. The 10-leg set reaches **139 towns it had never heard
  of**, with a flat one-corridor-each tail: Nowda, Ragunthgnj, Kaptanganj, Manjhaul.
  There was no top-20 of missing cities to add; the tail *was* the gap.
- **Fix.** Placement moved onto the centre code, which carries a PIN — the same reason
  D-002 keys corridors on codes rather than names. `centre_coords.csv` is generated
  once from GeoNames postal data and places 1,605 of 1,657 centres; the hand table
  stays as the fallback for the 52 whose PIN is `000000`. **Coverage went 101 → 273 of
  273 bottlenecks, and 1,130 of 1,130 corridors.** Recorded as D-019.
- **Cost.** ~2 hours, and it was only found by measuring coverage after the decision
  rather than assuming the page followed the CSV. It *did* follow the CSV — every
  corridor in it was read, and two thirds were then dropped on the floor.
- **Carry, and this is the general one:** **a decision made in one member's area
  silently changed the correctness of another's.** D-018 was argued entirely on
  statistics — support, power, effect size — and every argument was sound. Its largest
  practical effect was on a coordinate lookup nobody was thinking about. The Week 2
  writeup had even predicted the *colour ramp* would need attention at the wider range
  and said nothing about placement, because the ramp was the visible half. When a
  decision changes the shape of a shared artefact, the checklist is every consumer of
  that artefact, not the ones that come to mind.

### P-25 · A model with the better RMSE and R2 had the worse MAE
**Week 3 · Lahari · resolved**

- **Symptom.** The Week 3 linear regression beat OSRM comfortably and looked like a
  clean win on RMSE (96.8 vs the corridor-mean baseline's 101.7) and R2 (0.811 vs
  0.791). Its MAE was *worse* — 41.2 min against the corridor mean's 36.1 — on the same
  test split. Two metrics, two different answers to "which model is better."
- **Cause.** Not a bug in either number. OLS minimises squared error, which is exactly
  what RMSE and R2 measure and not what MAE measures. The audited network has corridors
  running up to 13.9× its own typical overrun (D-018) — genuine heavy-tailed outliers —
  and a single global coefficient set can trade a little bias on the ordinary legs in
  between for less squared error on the extreme few. The corridor mean cannot make that
  trade: each corridor's prediction comes from its own local average, so one extreme
  corridor's history never leaks bias into a calmer corridor sharing a coefficient.
- **Fix.** Not a model change — a stated choice. D-022 fixes MAE as the metric Week 4
  is ranked on, since it is the one `benchmarks/ml_results.md` was already reporting and
  the one "average error in minutes" plainly means. RMSE and R2 stay in every model's
  row as diagnostics, specifically because their disagreement with MAE is itself
  informative, not because either could quietly become the tiebreaker.
- **Cost.** ~20 minutes once the numbers were actually compared rather than skimmed —
  the RMSE and R2 columns alone read as an unambiguous win, and would have if MAE had
  not been checked against the same table.
- **Carry:** whichever metric a report leads with has to be the one models are picked
  on, checked explicitly against the alternatives rather than assumed to agree with
  them — a model can be a genuine improvement by one honest metric and a regression by
  another, on the same held-out legs.

## Process and tooling

### P-15 · The hub leaderboard started at rank 27
**Week 2 · Mounika · resolved**

- **Symptom.** The friction leaderboard was ordered correctly but numbered 27, 53, 62 …
  with no rank 1 anywhere.
- **Cause.** `row_number()` ran over all 1,657 hubs and the rank was nulled for
  unsupported hubs *afterwards*, so those hubs still consumed rank numbers.
- **Fix.** Rank inside `partitionBy("has_support")`, and **assert** the result is a
  dense `1..N` so the run fails instead of publishing a plausible-looking table.
- **Cost.** ~20 minutes, caught by reading the output CSV rather than the code.

### P-16 · A test suite that failed against correct code
**Week 2 · Mounika · resolved**

- **Symptom.** 22 of 23 mock-TMS tests failed with `KeyError: 'order_ref'`.
- **Cause.** `.env` on that machine sets `TMS_API_KEY`, which switches the API's auth
  on. The tests were not sending the header, so every response was a 401. The
  application was right and the tests were wrong.
- **Fix.** The test client sends the key when one is configured, and three new tests
  control `TMS_API_KEY` themselves so auth behaviour is asserted rather than inherited
  from whatever a developer happens to have in `.env`.
- **Cost.** ~15 minutes. Worth remembering that a wall of red is not proof the code is
  broken.

### P-17 · A `Window` at module level cannot be imported
**Week 2 · Mounika · resolved**

- **Symptom.** `python -m src.pipeline.hubs` failed at import with
  `SESSION_OR_CONTEXT_NOT_EXISTS`.
- **Cause.** A module-level `Window.partitionBy(...)` constant needs a live
  SparkContext, which does not exist at import time.
- **Fix.** Build the window inside a function. This also matters for the dashboard,
  which imports pipeline modules without ever starting Spark (D-009).
- **Cost.** ~5 minutes, but it would have broken the dashboard rather than the stage.

### P-18 · The linter objects to how FastAPI is written
**Week 2 · Mounika · resolved**

- **Symptom.** `ruff` flagged 12 × `B008 Do not perform function call in argument
  defaults` across the TMS routes.
- **Cause.** `Depends(...)` and `Query(...)` in argument defaults *is* FastAPI's
  dependency-injection mechanism. B008 targets the general Python footgun of a mutable
  default evaluated once at import; here that single evaluation is the intended
  behaviour.
- **Fix.** A file-scoped `# ruff: noqa: B008` with a comment explaining why, rather
  than restructuring working code to satisfy a rule that does not apply to it.
- **Cost.** ~10 minutes. The general point: suppress a rule *with a reason written
  down*, or fix the code — never silence a linter blindly.

### P-19 · One member's week split across two documents and two branches
**Week 2 · all · resolved**

- **Symptom.** Week 1 produced two separate docs for Lahari
  (`W1_lahari_data_dictionary.md` and `W1_lahari_eda.md`), and Week 2 opened two
  branches for Krishna. Both split one person's week across two places.
- **Cause.** Each generator script owned a whole document, and side work got its own
  branch instead of going on the week's branch.
- **Fix.** `src/common/docs.py` lets several scripts own delimited **sections** of one
  document, so re-running a generator updates its section and leaves the rest alone.
  Krishna's two Week 2 branches were consolidated onto the branch named in the
  GIT_RULES §5 table. The rule is now explicit in `CONTRIBUTING.md` §7: **one branch
  and one document per member per week.**
- **Cost.** ~1 hour of tidying, and it stays fixed rather than needing re-tidying every
  week.

---

## Still open

Week 2's two blocking problems (P-12 and the support floor) are both closed above.

| # | Problem | Owner | Blocks |
|---|---|---|---|
| P-23 | One city-alias truth in two files — the patch holds, the duplication does not. Lower urgency since D-019: the map no longer places by name, so the lists now only affect labels and the 52-centre fallback | Lahari + Krishna | label drift; a fallback gap |
| — | Null `source_city` / `dest_city` in `clean_v1` on `Mumbai Hub (Maharashtra)`-shaped names. The map works around it; the cache still carries it, and fixing at source is a `clean_v2` under D-016 | Mounika | any Week 3 feature keyed on city |
| — | 13.5% of in-trip handoffs are chain breaks (D-015) | Mounika | Week 5 stream replay |
| — | JDK 17 + winutils on Lahari's machine | Lahari | her local Spark runs |
| — | No dashboard screenshots captured for W1 or W2 (GIT_RULES §3) | Krishna | Week 8 demo assets |
