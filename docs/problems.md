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

### P-27 · A seeded "invoice error" printed a negative total
**Week 3 · Lahari, reviewing Krishna's D-021 · resolved**

- **Symptom.** `total_mismatch` (D-021's seeded-error taxonomy) picked a delta from a
  fixed `+/-50..500` range and added it to the invoice's `total_amount`. Nothing raised.
  Checking the actual 120-record run against its own manifest, one of the five
  `total_mismatch` invoices (`w3_00059`, a small Carting shipment: freight 230.00 +
  other 29.07 = 259.07) printed `total_amount = -116.40`.
- **Cause.** The delta's range was picked to look reasonable against a typical
  mid-sized invoice and never checked against the smallest ones. This network's
  Carting shipments run as low as ~₹30 in `freight_charge` (Week 1's route-type split
  already showed Carting is proportionally the worse-behaved route type); a delta of
  up to 500 absolute rupees dwarfs a total that size.
- **Fix.** The delta is now a percentage of the invoice's own `total_amount`
  (5-30%, either sign) rather than a fixed rupee amount, so it scales with the invoice
  it lands on and cannot cross zero at this magnitude. Same two `rng` calls as the
  version it replaces (a `choice` then a `uniform`), so which records get which seeded
  error kind — the part everything else in the corpus depends on being reproducible —
  is unchanged; only the `total_mismatch` records' printed totals moved.
- **Cost.** ~20 minutes once the manifest was actually checked against the label JSON
  rather than trusted because the generator ran cleanly. **A negative total is the
  wrong kind of "wrong"** for what this error is supposed to test: rule 5 asks an
  extraction agent to report an arithmetic mismatch exactly as printed rather than
  reconcile it, and a mismatch has to look like a plausible clerical error for that to
  be a meaningful test — a negative grand total reads as an obviously broken document
  before any extraction is attempted, on this document alone giving away the exact
  thing the corpus is supposed to be testing whether an agent can catch quietly.

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

### P-25 · The natural corridor-history clock leaks the future
**Week 3 · Mounika · resolved**

- **Symptom.** The obvious first draft of the Stage 4 feature pipeline ordered each
  corridor's history by `od_start_time` — a leg "knows about" every corridor leg that
  had already *departed* by the time it was created. It runs, produces plausible
  numbers, and raises nothing.
- **Cause.** Departure is not when a leg's outcome becomes knowable; *arrival*
  (`od_end_time`) is, because the duration itself is not known until the leg lands.
  Measured directly rather than argued: on the naive clock, **46.4% of legs** are
  created and dispatched in the same second, so a leg reads its own departure as
  already-known history; a further **8.4%** are handed the duration of a different
  journey that had departed but not yet landed. **48.6% of the 26,369-leg table is
  affected either way**, and the direction of the error only helps the model — a leg
  that has partly seen its own answer scores *better*, not worse, so nothing about the
  output would have looked wrong.
- **Fix.** History is ordered on `od_end_time` instead: every leg emits a *fact* when
  it finishes and a *query* when it is created, and a leg only ever sees facts that
  landed before its own query. Verified with a hand-built adversarial case
  (`tests/test_features.py::test_in_flight_leg_is_excluded`) — a leg still on the road
  at query time must contribute nothing — and by an independent recomputation of
  `corr_n_prior` on a 200-row sample with the predicate spelled out longhand
  (`od_end_time <= trip_creation_time`), which matched the window's output exactly.
  Recorded as D-020.
- **Cost.** ~1.5 hours, entirely spent because the naive version *looked* finished — it
  ran clean, the coverage numbers were plausible, and nothing about a leakage bug looks
  different from a correct feature until it is checked against an independent
  computation. The 46.4%/8.4% numbers now live in the feature report so the trap stays
  visible even after the fix, rather than disappearing the moment the code is right.

### P-26 · The obvious noise pipeline needs a system binary nobody has installed
**Week 3 · Krishna · resolved**

- **Symptom.** The natural way to add scan artefacts — render the PDF, rasterise it
  with `pdf2image`, degrade the raster — throws `PDFInfoNotInstalledError` before it
  ever reaches the degradation step.
- **Cause.** `pdf2image` shells out to `poppler`'s `pdftoppm`, a system binary that
  `pip install` does not provide and that none of the three machines this project runs
  on has — the same class of "the pip package is not the whole dependency" problem
  D-012 spent an afternoon on for Spark's `winutils.exe`.
- **Fix.** `noise.py` draws the same field list `templates.py` prints
  (`templates.field_rows`, one shared source per D-021's write-up) straight onto a
  Pillow canvas with `ImageFont.load_default(size=...)` rather than any installed
  font, then degrades that raster directly. Two independent renderers over one shared
  field list, not a render-then-rasterise pipeline — reproducible on any of the three
  machines with only what `requirements.txt` already installs.
- **Cost.** ~20 minutes, caught before writing a single document rather than after
  building 120 of them on a machine that happened to have poppler. `pdf2image` and
  `pytesseract` stay in `requirements.txt` for Week 4, when OCR runs against these
  images for real.

### P-28 · A model with the better RMSE and R2 had the worse MAE
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
- **Fix.** Not a model change — a stated choice. D-024 fixes MAE as the metric Week 4
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

### P-29 · The delay classifier would not converge until the features were scaled
**Week 3 · Lahari · resolved**

- **Symptom.** `LogisticRegression().fit(train[FEATURES], train["is_delayed"])` raised
  `ConvergenceWarning: lbfgs failed to converge after 1000 iteration(s)`, and raising
  `max_iter` further did not clear it.
- **Cause.** `FEATURES` was built for OLS, which has a closed-form solution and never
  cared about feature scale. Logistic regression's `lbfgs` solver is gradient-based and
  does — `planned_min` and `planned_km` run into the hundreds while the `*_is_cold`
  indicators are 0/1, so the loss surface is badly conditioned along some coordinates
  and barely moves along others.
- **Fix.** `StandardScaler` in a pipeline ahead of `LogisticRegression`, exactly the fix
  sklearn's own warning links to — not a sign the fit itself was wrong, and not a reason
  to touch `FEATURES` (the linear regressor still uses it unscaled, correctly).
- **Cost.** ~10 minutes. Worth remembering for Week 4: any gradient-based MLlib model
  reading the same feature table needs the same scaling step; the tree-based
  Random Forest and GBT it is actually built for do not.

### P-34 · The official Tesseract download mirror is unreachable from this machine
**Week 4 · Krishna · resolved**

- **Symptom.** `README.md`'s prerequisite table has listed Tesseract since Week 1
  (`check_env`'s Optional check has warned `FileNotFoundError` every week since), and
  the obvious next step — the UB-Mannheim installer linked from Tesseract's own wiki,
  `digi.bib.uni-mannheim.de/tesseract/...` — would not connect at all: not a slow
  download, a connection failure, while every other host tried (github.com, pypi.org,
  sourceforge.net, huggingface.co) resolved fine.
- **Cause.** That one host, specifically, appears to be unreachable from this network
  — not a Tesseract problem, a that-domain problem. No proxy or DNS override was
  available to fix the host itself, and the mirror is the only place UB-Mannheim
  ships the installer from directly.
- **Fix.** Tesseract's own GitHub releases (`tesseract-ocr/tesseract`, tag `5.5.3`)
  mirror the identical installer as a release asset, authored by the same maintainer
  who builds the UB-Mannheim installer (`stweil`) — a legitimate alternate host for
  the same official artefact, not a third-party rebuild. NSIS installers can be
  extracted directly with 7-Zip without running them (`7z x installer.exe`), which
  gave `tesseract.exe` and its DLLs without ever executing an installer or needing
  admin/UAC — the same portable-extraction instinct D-012 already used for the JDK
  zip. The installer itself does not bundle language data (it downloads `eng.
  traineddata` at install time via an NSIS plugin); that file was fetched separately
  from `tesseract-ocr/tessdata_fast` on GitHub. Both live outside the repo at
  `C:\Users\kuchu\tesseract-ocr\`, on `PATH`, with `TESSDATA_PREFIX` set at User scope
  — mirroring exactly how `JAVA_HOME`/`HADOOP_HOME` are documented in
  `spark-run-environment`, not committed anywhere.
- **Cost.** ~25 minutes, almost all of it a slow download of a 26.6 MB file. Worth
  remembering: a single unreachable domain looks exactly like "the tool doesn't have
  a Windows build" until every other host is checked and turns out fine.

### P-35 · The Week 1 default Gemini model was retired mid-project
**Week 4 · Krishna · resolved**

- **Symptom.** The Document Intelligence Agent's first real LLM call failed with
  `404 NOT_FOUND: This model models/gemini-2.0-flash is no longer available`, quoting
  its own replacement name in the error.
- **Cause.** `gemini-2.0-flash` was pinned as the default in `.env.example` and
  `src.agents.llm.DEFAULT_MODELS` back in Week 1 and never revisited — every agent
  since (`hello_agent`, the doc corpus generator's LLM-free path) either did not call
  the model or was not exercised again in the months since. A free-tier model name is
  not a fact that stays true for the length of an 8-week project; D-007's single LLM
  construction site meant this was one string to fix, not five.
- **Fix.** `DEFAULT_MODELS["gemini"]` and both `.env`/`.env.example` moved to
  `gemini-3.6-flash`, the name the 404 itself named. Separately, and only visible
  once the model call actually succeeded: `response.content` came back as a **list**
  of content-block dicts rather than a plain string — a shape difference between
  Gemini's newer responses and what `hello_agent`'s original smoke test (a short,
  simple prompt) happened to see. `document_agent._response_text()` flattens either
  shape once, the same "one call site" reasoning D-007 already applies to construction
  rather than to response parsing.
- **Cost.** ~20 minutes. Worth carrying to Week 7's evaluation runs and Week 6's
  agent-eval: a model pinned once at the start of an agentic project is exactly the
  kind of dependency that goes stale silently until the code that calls it actually
  runs again.

### P-36 · The free-tier LLM quota is 20 requests *per day*, not per minute
**Week 4 · Krishna · resolved (accepted as a documented constraint, not a bug)**

- **Symptom.** A 40-document smoke run (`--count 20`, 20 consignments × BOL+invoice)
  processed the first 19 documents cleanly, then every call from the 20th on failed
  `429 RESOURCE_EXHAUSTED` — with escalating suggested retry delays (14s, 36s, 58s...)
  that occasionally let a later call sneak through, landing at 22/40 succeeding rather
  than a clean 19/40.
- **Cause.** The error body names the exact quota:
  `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue: 20` — a **daily**
  cap per project per model on `gemini-3.6-flash`'s free tier, not the per-minute rate
  limit `with_fallback`'s retry-and-backoff design (D-007) was built to survive. The
  Week 2 sync's open-items table already named exactly this risk ("second LLM key... —
  blocks Week 7 eval runs") — it simply arrived at Week 4 instead of Week 7, the moment
  an agent that actually calls the model at any volume first existed.
- **Fix.** Not a retry loop — a daily cap does not lift by waiting seconds. The
  per-document `try/except` already in `run_corpus` (not a single all-or-nothing call)
  meant the quota wall did not corrupt the run: it produced 22 real predictions and 18
  documents each recording the `RESOURCE_EXHAUSTED` reason in their own `error` field,
  in the one predictions file. Decided in D-032: the evaluation harness (Lahari, D5)
  scores whatever the file actually contains and reports coverage beside accuracy,
  rather than the agent pretending a clean run happened.
- **Cost.** ~10 minutes to read the error body all the way to the quota name, plus the
  ~18 minutes the run itself spent retrying against a wall that was not going to move.
  The real cost is forward-looking: a full 120-document corpus run needs a second
  provider key or several days, not a code fix.

### P-37 · Every python invocation on this machine silently spawns a second interpreter
**Week 4 · Krishna · resolved (worked around; root cause is machine-level, not this repo's)**

- **Symptom.** Launching the D3-D4 prompt-comparison batch produced two live
  `python.exe` processes for one command — one from this project's venv, a second
  from an unrelated system-wide Python 3.12 install, both running the identical
  `-m src.agents.document_agent ...` argv, the second a direct child of the first.
  Killing what looked like a stray duplicate and relaunching reproduced the same
  pair again. A trivial control command (`python -c "import time; time.sleep(6)"`,
  no project code, no imports beyond the standard library) doubled the exact same
  way, proving this has nothing to do with `document_agent.py`, `pytesseract`, or
  `langchain_google_genai`.
- **Cause.** Not identified — some machine-level hook (a `sitecustomize.py`/`.pth`
  file, or third-party monitoring software) that every `python.exe` on this machine
  runs at interpreter startup, re-executing the same command under a second
  interpreter as a child process. Out of scope to chase down further here: it is a
  property of this machine, not of anything in `requirements.txt` or this repo's
  code, and every long batch run this project has actually needed (Lahari's model
  training, Mounika's retrain script, this agent's batch runs) has completed
  correctly despite it.
- **Fix.** Checked, rather than assumed harmless: the log each run produces is a
  single clean sequence with no duplicated or interleaved lines, meaning only one of
  the two processes does real work while the other sits inert — a genuine risk this
  project cannot fully rule out is that a *concurrency-sensitive* future task (Week
  5's Kafka producer, anything that writes to a shared file without one process's
  lock) could see actual doubled work rather than a harmless spawn. Documented so
  the next long-running background command started on this machine is checked the
  same way (`Get-CimInstance Win32_Process` for a second matching command line)
  rather than assumed single-process.
- **Cost.** ~15 minutes and one wasted LLM quota call (3 documents extracted then
  killed, mid-write, before `run_corpus` reached its single end-of-run
  `out_json.write_text` — those 3 results are unrecoverable, though the quota spend
  itself is the only real cost since nothing downstream ever read them).

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
