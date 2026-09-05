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
