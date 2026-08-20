# Decision log

Running record from the weekly syncs (GIT_RULES §2). One entry per decision that
later work depends on. **Never edit a decided entry** — supersede it with a new one
and link back, so the report and the viva can both reconstruct why a thing is the way
it is.

Status values: `DECIDED` · `OPEN` (needs team sign-off) · `SUPERSEDED by D-0xx`

---

## D-001 · Repository layout and branch model — `DECIDED`
**Week 1 · proposed by Mounika · all three agreed**

Adopt `GIT_RULES.md` as written: `main` / `dev` / `week<N>-<name>-<topic>`, merge
commits only, branches never deleted, `[W<N>][AREA]` commit format.

**Why:** the branch and commit trail *is* the per-member contribution evidence faculty
will read (GIT_RULES §9). Squashing or deleting branches destroys the artifact the
workflow exists to produce.

---

## D-002 · Corridor key and analysis grain — `DECIDED`
**Week 1 · Lahari + Mounika**

The corridor key is `source_center + ">" + destination_center` — **centre codes, not
facility names, and not city names.** All corridor statistics are computed at
**origin-destination leg grain**: 144,867 segment rows collapse to 26,369 legs.

**Why codes:** names are null on 554 rows and spelled inconsistently
(`Bangalore` / `Bengaluru`). Codes are never null and never ambiguous.

**Why leg grain:** `actual_time`, `osrm_time`, `osrm_distance` and
`actual_distance_to_destination` are *running cumulative totals within a leg*. Any
statistic computed over raw segment rows over-weights long trips. The leg total is in
the **last** row of the leg — selected by maximum cumulative `actual_time`, since 0.08%
of legs are not perfectly monotonic in file order.

**Consequences:** Stage 2's Spark reconstruction must reproduce
`benchmarks/raw/w1_leg_summary.csv` row for row. `src/ml/eda.py` asserts the
leg-constant columns really are constant and raises if that stops holding.

**Trap recorded:** despite its name, `actual_distance_to_destination` *increases*
along a leg — it is distance covered, not distance remaining.

---

## D-003 · Delay label threshold — `OPEN` ⚠
**Week 1 · raised by Lahari · blocks Week 3**

Label: `actual_time > T × osrm_time` at leg grain. The blueprint proposes `T = 1.25`.

**The problem the data revealed.** At `T = 1.25`, **93.6% of legs are labelled
delayed**, because the median leg already runs at 2.00× plan. A model that predicts
"delayed" for everything scores 93.6% accuracy while carrying zero information, and
the Week 6 Exception Agent built on it would flag essentially every shipment — the
same as flagging none.

| T | % legs delayed |
|---|---|
| 1.10 | 96.9% |
| 1.15 | 96.0% |
| **1.25** (blueprint) | **93.6%** |
| 1.50 | 83.6% |
| **2.00** (recommended) | **49.6%** |

**Recommendation on the table:**
1. Move the classification threshold to `T = 2.00` — a 49.6 / 50.4 split, and
   "takes at least twice the planned time" is defensible as *operationally late* on a
   network whose planner is biased this hard.
2. **Lead with regression, not classification.** `gap_min` (median 42 min, mean
   110 min) has no threshold problem, and the headline the blueprint actually wants —
   *our MAE vs OSRM's MAE* — is a regression result anyway.
3. Report the majority-class rate beside every classifier metric, permanently.

**Until this is decided,** `config.DELAY_THRESHOLD` holds the blueprint's `1.25` so
nothing changes silently under anyone. Changing it is a one-line edit in
`src/common/config.py`. Week 5's sensitivity run must be extended to include 2.00.

Evidence: `docs/W1_lahari_eda.md` §3, `benchmarks/raw/w1_delay_threshold_sensitivity.csv`.

---

## D-004 · Minimum corridor support for the audit — `DECIDED (revisit at W2)`
**Week 1 · Lahari**

Corridors with fewer than **30 observed legs** are excluded from the Stage 3 audit.

**Why:** a "worst corridor" ranking over 2,783 corridors, most seen once or twice,
ranks noise. 30 legs is the smallest support at which a Welch t-test on log-ratios is
worth reporting.

**The cost, stated openly:** 30 legs retains 99 of 2,783 corridors (3.6%) covering
18.9% of legs. **The audit is therefore a claim about the busy core of the network,
not about the whole of it, and the report must say exactly that.** A threshold of 10
legs would retain 40.6% of corridors and 78.6% of legs with weaker per-corridor tests.

**Revisit at the Week 2 gate** once the significance tests exist and the
power/coverage trade-off can be judged on results rather than in the abstract.

---

## D-005 · Train/test split — `DECIDED`
**Week 1 · Lahari**

The dataset's own `data` column (`training` 72.4% / `test` 27.6%) is **not** used as
our split. Week 3 defines a **time-based split** on `trip_creation_time` instead.

**Why:** the publisher's split has no stated construction, and the whole project turns
on not leaking future corridor behaviour into past-only features. A time-based split
is the only one whose leakage properties we can actually verify — and it is what the
Week 4 leakage checklist gates on.

The `data` column is retained in the cleaned cache as a plain feature/marker.

---

## D-006 · Suspect rows are flagged, never dropped — `DECIDED`
**Week 1 · Mounika + Lahari**

Stage 1 keeps rows with `segment_actual_time <= 0` (1,973) and
`segment_osrm_time == 0` (2,347), marking them `is_negative_segment`,
`is_zero_osrm_segment`, and `is_suspect`. Downstream stages filter on the flag and say
in writing that they did.

**Why:** these are artefacts of the source system, not random corruption. Negative
segment times are scan clock skew; dropping them would bias hub dwell downward.
Silently deleting 2.9% of rows before an audit is exactly the kind of undocumented
choice that makes a result unreproducible.

**Separately:** `segment_factor` carries a **`-1` sentinel**, not a ratio, on the
zero-OSRM rows — verified by confirming the column equals
`segment_actual_time / segment_osrm_time` to floating-point precision everywhere
`segment_osrm_time > 0`. A sentinel that looks like a plausible number is more
dangerous than an infinity, because it survives every mean and model fit without
complaint. Stage 1 nulls it there. **Never aggregate the raw column.**

---

## D-007 · One LLM construction site — `DECIDED`
**Week 1 · Krishna**

Every agent obtains its model from `src.agents.llm.get_llm()`. No agent constructs a
provider client directly.

**Why:** free tiers rate-limit and change. Swapping provider becomes a `.env` edit
rather than five edits across five agents, automatic fallback keeps a Week 7
evaluation run from dying mid-way, and Week 7's trace viewer has one log shape to read
because there is one call site.

---

## D-008 · Prompts are versioned and never overwritten — `DECIDED`
**Week 1 · Krishna**

Prompts live at `src/agents/prompts/<agent>/v<N>.md`. A new version is a new file; the
old one stays forever. Evaluation runs pin an explicit version, recorded next to the
score in `benchmarks/`.

**Why:** GIT_RULES §7 wants commits like `invoice_no accuracy 0.71 -> 0.93`. That
claim is only checkable if the prompt that scored 0.71 still exists.

---

## D-014 · A leg's totals come from its last row by source order — `DECIDED (Lahari to confirm)`
**Week 2 · Mounika · raised by the Stage 2 validator**

Stage 2 selects each OD leg's cumulative totals from the row with the highest
**`source_row_index`** — the source file's row order, preserved by Stage 1 — not from
`max(actual_time)`.

**Why it came up.** Stage 2's first implementation ordered by `max(actual_time)` and
failed validation against Lahari's Week 1 pandas oracle on 80 legs. Investigating the
raw file settled it:

- **1,861 legs (7.1%) have a tie on maximum `actual_time`** — their trailing segments
  add zero minutes — so "the row with the largest `actual_time`" does not identify one
  row.
- On every one of those 1,861 legs the tied rows carry **identical `actual_time`** but
  **different `osrm_time` / `osrm_distance`**, so the choice changes the leg's OSRM
  numbers while leaving its realised time untouched.
- Checked against the true final row in file order: on the 80 originally-disputed legs
  it agreed with the last-row rule **80/80** and with the oracle's rule **0/80**.

**The oracle's rule is the wrong one.** pandas `idxmax()` returns the *first* row
holding the maximum, which lands earlier than the final scan. Neither `max(actual_time)`
nor `max(osrm_time)` reproduces file order exactly (127 legs still differed), so Stage 1
now emits an explicit `source_row_index` and Stage 2 orders by it. The index is asserted
unique in Stage 1 — with no ties left, the selection is deterministic.

**Impact on results: none at reported precision.** Median gap ratio 2.0000, mean gap
110.00 min, 98.30% of legs over plan — identical under all three rules. Mean
`osrm_distance` moves 114.8316 → 114.8247 (0.006%).

**Status.** Stage 2 validates green: every column matches the oracle to floating-point
precision, with 1,581 legs differing by this tie-break alone, reported separately and
classified by an exact signature (`actual_time` and `n_segments` identical, a cumulative
column different). Verified that **0** legs differ with a differing `actual_time` — that
would be a genuine reconstruction bug.

**Lahari to confirm**, then regenerate `benchmarks/raw/w1_leg_summary.csv` from
`trips_v1` so the oracle and the pipeline agree exactly and the residual 1,581 goes to
zero. Her Week 1 headline numbers do not change.

---

## D-009 · The dashboard reads only cached artefacts — `DECIDED`
**Week 1 · Krishna + Mounika**

`src/dashboard/` reads Parquet from `data/processed/` and CSVs from `benchmarks/raw/`.
It never reads `data/raw/` and never starts a Spark session.

**Why:** the demo has to be responsive and must not be one Spark job away from a stall
in front of the panel. It also enforces the architecture: each plane consumes only
frozen outputs of the plane below.

---

## D-010 · Textual null sentinels are converted on read — `DECIDED`
**Week 1 · Mounika · found by running Stage 1, not by inspection**

Stage 1 converts `""`, `nan`, `NaN`, `null`, `None`, `NA`, `N/A`, `-` to real nulls
across every string column, and reports the count per column.

**Why this is not housekeeping.** Missing facility names in this file are the literal
three-character string `nan`, not empty fields. **pandas coerces `nan` to `NaN` on
read; Spark does not.** The same file therefore shows 554 missing names in a pandas
profile and **zero** in Spark — so two members analysing "the same data" would have
disagreed and neither would have been obviously wrong.

Left unconverted it would have put a facility in a city called **"nan"** on the Week 2
India map, and quietly polluted any group-by on city or state.

**Anyone comparing a pandas number to a Spark number must account for this.**

---

## D-011 · Missing names are unrecoverable; state is inferred from the PIN — `DECIDED`
**Week 1 · Mounika**

The 554 missing names belong to **14 centre codes**, and none of those codes carries a
name on any row anywhere in the dataset — checked, not assumed. The names cannot be
recovered from the data.

The **state** can be: centre codes are `IND` + a six-digit Indian PIN + three
characters, so `IND282002AAD` carries PIN 282002 → Agra → Uttar Pradesh. Stage 1 fills
the state from the PIN's first two digits (the postal circle) on 551 rows, marking them
`state_from_pin`.

**City is left null rather than guessed** — the PIN prefix identifies a circle, not a
city, and a wrong city would land as a wrong dot on the map.

*Supersedes the original claim in the W1 writeup that names were backfillable. The
backfill step is retained because it is correct and free if a future mirror ships
partially-named codes, but it recovers 0 today and the report says so.*

---

## D-012 · Windows/Spark environment baseline — `DECIDED`
**Week 1 · Mounika**

- **JDK 17 via the portable Temurin zip**, not `winget`. The MSI needs UAC elevation
  and hangs indefinitely in a non-interactive shell.
- **PySpark 4.0**, not 3.5. On Python 3.13 the conventional pins (`pyspark==3.5.1`,
  `numpy==1.26.4`, `pandas==2.2.2`, `pyarrow==15`, `scipy==1.13.1`) have **no cp313
  wheels**; pip falls back to source builds and effectively hangs. Check before
  changing a pin: `pip download <pkg>==<ver> --no-deps --only-binary=:all:`.
- **winutils.exe + hadoop.dll in `C:\hadoop\bin`, `HADOOP_HOME=C:\hadoop`.** Spark
  reads without them but cannot write Parquet — `RawLocalFileSystem.setPermission`
  calls `getWinUtilsPath`. Sourced from the cdarlint/winutils mirror; unsigned
  third-party binaries, standard practice for Spark on Windows, recorded here so the
  team knows what is on their machines.
- **Virtualenv lives outside the OneDrive folder.** A venv containing PySpark is
  several GB of small files and OneDrive will try to sync every one.

---

## D-013 · One timestamp format, with an optional fraction — `DECIDED`
**Week 1 · Mounika · found by running Stage 1**

All four timestamp columns parse with `yyyy-MM-dd HH:mm:ss[.SSSSSS]`.

**Why the optional part is the data, not defensiveness:** `cutoff_timestamp` is mixed —
141,438 rows are second-precision and 3,429 (2.37%) carry microseconds. A fixed
second-precision format throws on that 2.37% under Spark 4's ANSI mode.

The format stays explicit rather than inferred, so a genuinely new shape still stops the
pipeline instead of silently nulling a column.

---

## D-015 · Hub friction is measured *within* legs, and ranked on dwell share — `DECIDED (Lahari to confirm the ranking metric)`
**Week 2 · Mounika · found by running Stage 3**

### The between-leg gap is not dwell

The intuitive hub-dwell measure is the gap between a shipment arriving at hub H on one
leg and departing on the next: `next.od_start_time − this.od_end_time`. **Stage 3 was
built on that and the measurement says it does not work.** Over all 11,552 in-trip
handoffs:

| Handoff kind | n | Non-zero gap | Median gap |
|---|---|---|---|
| Trip continues from the **same** centre | 9,987 | **1.4%** | **0 min** |
| Next leg starts at a **different** centre | 1,565 | **100%** | 90 min |

The publisher closes one leg's OD window at the instant it opens the next, so on a
continuous handoff there is structurally no gap left to measure. Every non-zero gap is
a **chain break** — 13.5% of handoffs, where the shipment reappears at a facility it
never travelled to on any leg in the file. That gap is unobserved movement, not rest.

**Consequence:** the between-leg gap is emitted as `median_unobserved_gap_min` and
`chain_break_rate`, named for what it actually is. It is a data-quality signal the
streaming replay (W5) will need — a replayed trip jumps facilities on 13.5% of
handoffs — and it is **not** the hub dwell number.

The measurable friction is within the leg: `dwell_min = start_scan_to_end_scan −
actual_time`, the part of a leg's wall clock the shipment was not moving. Median 49
min. Verified across all 26,369 legs that `start_scan_to_end_scan` equals the OD window
to the minute and `dwell_min` is never negative.

### Two metrics that disagree, so the choice is explicit

`dwell_min` correlates **0.54** with the leg's wall clock — ranking hubs by raw minutes
partly ranks them by how long their legs happen to be. The scale-free alternative is
`dwell_share = dwell_min / start_scan_to_end_scan` (median 0.35: a third of a typical
leg's clock is stationary). The two rankings agree on only **8 of the top 20**
supported hubs; rank correlation 0.49.

**Decision: `friction_rank` is assigned on `dwell_share`**, because it compares hubs
serving short and long corridors on the same basis. Raw minutes stay in the table
beside it — they are what a customer actually waits, and the report needs both.
`dwell_share` is mildly *negatively* correlated with leg length (−0.28), which is what
a roughly fixed per-leg hub cost looks like.

### Attribution and support

A leg's idle minutes cannot be split between its origin and destination from leg-grain
data. Both ends are credited, reported separately as `*_out` and `*_in`. That split is
not decoration: across supported hubs the two series correlate only **0.41**, so a hub
can be slow to dispatch and quick to receive.

**Support threshold: 30 outbound legs**, mirroring D-004 for corridors. That leaves
**121 of 1,657** facilities ranked. Unsupported hubs keep their statistics and get a
null `friction_rank`, so nothing is hidden and nothing unreliable is ranked.

**For Lahari:** the ranking metric is yours to confirm for the audit writeup — the
table carries both, so switching costs a sort, not a re-run.

---

## D-016 · Cached Parquet has a frozen contract, and versions are added, never repointed — `DECIDED`
**Week 2 · Mounika**

`src/pipeline/contracts.py` freezes the exact column set, per-column Spark type,
partition columns, key, and row count of `clean_v1`, `trips_v1` and `hubs_v1`.
`python -m src.pipeline.contracts` verifies the caches against it and exits non-zero
on any difference.

**Why a column that was *added* is also a breach:** three people read these caches
concurrently. A contract that tolerates new columns silently is not a contract, and an
added column means the shape changed — which is exactly what a reader needs told.

**Versioning rule.** When a stage's output changes shape: add `CLEAN_V2` (etc.) to
`config.py`, add a new `Contract` with `version=2`, and move the stage's default
`--output`. **Never repoint an existing version.** Teammates' in-flight work keeps
reading what it was written against, and the check keeps passing for both.

The frozen row counts make this a regression test on the pipeline, not only on its
column names: the raw CSV is pinned by SHA-256, so identical code over identical input
must produce identical counts. Verified to catch renamed columns, type drift, dropped
columns, changed row counts and broken keys — with no false alarm on the real caches,
and a *skip* rather than a failure for a dataset a teammate has not built yet.

---

## D-017 · The mock TMS validates like a real one, and its facilities are real — `DECIDED`
**Week 2 · Mounika**

The TMS (`src/tms/`, FastAPI + SQLite) is synthetic scaffolding, declared as such. Two
choices in it are load-bearing for later weeks:

**Facilities are seeded from the network data**, all 1,657 centre codes from `hubs_v1`,
carrying each hub's friction rank. So an order the Order Entry Agent files in Week 5
names a centre that exists in the corridor audit, and the Week 6 Invoice Auditor can
ask what that corridor should have cost. It falls back to the committed 121-hub CSV so
a fresh clone gets a working TMS before the caches are built.

**It rejects.** Unknown centre code, origin equal to destination, non-positive weight,
arrival before departure, a second shipment on one order, a cancelled order being
reopened — all refused, with the offending value named in the message so the agent's
clarification path has something to quote. *A stub that always returns 200 would make
the Week 5 and 6 agent evaluation meaningless: the numbers are only worth reporting if
the agent could have failed.*

**Idempotency is in the API, not left to the agent.** `POST /orders` with a repeated
`external_ref` returns the existing order with HTTP 200 and `idempotent_replay: true`.
An agent reading an inbox *will* retry and mail *will* be redelivered; making each
agent solve that separately is how a demo ends up with duplicate orders.

Auth is off until `TMS_API_KEY` is set, then required on everything except `/health` —
the Week 6 boot script waits on `/health` and should not need a key to learn the
service is up.

---

## Open items carried into Week 2

| Item | Owner | Blocks |
|---|---|---|
| **D-003** — delay threshold / regression-first framing | Lahari | Week 3 features, Week 4 models |
| D-004 revisit — support vs coverage, on real test results | Lahari | Week 2 audit writeup |
| City-name normalisation table for the India map (`Bangalore`/`Bengaluru`, `MAA`, `FBD`) | Krishna | Week 2 map |
| JDK 17 + winutils on Lahari's and Krishna's machines (D-012) | all | their local Spark runs |
| Second LLM key in `.env` so `with_fallback` has somewhere to fall | Krishna | Week 7 eval runs |
