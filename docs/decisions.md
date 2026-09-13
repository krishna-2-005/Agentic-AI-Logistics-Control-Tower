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

## D-003 · Delay label threshold — `DECIDED`
**Week 1 · raised by Lahari · closed at the Week 2 sync, all three agreed**

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

**Decided: all three recommendations are adopted.**

1. `config.DELAY_THRESHOLD = 2.00`. The label is now "took at least twice the planned
   time", which splits the legs 49.6 / 50.4 and is defensible as *operationally late*
   on a network whose median leg already runs at 2.00× plan.
2. **The project leads with regression.** The headline result of Week 4 is MAE on
   `gap_min` against OSRM's MAE — a comparison with no threshold in it at all.
   Classification is the secondary framing, kept because Week 6's Exception Agent needs
   a flag to act on, not because it is the stronger result.
3. **The majority-class rate is reported beside every classifier metric, permanently.**
   At T = 2.00 that is 50.4%, so an accuracy of 0.72 now reads as what it is. This is a
   rule for the report and the paper, not a one-off caveat.

**Why 2.00 and not 1.50.** 1.50 leaves 83.6% positive — better than 93.6% and still a
classifier that can score in the eighties by answering "delayed" every time. The
threshold is chosen to make the *label* informative, not to make the network look
better or worse than it is; on this data the balanced point and the defensible English
sentence happen to be the same number, which is the only reason to prefer a round 2.00
to a tuned one.

**What it does not change.** The Week 1 finding stands exactly as written and is the
reason for this decision: at the blueprint's 1.25, **93.6% of legs are labelled
delayed**. That number stays in `results.md` and in the paper, because a reader has to
see why the threshold moved. The full sweep is in
`benchmarks/raw/w1_delay_threshold_sensitivity.csv` and nothing about it was recomputed
— only which row the project builds on.

**Carried to Week 5:** the sensitivity run is extended to 1.15 / 1.25 / 1.50 / 2.00, so
the choice is shown to be a choice rather than a hyperparameter nobody revisited.

Evidence: `docs/W1_lahari_data_dictionary_and_eda.md` §3,
`benchmarks/raw/w1_delay_threshold_sensitivity.csv`.

---

## D-004 · Minimum corridor support for the audit — `SUPERSEDED by D-018`
**Week 1 · Lahari**

Corridors with fewer than **30 observed legs** are excluded from the Stage 3 audit.

**Why:** a "worst corridor" ranking over 2,783 corridors, most seen once or twice,
ranks noise. 30 legs is the smallest support at which a Welch t-test on log-ratios is
worth reporting.

**The cost, stated openly:** 30 legs retains 99 of 2,783 corridors (3.6%) covering
18.9% of legs. **The audit is therefore a claim about the busy core of the network,
not about the whole of it, and the report must say exactly that.** A threshold of 10
legs would retain 40.6% of corridors and 78.6% of legs with weaker per-corridor tests.

**Revisited at the Week 2 gate, on results.** The audit was re-run end to end at each
threshold — aggregate, Welch, and a fresh BH correction over whatever family the
threshold defines — and the trade-off is not the one this entry assumed. The share of
tests that come back significant barely moves between 10 and 30 legs (70% against 71%),
so the looser threshold is not buying significance with noise; what the 30-leg floor
costs is the finding itself. The worst corridor at 30 legs runs 1.92× the network's
typical overrun, at 10 legs it runs 13.9×. The genuinely broken corridors are mostly
rare corridors, and the floor removes them before the test runs.

`MIN_CORRIDOR_SUPPORT` moved to 10 at the Week 2 sync — see **D-018**, which carries the
decision and the caveats it commits us to. This entry is left as written, per the rule at
the top of this file: the reasoning for a 30-leg floor is still sound reasoning, and the
report needs to be able to reconstruct why the project believed it.

Evidence: `docs/W2_lahari_corridor_audit.md` §4,
`benchmarks/raw/w2_support_sensitivity.csv`.

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

## D-019 · The map places a corridor by centre code, not by facility name — `DECIDED`
**Week 2 · Krishna · forced by D-018**

Corridor **position** on the India map comes from the six-digit PIN inside the centre
code (`IND282002AAD` → 282002 → Agra). The facility name is used only for the **label**
on the bubble. `src/dashboard/reference/centre_coords.csv` holds one row per centre,
generated once by `python -m src.dashboard.build_centre_coords` and committed; the
dashboard reads the CSV and never the generator (D-009).

**Why it had to change.** The name-based lookup was fine for the 99 metro corridors
D-004's floor allowed. D-018 widened the audited set to 1,130 corridors reaching 139
towns the hand-maintained table had never heard of, and the map dropped to placing
**101 of 273 bottlenecks** — with no error, because an unplaceable corridor is simply a
dot that never appears (P-24). A hand-maintained city list cannot follow the audit
wherever the audit goes; a centre code can.

**This is D-002's reasoning applied to geometry.** Corridors are keyed on centre codes
because names are null on 554 rows and spelled several ways. Placement had been left on
names anyway, which is why the same class of bug surfaced twice (P-21, P-23) before it
surfaced fatally. **Names are for reading, codes are for geometry.**

| Route | Centres placed |
|---|---|
| PIN inside the centre code (GeoNames) | 1,605 of 1,657 — 96.9% |
| Facility-name fallback, hand table | the remaining 52, whose PIN is `000000` or absent from postal data |
| **Audited corridors placed** | **1,130 of 1,130; 273 of 273 bottlenecks** |

**The fallback is kept, not retired.** `IND000000ACB` is a working Gurgaon centre with
a placeholder PIN — the publisher uses `000000` on real facilities, so the code cannot
be the only route. The page reports whatever neither route places, by facility name, so
the next gap is loud rather than silent.

**Third-party data, declared.** Coordinates are GeoNames postal data for India,
**CC BY 4.0**, attributed in `data/README.md` and on the map page itself. `pgeocode` is
in `requirements.txt` under reference-data tooling, needs the network only when the
table is rebuilt, and is never imported by the dashboard.

**One data-quality finding fell out of it:** `IND68004AAA` carries a **five**-digit PIN,
so D-011's `IND` + six digits + three characters shape is not universal. The generator
reports codes that do not match rather than skipping them silently.

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

## D-015 · Hub friction is measured *within* legs, and ranked on dwell share — `DECIDED (ranking metric confirmed at W2)`
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

### Confirmed in the Week 2 audit — Lahari

`dwell_share` stands. The confirmation is not a re-argument of the reasoning above: the
two metrics were scored against a column **neither of them is built from**, the corridor
audit's `excess_ratio`, over the 119 supported hubs that appear as an origin in the
audited set. Raw `dwell_min` correlates **+0.55** with how long a hub's legs are
*planned* to take, so a leaderboard on minutes would substantially be a leaderboard of
hubs serving long legs — this entry's suspected confound, now measured from outside
rather than argued. `dwell_share` runs **−0.30** against the same column.

**A second result that was not expected here: hub friction is not corridor friction.**
Neither metric tracks the overrun of the corridors leaving the hub (−0.05 for share,
−0.00 for minutes). Idle time at a facility and the planner being wrong about the road
between facilities are close to independent on this network, so the India map and the
hub leaderboard are two separate claims and must not be presented as one, and Week 3
should carry hub friction as its own feature rather than assume corridor history
already contains it.

Evidence: `docs/W2_lahari_corridor_audit.md` (hub-ranking section),
`benchmarks/raw/w2_audit_report.json` → `hub_metric_check`.

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

## D-018 · Lower the audited-corridor support floor to 10 legs — `DECIDED`
**Week 2 · raised by Lahari · agreed by all three at the Week 2 sync · supersedes D-004**

D-004's 30-leg floor was set in the abstract, before any significance test existed. Now
that one does, the whole audit re-run at each threshold says the floor is not trading
power for coverage — it is removing the bottlenecks.

| Min legs | Corridors tested | % of legs covered | % of tests significant | Bottlenecks | Worst excess ratio |
|---|---|---|---|---|---|
| **10** (recommended) | 1,130 | **78.6%** | 70% | 273 | **13.9×** |
| 20 | 268 | 33.4% | 74% | 78 | 4.08× |
| **30** (D-004, current) | 99 | **18.9%** | 71% | 34 | **1.92×** |
| 50 | 33 | 9.8% | 70% | 11 | 1.54× |
| 100 | 8 | 3.5% | 88% | 1 | 1.17× |

**Recommendation: move the audited set to 10 legs, and print the leg count in every
ranked row.** Welch is valid at n = 10, the comparison group is the whole 26,369-leg
network either way, and the significant share barely moves — so the extra corridors are
not noise passing a weaker test. What they are is the finding: at 30 legs the audit
speaks for 18.9% of the network and its worst corridor runs 1.92× the network's typical
overrun; at 10 it speaks for 78.6% and the worst runs 13.9×.

**The one real cost, stated so the sync can weigh it.** Winner's curse at the top: with
1,130 corridors tested, the single largest `excess_ratio` is the likeliest of all of
them to be a lucky sample, so the first few rows of the loose table are provisional in
a way the 30-leg table's are not. The leg count in every row is what lets a reader see
that; a top-20 map built off the loose table should carry it too.

**Decided: the floor moves to 10.** `config.MIN_CORRIDOR_SUPPORT = 10`, and the audit
was re-run end to end at it. The Week 2 headline is now **273 bottlenecks and 512
significantly faster corridors of 1,130 tested, covering 78.6% of the network's legs,
worst corridor 13.88×** — Kanpur → Kanpur, on 13 legs.

D-004 is **superseded, not overturned.** Its reasoning — that ranking 2,783 mostly
singleton corridors ranks noise — still holds, and a floor is still needed. What the
sweep showed is that the floor was one notch higher than the thing it was built to
find.

**Three things the decision commits us to, because the cost is real:**

1. **Every ranked row prints its leg count.** With 1,130 tests in the family, the
   single largest `excess_ratio` is by construction the likeliest of all of them to be
   a lucky sample. The leg count is what lets a reader discount a 13.9× on 13 legs
   against a 1.5× on 100.
2. **The 30-leg audit stays, as `benchmarks/raw/w2_corridor_audit_support30.csv`.**
   Not as an archive — as the comparison view whose top rows carry no winner's curse
   worth naming. A claim that survives both tables goes in the paper; a claim that
   appears only at the top of the loose table is a lead.
3. **Both tables are cited in the report, because they describe different networks.**
   This was not anticipated when the recommendation was written and is the most
   interesting thing to come out of it: *the two top-20 tables share no corridor at
   all.* The 30-leg table is metro — Maharashtra 11 of 20, Mumbai/Bhiwandi,
   Delhi/Gurgaon, intra-Hyderabad — and reads as a story about urban congestion. The
   10-leg table is district feeders between towns — Bihar 4, Maharashtra 3, Uttar
   Pradesh 2 — Phulpur → Allahabad, Malvan → Sawantwadi, three separate corridors into
   Muzaffarpur. **What the busy core suffers from and what the network's worst
   corridors suffer from are not the same thing**, and Week 4's error analysis must not
   assume one model explains both.

**Consequences for the rest of the project.** Week 3's corridor-history feature now has
78.6% of legs with a corridor it has seen before rather than 18.9% — the single largest
gain from this decision, and it is a coverage gain, not a significance one. Week 6's
Invoice Auditor can price far more corridors from measured history. Krishna's India map
follows the CSV without a code change, but its colour ramp and its coordinate table both
needed work at the wider range — see P-22 and P-23.

Evidence: `docs/W2_lahari_corridor_audit.md` §4,
`benchmarks/raw/w2_support_sensitivity.csv`, `w2_corridor_audit_support30.csv`.

---

## D-020 · Leak-free feature pipeline: past-only history via an event-stream as-of join — `DECIDED`
**Week 3 · Mounika · closes the Week 2 open item on corridor history**

D-018's open item said it plainly: `excess_ratio` in `w2_corridor_audit.csv` is fitted
over the **whole** 26-day window, so handing it to a model as-is means training on a
column that already contains the answer for every leg it will later be scored on
(D-005). Stage 4 (`src/pipeline/features.py`) recomputes corridor, source-hub and
destination-hub history from scratch, **as of each leg's own `trip_creation_time`**,
so the number a leg sees is only ever built from legs that had already happened.

**The trap was the clock, not the aggregation.** A leg is created at
`trip_creation_time` and that is a legitimate decision point — checked across all
26,369 legs, `trip_creation_time <= od_start_time` without exception. But a *prior*
leg's outcome is not usable the moment it starts; it is usable when it **finishes**,
at `od_end_time`. Ordering a corridor's history by `od_start_time` — the natural thing
to write — quietly reads outcomes from journeys still on the road. Measured directly
rather than argued: on the naive clock, **46.4% of legs would read their own
departure as a known fact** (created and dispatched in the same second) and a further
**8.4% would be handed another journey's duration before that journey had landed**;
**48.6% of the table is affected either way.** This is logged as P-25.

**How the as-of aggregate avoids a self-join.** A per-corridor self-join with an
inequality predicate is a cross join per corridor — the busiest corridor in this data
runs 151 legs, which is 22,801 pairwise comparisons for one corridor alone, and the
cost grows with the square of traffic rather than with it. Instead every leg emits a
**fact** at `od_end_time` ("this outcome is now known") and a **query** at
`trip_creation_time` ("what was known here?"); both are unioned, partitioned by key,
ordered by `(event_time, kind)` with facts sorting first, and a running window
accumulates the fact columns up to each query row in one pass. The same shape gives
hub history by partitioning on the centre code instead of the corridor.

**What the table refuses to contain.** `actual_time`, `dwell_min`, `gap_ratio`,
`n_segments`, every `segment_*` sum, and the OD window itself are outcomes, not
features — listed in `BANNED_FEATURES`, and the writer raises rather than emits a
table containing any of them. `gap_min`, `log_gap_ratio` and `is_delayed` are carried
through only as `TARGETS` for Lahari's Week 3 baselines and Week 4 models.

**Coverage, at build time:** 88.91% of legs have at least one prior leg on their own
corridor (mean 10.77 prior legs, median 6), 93.44% have source-hub history, and the
remaining 11.09% are a corridor's genuine first sighting — nulled, not defaulted to
zero, so a model can tell "never seen" from "seen and calm" (D-018's wider 10-leg
floor is what makes 88.91% possible at all; at the old 30-leg floor's 18.9%-of-legs
coverage this number would be far lower).

**Both hub ends get history, closing D-015's open note.** Week 2 found hub friction
and corridor friction are close to independent (`docs/decisions.md` D-015) and said
Week 3 should carry hub friction as its own feature rather than assume corridor
history already encodes it. `src_*` and `dst_*` columns are the same as-of join
partitioned on `source_center`/`destination_center`, so the feature table carries all
three histories side by side rather than one standing in for the others.

**Frozen as `features_v1`, versioned like every other cache (D-016).** `leg_id`
(`trip_uuid|od_start_time|corridor_id`) replaces `trips_v1`'s three-column key because
a trip can legitimately repeat a corridor on a different day and the key needs the
departure time to stay unique. Registered in `src/pipeline/contracts.py` as a new
`Contract`; `python -m src.pipeline.contracts --keys` passes at 26,369 rows, 33
columns, same grain as `trips_v1` — no leg is dropped by this stage.

Evidence: `docs/W3_mounika_feature_pipeline_and_tms.md`,
`data/processed/features_v1/_feature_report.json`, `tests/test_features.py`.

---

## D-021 · Document chain and GSTIN shape for the synthetic corpus — `DECIDED (confirmed by Lahari)`
**Week 3 · Krishna**

Two calls W2 §4 left open for the sync: whether the document set generates chains
independently or with deliberate mismatches, and whether synthetic GSTINs should be
checksum-valid or obviously fake. The execution plan puts the seeded-error taxonomy
jointly with Lahari (W3 D3-D4, D5); this entry was Krishna's half of that, built and
run solo, and carried the same provisional status D-014 held until Lahari confirmed
it below.

**Proposed, and what the generator currently does:**

1. **One `ConsignmentRecord` backs both the BOL and the invoice**, never generated
   independently — W2 §4's own finding was that independent generation makes
   cross-document consistency unevaluable. `seed_errors.py`'s `corridor_mismatch` kind
   then deliberately breaks that agreement on a minority of records, rather than the
   two documents never agreeing to begin with.
2. **GSTINs are shape-valid, not checksum-valid.** Right length, right character
   classes, a real state-code prefix drawn from the consignment's own state — but the
   final checksum character is random, not computed, so nothing generated here could
   be mistaken for a real, checkable GSTIN. Declared as scaffolding, the same word
   D-017 uses for the mock TMS.
3. **A five-kind seeded-error taxonomy at a 15% rate** — `total_mismatch`,
   `duplicate_document_number`, `corridor_mismatch`, `ocr_confusable_corruption`,
   `missing_field` — each chosen to exercise a rule already written into
   `doc_extraction/v1.md` rather than an arbitrary corruption. Detail and counts on
   the 120-document run: `docs/W3_krishna_doc_corpus.md` §3.

**Why this needed Lahari's sign-off before Week 4 relies on it.** She evaluates every
agent Krishna builds by design (execution plan §2, "keeps builder and judge
separate"); a seeded-error taxonomy the builder chose alone is exactly the kind of
thing that evaluation separation exists to catch problems with.

**Lahari's confirmation (W3 D5).** All three proposed points are sound and stay as
written: one shared record backing both documents is the only way `corridor_mismatch`
means anything (§1 above), GSTINs declared as shape-only scaffolding is the right call
for the same reason D-017 scaffolds the mock TMS, and five kinds each tied to a named
`doc_extraction/v1.md` rule is a taxonomy that tests the prompt rather than an
arbitrary corruption grab-bag. Confirmed with one fix and one caveat carried forward:

- **`total_mismatch` printed a negative invoice total on one of the five generated
  instances** (`w3_00059`, freight+other = 259.07, printed total = -116.40) — its
  fixed `+/-50..500` rupee delta was never checked against this network's smallest
  Carting shipments, where `total_amount` itself can be under that range. Fixed to a
  percentage of the invoice's own total (5-30%, either sign), which cannot cross zero
  at this magnitude; the corpus was regenerated and every other record's assigned
  error kind is unchanged (same two `rng` draws, same stream position). Logged as
  P-27.
- **Carried as a caveat, not a blocker, for Week 4's evaluation writeup:** at 120
  documents and five kinds sampled independently at 15%, `corridor_mismatch` landed on
  only 2 of 120 records. A per-kind accuracy claim at that count is anecdotal in
  exactly the way D-004's 30-leg floor was before D-018 — Week 4 should report
  per-kind detection counts alongside accuracy, not accuracy alone, and treat any
  single-digit-count kind's number as a lead rather than a result, the same reading
  D-018 gives a bottleneck resting on 10 legs.

Evidence: `docs/W3_krishna_doc_corpus.md`, `src/agents/doc_corpus/seed_errors.py`,
`benchmarks/raw/w3_doc_corpus_manifest.csv`, `docs/problems.md` P-27.

---

## Open items carried into Week 3

Week 2's two blocking decisions (D-003, D-018) are both closed above. What remains is
carried forward with an owner and a named blocker — nothing is closed by silence.

| Item | Owner | Blocks |
|---|---|---|
| **One canonical city-alias table.** `src/ml/audit.py:CITY_ALIASES` and `src/dashboard/reference/india_city_coords.csv` now carry the same aliases in two places and can drift — they already did, at the 10-leg floor (P-23). Merging them means a shared reference neither the audit nor the dashboard owns. | Lahari + Krishna | nothing yet; a silent map gap when either list moves |
| **Null `source_city` / `dest_city` in `clean_v1`** for `Mumbai Hub (Maharashtra)`-shaped facility names. The map works around it (P-21); the cache still carries it, and anything else joining on those columns will hit it. Fixing at source is a `clean_v2` under D-016's versioning rule. | Mounika | any Week 3 feature keyed on city |
| ~~**Corridor history must be computed past-only.**~~ Resolved by **D-020** — `src/pipeline/features.py` recomputes it as of each leg's own creation time. | Mounika | — |
| **Week 4 error analysis splits the two audit views.** D-018 found the 10-leg and 30-leg top tables share no corridor; the per-corridor claim has to say which set it is evaluated on. | Lahari | Week 4 headline |
| JDK 17 + winutils on Lahari's machine (D-012) | Lahari | her local Spark runs |
| Second LLM key in `.env` so `with_fallback` has somewhere to fall | Krishna | Week 7 eval runs |
| Weekly dashboard screenshots in `demo/screenshots/` (GIT_RULES §3) — none captured for W1 or W2 | Krishna | Week 8 demo assets |

---

## D-022 · Baseline train/test split fixed at the 80th percentile of `trip_creation_time` — `DECIDED`
**Week 3 · Lahari · fixes the split D-005 deferred**

D-005 decided the split would be time-based rather than the dataset's own `data`
column, and left the exact cut to whichever week first trains something. That week is
this one: the split is the 80th percentile of `trip_creation_time` over the
26,369-leg `features_v1` table — 21,095 training legs (`trip_creation_time` <=
2018-09-28 23:12:35 UTC), 5,274 held out.

**Why a quantile and not a fixed date.** A fixed date only matches this exact extract;
a quantile is the thing Week 4 actually needs to reproduce — the *fraction* held out —
regardless of small changes upstream. And why chronological rather than random: the
model this project cares about is deployed once and predicts forward, so a random
split scores it on legs mixed in time with the ones it trained on, which is not how it
will ever run.

**Why this cannot leak despite reusing D-005's reasoning almost verbatim.** Every
as-of feature in `features_v1` (Stage 4) is already computed relative to each leg's
own `trip_creation_time`, so no choice of split boundary can hand a training leg a
feature built from a leg that is, in the deployed sense, in its future. The split only
decides which legs the *baselines and Week 4's models* are fitted and scored on — it
is not load-bearing for the feature table's own leakage guarantee.

**Binding on Week 4.** `src.ml.baselines.time_split(frac=0.80)` is the one function
Week 4 imports rather than reimplements. A "beats these baselines" claim is only true
if the comparison model saw the same 21,095 training legs and was scored on the same
5,274 held out.

Evidence: `docs/W3_lahari_baselines.md` §1, `benchmarks/raw/w3_baseline_report.json`.

---

## D-023 · Cold-start corridor/hub history gets an explicit indicator, not a silent zero — `DECIDED`
**Week 3 · Lahari**

11.09% of legs are a corridor's first sighting (`corr_n_prior == 0`; 6.56% / 6.33% for
source / destination hub) and Stage 4 correctly leaves their `*_mean_log_ratio`,
`*_mean_gap_min`, `*_last_log_ratio` and `*_hours_since_last` null — there is nothing
to report. `LinearRegression` cannot take a null, so those columns are filled with 0,
but paired with a `{corr,src,dst}_is_cold` indicator, and `*_std_log_ratio` is
additionally filled on the single-observation case (`n_prior == 1`; variance needs two
points).

**Why the indicator is not optional.** A silent `fillna(0)` on `corr_mean_log_ratio`
alone would tell the model "this corridor runs exactly on plan" for a corridor it has
never seen — the opposite of not knowing, and a systematic bias toward under-predicting
the gap on exactly the legs with no evidence either way. The indicator lets the model
separate "no history, filled with 0" from "history says 0", and
`prepare_model_features()` asserts on every run that no column is null anywhere the
cold flag does not already explain, so a change to Stage 4's null contract fails loudly
here rather than silently degrading the fit.

**The corridor-mean baseline handles the same 11.09% differently, deliberately.** It
falls back to OSRM's own prediction (zero gap) rather than a filled mean, because that
baseline has no coefficients to carry an indicator through — falling back to the
*other* baseline already in the table is the only choice that does not smuggle in a
third, unnamed baseline under the corridor-mean's name.

Evidence: `docs/W3_lahari_baselines.md` §2,
`data/processed/features_v1/_feature_report.json` (`pct_cold_start` 11.09).

---

## D-024 · Week 4 is judged on MAE, not RMSE or R2 — `DECIDED`
**Week 3 · Lahari · forced by a real disagreement between the two**

The Week 3 linear regression scores worse than the much simpler corridor-mean baseline
on MAE (41.2 vs 36.1 min) while scoring *better* on RMSE (96.8 vs 101.7) and R2 (0.811
vs 0.791) — the two families of metric rank the same two models in opposite order, on
the same test split. This is not a bug in either model: OLS minimises squared error,
which is RMSE and R2's objective and not MAE's, and the network's own heavy-tailed
corridors (up to 13.9x per D-018) are exactly the shape of data where that distinction
shows up — a few extreme legs are worth trading a little bias on ordinary legs to fit
under a squared loss, and worth nothing under an absolute one.

**Decided: `benchmarks/ml_results.md`'s baseline table, and every Week 4 comparison
against it, ranks on MAE.** It is the metric the table was already reporting before
this conflict surfaced, and it is the one a plain reading of "average error in minutes"
means. RMSE and R2 are still reported beside it as diagnostics — the disagreement
itself is informative, per this entry — but they do not decide which model is called
better.

**Consequence for Week 4.** A Random Forest or GBT that improves RMSE without
improving MAE over the corridor-mean baseline is not a result. Both metrics go in the
report for every model, exactly as this entry's numbers do, so the choice is visible
rather than assumed.

Evidence: `docs/W3_lahari_baselines.md` §3, `benchmarks/raw/w3_baseline_metrics.csv`.

---

## D-025 · Delay classifier v1 is logistic regression, scored beside every model's implied threshold call — `DECIDED`
**Week 3 · Lahari**

The execution plan's W3 D3-D4 asks for a delay classifier and an evaluation harness
computing precision/recall/F1 for every model, alongside the MAE/RMSE regression
table D-022 through D-024 already closed. `is_delayed` is D-003's label, unchanged:
`actual_time > 2.00x planned_min`, 49.7% positive over all 26,369 legs — close enough
to even that D-003's own concern (report the majority rate beside every classifier
metric, permanently) actually bites here, unlike at the blueprint's 93.6%-positive
1.25 threshold.

**Decided: logistic regression over the same `FEATURES` as the Week 3 linear
regressor is delay classifier v1**, and every regression baseline in the table — OSRM,
corridor mean, linear regression — gets its classification score by thresholding its
own `gap_min` prediction against the identical rule the label is built from
(`threshold_to_label`), rather than fitting a second, separately-calibrated model
under each baseline's name. `LogisticRegression`'s solver needed the features
standardised first (`StandardScaler` in a pipeline) to converge — `FEATURES` mixes
minutes, kilometres and 0/1 indicators on scales OLS's closed-form fit above never had
to care about.

**Result: the fitted classifier is the strongest model in the table, and the
corridor-mean threshold is close behind on a different trade-off.** Logistic
regression reaches 0.764 F1 on test (0.761 precision, 0.767 recall) against the
majority class's 0.000; thresholding the corridor mean reaches 0.762 F1 with more
recall (0.831) and less precision (0.704). `OSRM`'s threshold and the majority class
make the identical degenerate call — "not delayed" for every leg — since OSRM's own
estimate never disagrees with itself by 2x. Unlike D-024, MAE and F1 do not disagree
about which model is better here: logistic regression is not the same object as the
linear regressor (it is fit on `is_delayed` directly, not thresholded from `gap_min`),
so this is a separate result rather than the same finding restated.

**Consequence for Week 4.** Random Forest and GBT owe this same classifier table,
scored with `add_delay_label` and `threshold_to_label` rather than a redefined label —
the model to clear is logistic regression's 0.764 F1, not the majority class's 0.000.

Evidence: `docs/W3_lahari_baselines.md` §5, `benchmarks/raw/w3_classifier_metrics.csv`,
`w3_baseline_report.json`.

---

## D-026 · Random Forest and GBT are trained through real MLlib, not scikit-learn — `DECIDED`
**Week 4 · Lahari**

Week 3's baselines (`src.ml.baselines`) fit their linear/logistic models in
scikit-learn on purpose, arguing that 26,369 rows is not a distributed workload and
scikit-learn would not distribute it even if it were. That argument does not carry
over to this stage. `README.md`'s architecture and its own resume-line claim are
specifically "trains MLlib models that outperform that planner" — this is the one
stage where that has to be literally true, not merely compatible with being true. So
Random Forest and GBT are trained through `pyspark.ml` (`RandomForestRegressor`,
`GBTRegressor`) in a real MLlib `Pipeline`, tuned via MLlib's own `CrossValidator`, per
the "Honest scope" defence the README already makes for the rest of the batch layer.

**What does *not* move into Spark: the split, the cold-start fill, and the
`{corr,src,dst}_is_cold` indicators.** `time_split` and `prepare_model_features`
(`src.ml.baselines`, D-022/D-023) are imported, not reimplemented in Spark SQL.
Rebuilding D-023's null-handling policy a second time is the exact shape of the trap
P-23 already cost this project once — two lists holding one truth, which had already
drifted by the time it was noticed. `features_v1` is 26,369 rows; collecting it once
to pandas for the split and the fill, then handing the prepared frames to Spark only
for the model fit and the hyperparameter search, is the one division of labour that
does not duplicate anything.

**Why k-fold CV over the training rows does not reopen D-022's leakage question.**
D-022 argued that no choice of split boundary can leak, because every as-of feature in
`features_v1` is already computed relative to each leg's own creation time — the
guarantee lives in the feature table, not in how its rows are partitioned. That
argument is general, not specific to an 80/20 cut: it applies equally to a k-fold split
of the training rows for hyperparameter selection. `CrossValidator` below folds only
the 21,095 training legs the test set never touches, and Spark's own contract for
`CrossValidator.bestModel` refits the winning hyperparameters on the entire training
set before this module calls `.transform()` on it.

**Result, reported as it stands.** Random Forest is the stronger of the two Week 4
models (36.9 min MAE on test vs GBT's 38.3), and both comfortably beat OSRM (107.1) and
the linear regressor (41.2) — but **neither clears the corridor-mean baseline's 36.1
min**, the number D-024 already fixed as what Week 4 actually has to beat. This is not
reframed around RMSE or R2 (Random Forest's are the best in the table: 93.2 min RMSE,
0.824 R2): D-024 decided MAE is what ranks these models, and a tuned tree ensemble
trailing a single per-corridor average by 0.8 min is the honest result, not a headline
to round away. Per-corridor, Random Forest still improves 1,369 of 1,646 test corridors
over OSRM (83%), so the network-wide number is not hiding a model that only helps a
handful of corridors — see `docs/W4_lahari_beat_osrm.md` §2.

Evidence: `docs/W4_lahari_beat_osrm.md`, `benchmarks/raw/w4_model_metrics.csv`,
`w4_corridor_gains.csv`, `w4_feature_importances.csv`, `w4_cv_report.json`,
`w4_model_report.json`, `docs/problems.md` P-30.

---

## D-027 · Ablations refit at the already-tuned hyperparameter point, not a fresh grid search per feature block — `DECIDED`
**Week 4 · Lahari · D3-D4**

The execution plan asks D3-D4 to check two blocks of `FEATURES`: corridor-history
(`corr_*`) and temporal (`created_hour`/`created_dayofweek`/`created_is_weekend`). The
question an ablation is actually answering matters for how expensive it has to be:
**"what does this block cost the model D1-D2 already tuned"** is a different, far
cheaper question than **"what is the best model without this block"** — the second
needs its own `CrossValidator` grid search per ablation (roughly tripling D1-D2's
Spark cost for a number nothing downstream reads), the first needs one fit per
ablation at the hyperparameters `w4_cv_report.json` already recorded.

**Decided: `fit_fixed_mllib_model()` refits once per (model, ablation) pair at the
already-tuned `best_params`, no `CrossValidator`.** Six fits total (2 models × 3
configs: full, drop-corridor-history, drop-temporal) rather than 24 (2 models × 3
configs × the D1-D2 grid), and the result answers the question D3-D4 actually asks —
whether a block earns its keep at the model this project is actually shipping, not at
some other, unshipped hyperparameter point a second search might have preferred for a
smaller feature set.

**Result: the corridor-history block dominates, on both models — confirming D1-D2's
feature-importance ranking against a real refit rather than reading it off the fitted
model's internal split statistics alone.** Dropping `corr_*` costs Random Forest 3.30
min MAE and GBT 2.43; dropping the three temporal columns costs 0.11 and 0.72
respectively — a real but much smaller effect. A high split-based importance and a
high held-out MAE cost are not guaranteed to agree (a feature can look important to
the fitting algorithm's internal bookkeeping without actually being load-bearing for
generalisation); here they do, which is itself worth stating rather than assuming.

**What this does not test.** An "FTL vs Carting separately" ablation was floated
speculatively in `benchmarks/ml_results.md` at the Week 3 close but is not part of the
execution plan's actual D3-D4 line and was not run — noted there as an open idea
rather than silently implied by this entry's results.

Evidence: `docs/W4_lahari_beat_osrm.md` §6, `benchmarks/raw/w4_ablations.csv`.

---

## D-028 · Document-extraction F1 is micro-averaged over (document, field) pairs, and a null prediction is neither a hit nor a miss — `DECIDED`
**Week 4 · Lahari · D5**

The first Layer 2 evaluation number this project has produced. `src/ml/doc_eval.py`
scores Krishna's predictions files against the Week 3 ground-truth labels, never
importing `src.agents.document_agent` beyond reading the JSON it already wrote — the
execution plan's "keeps builder and judge separate" applied literally, not just in
spirit.

**Micro-averaging, not per-document-then-averaged.** Precision/recall/F1 are computed
by pooling true/false positives and false negatives over every (document, field) pair
in the scored set, then computing one P/R/F1 from the pooled counts — not by scoring
each document separately and averaging document-level F1 scores. A macro average
would let a document with fewer populated fields (a BOL's two always-null fields)
count exactly as much as a fully-populated invoice; pooling first means every field
extraction counts the same regardless of which document it came from.

**A field is a true positive only when the true value is non-null and the prediction
matches it exactly.** Correctly returning null on a field the document genuinely does
not carry (a BOL's `total_amount`, rule 1's "never invent a value") is excluded from
precision/recall entirely — not rewarded as a hit, not penalised as a miss. Verified
this is not a coincidence of how the numbers happened to land: the **null baseline**
(predict nothing, ever) scores exactly **0.000 F1** here, which is what a trivial
extractor scoring against a well-posed metric should score — the same "report the
majority-class rate beside every classifier metric" instinct D-003 established,
applied to an extraction task's own degenerate baseline.

**Result: v1 scores 0.853 F1, v2 scores 0.929**, each against the documents that
version's quota-capped run actually produced (D-032) — not the identical sample in
both cases, so this is not a perfectly controlled before/after on the exact same
documents (D-033's smaller, paired 16-document comparison is that view; this is the
full-coverage view). Per-field detail lives in `docs/W4_lahari_beat_osrm.md`'s
doc-eval section, not repeated here.

**What this entry could not do, stated rather than silently skipped.**
`agent_evaluation.md`'s own recording rules ask for a trivial *regex* baseline beside
the metric, which would say more than "predict nothing" does about the fixed-shape
fields (`document_number`, the two centre codes) D-033's v2 prompt specifically
targets. `document_agent.run_corpus` does not persist the raw OCR text in its
predictions file, only a character count, so a regex-on-OCR-text baseline cannot be
computed from what exists today — carried forward as an open item for whoever next
touches that module, not implied to have been checked.

Evidence: `src/ml/doc_eval.py`, `tests/test_doc_eval.py`,
`benchmarks/raw/w4_doc_eval_field_accuracy.csv`, `w4_doc_eval_summary.json`,
`benchmarks/agent_evaluation.md`.

---

## D-029 · Auto-retraining skips a cached stage rather than always rebuilding, and champion swap is a strict MAE improvement — `DECIDED`
**Week 4 · Mounika**

`src.automation.retrain` (execution plan W4 D1-D2) is the one command that runs
clean → reconstruct → hubs → features → train → evaluate → champion/challenger swap.
Two design calls in it are load-bearing enough to record.

**A stage runs only if its frozen output does not already exist.** D-016 versions
`clean_v1` / `trips_v1` / `hubs_v1` / `features_v1` precisely so a schema change adds a
new version rather than silently repointing one — an "auto-retraining" script that
rebuilds all four Spark caches from raw on every invocation would defeat that: it would
turn a scheduled or triggered retrain into a scheduled full reprocessing job, at whatever
cost Stage 1-4 take on 145K raw rows, for no reason on a day nothing upstream changed.
`--force-rebuild` is the explicit escape hatch for "the raw data actually changed, start
over" — the default is not.

**Each pipeline stage runs as its own subprocess, not an in-process import.** Every
stage module (`src.pipeline.clean`, `.reconstruct`, `.hubs`, `.features`) opens and
stops its own `SparkSession`. Importing four of them into one Python process and
calling their `main()`s in sequence would mean reasoning about whether a second
`get_spark()` call inside the same process returns the first stage's still-open
session or conflicts with it — `src.common.spark.get_spark()` is a module-level
singleton via `getOrCreate()`, so it would. `subprocess.run([sys.executable, "-m",
module])` gives every stage a clean JVM and a clean exit, the same isolation the stages
already have when run by hand from the command line.

**Champion swap is `challenger_mae < champion_mae`, nothing softer.** The challenger
is whichever of Random Forest/GBT `src.ml.models.run()` (Lahari's entry point, not
reimplemented here) already picked as its own winner on test MAE (D-024). No champion
on record promotes automatically — there is nothing to lose to. Otherwise the swap
requires a strictly better number, not a tie, not a percentage improvement, not human
approval: an unattended loop that requires a person to approve every promotion is not
autonomous, and a threshold looser than "better" risks a slow ratchet toward a worse
model across many small, technically-passing swaps. The promotion still leaves a
paper trail either way — `w4_retrain_history.jsonl` gets a line whether or not the
challenger won, so "the loop ran and declined to promote" is as visible as "the loop
ran and promoted."

**What the champion actually is, on disk.** `MODELS_DIR / "champion"` is a direct copy
of whichever `{name}_v1` MLlib `PipelineModel` directory won — not a JSON pointer to
it. This matches an existing convention already written into
`src/dashboard/app.py`'s artefact-status check
(`(config.MODELS_DIR / "champion").exists()`), built before this decision, for the
not-yet-built what-if predictor page (Krishna, D5) to load directly with
`PipelineModel.load()`. `champion_metrics.json` sits alongside it for this script's own
comparison logic and for a human to read without deserialising a Spark model.

Evidence: `src/automation/retrain.py`, `benchmarks/raw/w4_retrain_history.jsonl`,
`data/models/champion_metrics.json`.

---

## D-030 · Pipeline hardening: a preflight check before Spark, a bounded retry per stage — `DECIDED`
**Week 4 · Mounika · D3-D4**

D1-D2 already made `retrain.py` skip a cached stage and isolate every stage in its
own subprocess (D-029). D3-D4's "pipeline hardening" asks what happens when a stage
*fails*, which D1-D2 left as an immediate, un-retried `RuntimeError`.

**A preflight check runs before any subprocess, not after the first one fails.**
`preflight()` checks the same thing `check_env.check_java` checks — `JAVA_HOME` set
and pointing at a real JDK — and raises one clear message naming the cause if it does
not. **Found while testing this, not by inspection:** this machine's own local `.env`
(gitignored, per-machine) still carried `JAVA_HOME=C:\Users\HP\jdks\...` — the *other*
machine's path from `spark-run-environment`'s own account of Week 1-2's history —
masked only because the correct value already sits in the User-scope environment
variable and `load_dotenv()` does not override a variable that already exists. Popping
`JAVA_HOME` from `os.environ` before calling `preflight()` (simulating a shell where
that precedence does not hold) surfaced the stale value immediately, and it was
fixed on this machine's `.env` as a result — a landmine this decision's own testing
found rather than one that was ever hit for real. Without the preflight check, that
same stale value would have made all four pipeline stages fail with an identical,
unhelpful Spark bootstrap traceback instead of one line naming `JAVA_HOME`. Logged as
P-33.

**Each stage gets `MAX_STAGE_ATTEMPTS = 2` with a fixed backoff, not an unbounded
retry loop.** This project has one concrete transient failure on record — P-30's
driver-heap exhaustion during Random Forest's CV search, resolved partly by
sequential fitting and partly by the observation that memory pressure on this
machine varies with what else is open. A bounded retry gives a stage one more chance
after a transient resource squeeze without turning a genuinely broken stage (bad
code, bad input) into a long, silent hang — it will simply fail the same way twice
and raise, exactly as D1-D2's version did on the first attempt.

**Verified without re-running the batch pipeline for real.** Retrying the actual
~40-minute Spark chain twice to test a retry loop would cost 80 minutes to check
behaviour that does not depend on Spark at all. `tests/test_retrain.py` checks
`preflight()` against a missing, a present-but-empty, and a valid `JAVA_HOME`; checks
`ensure_batch_pipeline` skips an existing output without invoking anything, and
retries exactly `MAX_STAGE_ATTEMPTS` times against a deliberately-nonexistent module
before raising; and checks `promote_challenger` promotes with no champion on record,
declines a challenger that does not beat one, promotes one that does, and leaves the
champion directory untouched on a decline — all against throwaway `tmp_path`
champion/models directories, never the developer's real `data/models/champion`. The
real Stage 1-4 modules and Lahari's `run()` were already exercised end to end in
D1-D2; this entry hardens and tests the orchestration around them, not the stages
themselves.

Evidence: `src/automation/retrain.py` (`preflight`, `MAX_STAGE_ATTEMPTS`),
`tests/test_retrain.py`.

---

## D-031 · The stream event schema is D-020's fact/query design, replayed as JSON — `DECIDED (proposed; Krishna and Lahari to confirm at the Week 5 sync)`
**Week 4 · Mounika · D5**

The execution plan's D5 line asks for a stream event JSON schema, agreed with both
teammates, ahead of Week 5's Kafka producer. The design question that actually
matters is not field names — it is *what a Kafka producer replaying `trips_v1`
should emit*, and D-020 already answered a version of that question for the batch
feature pipeline.

**Decided: one topic, two event kinds — `query` and `fact` — the same two D-020
already built.** A `query` event fires at a leg's `trip_creation_time` and carries
exactly what the champion model predicts on (`route_type`, `planned_min`,
`planned_km`, `created_hour`/`created_dayofweek`/`created_is_weekend`). A `fact`
event fires at `od_end_time` and carries exactly the outcome columns D-020's
`BANNED_FEATURES` boundary already forbids a query from seeing (`gap_min`,
`log_gap_ratio`, `is_delayed`). Week 5's Structured Streaming job joins incoming
`query` events against a broadcast table built from `fact` events the same way Stage
4 already joins a leg's query against every fact that landed before it — the
streaming layer answers to the same contract the batch layer already proved leak-free
(P-25), rather than a second, independently-invented event shape for the same idea.

**Why this is not scope creep from D5's actual ask.** A schema with no connection to
how the model was trained is a schema someone will get wrong the first time the
streaming join is written — the two would drift the way `CITY_ALIASES` and
`india_city_coords.csv` already drifted once (P-23) before either list was reasoned
about to be different from the other. Reusing D-020's split by construction, not by
convention, is what keeps that from happening a second time.

**Verified against real data, not asserted on paper.** `src/streaming/schema.py
--examples` reads real rows from `features_v1`, derives each fact event's
`event_time` as `od_start_time + actual_time` (`actual_time = gap_min + planned_min`,
`src.ml.baselines`'s own `TARGET` definition) rather than approximating it, and
validates every generated event against `docs/schemas/stream_event.schema.json`
before writing it. Hand-checked one example end to end: `planned_min=46.0`,
`gap_min=101.0` → `actual_time=147` min → `od_start_time 00:02:09` + 147 min =
`event_time 02:29:09`, exactly what the module computed; `is_delayed=1` matches
D-003's `147 > 2.0 * 46` and `log_gap_ratio` matches `log(147/46)` to the printed
precision.

**Status: proposed, not confirmed.** Unlike D-021 (Krishna's seeded-error taxonomy,
confirmed by Lahari at the Week 3 sync and recorded as such), this entry has not yet
had that conversation — there is no Week 5 producer or streaming job built against it
yet for a confirmation to be about. Carried into Week 5 as the schema Krishna's
Kafka-adjacent work and Lahari's stream-equals-batch correctness test (her own
declared Week 5 task) both need to agree with before either is built against it.

Evidence: `docs/schemas/stream_event.schema.json`, `src/streaming/schema.py`,
`tests/test_stream_schema.py`, `demo/sample_events/trip_replay_sample.json`.

---

## D-032 · The Document Intelligence Agent's free-tier LLM quota is a hard daily cap, and partial coverage is reported as such — `DECIDED`
**Week 4 · Krishna**

The Week 2 sync's open-items table flagged this in the abstract: "second LLM key in
`.env` so `with_fallback` has somewhere to fall — blocks Week 7 eval runs." It arrived
three weeks early. A 40-document smoke run (20 consignments) against
`gemini-3.6-flash` succeeded on 22 documents and failed the remaining 18 on
`429 RESOURCE_EXHAUSTED`, quoting the free tier's own limit:
`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue: 20`. This is a
**daily** cap per project per model, not a per-minute rate limit `with_fallback`'s
retry logic could wait out — the run's own escalating `retryDelay`s (14s, 36s, 58s...)
show the client backing off correctly against a ceiling that does not lift again until
tomorrow.

**Decided: the agent's own error-handling already does the right thing, and stays as
built rather than gaining retry-until-tomorrow logic.** `run_corpus`'s per-document
`try/except` (not one big transaction) means a quota wall does not corrupt or abort
the run — it produces exactly what it produced: 22 real predictions and 18 documents
each recording *why* they have none, in the same predictions file. A `RESOURCE_EXHAUSTED`
entry and a `json.JSONDecodeError` entry both look like `predicted_fields: null`, which
is correct — both are "the agent could not extract this one," and Lahari's D5 harness
needs exactly that shape regardless of cause.

**Consequence for D5 and beyond.** The evaluation harness must score whatever the
predictions file actually contains and report **coverage** (documents attempted vs.
documents that produced a prediction) beside every accuracy number — the same
"majority-class rate reported beside every classifier metric, permanently" instinct
D-003 established, applied to a different kind of denominator problem. A field-level
accuracy computed only over the 22 that succeeded is not wrong, but it is silent about
being computed over 55% of the intended sample unless the harness says so. Running the
full 120-document corpus in one day is not currently possible on the configured free
tier; it either wants a second provider key (`ANTHROPIC_API_KEY`, the Week 2 open item,
finally forced rather than merely anticipated) or spreading a full-corpus run across
several days.

**What this is not.** Not a document-extraction bug, and not evidence the agent
performs badly — of the 22 attempted with a live quota, extraction succeeded on all of
them (D3-D4's prompt-iteration numbers are the ones that will say how *well*). This is
a provider-capacity ceiling, the same class of thing D-007 built `with_fallback` to
survive and the same class of thing P-35 already found once this week (a pinned model
name going stale) — free-tier LLM access is not a stable foundation to size an
evaluation corpus against, and the project's numbers have to say so rather than quietly
running smaller than planned.

Evidence: `benchmarks/raw/w4_doc_agent_predictions.json` (22 ok, 18 `RESOURCE_EXHAUSTED`
of 40 attempted), `docs/problems.md` P-36.

---

## D-033 · Prompt v2: `document_number` fixed from 6% to 100% correct, with one honest trade-off exposed by the seeded-error corpus — `DECIDED`
**Week 4 · Krishna · D3-D4**

D1-D2's 22 successful extractions were read by eye against ground truth (`docs/W4_krishna_doc_agent.md` §3) and one field stood out: `document_number` was transcribed as raw OCR noise (`\NVOO00001`, `LROOOOOO6`) rather than resolved to the fixed `LR`/`INV` + 7-digit shape `doc_extraction/v1.md`'s own rule 6 already applies to centre codes but never extended to this field. `doc_extraction/v2.md` extends the same shape-based correction to `document_number` and a facility-name suffix code, adds `|` to the OCR-confusable set (this pipeline's own rendering of a misread `I`/`l`), and adds lost-decimal-point handling for `weight_kg`/amount fields — each tied to a concrete failure observed in D1-D2's output, not a speculative rewrite.

**Measured, on the 16 documents both prompt versions actually extracted** (a fresh v2 batch capped by the same daily quota as D-032 — 8 consignments, seq 1-8, both document types):

| Field | v1 correct | v2 correct |
|---|---|---|
| `document_number` | 1/16 | **16/16** |
| `origin_centre_code` | 14/16 | 16/16 |
| `origin_facility` | 8/16 | 10/16 |
| `destination_centre_code` | 16/16 | 15/16 |
| Full document, every field correct | 0/16 | **5/16** |

**The one apparent regression is not a regression — the seeded-error corpus caught a genuine, honest trade-off in v2's own design.** The single `destination_centre_code` miss is `SHP-000008`, manifest-flagged `error_types: ocr_confusable_corruption` (D-021's seeded taxonomy). `seed_errors.py` corrupts a character on the shared `ConsignmentRecord` *before* either the rendered document or the ground-truth label is generated from it (D-021 §1: one record backs both), so for this record the label itself legitimately reads `INDI40118AAA` — the corrupted value is what both the printed document and the ground truth agree really is there. v1's literal transcription matched it by coincidence, having no correction logic to second-guess. v2's shape-based rule 6/7 cannot distinguish "OCR degraded a correctly-printed character" from "the document was deliberately printed with a confusable-but-wrong one" — it resolves toward the fixed shape either way, correctly on the first case and incorrectly on the second. **This is real and stays in the table rather than being explained away**: a prompt that gets better at recovering OCR noise is, by the same mechanism, worse at faithfully reporting a genuine printed error the way rule 2 asks it to. At n=1 for this seeded kind in this sample, it is a documented trade-off, not yet a rate — the same "single-digit-count kind's number is a lead, not a result" reading D-021 already gives `corridor_mismatch`'s 2-of-120 count.

**Not the formal evaluation.** This comparison is Krishna's own qualitative check to decide whether v2 was worth keeping, scored by eye against 16 documents' labels — not Lahari's D5 harness, which is the authoritative, arms-length number (execution plan: "keeps builder and judge separate"). `benchmarks/agent_evaluation.md` is left for her harness to populate; this entry's table is provisional and may not match her numbers exactly once she scores the full corpus.

Evidence: `src/agents/prompts/doc_extraction/v2.md`, `benchmarks/raw/w4_doc_agent_predictions.json` (v1),
`w4_doc_agent_predictions_v2.json` (v2), `data/documents/w3_00008_bol.json`,
`benchmarks/raw/w3_doc_corpus_manifest.csv`.

---

## D-034 · The what-if predictor is the one dashboard page that starts a SparkSession, and it says so — `DECIDED`
**Week 4 · Krishna · D5**

D-009 decided the dashboard reads only cached artefacts and never starts Spark, so
the demo stays responsive. This page cannot honour that literally: the champion is a
real MLlib `PipelineModel` (D-026), and `PipelineModel.transform()` has no path that
does not go through a `SparkSession` — there is no cached CSV of "every possible
what-if input's prediction" to read instead.

**Decided: one narrow, named exception, not a quiet one.** `src/ml/predict.py`
starts Spark only inside `predict_delay()`, only when the page's "Predict" button is
actually pressed — every other page, and this page before that click, stays exactly
as Spark-free as D-009 asks. The page's own caption says so in plain language before
a user ever clicks, rather than the exception being discoverable only by reading the
code.

**The corridor picker and the OSRM defaults still come from a cached CSV**
(`w2_corridor_audit.csv`, already on every other page) — Spark is not needed to
choose a corridor or default its planned time/distance, only to run the model
afterward. This keeps the exception as narrow as the thing that actually needs it.

**Corridor and hub history is looked up fresh from `features_v1` inside the same
Spark session, not duplicated into a second cached file.** Two lists holding one
truth already cost this project once (P-23); reading Stage 4's own numbers directly,
every time the page runs, is the version of that lesson that does not require
remembering to keep a duplicate in sync. The lookup takes each key's single *most
recent* known snapshot regardless of the departure date chosen in the form — a
documented simplification of D-020's live as-of join, not a silent one, since
building a true as-of join for one form submission would re-derive Stage 4's whole
join a second time for a page whose job is illustrating the model, not re-litigating
D-020's leakage guarantee. Cold corridors/hubs (D-023's zero-fill-plus-flag policy,
reused rather than reimplemented) are surfaced in the UI rather than silently
predicted through.

**Verified against real data, both paths.** A known bottleneck corridor
(`IND208012AAA>IND209304AAA`, the network's #1 worst per the Week 2 audit) predicts a
large gap and a delay call the audit's own history makes plausible; a corridor and
both hub codes that do not exist anywhere in `features_v1` correctly report
`cold_flags` all `True` and still produce a sane, non-crashing prediction. The
Spark-free half (`build_result`'s threshold arithmetic) is covered by
`tests/test_predict.py`; the Spark-dependent half is exercised interactively (the
same reasoning D-030 on Mounika's branch gives for not re-running a real batch job
inside a pytest suite) since it needs a real champion model on disk that CI does not
have.

Evidence: `src/ml/predict.py`, `src/dashboard/app.py` (Delay predictor page),
`tests/test_predict.py`.

---

## D-035 · The replay runs on the file sink, and the Kafka path ships unexercised rather than unwritten — `DECIDED`
**Week 5 · Mounika · D1-D2**

The execution plan's W5 line carries its own escape hatch: *"3-day rule: if Kafka
fights the environment, switch to file-streaming fallback."* On this machine Kafka
does not fight so much as fail to exist — `docker --version` is not a command
here, so there is no broker to point a producer at, and `README.md`'s prerequisite
table already lists Docker as Week-5-optional for exactly this reason.

**Decided: both sinks are written behind one `emit()`, the file sink is what runs,
and the write-up says which is which.** `FileSink` lands one JSON-lines file per tick
in `STREAM_TRIPS_DIR` for Spark's file source to pick up; `KafkaSink` is a real
`KafkaProducer` keyed on `corridor_id`, imported lazily so a machine with no broker
never touches it. Switching is `--sink kafka` or `STREAM_SOURCE` in `.env`, not a
rewrite.

**Why write the Kafka path at all if it cannot be run here.** Because the claim the
architecture makes (`README.md`: "Kafka producer (trip replay) → Spark
Structured Streaming") is a claim about the code, and code that does not exist cannot
be reviewed, corrected, or run by a teammate whose machine *does* have Docker. What
would be dishonest is running the file path and describing it as Kafka; what is
honest is shipping both and saying plainly that only one has been executed here. The
same "declared openly as scaffolding" standard `README.md` already applies to the
mock TMS and the synthetic corpus.

**Two details that are not arbitrary.** Files are written to `.tick_NNNNNN.jsonl.tmp`
and then renamed, because Spark's file source lists a directory and will read a file
that is still being written — a half-written final line surfaces at the consumer
as a malformed record, a long way from its cause. And the Kafka path keys on
`corridor_id` so one corridor's facts and queries land on one partition in order,
which is what a future stateful consumer needs and what a round-robin default would
quietly take away.

**Time compression is proportional, not uniform.** Each event's real `event_time` maps
linearly onto the replay window, so a quiet night stays quiet and a busy morning still
bursts. Spreading the events evenly would have produced a smoother, better-looking
throughput number than the data supports — the same instinct D-003 applies to a
majority-class baseline, applied to a rate.

Evidence: `src/streaming/producer.py`, `tests/test_producer.py`,
`docs/W5_mounika_kafka_streaming.md`, `docs/problems.md` P-38.

---

## D-036 · An ambiguous order produces one question, and the agent never guesses a field the email did not state — `DECIDED`
**Week 5 · Krishna · D1-D2**

The `order_entry` prompt slot has carried the requirement since Week 3: *"an ambiguous
order must produce a question, not a confident guess."* This entry records how that is
actually built and, more usefully, how it is made *measurable*.

**Decided: the model returns its own `file` / `clarify` decision, and a `clarify`
names the single field it is blocked on.** Not a confidence score, not a list of
everything imperfect — one `missing_field` and one sentence a customer can answer.
A list of five questions is a form, and a customer who receives a form does the work
the agent was supposed to do.

**Why the corpus contains deliberately broken emails.** An agent judged only on clean
input scores perfectly and tells you nothing: there is no way to distinguish "asks
when it should" from "never asks at all". `src/agents/order_corpus.py` therefore
generates five variants — `clean`, `missing_weight`, `missing_pieces`,
`vague_origin`, `ambiguous_route` — and every non-clean one records
`expected_missing`, the field a good question has to be about. That is what lets
Lahari's D5 harness score *which* question was asked, not merely whether one was.
Ground truth also **omits** whatever the variant removed from the email, so an agent
is never marked wrong for declining to invent a value nobody wrote — the same
"the label is what is printed, not what is true" principle D-021 fixed for the
document corpus.

**Validation is a separate stage from extraction, on purpose.** `validate_order()` is
pure Python and re-checks what the TMS's `OrderCreate` will check anyway. That looks
like duplication and is not: a model returning `pieces: 0` is a *prompt* problem, and
catching it one function from where it happened says so, where the same failure
arriving as a 422 from an HTTP call three layers away looks like an *environment*
problem. The three stages fail differently because they are broken differently.

**Result, six development emails:** 6 of 6 correct — three clean emails filed as
real orders in the TMS (`ORD-000001` .. `ORD-000003`, `source=agent`), three ambiguous
ones clarified, and each clarification named the right field. Extraction matched
ground truth on every field the emails stated, with no mismatches. Re-posting a filed
`external_ref` returns 200 and creates nothing, so a replayed email cannot double-file
(D-017's key doing exactly what it was built for).

**What this result is not.** Six emails, from the corpus the agent was developed
against. The number that counts is Lahari's, on the 50-case set she authors at D5,
which the agent has never seen — the same builder/judge separation D-028 applies
to document extraction. This entry's 6-of-6 is a smoke test that the path works end to
end, not an accuracy claim.

Evidence: `src/agents/order_agent.py`, `src/agents/order_corpus.py`,
`src/agents/prompts/order_entry/v1.md`, `tests/test_order_agent.py`,
`benchmarks/raw/w5_order_agent_runs.json`, `docs/problems.md` P-40, P-41.

---

## D-037 · The streaming job scores by handing each micro-batch to the batch code, and joins a history snapshot it does not update — `DECIDED`
**Week 5 · Mounika · D3-D4**

Two decisions about `src/streaming/job.py` that are easy to make by accident and
expensive to reverse.

**Decided: `foreachBatch`, calling the same functions the batch path calls.** Not
because a streaming DataFrame could not express the join and the model transform —
it could — but because of what Lahari proved at D1-D2. Her stream-equals-batch
test shows identical rows produce identical predictions; that guarantee is worth
something only if the two paths are *the same code*. A streaming-native
reimplementation would make it a claim about two things that look alike, which is the
kind of claim that holds until the day it does not. Concretely, the micro-batch goes
through pandas and back so it can call `src.ml.baselines.prepare_model_features` —
the same function — rather than a Spark translation of D-023's cold-start policy
and D-019's `is_ftl` encoding. **The round trip costs 0.08 seconds in a 71-second
full-replay run: 0.1%.** That number is why the decision is cheap, and it was measured
rather than assumed (D-038's harness exists partly to answer exactly this).

**Decided: the joined history is a static snapshot, and fact events are counted and
dropped.** The plan says "join broadcast features", and that is what this is: one
window function over `features_v1` per key at start-up, broadcast, then joined to every
query event. A leg finishing mid-replay therefore does **not** update the history the
next query is scored against.

That is a real limitation and it is stated in three places rather than one, because a
streaming layer that quietly discards half its input is misrepresenting itself: the
module docstring, the run summary (`facts_dropped`), and here. Making history live
means stateful aggregation with as-of semantics — re-deriving Stage 4's guarantee
inside a stream — which is Week 6+ work, not a flag. `src.ml.predict` already
takes the identical simplification for the what-if page and documents it identically.

**A consequence worth naming before anyone quotes a number off it.** The snapshot is
each key's *latest* known history, i.e. from the end of the observation window, and the
replay then scores legs from the beginning of that window against it. For the intended
direction — score what happens next against what is known now — that is
correct. For a replay of history it hands the model a snapshot from after the leg it is
scoring. So the alert stream's precision and recall (D-038) describe how the sink
behaves, not how well the model predicts. Lahari's Week 4 test-set numbers remain the
project's honest accuracy claim.

**Decided: alerts have a written contract, `docs/schemas/alert.schema.json`.** Krishna's
panel and bot (D3-D4, D5) consume that directory and nothing else of this module. Same
reasoning D-031 gives for writing the event schema down: three people cannot hold a
shape in their heads compatibly. `tests/test_stream_job.py` pins the Python and the
schema to each other in both directions, because a contract in two files drifts.

Evidence: `src/streaming/job.py`, `docs/schemas/alert.schema.json`,
`tests/test_stream_job.py`, `docs/W5_mounika_kafka_streaming.md`.

---

## D-038 · Throughput is reported as a saturated scoring rate with the stage breakdown beside it, never as one events/sec headline — `DECIDED`
**Week 5 · Mounika · D5**

The plan asks for "events/sec sustained" and "event-to-alert ms". Both are easy to
report in a way that is technically true and practically meaningless.

**The trap.** Run the replay at a comfortable rate, watch the job keep up, divide
events by wall-clock seconds, publish it. That number is the *producer's* pacing
wearing the job's name: offer 100 events/sec to a pipeline that can do 700 and it
measures 100. The first version of this harness did exactly that and reported
figures between 98 and 179 events/sec that varied with the offered load and told us
nothing about capacity.

**Decided: three numbers, each with a stated denominator.**
1. **Produced rate** — what the producer actually achieved, from its own wall
   clock, not its schedule.
2. **Saturated scoring rate** — events divided by the seconds actually spent
   inside `process_batch`, excluding every second the stream sat waiting for a file.
   This is the capacity figure and the only one that does not move with the offered
   load.
3. **Event-to-alert latency** — tick-file modification time to alert write,
   including file-source discovery and the trigger interval, because a consumer
   waiting for an alert waits for those too.

**Decided: a stage breakdown ships with every measurement.** "14 seconds per
micro-batch" is a complaint; "13.2 of those 14 seconds are inside
`createDataFrame` + `transform` + `collect`, and 0.06 is the pandas round trip" is a
finding. It settled the one design question D-037 left open, and it is what shows the
pipeline is bound by a **fixed per-batch cost** rather than by event volume — the
same batch takes ~14s whether it holds 1,618 events or 4,000.

**Consequence: this pipeline gets faster with *fewer, larger* batches**, which is the
opposite of the usual latency instinct and is why `max_files_per_trigger` is an exposed
dial rather than a constant. Capping it at 4 files to chase latency made a 20-second
replay undrainable — 9 batches at ~14s each — while the uncapped run finished
the same work in 2. Both configurations are kept in `benchmarks/raw/`, because the
trade-off *is* the result.

**Decided: `kept_up` is computed, not asserted**, from whether the job drained
everything offered inside the replay plus a drain window of four batch times. Two
attempts at that verdict were wrong before this one (P-43, P-44), which is the argument
for the harness returning structured stats a test can hold rather than a log line a
human reads.

Evidence: `src/streaming/throughput.py`, `benchmarks/raw/w5_stream_throughput*.json`,
`tests/test_stream_job.py`, `docs/W5_mounika_kafka_streaming.md`.

---

## D-039 · The alert bot sends a shortlist, not the stream, and says which channel actually ran — `DECIDED`
**Week 5 · Krishna · D3-D4 and D5**

Mounika's full replay produced **17,317 alerts from 26,369 legs** (D-037, D-038). That
number is the design input for everything downstream of it: a panel that lists them
all is a log, and a bot that forwards them all is a firehose with a phone number. The
dependable outcome of paging someone for two of every three shipments is that they stop
reading, at which point the alerting system has negative value — it costs attention
and trains people to ignore it.

**Decided: the bot sends a shortlist, and every part of the shortlist is a stated rule.**
1. **New only**, keyed on `alert_id` — the idempotency key `alert.schema.json`
   defines for exactly this. Seen ids persist in a small state file, so a restart or a
   re-emitted micro-batch does not page anybody twice. Verified by running it twice
   against the real sink: 10 sent, then the *next* 10, 20 distinct ids, no repeats.
2. **Worst first, by excess over the leg's own threshold**, not by raw predicted
   minutes. A 400-minute haul running 30 minutes long is ordinary; a 40-minute run doing
   the same is not. `excess_min` is the quantity D-003's rule already tests, so the
   ranking and the flag are the same measurement.
3. **A hard cap per run** (`--top`, default 10), with the held-back count logged
   (`1344 held back by the cap`). A cap that truncates visibly is a policy; a bot that
   silently drops is a bug nobody can see.

**Decided: the message carries two things the plan did not ask for.** The plan says
"shipment, corridor, predicted delay". A delay with no scale is unreadable — "+511
min" means something different on a 132-minute leg than on a 900-minute one — so
the planned time rides along. And a prediction made off a cold history says so, because
D-023 already established that a zero-filled history is not the same claim as a
corridor that runs on time.

**Decided: the file channel is what runs, and the documentation says so.** Telegram
and email are implemented, and the SMTP and Bot API calls are real code, but this
project has no bot account and no SMTP credentials, so **neither has ever been run
against a live service**. That is D-035's rule for the Kafka sink applied a second
time: the choice is one flag, and the write-up says which flag was actually pulled
rather than letting three channel classes imply three working integrations. A channel
selected without its variables refuses at start-up naming what it needs (`telegram
channel needs TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID`), rather than failing per message
halfway through a send loop and leaving the state file half-written.

**Decided: the panel and the bot read the sink through one module**,
`src.dashboard.alerts`. Parsing two differently-natured clocks, deduplicating replayed
batches and ranking by severity are each easy to get subtly wrong, and getting them
wrong in two places is how the panel and the bot would come to disagree about which
alert is worst. The page also stays inside D-009: no Spark on a page that only reads a
directory.

Evidence: `src/dashboard/alerts.py`, `src/agents/alert_bot.py`, the Live alerts page in
`src/dashboard/app.py`, `tests/test_alerts_panel.py`, `docs/W5_krishna_order_entry.md`.

---

## D-040 · 2.00× stays, the alert flag should not come from the regressor, and the order agent is judged on a set its builder never saw — `DECIDED`
**Week 5 · Lahari · D3-D4 and D5**

Three conclusions from two measurements. The first two need to reach Week 6 before the
Exception Agent is built on top of the alert stream.

**1. D-003's threshold is right, and for a different reason than D-003 gave.** D-003 moved
from 1.25× to 2.00× on the base rate alone, in Week 1, with no model to test it
on. The sweep re-scored every classifier at 1.15, 1.25, 1.50 and 2.00 on the same test
legs. **The best classifier's MCC barely moves: 0.507, 0.528, 0.540, 0.536.** So the
threshold does not change how much signal a model can find; the data holds about the
same amount of information about lateness wherever the line is drawn. What the threshold
does change is **volume**: the best model flags 97.9% of legs at 1.15× and 49.3% at
2.00×. A flag raised for nearly every leg carries no information for whoever
receives it, which is D-003's operational argument, now backed by measurement instead of
inference. The base rates also reproduce D-003's Week 1 table to the decimal (96.0, 93.6,
83.6, 49.7%).

**MCC, not F1, is the metric for any threshold question in this project.** At
1.15× the majority class (the classifier that says "delayed" for every leg) scores
F1 **0.977** and MCC **0.000**. F1 rewards the trivial classifier precisely when
positives dominate, which is exactly the situation a threshold sweep creates. From here
on every classifier table carries MCC beside F1, the same way D-003 rule 3 already makes
every table carry the majority-class rate.

**2. The stream's alert flag should not be the champion regressor's threshold crossing.**
This is the result that matters for Week 6. The model the stream actually runs (D-037) is
the champion GBT *regressor*, and it flags a leg when its predicted gap crosses the line.
On the held-out test set, at the decided 2.00×:

| | MCC | alert rate | precision | recall |
|---|---|---|---|---|
| champion, thresholded | 0.477 | **67.6%** | 0.654 | 0.904 |
| logistic regression | **0.536** | 49.3% | — | — |
| corridor mean, thresholded | 0.502 | — | — | — |
| true rate | — | 48.9% | — | — |

The champion was chosen for regression (D-029), where it is genuinely best, but as an
alarm it is **beaten by logistic regression and even by the corridor-mean baseline**. It
over-alerts by about a third, which matches the 65.7% alert rate Mounika's full replay
showed and the 2-of-3 flood Krishna's bot had to shortlist (D-039). This is a
held-out-test-set measurement, so it is a valid accuracy claim; the replay's numbers were
not (D-037).

**Decided: Week 6 flags alerts with a classifier, or with a recalibrated cut on the
champion's gap, chosen by MCC on the validation split.** It must not keep the raw
`gap > (T - 1) × planned` crossing. This changes what the stream flags, not what it
predicts; the champion stays the regressor behind the "+N min" every alert shows. Not
changed this week: the gate is about plumbing, and swapping the flag after the stream,
panel and bot were measured would invalidate every figure they report.

**3. The order agent is judged on an authored set, 20 cases a day, on its own model.**
Fifty cases: ten templates, each testing something Krishna's corpus never does (tonnes,
pieces in words, a forwarded correction, a city-only *destination*, two missing fields
where rule 2 fixes which question comes first). Each template is instantiated on five
real records drawn with a different seed from his. That is D-028's builder/judge split,
applied to the second agent. The set runs **only on Gemini**, the model the agent was
built on, at 20 calls a day. The harness resumes where it stopped and **never records a
quota refusal as a result**, so a 429 cannot turn into a scored failure. Cases run
`dry_run`: the judgement is on the decision and the fields, because `POST` was verified
end to end at D1-D2.

**40 of 50 run, 40 succeeded** (2026-09-11 and 2026-09-13, 20 a day). Four of four on
every one of the ten templates. Every should-file case filed with every field right,
including the tonnes conversions, the corrected weight and pieces written as words.
Every should-ask case asked about exactly the right field, and no `missing_two` case
asked about service before weight. No order was filed on an invented value; no question
was needless. **A perfect score on 40 templated cases is a ceiling, not a verdict.** It
says these ten failure modes are handled. It cannot distinguish a good agent from an
excellent one, and the next eval should be built from email the agent gets wrong.

**Week 5 was closed at 40 of 50 rather than held open another day** for the last
10 cases, which run as a follow-up commit. Every generated table says "40 of 50" where it
quotes a rate, so the partial state is visible wherever the number is, not only here.

Evidence: `src/ml/threshold_sensitivity.py`, `src/ml/order_eval.py`,
`src.ml.baselines.delay_label`, `benchmarks/raw/w5_threshold_sensitivity.csv`,
`benchmarks/raw/w5_order_eval_*.json*`, `docs/W5_lahari_stream_validation.md`.

---

## D-041 · The agents decide with arithmetic; the model only writes the sentence — `DECIDED`
**Week 6 · Krishna · D1-D2 and D5**

Both Week 6 agents — the Tracking & Exception Agent and the Invoice Auditor —
are built the same way, and the split is the week's main design decision.

**Deterministic: every judgement that has a right answer.** Exception severity is a rule
over the excess past each leg's own delay threshold. The invoice verdict is four
comparisons: the invoice's own sum, the corridor's audited rate band, the share taken by
other charges, and whether the invoice number has been seen before. None of these is an
opinion.

**Generated: the customer-facing sentence, and nothing else.** Both agents render a
versioned prompt (`exception_triage/v1`, `invoice_audit/v1`) that is handed the findings
and forbidden to add to them, and both fall back to a template on any model failure
without changing the verdict.

**Three reasons, in order of how much they mattered.**
1. **A model's severity is not reproducible.** Lahari's D3-D4 evaluation scores this
   agent against what the replay actually did. That score means nothing if re-running
   the agent on the same alert can produce a different grade. The same argument killed
   the idea of asking a model whether an invoice is overpriced: the project knows the
   corridor's rate band exactly.
2. **Arithmetic has a right answer, and a model would approximate it.** "How far past
   its own threshold is this leg" is a division.
3. **It fits a 20-call-a-day free tier** (D-032). This is the *least* important reason
   and the one that would have been easiest to lead with. `--no-draft` and `--no-llm`
   run the entire lifecycle with zero calls, which is how Gate 6 was demonstrated on a
   day the quota was already spent on Lahari's evaluation.

**What this costs.** The agents are less "agentic" than the blueprint's framing
suggests: they do not reason their way to a severity, they compute one. That is a real
trade, and the honest defence is that everything a model would have decided here is
something the project can already calculate, and everything it could not calculate
(the wording) is exactly what was left to the model.

Evidence: `src/agents/exception_agent.py`, `src/agents/invoice_auditor.py`,
`src/agents/prompts/exception_triage/v1.md`, `src/agents/prompts/invoice_audit/v1.md`.

---

## D-042 · The lifecycle is a graph because two of its edges are decided by agents, and the MCP tools wrap capabilities rather than reimplement them — `DECIDED`
**Week 6 · Krishna · D3-D4**

**Decided: a LangGraph `StateGraph`, not four function calls.** The composition
`order email -> TMS -> monitoring -> exception` looks linear and is not. Two edges are
conditional, and neither is decided by the orchestrator:

* out of `intake`, the **Order Entry Agent** decides: an ambiguous email routes to
  `clarify` and **never reaches the TMS**;
* out of `monitor`, the **streaming job** decides: a shipment it has not flagged routes
  to `done` and never becomes an exception.

Written as straight-line code those become `if` statements tangled with the work. As
edges they are the structure, and every run records the path it took — which is
what makes "why did this email never reach the TMS" answerable from the artefact rather
than from a log. Ten cases took three distinct paths on the first real run: five
`intake -> clarify`, three `intake -> book -> monitor -> done`, two
`intake -> book -> monitor -> triage -> done`.

**Decided: the orchestrator never re-scores anything.** `monitor` reads the alert sink
the Week 5 job writes. It would have been easy to call the champion model directly and
get a fresher answer; that would put a second scoring path in the project, and D-037
went to some trouble to ensure there is exactly one.

**Decided: every MCP tool is a thin wrapper over a module that already exists.** The
server exposes corridor stats, alerts, predictions and TMS operations, and computes
none of them. A tool that reimplements the capability behind it is two implementations
of one thing waiting to disagree, which is P-23, P-42 and P-48 in three different
costumes. The one expensive tool, `what_if_delay`, says in its own docstring that it
starts Spark and points callers at the instant alternative.

Evidence: `src/agents/orchestrator.py`, `src/agents/mcp_server.py`,
`tests/test_orchestrator.py`, `benchmarks/raw/w6_orchestrator_runs.json`.

---

## D-043 · The invoice rate band is the corpus's own generator model, which makes v1 exact and circular at the same time — `DECIDED`
**Week 6 · Krishna · D5**

The auditor needs to answer "is this freight charge too high for this corridor". It
does so with a band: the corridor's audited `mean_osrm_km` (Week 2) times the rate model
`src/agents/doc_corpus/records.py` uses to generate invoices — FTL at 28-45 per km,
Carting at 6-10 per km-tonne plus 2-4 per kg — widened by 15%.

**This is exact for these invoices and worthless as a claim about real freight
pricing**, because the generator and the auditor share one model. It measures whether
the auditor catches an invoice that departs from the network's own observed rates. It
does not show those rates are right. Stating that plainly is the decision: the
alternative was to quietly present 20-of-20 as though it were evidence about pricing.

**Decided anyway, for v1**, because the auditor's job this week is to be *wired and
measurable*, and a band fitted from billed history is a Week 7+ piece of work that needs
billed history the project does not have. The 15% tolerance is set so that no clean
invoice in the corpus is disputed: a false dispute costs a supplier relationship, which
is worth more than the few hundred rupees a missed marginal overcharge represents.

**Decided: a corridor with no audited distance produces no finding at all.** Not a
dispute, not a warning-that-becomes-a-dispute. "We cannot check this" and "this is
wrong" are different statements, and the TMS has only `approved`/`disputed` to say them
in. Disputing an invoice because the network lacks history on its corridor would bill a
supplier for our own data gap.

Result on the development corpus: **20 of 20 verdicts matched the seeded ground truth**
(10 disputed, 10 approved, no clean invoice disputed). Lahari's D5 evaluation is the one
that counts, on a set this auditor's author did not write (D-028).

Evidence: `src/agents/invoice_auditor.py`, `tests/test_invoice_auditor.py`,
`benchmarks/raw/w6_invoice_audit_runs.json`.
