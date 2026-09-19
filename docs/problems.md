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

### P-30 · Random Forest's first CV run exhausted the driver heap
**Week 4 · Lahari · resolved**

- **Symptom.** `python -m src.ml.models` died mid-`RandomForestRegressor` fit with
  `java.lang.OutOfMemoryError: Java heap space` inside `RandomForest.findBestSplits`,
  during the first hyperparameter combination of the very first fold.
- **Cause.** Two compounding choices, not one. `maxDepth=10` was in the first grid —
  `findBestSplits` collects per-node, per-feature, per-bin split statistics on the
  driver, and node count grows with depth roughly like 2^depth, so depth 10 is a real
  memory step up from depth 5-8. That alone might have fit; `CrossValidator(...,
  parallelism=2)` then ran two such fits concurrently in the same local[*] JVM, on a
  machine with only ~5.6 GB free of 16 GB total alongside a normal dev session
  (browser, IDE). Neither choice was wrong in isolation on a machine with more
  headroom; together, on this one, they were.
- **Fix.** `maxDepth` capped at 8 in both grids, `CrossValidator(parallelism=1)` so
  only one candidate model fits at a time. Depth 8 still comfortably outgrows the
  linear model's fixed global coefficients (D-026), and sequential CV cost this run
  about 25-30 minutes wall clock against a faster but heap-exhausting parallel one that
  never finished at all.
- **Cost.** ~15 minutes to read the stack trace and identify both contributing
  factors, then one clean run to confirm the fix. Worth carrying to Week 5's streaming
  job and Week 7's scale appendix: this machine's real memory headroom during a normal
  work session is well under Spark's configured driver memory, not the 16 GB the
  spec sheet says.

### P-31 · `command | tee logfile` reported success for a job that had crashed
**Week 4 · Lahari · resolved**

- **Symptom.** The first, OOM-killing run of `python -m src.ml.models` (P-30) was
  launched as `python -m src.ml.models | tee run.log`, and the tool that ran it
  reported exit code 0 — read at a glance, a green run that had in fact thrown a
  `Py4JJavaError` and a Python traceback partway through, both sitting in `run.log`
  the exit code claimed was clean.
- **Cause.** In a POSIX pipeline, `$?` (and this project's tooling reads the same
  signal) is the *last* command's exit status by default — `tee`'s, which succeeds
  as long as it can write the file, regardless of what the process feeding it did.
  A crashed left-hand command is invisible to anyone checking only the pipeline's
  reported result.
- **Fix.** Redirect to a file directly (`command > log 2>&1`) rather than piping
  through `tee`, so the shell's own exit status is the command's; where a pipeline is
  unavoidable, `set -o pipefail` (or bash's `${PIPESTATUS[0]}`) recovers the real
  status. Caught here only because the output files were checked by hand against what
  the run should have produced, not because anything flagged the mismatch — the same
  "verify by running and checking, not by a green light" instinct `CONTRIBUTING.md` §10
  already asks for, extended to the exit code itself.
- **Cost.** No wrong number reached a report — this was caught before anything
  downstream read the (nonexistent) output of the crashed run. Worth carrying forward:
  a reported success is only as trustworthy as what it is actually measuring.

### P-32 · Calling Lahari's entry point mid-week needs her branch's file, not just her function signature
**Week 4 · Mounika · resolved (a testing-process finding, not a code defect)**

- **Symptom.** Validating `src.automation.retrain` locally (before either branch had
  merged to `dev`) by temporarily placing a copy of `src/ml/models.py` on this branch
  ran the full Random Forest + GBT fit successfully, then crashed on the very last
  step: `ValueError: Unknown section 'beat-osrm'. Add it to SECTION_ORDER...` from
  `src/common/docs.py`.
- **Cause.** `models.run()` calls `docs.write_section(..., "beat-osrm", ...)`, and
  `"beat-osrm"` was added to the shared `SECTION_ORDER` list as part of *Lahari's*
  commit — which, on this branch, does not exist, because only her `models.py` was
  copied over for the test, not the one-line `docs.py` change that goes with it. A
  genuine `git merge` would never hit this: both files land on `dev` together when
  her PR merges. This is an artefact of validating one branch's entry point against
  another still-unmerged branch's code, on one machine, before the week's gate.
- **Fix.** Not a change to either branch. The already-computed `w4_model_report.json`
  (written to disk *before* the crashed `docs.write_section` call — model artefacts
  and CSVs are saved earlier in `run()`) was replayed through `promote_challenger()`
  directly, rather than re-running the ~40-minute training a second time. Champion
  promotion and the history log both completed correctly against that report.
- **Cost.** ~5 minutes to read the traceback and recognise it as a local-testing
  artefact rather than a bug in either branch's committed code. Worth carrying to
  Week 5 and beyond: an entry point that writes to a *shared* file
  (`src/common/docs.py`'s `SECTION_ORDER`) couples whoever calls it to whoever last
  edited that shared list, in a way a function signature alone does not reveal.

### P-33 · A stale `JAVA_HOME` from a different machine, masked by variable precedence
**Week 4 · Mounika · resolved, found while writing D-030's preflight check**

- **Symptom.** Writing `retrain.preflight()` (D-030) and testing it against a
  deliberately broken `JAVA_HOME` turned up a second, real problem: popping
  `JAVA_HOME` from the process environment and letting `config.py`'s `load_dotenv()`
  fill the gap surfaced `JAVA_HOME=C:\Users\HP\jdks\jdk-17.0.20+8` — a path that does
  not exist on this machine at all.
- **Cause.** This machine's local `.env` (gitignored, never shared, never the same
  file across the three members' machines) still carried the *other* machine's JDK
  path — `spark-run-environment`'s own note that "the earlier Week 1–2 work was built
  on a different machine (`C:\Users\HP\...`)" was about the Parquet caches, but the
  same stale value had also been sitting unnoticed in `.env` since around then. It
  never caused a visible failure because the correct value already sits in this
  machine's User-scope environment variable, set outside the repo, and
  `python-dotenv`'s `load_dotenv()` does not override a variable that already exists
  in `os.environ` — so every real run of every stage this whole project has used the
  right value, by precedence, while the wrong one sat one layer underneath it.
- **Fix.** Corrected `.env`'s `JAVA_HOME` to this machine's real path. Not committed —
  `.env` is gitignored by design (GIT_RULES §7) — so this is a local fix, not a repo
  change, and each of the three members' own `.env` needs checking on its own merits
  rather than assumed correct because Spark has always worked so far.
- **Cost.** ~5 minutes once `preflight()`'s own test surfaced it. **The general point
  the fix doesn't cover:** environment-variable precedence means a wrong value in one
  layer can sit silently underneath a right value in another for months, invisible
  until something removes the layer that was covering for it — the same shape of trap
  as P-06's Parquet cache built on a machine that no longer existed, just one layer
  further down the stack.

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

### P-38 · Mixed-precision timestamps broke the replay schedule — the same trap as P-09, two layers up
**Week 5 · Mounika · resolved**

- **Symptom.** The first real producer run died in `compress_schedule` with
  `ValueError: time data "2018-09-12T00:23:34" doesn't match format
  "%Y-%m-%dT%H:%M:%S.%f"`. Event *building* and schema *validation* had both already
  passed on all 600 events; only the scheduling step threw.
- **Cause.** `pd.to_datetime` on a list infers one format from the first element. A
  **query** event's `event_time` is `trip_creation_time.isoformat()`, which keeps
  microseconds; a **fact** event's is `od_start_time + timedelta(minutes=actual_time)`,
  which lands on a whole second whenever the leg's duration is a whole number of
  minutes — and on this data it very often is. First element had microseconds,
  so every whole-second fact event failed to parse.
- **Fix.** `pd.to_datetime(..., format="ISO8601")`, which accepts both shapes.
  `tests/test_producer.py::test_schedule_handles_mixed_precision_timestamps` is the
  regression guard, built from the two literal timestamps that actually collided.
- **Cost.** ~10 minutes. **This is P-09 again** — Week 1's `cutoff_timestamp`
  being second-precision on 141,438 rows and microsecond on 3,429 — and it
  arrived by a completely different route: not from the publisher's file this time,
  but from *our own* two event builders, one formatting a stored timestamp and the
  other formatting a computed one. The carry from P-09 was "one explicit format,
  never an inferred one"; that rule was applied to the Spark reader in Stage 1 and
  never to a pandas parse, so the second half of the codebase relearned it. Worth
  stating as a rule rather than a fix: **anywhere a timestamp is parsed from a
  collection, name the format.**

### P-39 · Spark counts days from Sunday, Python from Monday, and nothing raises
**Week 5 · Lahari · resolved**

- **Symptom.** The stream-equals-batch test's second check came back
  **0 agreements out of 500**. Predictions were bit-identical, but the temporal
  features a streaming job would recompute from `event_time` disagreed with the ones
  the event carries on *every single row*.
- **Cause.** Not a bug in either computation — two different, both-correct
  conventions for the same idea. Stage 4 builds the feature with Spark's
  `F.dayofweek`, which is **Sunday = 1** through Saturday = 7. A Python consumer
  reaching for `datetime.weekday()` gets **Monday = 0** through Sunday = 6. For
  2018-09-12, a Wednesday, that is **4 against 2**. The model was trained on the
  Spark encoding, so a consumer using the Python one would feed it a number on a
  different scale for every event.
- **Fix.** One shared `src.streaming.schema.temporal_features()` that both sides
  import, using `isoweekday() % 7 + 1` to reproduce Spark's encoding exactly. The
  streaming job (D3-D4) imports it rather than re-deriving day-of-week, which is the
  same "two lists holding one truth" trap P-23 already cost this project once
  — and this time the shared helper exists *before* the second consumer is
  written, not after it drifted. `tests/test_stream_validation.py` pins all four
  weekday values against Spark's convention.
- **Cost.** ~20 minutes, and it was free in the sense that mattered: **the test was
  written before the streaming job, so the trap was found before anything could fall
  into it.** Had the job been built first, this would have surfaced as a model
  quietly scoring every streamed event on a wrong day-of-week — no exception, no
  null, no row count out of place, and a per-corridor error small enough to look like
  ordinary model noise. `created_is_weekend` is genuinely convention-independent
  (both readings mean Saturday-or-Sunday), which is exactly why only one of the three
  fields disagreed and why a spot-check of the other two would have concluded
  everything was fine.
- **Carry:** *any* feature the batch pipeline computes with a Spark builtin and a
  consumer recomputes in Python needs one shared implementation, not two that agree
  on a test date. `created_hour` happens to agree in both; that is luck, not design.

### P-40 · `src.tms.seed` cannot do the one thing its docstring promises
**Week 5 · found by Krishna, owned by Mounika · open (worked around)**

- **Symptom.** `python -m src.tms.seed`, run to prepare the TMS for the Order Entry
  Agent, died with `sqlalchemy.exc.IntegrityError: FOREIGN KEY constraint failed` on
  `DELETE FROM facility`.
- **Cause.** `seed()` promises in its own docstring that *"orders and shipments survive
  unless `reset`"*, and then calls `session.exec(delete(Facility))` unconditionally.
  `Order` holds a foreign key to `Facility`. So the moment the database contains a
  single order, the non-reset path — the one the docstring describes as the safe
  default — cannot run at all. It has never worked; it just was not exercised,
  because until now nothing had filed an order before a re-seed.
- **Worked around, not fixed.** `--reset` cleared one leftover Week 2 test order and
  the seed completed. That is fine today: the row was throwaway. It will not be fine
  in Week 6, when the agents have filed orders worth keeping and someone re-runs the
  seed after a pipeline re-run — they will either hit this error or reach for
  `--reset` and destroy real agent-filed data.
- **The actual fix, for its owner.** Upsert the facilities rather than delete-then-
  insert: the 1,657 codes are the same on both sides of a re-seed, so nothing needs
  deleting for the reference data to be refreshed. Left to Mounika as the area owner
  (GIT_RULES SS10) rather than patched from an agents branch — it is her module,
  and the fix wants a test that files an order and then re-seeds, which belongs with
  the TMS suite.
- **Cost.** ~10 minutes to diagnose, none to work around. Logged rather than fixed in
  passing because a silent `--reset` habit is exactly how the Week 6 version of this
  becomes "where did the orders go?"

### P-41 · The agent's own validator passed an order the TMS rejected
**Week 5 · Krishna · resolved**

- **Symptom.** Every clean email extracted perfectly, validated clean, and then came
  back `HTTP 422` from `POST /orders`:
  `source: Input should be 'api', 'agent' or 'seed'`. Three of six emails failed at the
  last step, after everything the agent could check had passed.
- **Cause.** `post_order` set `"source": "EMAIL"` — a value invented at the call
  site because it read well, and not a member of the TMS's `OrderSource` enum. The
  agent's `validate_order()` had nothing to say about it for a structural reason worth
  naming: **it validates the fields the model extracted, and `source` is not one of
  them.** It is set by the agent itself, in the payload builder, downstream of every
  check.
- **Fix.** Import the enum and use `OrderSource.AGENT.value`. Not "add `source` to the
  validator" — that would catch the next wrong string, but this class of bug
  disappears entirely when the value cannot be invented in the first place. Same
  reasoning as D-031 reusing one event schema and P-23's two-lists-one-truth lesson:
  where a contract already exists in code, import it rather than retype it.
- **Cost.** ~10 minutes and three wasted LLM calls against a 20-a-day quota (D-032),
  which is the part that stung. **The generalisable lesson:** a validation layer that
  checks *the model's output* rather than *the payload actually sent* has a blind spot
  exactly the size of whatever the code adds afterwards — and everything in that
  blind spot fails at the far end of a network call, where it looks like someone
  else's problem.

### P-42 · The stream was about to publish a label computed at the threshold the project rejected in Week 2
**Week 5 · Mounika · resolved**

- **Symptom.** Scoring the replay's alerts against the `is_delayed` its own fact events
  carried gave precision 0.981 and recall 0.688. Both numbers were wrong, and the tell
  was the base rate beside them: **93.6% of the 26,369 replayed legs came back
  "delayed"**, against the 49.7% D-003 records for the decided threshold. 93.6% is not
  a near miss. It is *exactly* the figure D-003's own table gives for `T = 1.25` —
  the blueprint's threshold, which the team rejected at the Week 2 sync.
- **Cause.** `src.pipeline.reconstruct` writes `is_delayed` into the parquet using
  `config.DELAY_THRESHOLD` **as it stood when the cache was built**. D-003 moved that
  constant from 1.25 to 2.00; the frozen caches (D-016) were never rebuilt, so the
  column has been stale ever since. 11,583 of 26,369 legs — 43.9% — carry a
  label that contradicts the same threshold recomputed from `gap_min` and `planned_min`.
- **Why eight weeks passed without anyone noticing.** `src.ml.baselines.add_delay_label`
  recomputes the label from `gap_min` before every fit, on purpose. So every model in
  Weeks 3 and 4 trained and scored on the *correct* label, and the stale column was
  overwritten on the only code path that had ever read it. It was not hidden by luck;
  it was hidden by a downstream correction working exactly as designed. `fact_event` was
  the first consumer to read the column straight from the parquet and put it on the wire.
- **Fix.** `fact_event` recomputes the label rather than carrying it, and `is_delayed`
  was **removed from `EXAMPLE_COLUMNS` altogether** — not loading a stale column is
  a stronger guarantee than remembering not to use it. Four tests pin the behaviour, and
  the fixture row deliberately carries the *wrong* stale value, because a fixture holding
  the right answer cannot tell "recomputes" from "copies". With the label corrected the
  same comparison reads precision 0.686, recall 0.907 — a different system's worth
  of difference from what the stale label showed.
- **Not fixed here, deliberately: the parquet still holds the stale column.** Rebuilding
  it means re-running the pipeline and unfreezing a cache D-016 froze on purpose, and the
  two consumers that matter now both recompute. The remaining risk is a *third* consumer
  reading it directly, which is why this entry exists and why the column is no longer
  loaded on the path that would have.
- **Carry.** A cached column computed from a constant is a snapshot of that constant, not
  a definition of it. Anywhere a decision changes a threshold, every derived cache is
  stale from that moment — and a downstream recomputation that quietly papers over
  it removes the only symptom anyone would have seen.

### P-43 · A micro-batch that never finished was counted as work completed
**Week 5 · Mounika · resolved**

- **Symptom.** Two throughput steps replaying **identical** events reported 661 alerts
  and 1,347 alerts, while both claimed all 4,000 events processed and both reported
  `kept_up: true`.
- **Cause.** `process_batch` incremented the event counters at the top, before scoring.
  When the stream was stopped at the end of a step, a micro-batch still in flight had
  already booked its full event count but never wrote its alerts. So the run that did
  half the work looked identical to the run that did all of it — on the very field
  the harness uses to decide whether the pipeline kept up.
- **Fix.** One `_record()` call at the end of the successful path, plus the same call on
  the "all facts, nothing to score" path so that batch is still counted. The counters now
  mean *finished*, not *started*.
- **Cost.** ~20 minutes, all of it in noticing. **What made it visible was a number that
  should have been constant not being constant** — the same events must produce the
  same alerts. Nothing in the harness's own output flagged it; the run reported success
  in the field designed to report failure.
- **Carry.** Instrumentation placed for convenience measures something adjacent to what
  it claims. A counter incremented on entry counts attempts; if the metric's name says
  "processed", it has to be incremented where processing ends.

### P-44 · The drain window was one batch long, so "did it keep up" was decided by the clock
**Week 5 · Mounika · resolved**

- **Symptom.** The same 4,000 events scored 1,618 in one run and 4,000 in the next
  — at a *lower* offered rate. `kept_up` flipped between runs of the same
  configuration.
- **Cause.** The harness gave the job 20 seconds to finish its backlog after the replay
  stopped. A micro-batch on this machine takes ~14 seconds. So whether a step "kept up"
  depended on whether the 20-second timer happened to fall inside a batch or between two
  — a coin flip weighted by luck, reported as a capacity measurement.
- **Fix.** `DRAIN_SECONDS = 60`, about four batch times, chosen *from the measured batch
  duration* rather than from taste. The verdicts became stable and, more usefully,
  started disagreeing with each other for real reasons: the 4-files-per-trigger
  configuration genuinely cannot drain a 36-file replay, and now says so every time.
- **Carry.** Any timeout in a measurement harness is a parameter of the measurement. If
  it is within one unit of work of the thing being measured, it is measuring itself.

### P-45 · The event schema declared Python's day-of-week while the pipeline emits Spark's
**Week 5 · Mounika · resolved**

- **Symptom.** `python -m src.streaming.producer --limit 8000 --validate` died with
  `7 is greater than the maximum of 6` on `created_dayofweek`.
- **Cause.** `stream_event.schema.json` declared the field `minimum: 0, maximum: 6`
  — `datetime.weekday()`'s range. Stage 4 builds it with Spark's `F.dayofweek`,
  which is **1 through 7**. 3,607 of 26,369 legs (13.7%) are Saturday, value 7, and fail
  validation against the contract that is supposed to describe them.
- **Why D1-D2 did not catch it.** The producer's smoke run replayed 300 legs, and
  `--limit` takes a *prefix* of the chronological order, so all 300 came from the first
  3.9 hours of 2018-09-12 — a Wednesday, value 4, comfortably inside 0-6. Every
  event validated. The validator was working; it was handed a slice that could not
  disagree with the bug.
- **Fix.** `minimum: 1, maximum: 7`, and the description now names the convention and
  points at `temporal_features` for anyone recomputing the field. 16,000 events spanning
  a full week validate.
- **This is P-39's trap in a third place.** Lahari found it between Stage 4 and a Python
  consumer and fixed it with a shared helper; it was also sitting in the *contract*, and
  a shared helper does not fix a schema. **P-39's closing claim that the trap was found
  "before anything could fall into it" was too strong** — two things already had.
  This is the second; the first is `src.ml.predict`, still live on the what-if page.
- **Carry.** When a convention mismatch is found, grep for the *values*, not just the
  code: every place the range 0-6 or 1-7 is written down is a place the convention was
  decided, including JSON Schemas, docstrings and test fixtures.

### P-46 · The what-if page has fed the model the wrong day of the week since Week 4
**Week 5 · found by Krishna, owned by Krishna · resolved at the Week 5 merge**

- **Symptom.** None visible, which is the problem. Found by reading, not by a failure:
  after P-45 turned up the day-of-week convention in a JSON Schema, the carry from that
  entry said to grep for every place the convention is decided, and
  `src/ml/predict.py` builds the what-if row with
  `"created_dayofweek": departure.weekday()`.
- **Cause.** `weekday()` is Monday = 0 through Sunday = 6. The champion was trained on
  Spark's `F.dayofweek`, Sunday = 1 through Saturday = 7 (P-39). The two never agree on
  any day — a Wednesday is 2 on the page and 4 to the model — so every what-if
  prediction since Week 4 D5 has been made on a day-of-week value from a different scale
  than the one the model learned. `created_is_weekend` is computed correctly on the same
  line, because "Saturday or Sunday" means the same thing in both conventions; that is
  exactly why the other two temporal fields looked fine at a glance.
- **Why this is P-39's first victim, not a new trap.** P-39 says the convention was
  caught "before anything could fall into it". This had already fallen in, a week
  earlier, on a page a user can click. P-45's entry already corrects P-39's claim;
  this is the case it refers to.
- **Fixed at the Week 5 merge.** `src.ml.predict.base_row` builds the non-history half
  of the row and takes its three temporal fields from
  `src.streaming.schema.temporal_features` — the one shared helper, which landed with
  Lahari's branch — rather than writing `isoweekday() % 7 + 1` a third time. A third
  implementation of one convention is how P-39, P-45 and this entry all happened. Two
  tests pin a Wednesday to 4 and Saturday and Sunday to 7 and 1.
- **How much it mattered, measured rather than guessed.** All 5,274 test legs were scored
  through the champion twice, once with the right encoding and once with what
  `weekday()` would have supplied. The two encodings disagree on every leg:
  - **35.9% of predictions move**, by **0.6 minutes** on average (median 0.0, 95th
    percentile 2.9, worst 62.9);
  - **13 delay calls flip (0.2%)**;
  - test MAE is **36.9 minutes either way**.
  The champion leans very little on day-of-week, so the damage was small. **That is luck,
  not design.** Under a model that weighted the day heavily, the same bug would have
  moved every what-if answer, and nothing would have raised.
- **Carry.** Grep for the *values* a convention produces, not just the function that
  produces them. `weekday()` appears nowhere near the word "dayofweek" in a way a
  search for the schema field would find.

### P-47 · The TMS database had drifted from its own models, and it blocked the entire Week 6 lifecycle
**Week 6 · found by Krishna, owned by Mounika · worked around**

- **Symptom.** `POST /shipments` returned **HTTP 500** for every order. Under it:
  `sqlite3.OperationalError: no such column: shipment.notes`.
- **Cause.** `Shipment` gained a `notes` field in the model. `SQLModel.metadata.create_all`
  creates missing *tables*; it never alters an existing one. `data/tms.sqlite` was
  created before that field existed, so the file and the models had silently disagreed
  ever since — harmless until the first code path actually wrote the column, which
  was Week 6's first shipment.
- **This is P-40's prediction coming true, almost word for word.** P-40 said: *"It will
  not be fine in Week 6, when the agents have filed orders worth keeping and someone
  re-runs the seed... they will either hit this error or reach for `--reset` and destroy
  real agent-filed data."* The database held three real agent-filed orders from Week 5.
  `--reset` would have destroyed them, and it was the obvious move.
- **Worked around without losing data.** A schema diff between
  `SQLModel.metadata.tables` and `PRAGMA table_info` found exactly one drifted column,
  added by `ALTER TABLE ... ADD COLUMN`. The three Week 5 orders survived; shipments
  booked immediately afterwards.
- **The actual fix, for its owner.** That diff is ten lines and belongs in Mounika's
  end-to-end boot script (W6 D1-D2), which is the one place that already knows it is
  about to start every service: check the schema against the models, add what is
  missing, and refuse to start if a column has *changed type* rather than merely being
  absent.
- **Carry.** An ORM that creates tables but never alters them is a migration system that
  works exactly once. Every model change after the first run is invisible until
  something writes the new column, and the error surfaces in whichever feature happens
  to touch it first — three weeks and two members away from the change that caused it.

### P-48 · The agent guessed the audit's vocabulary, so its escalation rule never fired and it told customers the opposite of the truth
**Week 6 · Krishna · resolved**

- **Symptom.** Two of the first three exception notifications said *"This corridor is a
  confirmed slow route in our own audit."* One of them was on a corridor the Week 2
  audit had confirmed **faster** than the network. Separately, a corridor that genuinely
  was a confirmed bottleneck was graded `high` when the rule said it should escalate to
  `critical`.
- **Cause.** One root, two symptoms. The severity rule tested
  `direction == "slower"`. The audit writes `"worse"` and `"better"`
  (`src/ml/audit.py` line 248). The comparison therefore never matched: **the escalation
  was dead code from the moment it was written**. The customer-facing template made the
  opposite mistake — it tested `is_significant` alone, which is true of corridors
  confirmed *faster* as well, and 512 of the network's corridors are exactly that.
- **Fix.** One predicate, `Investigation.confirmed_slow` (`is_significant` **and**
  `direction == SLOWER_THAN_NETWORK`), used by the severity rule, the evidence list and
  the template. The constant names the audit's word and cites the line that writes it,
  and `load_audit` now **validates the vocabulary on the way in**: an unknown direction
  value raises instead of silently disabling the rule. Verified on the same three alerts:
  the confirmed-slow corridor escalated `high -> critical`, and the confirmed-*fast* one
  stayed `low` and stopped claiming to be slow.
- **Cost.** Three tickets were filed with the wrong severity before it was caught, and
  two customers would have been told something false about their route.
- **Carry.** **A string comparison against another module's vocabulary is an untested
  assumption until something validates it.** Neither symptom raised: a comparison that
  never matches looks exactly like a condition that is never true, and the wrong
  sentence was fluent, plausible and confidently wrong. The rule now is: when comparing
  against a value another module produces, either import the constant or validate the
  domain — never retype the literal.

### P-49 · A shipment became invisible to the agent the moment it had one ticket
**Week 6 · Krishna · resolved**

- **Symptom.** The Exception Agent processed three alerts and filed three tickets. Run
  again, it reported that **all 1,347 alerts were on corridors we are not carrying**,
  including the three it had just ticketed.
- **Cause.** The agent treated `{created, in_transit}` as "in flight". Filing a ticket
  flags the shipment `exception` — the TMS does that deliberately, so that a
  consignment with an open ticket does not still read `in_transit`. So every shipment
  dropped out of the agent's view as soon as it had one ticket: **the second problem on
  an already-troubled consignment was precisely the one it could no longer see.**
- **Fix.** `IN_FLIGHT_STATUSES = {created, in_transit, exception}`. `delivered` is the
  only status that means "not ours any more"; the filter now names the terminal state
  rather than enumerating the healthy ones.
- **Carry.** A status filter written as a list of good states silently excludes every
  state added later, and the states added later are usually the interesting ones. Filter
  on what is finished, not on what is fine.

### P-50 · The documented producer command fails on every machine that follows the README
**Week 6 · Mounika · resolved for boot, open in `.env.example`**

- **Symptom.** `boot`'s first end-to-end run reported `FAIL producer`. Its log:
  `could not open the kafka sink: KafkaTimeoutError: Unable to bootstrap from
  localhost:9092`, after a 30-second stall.
- **Cause.** `STREAM_SOURCE` defaults to `kafka` in `config.py` and `.env.example`, and
  the producer honours it. D-035 recorded in Week 5 that this machine has no broker and
  that every reported number comes from the file sink — but every Week 5 run passed
  `--sink file` explicitly or called `FileSink` directly through the throughput harness,
  so nothing ever exercised the default. **The default has been wrong since Week 5 and
  only a script with no flags could find it.**
- **Fix.** `boot` passes `--sink file` explicitly and says why in a comment. The README
  now carries the same warning beside the bare command.
- **Not fixed: the default itself.** Flipping `STREAM_SOURCE` to `file` would make the
  documented Kafka path the one that needs a flag, which is a decision about what this
  project claims to be (D-035 deliberately ships the Kafka path unexercised rather than
  unwritten). Left for the Week 7 sync.
- **Carry.** A default that every caller overrides is not a default, it is a trap with a
  long fuse. The way to find one is to run the documented command with no flags, which is
  exactly what a boot script does and what six weeks of careful invocations never did.

### P-51 · The boot script quietly overwrote the evidence the write-ups cite
**Week 6 · Mounika · resolved**

- **Symptom.** After `boot` ran, `git diff` showed
  `benchmarks/raw/w6_orchestrator_runs.json` down by 178 lines and
  `w6_exception_runs.json` down by 119. Nothing had failed; the files had simply been
  replaced.
- **Cause.** Each agent writes its run to a fixed path in `benchmarks/raw/`. That is
  right when the run *is* the evidence, and wrong the moment a demonstration reruns the
  same agent with different arguments. `boot` runs the orchestrator over 5 cases;
  Krishna's write-up cites a 10-case run with three distinct paths. **Boot's smaller run
  silently became the artefact his document points at.**
- **Why it matters more than it looks.** Every number in this project is supposed to
  trace to a file in `benchmarks/`. A demonstration that rewrites those files breaks the
  trace without touching the prose, so the document and its evidence drift apart while
  both look fine. It would have been found at the worst possible moment: someone opening
  the JSON to check a figure in the report.
- **Fix.** `--out` on the Exception Agent and the orchestrator, defaulting to the
  benchmarks path they already used. `boot` passes `logs/boot/...` instead, so a
  demonstration leaves the cited evidence alone. The overwritten files were restored
  from git.
- **Carry.** A module that writes to a fixed artefact path has an implicit claim on it:
  *this run is the one that counts*. As soon as two callers exist, the path needs to be
  an argument — and the default should belong to whichever caller produces the
  evidence, not whichever was written first.

### P-52 · A leg's finish time was computed as departure plus moving time, which is not when it finished
**Week 7 · found by Lahari, fixed by Mounika · resolved in both places**

- **Symptom.** The as-of corridor history rebuilt for D-048's median baseline agreed with
  Stage 4's `corr_n_prior` on only **95.2%** of warm legs. Every disagreement ran the same
  way: 1,128 legs saw *more* prior history than Stage 4 gave them, never less.
- **Cause.** The first version derived a leg's finish time as
  `od_start + (gap_min + planned_min)`, i.e. departure plus `actual_time`. But
  `actual_time` is **moving** time: `reconstruct.py` defines dwell as
  `start_scan_to_end_scan - actual_time`. So every fact landed before the leg really
  finished, and legs still on the road were counted as known history — which is
  leakage, in the direction that flatters a baseline.
- **Fix in the diagnostics.** Join the real `od_end_time` from `trips_v1`, the column
  Stage 4's as-of join uses. Agreement: **100%** on both count and mean. The median
  baseline moved only from 33.06 to 33.04 min, so this changed no conclusion — but a
  baseline whose history is *provably identical* to the features' is worth the join.
- **The same proxy was in the streaming schema, and is now gone.**
  `src/streaming/schema.py::fact_event` stamped every fact event at
  `od_start + actual_time`, with a docstring calling it "exact, not an approximation".
  Measured against the real `od_end_time`, it was **early on 26,298 of 26,369 legs, by a
  median of 49.6 minutes** (mean 98.1, p95 345.2) — which is the median hub dwell Week 2
  reported, arriving as a bug. It cost nothing published, because the streaming job counts
  and drops fact events (D-037); the moment fact-driven live history is built it would have
  been the same leak as above, a query scored against legs that had not finished.
  `fact_event` now refuses a row with no finish time rather than deriving one, and the
  producer and sample-event writer join `od_end_time` from `trips_v1` — exact on all 26,369
  legs. The merge of the two branches then caught a third caller: a threshold test that
  built a fact row by hand.
- **Carry.** A duration column is not a clock. `actual_time` answers "how long was the
  truck moving", and adding it to a departure time answers a question nobody asked. When
  a timestamp exists in the data, join it; do not reconstruct it from parts that happen to
  have the right units.


### P-53 · A model call with no timeout hung the extraction evaluation for twenty minutes
**Week 7 · Krishna · resolved**

- **Symptom.** The G-01 smoke run of `src.ml.eval_extraction` cached three extractions
  and then printed nothing for twenty minutes. No error, no quota message, CPU idle.
- **Cause.** `get_llm()` built `ChatGoogleGenerativeAI` with the library defaults: no
  request timeout, and retries on transient errors. One request stalled on the
  provider side and the client waited on it indefinitely. Worse, a retried request is
  a request against the 20-per-day free tier (P-36), so a hang is not only lost time —
  it can quietly spend quota that the cache never records.
- **Fix.** `src/agents/llm.py` passes `timeout=REQUEST_TIMEOUT_S` (120 s) and
  `max_retries=MAX_RETRIES` (2) to both providers. A stalled call now fails inside two
  minutes, the evaluation's quota and error handling sees it, and the run resumes from
  its cache next time.
- **Carry.** Every network call needs a timeout chosen on purpose. A library default of
  "wait forever" is not a neutral choice; it turns a provider hiccup into a stuck
  process nobody is watching.


### P-54 · The MCP server's health tool crashed when the TMS was down — the one moment it exists for
**Week 7 · Krishna · resolved**

- **Symptom.** Driving the MCP server over real stdio (G-06) with the TMS stopped,
  `tms_health` returned a protocol error instead of reporting the TMS as down.
- **Cause.** `TMSClient` callers caught `(TMSError, OSError)`, on the assumption that a
  refused connection surfaces as `OSError`. With `httpx` it does not: `ConnectError` and
  its siblings derive from `httpx.HTTPError`, not `OSError`. The in-process tests had
  always run against a live TMS, so the down path was never exercised.
- **Fix.** `TMSClient._request` translates every `httpx.HTTPError` into
  `TMSError(0, "transport failure: ...")`, so callers handle one exception type for
  "the TMS did not answer" whichever layer failed. `tests/test_mcp_stdio.py` now points
  a client at a dead port and asserts the health tool reports the TMS down.
- **Carry.** An error path that no test forces is an error path that has never run.
  Catch what the library actually raises, and check by pointing at something that is off.


### P-55 · The residual sprint died twice in the JVM: once on lineage depth, once on heap
**Week 7 · Lahari · resolved**

- **Symptom.** The first `python -m src.ml.models_v2` run failed with
  `java.lang.StackOverflowError` at stage 2,046, deep into GBT training. The second got
  past GBT and failed in the Random Forest with `java.lang.OutOfMemoryError: Java heap
  space` while broadcasting 10 MB task binaries. The background wrapper reported the
  first failure as exit 0, because `stop_spark` raised on a dead JVM and masked the real
  error.
- **Cause.** Each boosting iteration extends the RDD lineage, and 200 of them nest deep
  enough to overflow the stack when the plan is deserialised; Week 4's shorter grids never
  reached that depth. The forest was 300 trees at depth 8, twice the largest Week 4 fitted
  on the 4 g driver, and a test suite was running a second Spark session at the same time.
- **Fix.** `setCheckpointDir` plus `checkpointInterval=10` on both estimators, which cuts
  the lineage instead of raising `-Xss` and moving the cliff. The forest went down to 150
  trees, Week 4's largest, and the run was repeated with nothing else using Spark. It
  finished in 10 minutes.
- **Carry.** Read the log, not the exit code, for a JVM job driven from Python. And a model
  bigger than anything fitted before on the same machine is a capacity test, so run it on
  its own.


### P-56 · The refusal gate was calibrated on questions too easy to refuse
**Week 7 · Krishna · open — second layer to be measured**

- **Symptom.** The Analytics assistant's refusal threshold (0.63 cosine distance) split
  twenty calibration probes perfectly: in-scope at most 0.588, out-of-scope at least
  0.681. On the fixed 30-question set it refused only 3 of 6 out-of-scope questions.
  "How many trucks does Delhivery own?" sat at 0.502 and "What is the GST rate on road
  freight?" at 0.539 — nearer the index than in-scope questions at 0.510, 0.531 and
  0.598.
- **Cause.** The out-of-scope calibration probes were general knowledge (capitals,
  bread, football). Distance to the nearest document measures *topic*, not whether the
  document *answers* the question, and a freight question about a freight company is
  on topic. The two distributions overlap, so no threshold separates them.
- **What was not done.** Tuning the threshold on the 30-question set until the misses
  go away. That is fitting the gate to the test, and the next domain-adjacent question
  would sail through the same way.
- **Fix, partly measured.** Two layers. The distance gate stays for precision — it
  refused nothing in scope (precision 100%) and costs zero quota. The second layer is
  the prompt's own rule to answer only from the context and otherwise return the
  refusal sentence. Its recall is measured by the model-phrased run of the same set
  (`benchmarks/raw/w7_assistant_run_llm.json`), which waits on quota.
- **Carry.** Calibrate a gate on the cases that are hard to separate, not the cases that
  are easy to name. The fixed evaluation set found this because it was written with
  domain-adjacent traps; the calibration set was not.


### P-58 · The extraction evaluation published "7.0% accuracy" from 37 documents it never sent
**Week 7 · Krishna · resolved**

- **Symptom.** The first real G-01 run wrote `w7_doc_extraction_eval.json` with
  **7.0% accuracy, 95.1% precision, 7.0% recall**. Nothing had crashed. Thirty-seven of
  40 rows had failed with `GEMINI_API_KEY is not set`, and every one of them had been
  counted as a document where the agent returned nothing.
- **Two causes, one theme.**
  1. The run started from a git worktree, whose `data/` is its own empty directory. The
     corpus path defaulted to the relative `data/documents`, so it found nothing. Same for
     `benchmarks/raw`. Both are now `config.DOCUMENTS_DIR` and `config.BENCHMARKS_RAW_DIR`,
     which are absolute.
  2. The row handler treated every exception as a total miss. That is right for a bad
     answer and wrong for a failure to ask: the quota branch beside it existed precisely
     to avoid publishing the free-tier limit as an accuracy number, and a missing key is
     the same kind of event.
- **Why it matters more than a wrong number in a scratch file.** Nothing in the output
  said "this machine was misconfigured". It said the agent scored 7%. A file like that is
  cited, and the citation survives long after the run is forgotten.
- **Fix.** `is_environmental()` classifies the failure: missing credentials, no network, a
  timeout, a provider 5xx. Those rows are left unscored like a quota refusal and counted
  separately in the report; an unparseable answer or a missing field is still the agent's
  miss. The rerun proved it immediately — a **503 UNAVAILABLE** arrived on row 12 and was
  excluded rather than scored as a zero.
- **Carry.** An evaluation harness needs to distinguish *the agent was wrong* from *the
  agent never ran*. If it cannot, its worst numbers are reports about the machine.


### P-59 · The preflight check sent a fresh clone to a command that cannot run yet
**Week 8 · Mounika · resolved**

- **Symptom.** The Week 8 reproducibility pass — clone the repository somewhere it has
  never been, follow the README — ran `python -m src.common.boot --check` and got a tidy
  list: cleaned parquet missing, run `python -m src.pipeline.clean`. Following that advice
  fails, because there is no raw dataset to clean.
- **Cause.** `preflight()` checked four generated artefacts and never checked the input
  they are generated *from*. On the machines where it was written the 55 MB CSV had been
  there since Week 1, so the first link of the chain was invisible to everyone who already
  had it.
- **Why a check that is 90% right is the problem.** A missing check is discovered at the
  first failure. A *confident and incomplete* check sends someone down a path that cannot
  work, and they debug `clean.py` instead of downloading a file. The whole point of
  `boot --check` is that it reports every problem before anything starts (D-044).
- **Fix.** The raw dataset is now the first preflight line, verified by size against
  `config.RAW_BYTES`, with `data/README.md` as its fix. A fresh clone now reads
  `[MISS] raw dataset: missing ...\data
aw\delhivery_data.csv -> download it — see
  data/README.md` above everything else.
- **Carry.** A preflight list is only as good as its first entry. When adding a check for
  a generated artefact, check what generates it, or the report is a well-formatted way of
  pointing at the wrong problem.

### P-60 · The assistant evaluation recorded six provider errors as the model's answers
**Week 7 · Krishna · resolved**

- **Symptom.** The model-phrased run of the 30-question set finished with 30 answers, six
  of them marked `draft_source: extractive` — verbatim passages, not model text. They were
  in the answers file, scored for route and source, and headed for groundedness judging as
  if the model had written them.
- **Cause.** The runner was meant to stop on a quota refusal and not record it. It looked for
  the error in the latest trace — but the assistant catches the model exception and falls
  back *before* the trace is written, so the trace never contains it. The quota branch could
  not fire, and any failure became an "answer". Two of the six were 503 UNAVAILABLE, the
  rest `Error calling model`.
- **Same shape as P-58.** An evaluation that cannot tell *the model was wrong* from *the
  model never answered* reports the provider's uptime as the model's quality.
- **Fix.** In model mode, any fallback is skipped and left for the next run; two in a row
  stop the run (quota or outage), because every further attempt spends a call to learn
  nothing. `--retry-fallbacks` drops recorded fallbacks so they are asked again. The
  groundedness summary reports **model-written** answers as its headline (17 of 18 grounded)
  and counts the six fallbacks separately rather than crediting them.
- **Carry.** A fallback is the right behaviour for a user and the wrong record for an
  evaluation. Code that does both has to know which one it is doing.

### P-61 · The assistant ranked hubs by the wrong measure, and the model caught it
**Week 7 · Krishna · resolved**

- **Symptom.** Asked "which hub has the longest dwell time?", the table route returned the
  friction ranking with Aluva first (350 min). The model-phrased answer said **Hubli, 373
  min**, citing rank 2 — contradicting the table's order and, on a first read, looking like
  a grounding failure.
- **Cause.** Friction ranks hubs by dwell as a *share of leg time* (Aluva 82%, Hubli 76%).
  Dwell *time* ranks by minutes, and across all 121 ranked hubs Hubli's 373 is the longest.
  The router sent every hub-dwell question to the friction table. **The model was handed
  both numbers, read them, and answered the question actually asked.** The question set's
  expected answer, the router's test and the demo script all said Aluva, and all three were
  wrong in the same way.
- **What it says about groundedness judging.** A mechanical check would have flagged the
  answer as disagreeing with its context's ranking. Reading it against the context is what
  showed the model was right and the scaffolding was not.
- **Fix.** Questions about dwell *time* sort `w2_hub_dwell.csv` by median minutes; questions
  about friction or congestion keep the friction table. Each context line now carries both
  measures. The v1 question set is left as it was (versioned sets are not edited in place);
  its T03 note is wrong and a v2 set should expect `w2_hub_dwell.csv`.
- **Carry.** A "longest" question needs the sort key the question names. Two rankings in one
  table is one ranking too many to guess between.

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

### P-57 · A commit went up with two failing tests because a pipe hid the exit code
**Week 7 · Krishna · resolved**

- **Symptom.** Commit `0d77ad0` on `week7-krishna-rag-assistant` was pushed while two
  tests failed: the MCP server's hand-typed `TOOL_NAMES` missed `search_knowledge`, so
  the server advertised 13 tools while `--list` printed 12.
- **Cause.** The check was `pytest ... | tail -3`. A pipeline's exit status is the last
  command's, so `tail` succeeded and the red summary line scrolled past unread.
- **Fix.** The next commit, `1f4b23e`, fixed the cause rather than the list: tool names
  are recorded by the `@tool` decorator that registers them, so they cannot go stale.
  Its message says the previous commit went up red. Test runs before a commit now read
  `${PIPESTATUS[0]}` explicitly.
- **Carry.** A hand-kept list of things that also exist in code will drift. And a check
  whose result you did not read is not a check.

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
