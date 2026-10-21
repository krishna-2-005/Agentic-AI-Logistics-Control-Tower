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
10 cases, which ran as follow-up commits. Every generated table says how many had actually
run where it quotes a rate, so the partial state was visible wherever the number was, not
only here.

**Closed 2026-09-18 (G-02): 50 of 50 run, 50 succeeded**, over five quota days
(2026-09-11, 09-13, 09-16, 09-17, 09-18). Five of five on every template; clarification
recall and precision both 1.00; still no invented order and no needless question. The last
10 cases changed nothing about the reading above — which is itself the useful part, since
a perfect score that survives a 25% larger sample is less likely to be luck.

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

---

## D-044 · Boot checks everything before it starts anything, and repairs schema drift instead of re-seeding — `DECIDED`
**Week 6 · Mounika · D1-D2**

**Decided: preflight reports every problem at once, and blocks on none of them
silently.** Six weeks of this project have produced one recurring failure shape: a run
dies twenty minutes in because an artefact three stages back was never built. `boot`
checks the cleaned parquet, the feature table, the champion model, the corridor audit,
the TMS schema, Java and the LLM key *before* the first process starts, prints each with
the exact command that fixes it, and stops if an artefact is genuinely missing. A
missing LLM key is reported and **not** blocking, because every agent runs without one.

**Decided: drift is repaired with `ADD COLUMN`, never by re-seeding.** `create_all`
makes missing tables and never alters an existing one, so a model that gains a field
disagrees with the database file from that moment until something writes the column
(P-47). The obvious fix — re-seed — would have destroyed three real
agent-filed orders, which is exactly what P-40 predicted in Week 5. So `boot` diffs
`SQLModel.metadata` against `PRAGMA table_info` and adds what is missing, in place.

**A column whose *type* changed is reported and never rewritten.** That is a migration,
and a migration is a decision with data loss attached. Guessing at one silently is how a
database quietly stops meaning what it says. `ADD COLUMN` is the only DDL this module
will ever emit; anything else is a person's call.

**Decided: `boot` pins `--sink file` rather than inheriting `STREAM_SOURCE`.** The
configured default is `kafka` and there has never been a broker on this machine (D-035),
so the bare producer command times out and exits 1. A script whose whole promise is "one
command that works" cannot inherit a default that works nowhere (P-50).

Evidence: `src/common/boot.py`, `tests/test_boot.py`, `docs/W6_mounika_vectordb.md`.

---

## D-045 · The vector store indexes a document per corridor, and is never a source of truth — `DECIDED`
**Week 6 · Mounika · D3-D4**

**Decided: one document per corridor, per hub, and per documentation *section* —
not per table, and not per fixed-size chunk.** A retrieval answer is only as good as the
unit it retrieves. "Here is the corridor audit CSV" answers nothing; "IND203390AAA>
IND201301AAF averages 299 minutes against a 97-minute plan over 20 legs, confirmed
slower than the network, bottleneck rank 15" is an answer on its own. Documentation is
split at its own headings for the same reason: a decision entry is a unit of meaning, and
a fixed 500-character window cuts it mid-argument and retrieves the half without the
decision. 1,434 documents: 1,130 corridors, 20 hubs, 284 doc sections.

**Decided: the audit's vocabulary is translated on the way in.** The table says `worse`;
the indexed sentence says "statistically confirmed slower than the network". A retrieval
system hands text to a reader or a model, and P-48 is what that word costs when it
travels raw.

**Decided: Chroma's default ONNX embedding, not `sentence-transformers`.** The latter
pulls ~2.5 GB of torch onto a machine with about 5.6 GB of usable RAM for an embedding of
the same family. The ONNX model is ~80 MB, downloaded once, and runs on CPU: 1,434
documents in about 90 seconds.

**Decided: nothing reads from the index to compute a number.** Every document is
generated from a table or a file that remains the authority, so the index is always safe
to delete and rebuild. It is a way of *finding* things the project already knows.

**Stated limitation: semantic search does not rank by magnitude.** Asked "which hub has
the longest dwell time", it returns rank 11 above rank 1 — both are relevant, and
nothing in an embedding knows 350 > 257. Superlatives belong to the tables; retrieval is
for finding the right document, not for ordering it. Week 7's assistant must consult the
table for "worst", or it will confidently answer with whatever sounded closest.

Evidence: `src/common/vectordb.py`, `tests/test_vectordb.py`, the `search_knowledge`
tool in `src/agents/mcp_server.py`.

---

## D-046 · The results freeze detects drift; it does not make anything immutable — `DECIDED`
**Week 6 · Lahari · D1-D2**

Layer 1 is finished, and the paper will quote it. The risk is not that someone edits a
number in the report — it is that someone re-runs a stage, the artefact changes by
0.2, and the report keeps saying what it said. Six weeks of regenerating tables is
exactly how a figure quietly stops matching its source.

**Decided: freeze the *values and their sources*, and provide `--verify`.** Each of the
31 Layer 1 numbers is recorded with the file it came from and a hash of that file's
contents. `--verify` recomputes every value, re-hashes every source, and reports what
moved. Nothing is made read-only: re-running a stage overwrites its artefact exactly as
before. **Detection is the property a paper needs; immutability is a property a project
cannot have while it is still running.**

**Decided: a file rewritten with identical numbers is reported, and is not a failure.**
The two lists are separate — `changed` (a value moved) and `files_rewritten` (the
bytes moved, the numbers did not). Collapsing them would cry wolf every time a table was
regenerated, and a check people learn to ignore is worse than no check.

**Decided: an entry whose source is missing is a *problem*, not a skipped row.** A Layer
1 number that can no longer be traced to a file is a finding. Silently dropping it would
make the freeze shrink quietly, which is the failure mode it exists to prevent.

**Decided: this is mine, not each author's.** Same reason as D-028: the person who
produced a number is the worst-placed to notice it no longer matches its file, because
they remember what it said.

Evidence: `src/ml/results_freeze.py`, `benchmarks/results_freeze_v1.json`,
`docs/RESULTS_SUMMARY.md`, `tests/test_agent_eval.py`.

---

## D-047 · Severity earns its place as a filter; the invoice tolerance has a measured cost — `DECIDED`
**Week 6 · Lahari · D3-D4 and D5**

Two evaluations, two numbers that should change what Week 7 builds.

**1. The Exception Agent's severity grades track real lateness, so they should be used
as a filter.** Scored against the replay's own fact events — 2,000 legs, 1,082
genuinely delayed — the agent's notification precision is **72.1%** overall, which
is the stream's precision, because the agent notifies on everything it is handed. But
precision by grade is **monotone**:

| grade | notified | precision |
|---|---|---|
| low | 434 | 53.2% |
| medium | 344 | 68.6% |
| high | 275 | 85.1% |
| critical | 294 | 91.8% |

**Decided: a severity floor is a real policy lever and should be one.** Notifying at
`high` or above sends 42% of the volume at **88.6%** precision, reaching 46.6% of all
delayed legs; at `critical` only, 22% of the volume at **91.8%**. The arithmetic severity
rule (D-041) is not just reproducible, it is *informative* — which is the thing a
model-assigned severity could never have demonstrated, because there would have been no
stable grade to measure.

Not decided here: **where** the floor goes. That is an operations question about how many
notifications a desk can act on, and nobody on this team is the customer. The table is
the deliverable; the threshold is theirs.

**2. The Invoice Auditor's 15% tolerance hides overcharges up to 15%, and now that is a
number.** On a 60-invoice set the auditor's author never saw: **86.7% accuracy, zero
false disputes, 8 misses — and all 8 are the same kind**, `overcharge_hidden`, an
invoice 10% above the corpus's rate band and therefore inside the auditor's tolerance.

**Decided: the tolerance stays for v1, and the miss is published beside the accuracy.**
Zero false disputes is the right direction to be wrong in (D-043's argument), and
tightening the band would trade that away. But "86.7% accurate" alone would be a
misleading headline: the auditor is perfect on eight of ten kinds and blind on one, and
the blindness is a design choice with a price tag. A v2 fitted from billed history can
narrow the band on evidence rather than on a guessed 15%.

**Both evaluations cost nothing to re-run** — no model, no TMS, no quota —
because both agents compute their verdicts (D-041). That is the return on that decision,
and it is why these numbers exist at all in a week with 20 API calls a day.

Evidence: `src/ml/exception_eval.py`, `src/ml/invoice_eval.py`,
`benchmarks/raw/w6_exception_eval.json`, `benchmarks/raw/w6_invoice_eval.json`.

---

> **Correction, Week 8 (D-054):** the precision figures in D-047 were measured on a replay that joined each alert to end-of-data history. As-of, overall precision is 58.6% (not 72.1%) and by grade 39.7 / 51.3 / 76.6 / 85.3%. The ordering this decision rests on holds; the levels do not.

## D-048 · The Layer 1 freeze reopens for three days, and the diagnostics say the defect is the objective, not the features — `DECIDED`
**Week 7 · Lahari · D1 · execution plan v3.1 §1, §2.1 Step 1, G-04, G-11**

*Numbering note: v3.1 lists this as D-044. D-044 to D-047 were already taken in Week 6,
so every v3.1 decision shifts by four: its D-044 to D-049 are D-048 to D-053 here.*

**Decided: the results freeze (D-046) reopens for W7 D1-D3 only, for the ML correction
sprint.** `w4_model_metrics.csv` stays untouched as the v1 result; the sprint writes
`w7_model_metrics_v2.csv`; whichever is adopted at the D3 sync (D-049) becomes the
paper's number and the other becomes an ablation row. Logged before any model code
changes, as v3.1 requires.

**The four diagnostics, in the order v3.1 names them.**

1. **Categorical-as-numeric: not present.** `fit_mllib_model` assembles `FEATURES` with a
   bare `VectorAssembler`. There is no `StringIndexer` and no corridor key in the vector at
   all — corridors enter only through their numeric history — so MLlib cannot be
   splitting an index alphabetically, and `maxBins` does not apply. The plan's most likely
   explanation is ruled out by reading the code.
2. **The corridor statistic is in the vector.** `corr_mean_gap_min` is one of the 27
   features. The Random Forest has the baseline's own answer as an input and still trails
   it.
3. **The fair baseline is the median, and it is much stronger: 33.04 min, not 36.13.**
   MAE is minimised by the median. Computed with Stage 4's exact as-of semantics —
   only legs finished before the query leg was created — and verified first: the
   as-of *mean* built the same way matches `features_v1.corr_mean_gap_min` on **100%** of
   warm legs.
4. **The single-node reference says the gap is the loss function.** sklearn
   `HistGradientBoostingRegressor`, same features, same split: **34.70 min on squared
   loss, 29.59 min on absolute loss** — a 5.1-minute swing from the objective alone,
   and the absolute-loss model beats the median baseline by 3.45 minutes.

| test MAE, min | |
|---|---|
| OSRM | 107.09 |
| MLlib GBT (W4) | 38.28 |
| MLlib Random Forest (W4, the reported model) | 36.89 |
| corridor mean (the W4 bar) | 36.13 |
| HistGBR, squared loss | 34.70 |
| **corridor median (the real bar)** | **33.04** |
| HistGBR, absolute loss | **29.59** |

**Reading.** v3.1 framed the outcome as "if MLlib loses and a single-node model wins, the
problem is MLlib configuration". It is more specific than that: the problem is **what the
model is asked to minimise**. MLlib's Random Forest is squared-loss only, and the table
grades absolute error. The features carry real signal — an absolute-loss model on the
same 27 columns clears the strongest statistical baseline by 10% — so the sprint's
Step 3 (GBT with `lossType="absolute"`, on the residual) is aimed at the actual defect.

**Two consequences for the sprint, decided now.**
- **The bar the paper reports against is 33.04, not 36.13.** A v2 that beats the mean but
  not the median has not beaten the baseline, and reporting the weaker one would be
  choosing the comparison after seeing the result.
- **The residual target in Step 3 uses the median as `corridor_baseline`**, not the mean,
  for the same reason: a model that learns nothing then reproduces the strongest baseline
  rather than a weaker one.

**G-11, closed without a feature.** The data spans **11 September to 3 October 2018** (21
days). Navratri 2018 began 10 October and Dussehra fell on 19 October, both after the last
leg, so there is no festival window to encode. Ganesh Chaturthi (13 September) is inside
the window but on one day in the training period only; the chronological test split starts
around 28 September, so the flag would be constant in test and could never be validated.
No `is_festival_window` in features_v2.

Evidence: `src/ml/ml_diagnostics.py`, `benchmarks/raw/w7_ml_diagnostics.json`,
`src/ml/models.py` (`fit_mllib_model`), `docs/problems.md` P-52.

## D-049 · The sprint's GBT clears the bar on paper and loses on every corridor with history; the fix is chosen on validation before the test set sees it — `DECIDED`
**Week 7 · Lahari · D3 · execution plan v3.1 §2.1 Step 5 (its D-045), G-04**

**What the first v2 run says.** `python -m src.ml.models_v2`, test split, MAE in minutes:

| slice (corridor support in train) | n | corridor median | v2 GBT, absolute loss | v2 RF | sklearn absolute-loss reference |
|---|---|---|---|---|---|
| unseen | 294 | 111.18 | **80.18** | 77.80 | 67.05 |
| 1-9 | 1,548 | **31.79** | 32.78 | 33.29 | 31.22 |
| 10-29 | 2,723 | **26.26** | 27.49 | 28.10 | 25.06 |
| >=30 | 709 | **29.45** | 31.46 | 31.75 | 27.35 |
| **overall** | 5,274 | 33.04 | **32.52** | 32.88 | 29.52 |

The adoption rule returns **outcome 1**: 32.52 is more than 1% under 33.04. It is true and
it is not the result it looks like. The whole margin comes from the 294 legs on corridors
the training set never saw, where the "baseline" is the OSRM plan (gap 0). On the 94% of
legs with any history, the GBT is 1.0 to 2.0 minutes *worse* than looking up the median.
The rule as written in v3.1 never asks about well-observed corridors for outcome 1 — only
for outcome 2 — so it cannot see this. That gap in the rule is recorded here rather than
patched after the result.

**Why the GBT underperforms, read from the saved model.** MLlib's absolute-loss GBT fits
its first tree to the raw target with weight 1 (leaf values −1,382 to +2,605 min — a
squared-loss tree, pulled by outliers) and every later tree to the *sign* of the error,
with leaf values in [−1, 1] scaled by `stepSize`. At `stepSize=0.05`, the 199 corrective
trees can move a prediction by **at most 9.95 minutes in total**. The objective D-048
pointed at is barely switched on. sklearn's `HistGradientBoostingRegressor` updates leaves
to the median of the residuals instead, which is why the same features and target reach
29.52 there and beat the median on every slice. Features are not the limit; the MLlib
optimiser settings are.

**Decided, before any further run touches the test split:**

1. **`stepSize` is chosen on validation, not test.** The training split is cut
   chronologically again at the same 80% fraction (`time_split`), and GBT with
   `lossType="absolute"`, `maxIter=200`, `maxDepth=6` is fitted at `stepSize` ∈
   {0.05, 0.3, 1.0} on the earlier part and scored on the later. Nothing else in the grid.
2. **Whichever step size wins on validation is refitted on the full training split and
   scored once on test. It replaces the candidate whatever that score is** — including if
   it is worse than 32.52. Picking between two test scores would be the selection D-048
   warned against.
3. **The rule is applied to it unchanged**, and the paper's model table reports the
   support slices next to the overall MAE for whichever model is adopted, so the reader
   sees where it wins and where a lookup is better.
4. **The sklearn model stays a reference, not a candidate.** The plan's model layer is
   MLlib; it is reported as the ceiling the MLlib model is measured against.

Evidence: `benchmarks/raw/w7_model_metrics_v2.csv`, `benchmarks/raw/w7_model_v2_report.json`,
`data/models/v2_gbt_residual`, `src/ml/models_v2.py`.

## D-050 · Step size was the defect; the v2 residual GBT is adopted as the reported model, and the serving champion does not move with it — `DECIDED`
**Week 7 · Lahari · D3 · execution plan v3.1 §2.1 Step 5 (its D-045), G-04**

D-049 fixed the procedure before it ran: pick `stepSize` on a chronological validation cut
of the training split, refit the winner on the full training split, score it **once** on
test, and adopt it whatever that score says. This records what happened.

**Validation (16,876 legs fit, 4,219 scored; the test split untouched).**

| stepSize | most the corrective trees can move a prediction | validation MAE |
|---|---|---|
| — (corridor median) | — | **29.89** |
| 0.05 (the D-049 candidate) | 9.95 min | 31.55 |
| 0.3 | 59.7 min | 30.51 |
| **1.0 (chosen)** | 199 min | **30.17** |

The ordering confirms the mechanism D-049 read out of the saved model: MLlib's
absolute-loss GBT fits one squared-loss tree and then moves each prediction by at most
`stepSize` per tree, so at 0.05 the objective the sprint was built around was barely
switched on. Nothing else in the grid varied.

**Note what validation says: every step size loses to the median there** (30.17 against
29.89). Adopting on that evidence alone would have been wrong, and scoring a second
candidate on test to find a winner is the selection D-048 warned against. The rule was
applied as written.

**Test, scored once (5,274 legs).**

| model | test MAE | vs the 33.04 bar |
|---|---|---|
| OSRM plan | 107.09 | — |
| v1 Random Forest (W4, reported) | 36.89 | +3.85 |
| corridor median (the bar, D-048) | 33.04 | — |
| v2 GBT residual, stepSize 0.05 | 32.52 | −0.52 |
| **v2 GBT residual, stepSize 1.0** | **30.90** | **−2.14 (−6.5%)** |
| sklearn HistGBR reference (not a candidate) | 29.52 | −3.52 |

**It wins on all fourteen slices**, which the 0.05 model did not: by support in training
(unseen −35.26, 1-9 −0.02, 10-29 −0.19, ≥30 −0.51), by route type, distance band and
departure hour. The adoption rule returns outcome 1 with `no_loss_on_well_observed` true,
so this time the headline is not carried by one slice — though it is worth stating plainly
that **most of the margin still comes from the 294 legs on corridors with no history**
(−35 min there is −1.97 of the −2.14 overall). On corridors the training set has seen, the
model is better than a median lookup by a fifth of a minute. That is a real gain and a
small one, and the paper should say so in the same sentence as the 6.5%.

**Decided:**

1. **`v2_gbt_residual_absolute_step1` is the paper's reported model**, and Week 4's Random
   Forest becomes an ablation row (D-048's unfreeze terms).
2. **The serving champion at `data/models/champion` does not change.** A residual model is
   `baseline + correction`, and the baseline is a per-corridor as-of median that the
   streaming job does not compute today — it carries the corridor *mean* in its history
   snapshots. Repointing the champion without that lookup would serve the correction alone,
   which is not a prediction of anything. Wiring the median into the serving path and
   moving the champion is Week 8 work, tracked against the retraining loop's
   champion/challenger promotion.
3. **The sklearn reference stays a reference.** It is still 1.38 min better than the
   adopted model, which is the honest ceiling statement for the MLlib configuration, not a
   result to report as the project's.

Evidence: `benchmarks/raw/w7_model_v2_stepsize_report.json`,
`benchmarks/raw/w7_model_metrics_v2_stepsize.csv`, `data/models/v2_gbt_residual_stepsize`,
`src/ml/models_v2_stepsize.py`.

## D-051 · The Layer 1 freeze closes again as v2; v1 stays as Week 6 left it — `DECIDED`
**Week 7 · Lahari · D5 · execution plan v3.1 §1 (controlled unfreeze), D-046, D-048**

D-048 reopened the results freeze for three days so the model could be corrected. This
closes it.

**Decided: the Week 7 freeze is `benchmarks/results_freeze_v2.json`, and
`results_freeze_v1.json` is not rewritten.** The first attempt did rewrite it, which would
have destroyed the thing the freeze is for: v1 is the record of what Week 6 reported, and
`--verify --path benchmarks/results_freeze_v1.json` is how anyone asks "what has moved
since the Week 6 sync" — today it answers that order-entry evaluation went from 40 cases to
50. A freeze that is silently updated in place answers nothing. This is D-016's versioning
rule applied to results rather than to data.

**Six Week 7 numbers join the freeze**: the median bar (33.04), the adopted model's MAE
(30.90), document-extraction per-field accuracy (0.9804) and the rows it was measured on
(11 of 40), the assistant's route accuracy (0.90), and the row count of the scale run
(56,353,613).

Two of those are deliberately unstable and belong in the freeze anyway: the extraction
accuracy will move when the remaining 29 rows run, and the assistant's route accuracy will
move if the question set grows. The freeze's job is to notice, not to prevent. Recording
the rows-scored number beside the accuracy is what makes the movement readable rather than
alarming.

Evidence: `src/ml/results_freeze.py`, `benchmarks/results_freeze_v2.json`,
`docs/RESULTS_SUMMARY.md`.

## D-052 · The paper targets ICCCI 2027 (20 February 2027), with an arXiv preprint that does not wait for it — `DECIDED`
**Week 8 · Krishna · D1 · execution plan v3.1 §3 (its D-046)**

*Numbering note: v3.1 calls this D-046; D-044 to D-047 were taken in Week 6, so its Week 8
decision lands here as D-052.*

v3.1 §3 puts this first because every Phase 2 date keys off it. Three venues were checked
on 18 September 2026:

| venue | status on 2026-09-18 | source |
|---|---|---|
| **ICCCI 2027** (9th Int. Conf. on Computer Communication and the Internet) | **submission 20 Feb 2027**, notification 20 Mar, camera-ready 25 May. 4-10 pages, double-blind | `iccci.org/sub.html` |
| ICCCNT 2027 | **not announced.** The most recent edition found was the 16th, July 2025 at IIT Indore | conference site and search |
| ICACCS 2027 | site (`icaccs.sece.ac.in`) serves a **self-signed certificate** and could not be read | — |

**Decided: ICCCI 2027 is the target, deadline 20 February 2027.** It is the only one of the
three with a published 2027 deadline, it is five months out — enough for the two-week draft
Phase 2 plans plus revision — and double-blind review suits a paper whose headline is a
method, not a system.

**Decided: the arXiv preprint is posted when the draft is done, not when the venue
answers.** v3.1 already says "arXiv preprint posted regardless of venue". Writing it down as
a decision makes the ordering explicit: the preprint is the deadline that actually binds,
and ICCCI is a submission the preprint does not wait for.

**Decided: the deadline is re-checked in the first week of January 2027**, and again before
submission. Conference sites move dates without notice, and a date copied into a plan in
September is not evidence in February. If ICCCNT 2027 announces before then with a
comparable deadline, it is reconsidered at that check — IIT-hosted ICCCNT has the stronger
reputation of the three, and the only reason it is not the target today is that it has no
published date.

**What this decision does not settle:** whether the work is one paper or two. The corridor
audit (claim 1) and the agent-architecture position (claim 6) are different contributions
to different audiences, and v3.1's claims map assumes one paper. That stays open until the
outline exists (G-09, this week).

Evidence: `https://iccci.org/sub.html` (read 2026-09-18).

**Update, 14 October 2026 (WP-10): the ICCCI 2027 call for papers is not yet published.**
Searched the conference site and EasyChair. Past deadlines: 1 February 2024, 15 February 2025,
15 March 2026, so the 2027 deadline is likely February–March 2027. That is an inference, not
a date; confirm on <https://iccci.pwr.edu.pl> when the CFP appears and write it here.

## D-053 · Serving the adopted model needs rolling state, not a lookup; it moves to Phase 3 — `CLOSED by D-070`
**Week 8 · Mounika · execution plan v3.1 §3, following D-050**

D-050 left the serving champion on the Week 4 model and called wiring the adopted model
"Week 8 engineering", on the understanding that the stream only lacked the per-corridor
median. Reading `src/pipeline/features_v2.py` against `src/streaming/job.py` says that
understanding was too small.

**What the stream can serve today.** `job.latest_history` takes, per key, the newest leg's
as-of history from the feature table and broadcast-joins it onto each query. That works for
any statistic defined over *all* prior legs of a key — which covers five of the eight v2
features: `corr_median_gap_min`, `corr_p90_gap_min`, `corr_iqr_gap_min`,
`corr_std_gap_min`, and the median the residual is added to.

**What it cannot, and why a lookup will not do.**

| feature | defined as | why a latest-value snapshot is wrong |
|---|---|---|
| `corr_mean_gap_7d`, `corr_n_prior_7d` | mean and count over the trailing **7 days of event time** (`rangeBetween(-7 days, 0)`) | the window moves with each query. A snapshot taken at the end of the data gives every replayed query the *last* week's history — future legs, for most of them |
| `src_dwell_by_hour_min`, `dst_dwell_by_hour_min` | median dwell keyed by **hub and departure-hour bucket** (`hub|bucket`) | keyed by two columns, one of them derived from the query's own time. A per-hub snapshot has the wrong key; a per-(hub, bucket) snapshot is buildable but is a different join from any the job does now |

**Decided:**

1. **The adopted model is not served in v1.0.** The paper reports it (D-050), the stream
   serves the Week 4 champion, and both facts are stated wherever either number appears.
   Stream-equals-batch for the adopted model (`w8_stream_validation_v2.json`, 500 of 500)
   tests the event format, not a running pipeline, and says so.
2. **Serving it is Phase 3 work, scoped as two pieces:** a `hub|bucket` history snapshot
   (a join the job does not do yet, but a snapshot all the same), and **stateful windowed
   aggregation** for the 7-day pair — Structured Streaming's event-time windows with a
   watermark, which is a different kind of job from the stateless broadcast join Week 5 built.
3. **A cheaper option was considered and rejected:** retrain the residual model without the
   two 7-day features so a snapshot join suffices. That would serve *a* v2 model, not *the*
   adopted one, and the reported and served numbers would still disagree — only less
   visibly, which is worse.

**A note on the existing stream, found while reading this.** The Week 5 job's all-history
snapshot is the newest leg's history *as of the end of the data*. On a live stream that is
exactly right: history up to now. On a **replay**, every replayed query is joined to history
that includes legs finishing after it. The stream-equals-batch test does not catch this,
because both of its paths read the same row. It does not affect any reported number — the
model's test MAE comes from the batch path, which is strictly as-of — but it means replay
alerts are scored with slightly more history than the moment they claim to be, and the
throughput page should say "replay" where it does.

Evidence: `src/pipeline/features_v2.py` (`rangeBetween`, `dwell_by_hour`),
`src/streaming/job.py` (`latest_history`, `enrich`).

## D-054 · Alert quality is re-stated from as-of history; D-047 survives at lower levels — `DECIDED`
**Week 8 · Lahari · execution plan v3.1 §3 (claims map, claim 6), D-047, D-053**

D-053 noted in passing that a replay joins every query to the history snapshot at the *end*
of the data. `src/ml/replay_leakage.py` measured what that did to the numbers the agent
layer reports, by scoring the same 2,000 replayed legs twice with the same served model:
once with the history each leg actually had at its own creation time (as-of, D-020), and
once with the end-of-data snapshot the replay used.

**The snapshot run reproduces `w6_exception_eval.json` exactly** — 1,347 alerts, precision
72.09%, and 434 / 344 / 275 / 294 alerts by severity at 53.2 / 68.6 / 85.1 / 91.8% — so the
measurement is of the thing that was published, not an approximation of it.

| | published (replay snapshot) | as-of |
|---|---|---|
| model MAE on the replayed legs | 32.81 min | **47.29 min** |
| alerts | 1,347 | 1,720 |
| notification precision | 72.1% | **58.6%** |
| recall of truly delayed legs | 89.7% | 93.1% |
| precision — low / medium / high / critical | 53.2 / 68.6 / 85.1 / 91.8% | **39.7 / 51.3 / 76.6 / 85.3%** |
| trivial policy: alert every leg | 54.1% | 54.1% |

**Why so large.** The producer replays the *earliest* legs. At their own creation time,
**1,290 of the 2,000 had no corridor history at all** (median prior legs: 0); the snapshot
gave them fourteen. The replay was the worst case for this leak, and it was the one
evaluated.

**Decided:**

1. **The agent layer's alert numbers are reported as-of from now on**, from
   `benchmarks/raw/w8_replay_leakage.json`. `w6_exception_eval.json` is kept as the record
   of what was measured and why it was wrong; it is not deleted and not quoted as a result.
2. **D-047 survives, at lower levels.** Its claim was that severity earns its place as a
   filter because precision rises with grade. As-of, it still rises monotonically
   (39.7 → 51.3 → 76.6 → 85.3%) — so the arithmetic severity rule ranks alerts by how
   likely they are to be real, which is the claim. What does not survive is the size: the
   overall gain over alerting every leg is **+4.5 points, not +18**, and the `low` grade is
   now *below* the trivial policy — notifying on `low` alone is worse than not filtering.
3. **The paper states both numbers and the reason**, in the agent-layer section. A replay
   leak that inflated a headline by 13.5 points is a finding about evaluating streaming
   systems, and it is better found by us than by a reviewer.

**What this does not touch.** Every Layer 1 number — the audit, the model's 30.90 MAE, the
threshold sweep — is computed on the batch path, which is strictly as-of. The stream-equals-
batch tests (500 of 500) are unaffected too: both of their paths read the same feature row.
The leak is specific to *replayed* alerts, which is why it survived until someone compared
a replayed prediction with the same leg's as-of prediction.

Evidence: `src/ml/replay_leakage.py`, `benchmarks/raw/w8_replay_leakage.json`,
`benchmarks/raw/w6_exception_eval.json` (the superseded measurement), P-62.

## D-055 · G-05 closes on a native broker, and the evidence is source equivalence, not speed — `DECIDED`
**Week 8 · Mounika · execution plan v3.1 §2 (G-05), D-035**

D-035 recorded that the Kafka path had never met a broker because there was no Docker on
the development machine. That was true, and it was the wrong constraint: Kafka is a Java
program and the machine has had a JDK 17 since Week 1.

**Decided: G-05 is closed on Apache Kafka 4.1.2 run natively** (single node, KRaft,
`scripts/kafka_native.ps1`), with `docker-compose.kafka.yml` kept for machines that have
Docker. One Windows trap is handled in the script: `kafka-server-start.bat` probes the
architecture with `wmic`, which Windows 11 no longer ships; setting `KAFKA_HEAP_OPTS`
skips the probe.

**Decided: the result reported for G-05 is equivalence, not throughput.** The same 2,000
legs replayed through Kafka and through the file source alert on **the same 1,347 legs with
the same predicted gaps — maximum difference 0.0 minutes**
(`w7_kafka_source_equivalence.json`). That is what "the source is one `readStream` swap"
claimed and could not show until now. The Kafka run's own figures (p50 event-to-alert
20.2 s, 86.7 events/sec scoring) are reported, but not compared with the 26,369-leg file
replay: this run offered 67 events/sec, so its throughput measures the producer.

**Not changed by this:** D-054's replay leak. Both sources join queries to end-of-data
history, so both carry it identically — which is also why it cannot affect the equivalence.

Evidence: `benchmarks/raw/w7_kafka_live.json`, `benchmarks/raw/w7_kafka_source_equivalence.json`,
`src/streaming/compare_sources.py`, `scripts/kafka_native.ps1`.

## D-056 · v1.0 ships with results freeze v3 — `DECIDED`
**Week 8 · Lahari · D-046, D-051**

`results_freeze_v3.json` is the freeze v1.0 ships with: the 37 values of v2, re-read now that
document extraction carries 20 of 40 rows rather than 11, plus five Week 8 values — as-of
exception precision (D-054), assistant groundedness, Kafka-to-file alert equivalence (D-055),
stream-equals-batch for the reported model, and the fresh-clone rebuild time. `--verify`
against v3 is clean at release.

v1 (Week 6) and v2 (Week 7) are unchanged, so `--verify --path` against either still answers
what moved since that point. Extraction accuracy will move again when rows 21-40 run; that is
the freeze working, and the row count beside it says why.

Evidence: `benchmarks/results_freeze_v3.json`, `docs/RESULTS_SUMMARY.md`.

## D-057 · The frontend is rebuilt on Next.js and statically exported to Vercel — `DECIDED`
**v4.0 Phase F1 · Krishna · execution plan v4.0 §3**

`src/dashboard/app.py` was 1,004 lines, one file, nine pages behind a sidebar radio
button. It was honest and correct and it was a Week 1 skeleton that grew a page a week.
What a first-time visitor saw was a build-status checklist, captions citing D-009 and
P-24, three chart libraries on one site, and four pages that print "needs the local Spark
session" on any host but the author's laptop.

**Decided: Next.js 15 + React 19 + TypeScript + Tailwind, `output: 'export'`, on Vercel.**
Observable Framework was the named fallback if the Overview page was not reading real JSON
by the end of D2. It was, so path A stands.

**Why static export is the right shape here and not just the fashionable one.** The public
dashboard is read-only by decision (D-009 — the dashboard reads only cached artefacts).
Eight of the ten routes therefore need nothing at runtime but JSON committed beside the
code. That removes the entire class of problem the Streamlit deployment had: no container
to sleep, no cold start, no "the URL is dead when someone clicks it from a CV".

**What was kept rather than redesigned.** The eight severity cut points (D-058), the
placement rule that position comes from the centre code and only the label from the name
(D-019, P-21, P-24), and the caveats — D-053's served-vs-reported split and D-054's as-of
precision — which are now asserted by `tests/test_web_numbers.py` rather than trusted to
survive a redesign.

Evidence: `web/`, `benchmarks/raw/` unchanged, `docs/deploy_web.md`.

## D-058 · One chart library and one map library for the whole site — `DECIDED`
**v4.0 Phase F1 · Krishna · execution plan v4.0 §3.3**

**Decided: ECharts for every chart, MapLibre GL + deck.gl for the map.** The Streamlit app
mixed `st.bar_chart`, Plotly and Folium, and mixed styling is most of why a dashboard reads
as amateur. Every chart goes through one wrapper (`web/components/Chart.tsx`) that resolves
the theme's own CSS variables, so a chart cannot keep dark-mode axis colours on a white
background.

**The eight severity cut points are carried over unchanged.** They were tuned against the
real bottleneck distribution — median 1.39, p75 1.78, p95 3.42 — so the bins hold
50 / 113 / 86 / 24 rather than piling 110 of 273 bottlenecks into one shade. Redesigning
them for the web would have been a visual decision overriding a measured one.
`test_severity_bins_are_the_tuned_ones` pins them.

**The map basemap needs no API key.** CARTO's styles are served publicly, which matters
because a key would have to be committed into a public bundle (D-062). The arcs are a
deck.gl overlay rather than part of the style, so tiles failing degrades the map to arcs on
a blank ground rather than to nothing.

**The Chart wrapper is hand-written, not `echarts-for-react`.** That package's peer ranges
had not caught up with React 19. Forty lines is cheaper than a dependency that blocks an
upgrade.

## D-059 · The site reads only generated JSON, and its numbers are tested against the freeze — `DECIDED`
**v4.0 Phase F1 · Mounika · execution plan v4.0 §5.1**

**Decided: `src/report/export_web.py` is the only writer of `web/public/data/`.** It reads
`benchmarks/raw/` and the committed reference CSVs — no Spark, no `data/` — so it runs in
CI on a fresh clone. Every file it writes carries its source path, generation time and
freeze version, which is what makes the Evidence link on screen generated rather than typed.

**Pre-aggregation is not an optimisation, it is the contract.** `w1_leg_summary.csv` is
10.9 MB; the Overview needs a 40-bin histogram and four scalars, which is 1 KB. The whole
site's data is 790 KB, 74 KB of it the corridor table after gzip.

**The guard that matters.** `tests/test_web_numbers.py` diffs the exported JSON against
`results_freeze_v3.json`, and `.github/workflows/web.yml` re-runs the export in CI and fails
if the committed output differs. A number on the site and the same number in the paper
therefore cannot drift apart without something going red. Four claims are pinned
explicitly because they are the ones a redesign would quietly lose: the 10-leg and 30-leg
top-20 lists stay disjoint (D-018), every corridor stays drawable (P-24), severity always
carries a word and not only a hue (W-11), and the exception agent reports 58.6% and never
the leaked 72.1% (D-054).

## D-060 · The predictor names the model that scored the request — `DECIDED`
**v4.0 Phase F1 · Lahari (copy) / Mounika (`model_id`) · W-05**

D-053 left the project reporting one model and serving another. On a page with a form and
a number, that gap is invisible unless the page says so.

**Decided: every `/api/predict` response carries `model_id`, and the result card prints
it.** The Predict page also carries the split in its own words above the form. A test
(`test_the_served_model_is_named_as_not_the_reported_one`) fails if the served model ever
equals the reported one without the note being updated, so the caveat cannot rot into a
false claim once the stream does serve the adopted model.

The scikit-learn serving twin from the plan's fallback was not needed: the decision is only
reached if a cold-start measurement forces it, and no API is deployed yet to measure.

## D-061 · The web app is the public artefact; Streamlit is retired at v1.1-web — `DECIDED`
**v4.0 Phase F2 · Lahari · execution plan v4.0 §8**

**Decided: `docs/deploy_dashboard.md` is superseded by `docs/deploy_web.md`, and
G-08 closes on the Vercel URL rather than a Hugging Face Space.**

**`src/dashboard/` is not deleted yet.** The plan retires it at the F2 gate, after the demo
script is rewritten and the user test passes. Deleting it now would break
`boot --dashboard` and the current demo script, and the Streamlit app is still the only
surface for the pages that need a local Spark session. It stays until the API Space exists.

## D-062 · Secrets exist only on the API Space; the web build is secret-free by construction — `DECIDED`
**v4.0 Phase F1 · Mounika · W-16**

A static bundle is published the moment it deploys, so anything committed under `web/` is
public. **Decided: no credential ever enters `web/`.** The map needs no key by choice of
basemap (D-058); the assistant's key will live as a Space secret and the browser will ask
the API, which asks the model.

Checked rather than asserted: the CI job greps the built bundle for Google, OpenAI and
GitHub token patterns and fails on a hit.

## D-063 · The public assistant defaults to the no-LLM route — `DECIDED`
**v4.0 Phase F2 · Mounika · W-04**

The free tier is 20 requests a day (`docs/cost.md`), which a public ask box can exhaust in
an hour — during a demo, by a stranger.

**Decided: `use_llm=false` is the default, LLM phrasing is capped server-side at 10 a day,
and the UI shows the quota state rather than an error.** This costs less than it sounds:
the assistant's routing and retrieval are code either way (D-041), so the extractive route
returns the same facts in blunter prose. The frontend's checkbox is opt-in and labelled
with the cap.

## D-070 · The stream serves the reported model on event-time state; D-053 closes — `DECIDED`
**Post-v1.0 (WP-11) · Mounika · closes D-053**

D-053 scoped serving the v2 model as two pieces: a `hub|bucket` history the job did not
join, and stateful windowed aggregation for the 7-day pair. Both are built. It went further
than that scope in one respect, deliberately.

**Decided:**

1. **All history is event-time state, not only the two pieces D-053 named.** Every event is
   keyed five ways (corridor, source hub, destination hub, and both hub-and-part-of-day
   pairs) and folded through `applyInPandasWithState`. A fact updates the state of the keys
   it belongs to; a query reads that state as of its own event time. Keeping the other 21
   history features on a snapshot would have left D-054's replay leak in the served path,
   and a model scored half on as-of history and half on end-of-data history reproduces
   nothing.
2. **One implementation, three callers.** The state is plain Python
   (`src/streaming/state.py`). The stream, the what-if predictor and the tests all fold
   events through it. It repeats Spark's arithmetic order (sequential sums, the
   `CentralMomentAgg` update for the sample std, Spark's percentile interpolation, the
   7-day RANGE frame over whole seconds) so that it equals the batch tables bit for bit,
   not approximately.
3. **v2 is the default; the champion path stays behind `--model champion`.** The W5 and W7
   throughput files were measured on it, and `src.streaming.throughput` pins it so re-runs
   still measure what those files describe.
4. **Facts carry two optional fields** (`created_hour`, `dwell_min`). The schema change is
   additive, and events and alerts written before WP-11 still validate. Alerts gain an
   optional `model_id`.
5. **The predictor is strictly as-of the departure asked about.** This replaces the Week 4
   simplification of reading each key's newest snapshot whatever the date.

**Evidence** (`benchmarks/raw/w10_stream_validation_v2.json`, from
`python -m src.streaming.validate_v2`). The full 52,738-event replay went through the running
job in two runs over one checkpoint, so the second half could score correctly only from state
restored out of the state store:

| check | result |
|---|---|
| sampled legs identical to batch (the acceptance test) | **500 of 500**, max difference 0.0 |
| all legs identical to batch | **26,369 of 26,369** |
| history features differing from `features_v2`, any leg, any of 26 columns | **0** |
| test-split MAE from the stream's own predictions | **30.90** (30.9048), the reported figure |
| facts dropped / events out of order | 0 / 0 |

**The cost, stated.** The stateful stage runs every micro-batch. On this laptop the resumed
run scored about 74 events/s of busy time, where the champion path managed 740 on the full
replay (`w5_stream_throughput_full.json`). The replay offers about 880 events/s, so the v2
stream does not keep up with a 60-second replay of the whole window. It keeps up with the real
one: 26 days of events arrive at well under one event per second. Both numbers stay in the
record; neither replaces the other.

## D-071 · Alerts reach people: Telegram and email run live, receipts kept; G-07 closes — `DECIDED`
**Post-v1.0 (WP-06) · Mounika · closes G-07, D-039's channel caveat**

G-07 has been open since Week 5: the bot's Telegram and email channels were written and
import-checked, but no credential existed, so only the file channel had ever sent anything.
The credentials now exist. An alert channel is proved by a message arriving, not by the
code calling the API, so this is what was decided about the run that closes it.

**Decided:**

1. **The proof is the provider's answer, kept.** Each send now returns a receipt
   (Telegram's `message_id` and HTTP status; for SMTP, the generated `Message-ID` and the
   server's report of zero refused recipients), and `--record` appends them to
   `benchmarks/raw/f2_alert_channel_live.json`. A send the provider did not acknowledge
   counts as a failure. A Telegram reply with `ok: false` used to pass silently and now raises.
2. **Identifiers are masked in the committed record.** The chat id keeps its last four digits
   and the address keeps two letters and its domain: enough to tell two destinations apart,
   not enough to reach anyone. A scan of the file against every value in `.env` found none.
3. **Real alerts, from a real replay, under D-039's own policy.** 2,000 legs went through the
   producer and the streaming job, which raised 1,347 alerts, the W6 count. The bot sent the
   three most severe by excess over their own threshold, on each channel, each channel with
   its own sent-state so neither suppresses the other. No hand-written test message counts.
4. **Three per channel, not more.** The cap is the bot's existing `--top`. The run proves
   the channel; it does not page a person 1,347 times to do it.

**Evidence:** `f2_alert_channel_live.json`: telegram 3 sent, 0 failed; email 3 sent, 0 failed.

**Also fixed while proving it.** Two tests had silently depended on this machine having no
credentials and on nobody noticing a rewritten file. `test_an_unconfigured_channel_refuses…`
read the real `.env` through `config` and stopped refusing the moment a bot existed, and
`test_a_batch_run_matches_the_seeded_truth` rewrote the committed
`w6_invoice_cases.json` on every run. Both now set their own state.

## D-072 · The public API: six routes, no TMS, limits in-process — `DECIDED`
**Post-v1.0 (WP-04) · Mounika · the work order's D-064, renumbered: D-064 to D-069 were reserved by it, unwritten**

`src/api/app.py` is the API behind the site's four live pages. What it is, and the choices
with a trade-off:

1. **Six routes and nothing else** (`/health`, predict and its status, alerts, traces,
   ask). A test asserts the route table, so a seventh cannot arrive unnoticed.
2. **The TMS is absent, not guarded.** The work order allowed binding it to localhost or
   keying its routes. Neither is needed: the public container imports no TMS route, so
   every TMS path is a 404 and there is no write route for a key to protect. The agents
   that need the TMS run from the repository, where it does.
3. **Limits written here, not taken from `slowapi`.** 30 predictions a minute per client
   and two in flight at once, 5 questions a minute, 120 reads a minute, 10 model answers a
   day in total, bounded inputs, 4 KB bodies. That is about forty lines
   (`src/api/limits.py`), keyed on the first `X-Forwarded-For` hop (the visitor, not the
   proxy) and hashed, so neither the limiter nor the logs hold an address. A refusal is a
   429 with `Retry-After`, which the site renders as "busy".
4. **Alerts are a recorded run, served live and labelled.** No stream runs in a free
   container. The API releases the v2 stream's 13,626 recorded alerts in order, a few per
   poll; every response carries `mode: "replay"`, and the Alerts page shows that label.
   Severity is the exception agent's own (`severity_for` after `investigate`), so the word
   means the same on the page and in a ticket.
5. **Traces never echo inputs.** The console needs agent, time, outcome; a public route
   that returned what one visitor typed to the next would be a leak by design.

**Evidence:** `tests/test_api.py` (29 tests). Measured on the local server: warm predict
p95 665 ms over 20 requests; 200 requests from one client gave 127 × 429 and 0 × 5xx.

## D-073 · Served from a free host with no JVM and no data — `DECIDED`
**Post-v1.0 (WP-04) · Mounika · follows D-072**

The plan was a free Hugging Face Docker Space. Creating it returned **402 Payment
Required**: Docker and Gradio Spaces on free CPU now need a paid subscription. The work
order rules out paid infrastructure, so the API moved to Render's free plan: 512 MB of
memory and no JVM to spare. Two things had to change, and both were proved, not assumed.

1. **The model runs without Spark.** MLlib saves a GBT as two small parquet files: the
   nodes and the tree weights. `src/ml/gbt_local.py` reads them and walks the 200 trees in
   numpy. On all 26,369 legs it is **identical to Spark, bit for bit**
   (`benchmarks/raw/w10_gbt_local_equivalence.json`), but only with the right summation:
   Spark adds the tree outputs with a BLAS dot product that accumulates in four lanes, and
   a plain left-to-right sum matched on only 2,009 legs, the rest off in the last bit. The
   verification compares four groupings and records them all, and it runs through the JSON
   file the host reads, not the parquet original.
2. **The host carries no Delhivery record.** `DATA_LICENSE.md` says the dataset is not
   redistributed. The predictor's history is a fold over every leg's outcome, but the public
   predictor only predicts *today*, and for a departure that late every feature depends
   only on per-key aggregates. `src/ml/history_snapshot.py` stores those aggregates: counts,
   means, the median and p90, the last value and its time. It reads exactly what the fold
   reads on **52,738 of 52,738** checks, and refuses a departure early enough that it would
   not. The alert feed carries corridor, predicted gap and severity, with no time and no id.
   `scripts/build_api_bundle.py` refuses to finish if any file contains a trip id, a leg id
   or an event time.

**Measured locally in the host's configuration** (numpy engine, snapshot, no parquet): no
JVM process, ready 1 s after start, about 0.3 s a prediction, 366 MB with the assistant's
index loaded. **Measured from the public URL** (control-tower-api.onrender.com, free plan,
Singapore): `/health` 200; every TMS write route 404; 20 warm predictions p50 292 ms, p95 345 ms
(`f1_api_latency.json`); 200 requests from one client in 16 s gave 127 × 429 and 0 × 5xx
(`f1_api_load_test.json`).

## D-074 · No AWS: the cloud week is dropped, and the project runs on no cloud account — `DECIDED`
**Post-v1.0 · Mounika · supersedes execution plan v3.1 §5 and v4.0 §11.2**

The plans carried a one-week AWS phase on a $40 credit: S3, Glue and Athena under a read-only
`run_sql` tool, a Textract-versus-Tesseract OCR comparison, and optionally Bedrock. None of it
had been built, no AWS account or key was ever configured, and the work order's own rule already
kept hosting off AWS.

**Decided: the project does not use AWS anywhere.** The site stays on Vercel, the API on Render
(D-073), both on free plans, and every result is reproduced on one laptop with no cloud
credentials. What that gives up, stated rather than implied:

* **No second OCR engine.** Document extraction is scored with Tesseract alone; the
  comparison stays future work (`eval_extraction.py` refuses any other engine by name).
* **No SQL-backed assistant answers.** The assistant answers from its ranked tables and its
  vector index, as measured (`w7_assistant_run_no_llm.json`, `w7_assistant_run_llm.json`); there
is no `run_sql` tool.
* **No independent recount of the audit in a second engine.** The audit counts
  (273 / 512 / 1,130) are reproduced by Spark and by the fresh-clone rebuild, not by Athena.

Text that described the AWS phase as upcoming (`docs/cost.md`, `docs/RELEASE_v1.0.md`,
`docs/deploy_dashboard.md`, a docstring) now says it was dropped. **Spend to date and planned:
$0.**


## D-075 · Pre-registration: a hierarchical back-off bar, and a residual model over it — `DECIDED`
**Post-v1.0 (upgrade B1) · Mounika · written and committed before any back-off number was computed**

**Why.** The bar the paper judges the model against, `baseline_median`, falls back to **0.0 minutes
on a corridor with no history** (`models_v2.py`, `baselines.py`): on those legs the "fair
baseline" predicts that the leg runs exactly on plan, which is OSRM. Most of the model's margin sits
on exactly those legs (294 unseen-corridor test legs: 111.2 → 75.9 min). A reviewer can say the
baseline has an unfair fallback. This entry fixes the baseline before it is measured.

**Method (all as-of: a prior leg counts only once it has *finished*, at `od_end_time`, before the
query leg's `trip_creation_time`; facts before queries on a tie, as D-020).**

1. *Levels,* in order of preference, each a median of `gap_min` over the prior legs in its group
   (the median is Spark's `percentile(0.5)`, the mean of the two middle values for an even count,
   exactly what `corr_median_gap_min` uses):
   L1 the leg's corridor; L2 its origin hub's outbound legs; L3 its destination hub's inbound
   legs; L4 its route type × distance band (the three bands are the train-quantile terciles of
   `planned_km` used by the paper's slice table); L5 the network, as-of.
2. *Hard back-off (b):* use the first level with at least one prior leg.
3. *Shrunken back-off (c):* each level's median is shrunk toward the next level's estimate with
   weight `n/(n+k)` where `n` is that level's prior-leg count, applied from L5 up to L1 (so `n = 0`
   reproduces the hard rule). `k` is chosen from {1, 2, 5, 10, 20, 50, 100} on the **validation**
   cut only (the second chronological 80/20 cut inside the training split, the same cut D-049 used),
   never on test.
4. *Check before use:* the L1 median must reproduce `features_v2.corr_median_gap_min` on every
   warm leg (to 1e-9), or the module refuses to write results (the builder-and-judge rule, D-028).

**Report on the test split (5,274 legs, unchanged):** MAE of (a) the old median baseline with its
0.0 cold fallback, (b) hard back-off, (c) shrunken back-off, (d) the v2 GBT (30.90) — overall, on
*cold* legs (`corr_n_prior == 0`, as-of), on *warm* legs, on the "unseen in training" slice, and on
all fourteen slices of the existing slice table. Output `b1_backoff_baseline.json` and
`b1_backoff_slices.csv`; per-leg predictions `b1_test_predictions.csv` for the significance study.

**Decision rule 1 — what "the bar" is.** The bar the paper, README and site use is the baseline
with the **lowest test MAE among (a), (b), (c)**. It is chosen on test *deliberately*: the
baselines have no fitted parameter except `k` (fixed on validation), and letting the bar be the
best of three on test can only make the model's comparison harder, never easier. If back-off
beats the old median, back-off becomes the bar everywhere and the old median is reported as a
row, not removed.

**Decision rule 2 — the residual model over the bar (`models_v3.py`).** A gradient-boosted
residual model (Spark MLlib, absolute loss, 200 trees, depth 6, as v2) is trained on
`gap − baseline`, where the baseline is the best of (a)/(b)/(c) **on validation** (so that choice
never sees test). Inputs are the 38 v2 inputs plus two as-of descriptors of the baseline used: its
level (1 to 5) and its prior-leg count. The only hyperparameter is the step size from
{0.05, 0.3, 1.0}, chosen on validation; the chosen model is refit on the full training split and
scored once on test (§5.3 of the paper, applied as written).

**Decision rule 3 — which model is "the reported model".** Of the two gradient-boosted residual
models, v2 (over the old median, step 1.0, already fixed) and v3 (over the validation-best
baseline), the one with the **lower validation MAE** is the reported model, **even if its test MAE
is higher than 30.90**. Both are reported with their test numbers.

**Decision rule 4 — claims.** If the reported model does not beat the bar by a block-bootstrap
confidence interval (by day) that excludes zero (study B2), the paper says so plainly and §5 is
reframed as "a strong back-off baseline is hard to beat; the model's value is …". That is still a
result. If the reported model changes from v2, the stream, the numpy tree reader, the API bundle
and the stream-equals-batch validation are re-run and must again be bit-identical; if that cannot
be done in this pass, v2 stays served and the paper and README state which model is served and
which is reported.

**Outcome (written after the runs, 2026-10-21).** Rule 1: on the 5,274 test legs the old median scores
33.04 min, hard back-off 32.39 and shrunken back-off 32.92 (k = 1 chosen on validation; every larger k is
worse, 31.41 rising to 69.29 at k = 100). Hard back-off is the bar, and it beats the old median, so the
old median's 0.0-minute cold fallback was an unfair advantage to the model. The model's margin over the
bar falls from 2.14 min (6.5%) to 1.49 min (4.6%). Where it sits: 204 cold legs (no prior leg on the
corridor as of the query) score 132.97 under back-off against 100.16 for the v2 model, and warm legs
28.35 against 28.12, so almost the whole gain is on cold legs. Rule 2: back-off has the lower validation
MAE of the three (29.36), so it is the baseline under v3; step 1.0 won on validation (31.14 against 31.56
and 32.52). Rule 3: validation MAE is 30.17 for v2 and 31.14 for v3, so **v2 stays the reported model**
(v3 scores 31.40 on test, worse than v2's 30.90). Notably the back-off bar itself scores 29.36 on the
validation cut, lower than either model, so on that cut the model does not beat the bar; the test split is
where it does. The paper says both. Rule 4 (interval) is decided by D-076; the served model is
unchanged because the reported model is unchanged, so the serving chain needs no re-validation.

## D-076 · Pre-registration: uncertainty for every model comparison, and a rolling-origin evaluation — `DECIDED`
**Post-v1.0 (upgrade B2) · Mounika · written and committed before any interval or test was computed**

*Status of knowledge when written:* the B1 back-off numbers and the v2 GBT's test MAE are known; no
confidence interval, p-value or fold result exists yet. Nothing below was chosen after seeing one.

**Quantity.** For model `f` and the bar `b` (D-075 rule 1), the per-leg difference
`d_i = |y_i − f_i| − |y_i − b_i|`, with `y` the realised gap. Negative favours the model; the mean of
`d` is the MAE difference.

**Intervals (module `src/ml/significance.py`, output `b2_significance.json`).**
1. *Paired bootstrap over legs,* 10,000 resamples, seed 20261021, 95% percentile interval. Reported,
   but legs are not independent (shared trips, vehicles, days), so it is **not** the paper's interval.
2. *Block bootstrap by calendar day (IST) of leg creation,* same resample count and seed: whole days
   are resampled with replacement. **This is the paper's interval.** The test split spans only about
   six calendar days, which makes this interval crude; the module also reports a **six-hour-block**
   version as a sensitivity check, and the paper says how many blocks each rests on.
3. *Wilcoxon signed-rank* on `d_i` (zero differences dropped), reported with the caveat that legs are
   dependent, so its p-values are optimistic.
4. *Diebold–Mariano* on `d_i` ordered by creation time, normal reference distribution, Bartlett-kernel
   (Newey–West) long-run variance with bandwidth equal to the **median number of legs per day** (the
   day-level dependence the plan names), and the conventional `floor(n^(1/3))` bandwidth as a second row.
5. *Holm correction* across the 13 non-overall slices, separately for each test. A slice "wins with
   interval excluding zero" if its block-bootstrap interval is entirely below zero; "wins after Holm"
   if its Holm-adjusted block-bootstrap p-value is below 0.05.

**Where applied.** Every model against the bar on: overall; cold legs (`corr_n_prior == 0`, as-of);
warm legs; legs on corridors unseen in training; and each of the paper's slices (support, route type,
distance band, departure hour; 14 including overall). Each model's own MAE also gets a block-bootstrap
interval (for Table 1).

**Rolling-origin evaluation (module `src/ml/rolling_origin.py`, output `b2_rolling_origin.csv`).**
The 22 calendar days of leg creation (IST; day 1 = 2018-09-12) are cut into four chronological folds,
fixed here: fold 1 trains on days 1–10 and tests on 11–13; fold 2 trains 1–13, tests 14–16; fold 3
trains 1–16, tests 17–19; fold 4 trains 1–19, tests 20–22. In each fold the baselines are recomputed
(as-of by construction; the distance-band cut points come from that fold's training legs) and the two
residual GBT **configurations are refit with their hyperparameters frozen, no retuning**: v2 (over the
old median, step 1.0) and v3 (over the back-off baseline, the step size D-075 chose). Report per-fold
MAE and the per-fold difference to the bar, and their mean ± standard deviation over folds. A fold's
training legs are those *created* before its test window, the same convention as the headline split;
a leg created just before a window may finish inside it, so its label is not strictly known at the cut,
which the paper states as a limit.

**Decision rule.** Report every interval and every fold, whatever they show. "The model wins all
fourteen slices" is replaced by "wins N of 14 with a block-bootstrap interval below zero, M after
Holm", with N and M as the module computes them. If the model's advantage over the bar is not
significant by the block interval, or loses in a fold, the paper says so in those words.

## D-077 · Pre-registration: stronger single-node baselines, a feature-group ablation, and the reporting rule — `DECIDED`
**Post-v1.0 (upgrade B6) · Mounika · written and committed before any of these models was fitted**

**Why.** A single-node `HistGradientBoostingRegressor` (29.52 on test) beats the reported MLlib model
(30.90), and the paper called it "not a candidate" without a reason. There was also no LightGBM or
XGBoost. A reviewer will ask whether the headline model is simply the weak one.

**Models (module `src/ml/model_zoo.py`, output `b6_model_zoo.json`).** All on the same split, the same
residual target and the same 40 inputs as v3 (the 38 v2 inputs plus the baseline's level and prior-leg
count): LightGBM with L1 loss; LightGBM with Huber loss (delta = the median absolute training
residual, computed on the inner training legs); XGBoost with `reg:absoluteerror`; scikit-learn
`HistGradientBoostingRegressor` with absolute loss; and a linear median (quantile 0.5) regression on
standardised inputs. **Identical tuning budget:** each boosted model gets 200 trees, depth 6, and
three learning rates {0.03, 0.1, 0.3} selected on the validation cut only (D-049's protocol: fit on
the inner training legs, score on the validation cut, refit the chosen setting on the full training
split, score once on test). The linear model has no hyperparameter. A secondary table repeats the
four boosted models over the *old* median with the 38 v2 inputs, so the 29.52 question is settled on
equal footing as well as on the new one.

**Reporting rule (supersedes the special case in D-075 rule 3, which assumed only v2 and v3).** The
paper's **reported model is the candidate with the lowest validation MAE regardless of library**:
Spark v2, Spark v3 or any model above. Its test MAE is reported whatever it is. If the reported
model is single-node, the paper says so, says what Spark serves (v2 or v3, the better of the two
by validation), and does not claim they are the same model. No model is labelled "not a candidate":
anything left out of the headline is listed in Table 1 with its validation and test MAE.

**Feature-group ablation (same module, `b6_feature_ablation.json`).** With the best boosted
single-node model's chosen settings, refit with one group removed at a time and report the change in
test MAE with a block-bootstrap interval (D-076) against the full model. Groups: *plan and route*
(`planned_min`, `is_ftl`); *distance* (`planned_km`); *time* (`created_hour`, `created_dayofweek`,
`created_is_weekend`); *corridor history* (the 12 `corr_*` v1 inputs and the corridor cold flag);
*hub history* (the 12 `src_*`/`dst_*` v1 inputs and their cold flags); *v2 dispersion and dwell* (the
eight v2 columns and their three missing-value flags); *baseline descriptors* (level, prior-leg count).
A group whose removal does not move test MAE by an interval excluding zero is reported as such.

**Outcome (written after the runs, 2026-10-21).** Over the old median with the 38 v2 inputs (the
secondary setting) the four boosted models score 29.66 (LightGBM L1), 30.53 (LightGBM Huber), 29.71
(XGBoost) and 29.75 (histogram GBT) on test, and the linear median regression 33.96; over the back-off
baseline with 40 inputs they score 30.19, 31.06, 30.49, 30.33 and 33.63. The 29.52 question is settled:
three independent libraries land within 0.1 minute of each other at 29.7, so the single-node figure
was not a lucky seed, and the MLlib model's 30.90 is about 1.2 minutes behind the same recipe in
another library. By the reporting rule the **reported model is LightGBM with L1 loss over the old
median** (validation 27.24, the lowest of all candidates; test 29.66, day-block 95% interval
[27.86, 31.12]; minus the bar -2.74 [-3.41, -2.11], wins on 14 of 14 slices). It is single-node. What
the API serves and the streaming job scores is still Spark v2 (30.90; minus the bar -1.49
[-2.25, -0.74], wins 10 of 14), which is the better Spark candidate by validation; the paper says the
two are different models and does not claim the served model has the reported score. Putting the
back-off descriptors in made every boosted model worse on validation, so the back-off bar is a fairer
yardstick but not a better feature. Feature-group ablation (LightGBM, primary setting, test MAE change on
removing the group, day-block interval): time -> +0.44 [0.14, 0.63]; hub history -> +0.15 [0.06, 0.26];
dispersion and dwell -> +0.29 [0.23, 0.35]; all others (plan and route, distance, corridor history,
baseline descriptors) move it by less than 0.07 with intervals that include zero. Corridor history alone
is redundant once hub history and the dispersion block are present, which fits the finding that the
gain over the bar sits on cold corridors.

## D-083 · The audit's legs are clustered by recurring service, not by trip or day — `DECIDED`
**Post-v1.0 · Mounika · inspected before the dependence-aware audit (D-080) was pre-registered**

The dependence-aware audit was planned to cluster on the trip, or on day-by-corridor blocks if
trips rarely repeat a corridor. Before choosing, `python -m src.ml.audit_data` measured the
clustering in the 26,369 legs (`benchmarks/raw/b3_dependence_diagnostics.json`). Its reading
reproduces the published audit first: 1,130 corridors, 273 slower, 512 faster, every
statistic within 1e-9 of `w2_corridor_audit.csv`.

* **Trips do not repeat corridors.** In all 1,130 tested corridors `n_trips = n_legs`; no trip
  visits a corridor twice. A trip cannot cluster a corridor's own legs. Trips do link a
  corridor to the rest of the network (1.78 legs per trip, intraclass correlation 0.072 of
  corridor-demeaned log-ratios), which a permutation inside a corridor cannot model.
* **The creation day is almost irrelevant.** 23 calendar dates, intraclass correlation 0.0036,
  design effect on a corridor mean about 1.0006.
* **The recurring service is the real cluster.** `route_schedule_uuid` repeats: a corridor has
  a median of 1 schedule (680 of 1,130 corridors run under exactly one), and the median
  (corridor, schedule) cell holds 11 legs. Within a cell the intraclass correlation is 0.095,
  giving a design effect of about 2.05 at the median corridor, so a typical corridor's 15 legs
  carry the information of about 7 independent ones. Where a corridor has a single schedule its
  corridor effect and its service effect cannot be told apart, and the correlation estimate is
  biased downward by demeaning on the corridor, so 2.05 is a floor for that reason.

**Decided: the cluster unit for the dependence-aware test is the (corridor, route schedule)
cell.** This replaces both clusterings named in the plan, on the evidence above. It is a
deviation from the plan's wording and is logged as one. D-080 states the permutation scheme
that uses it.

## D-080 · Dependence-aware corridor audit: four variants, one pre-registered headline rule — `DECIDED`
**Post-v1.0 · Mounika · B3 · written before `src/ml/audit_robust.py` is run**

The published audit (D-018) tests each corridor against the rest of the network with Welch's
t-test and Benjamini-Hochberg at 5%. Welch assumes independent legs; D-083 found legs of one
corridor and one recurring service are correlated (design effect about 2 at the median
corridor). This experiment asks how many of the 273 slower and 512 faster corridors survive.

**Variants, all on the same 1,130 corridors (10-leg floor), two-sided, alpha 0.05:**
1. `bh_welch`: the published audit, unchanged (reproduced to 1e-9 first).
2. `by_welch`: the same p-values, Benjamini-Yekutieli (valid under arbitrary dependence).
3. `bh_perm`: cell-permutation p-values, Benjamini-Hochberg.
4. `by_perm`: cell-permutation p-values, Benjamini-Yekutieli.
BH and BY come from `statsmodels.stats.multitest.multipletests` (`fdr_bh`, `fdr_by`).

**Permutation scheme (fixed now).** The exchangeable unit is the (corridor, route schedule)
cell of D-083, built over all 26,369 legs, because the "rest" group contains every other leg.
Let `m_b` be a cell's leg count and `ybar_b` its mean log-ratio. Cells are put in strata by
size: 1, 2, 3, 4, 5, 6, 7, 8 exact, then 9-11, 12-15, 16-22, 23 and over. One permutation
shuffles the cell means `ybar_b` among the cells of the same stratum, each position keeping its
own size and its corridor. A corridor's permuted statistic is
`D = (sum of m_b * permuted ybar_b over its cells) / n_c - (network total minus that sum) /
(N - n_c)`, the corridor's mean minus the mean of the rest; the network total is recomputed per
permutation. The observed `D` uses the real `ybar_b`. The p-value is two-sided,
`(1 + #{|D_perm| >= |D_obs|}) / (B + 1)`, with **B = 100,000 permutations, seed 20260801**, in
chunks, vectorised. 100,000 rather than 10,000 because the smallest attainable p-value at
10,000 permutations (1e-4) is too coarse for Benjamini-Yekutieli over 1,130 tests.
This is a global-null permutation (no corridor effect anywhere); with real corridor effects in
the pool it is conservative for the strongest corridors, and it treats cells of one stratum as
equally noisy. Both are stated limits. Cells in different corridors that share a schedule or a
trip stay independent in this scheme; BY is what covers that.

**Size check (reported, not a gate).** On 200 placebo datasets (cell means permuted, within-cell
deviations kept) the uncorrected Welch rejection rate at 0.05 and the mean BH-Welch discovery
count are reported, to show how far Welch's size is off under the cluster structure.

**Decision rule.** All four variants are declared valid for their own assumptions (BH-Welch is
the original). **The headline is the variant with the fewest significantly slower corridors;
ties go to the one with the fewest significantly faster.** If that variant is not `bh_welch`,
the headline drops to its counts everywhere, and `bh_welch` stays as a reported row. A corridor
is **robust** if it is significant, in the same direction, under both the headline variant and
`bh_welch`; otherwise a `bh_welch` discovery is **fragile**. Also reported: how many of the 273
and 512 survive each variant, and the pairwise Jaccard overlap of the top-20 slower lists
(ranked by `excess_ratio` among each variant's significant slower corridors).

**Amendment to D-080, made before the full run.** A 2,000-permutation smoke test of the code
(not the experiment: `b3_audit_robust.json` was overwritten by the real run) showed the rule
could end in a three-way tie at zero slower and zero faster, which D-080 does not resolve. The
tie-break is therefore fixed now: if the rule still ties after "fewest slower, then fewest
faster", the headline is the first of `by_perm`, `bh_perm`, `by_welch`, `bh_welch` (the more
conservative correction, and the cluster-aware test, first). Nothing else in D-080 changes.

**Outcome (D-080).** `python -m src.ml.audit_robust`, 100,000 permutations, seed 20260801,
`b3_audit_robust.json`. The published audit reproduced first (273 / 512, p-values within 3e-14).
Significant slower / faster by variant: `bh_welch` 273 / 512, `by_welch` 218 / 452, `bh_perm`
1 / 0, `by_perm` 0 / 0. **By the rule the headline is `by_perm`, which is 0 slower and 0 faster.**
No tie arose: `by_perm` alone has zero slower corridors (`bh_perm` has one), so the
tie-break was not used. So no corridor is
**robust** (significant under both the headline and the original): all 273 slower and 512
faster `bh_welch` discoveries are **fragile**. The top-20 lists barely overlap across the
independence and cluster-aware families (Jaccard 0.05 for `bh_welch` against `bh_perm`, 0 for
the others; `bh_welch` against `by_welch` is 1.0 because BY only removes the weakest). Why the
drop is so large: under 200 placebo datasets in which corridor membership is meaningless but
the cell structure is kept, Welch rejects 63.9% of corridors uncorrected at 0.05 and BH finds
680 discoveries on average (maximum 723, all 200 datasets non-empty), against 785 found on the
real data. The permutation p-values are not empty: 81 corridors fall below 0.05 and 18 below
0.01 (smallest 4e-5), and the top-20 slower corridors ranked by permutation p share a Jaccard
of 0.74 with the Welch top-20. They do not clear a 5% false discovery rate over 1,130 tests.
Reading, with the limits kept: 680 of the 1,130 corridors run under a single schedule, so for
them the test compares one service with the spread of services of the same size, and a
corridor effect cannot be separated from a service effect. The paper's headline becomes
"0 corridors survive the cluster-aware test"; the 273 / 512 stay as the original row and as a
screening list, not as confirmed bottlenecks.

## D-084 · Sensitivity: the permutation test's resolution limits what B3 can reject — `DECIDED`
**Post-v1.0 · Mounika · written before the 1,000,000-permutation run, after reading the B3 outcome**

The B3 headline (D-080) is the most conservative valid variant, Benjamini-Yekutieli over permutation
p-values, and it finds 0 of 273. With 100,000 permutations the smallest attainable p-value is
1/100,001 = 1.0e-5 (`permutation_p_floor`), while the smallest Benjamini-Yekutieli threshold over 1,130
tests is 0.05/(1,130 x H) = 5.8e-6 with H the 1,130th harmonic number (7.6), so **that variant cannot reject a
single corridor however large its effect**; the Benjamini-Hochberg variant needs p <= 4.4e-5 for its
first rejection and found one. A zero under the strictest variant is therefore partly a property of the
resolution, and the paper must not read it as evidence that the corridors are null.

**Run.** `python -m src.ml.audit_robust --permutations 1000000 --placebo 0 --suffix _1e6`, same seed,
same cells, writing `b3_audit_robust_1e6.json` and its corridors file. **Rule.** The headline stays the
100,000-permutation result because it was pre-registered; the 1,000,000 run is reported beside it as a
sensitivity analysis with its own counts, and the paper states that the strictest variant is
resolution-limited at 100,000. If the finer run rejects corridors, the paper says the headline is a lower
bound and reports both; it does not replace the headline after seeing it.

**Outcome (D-084, 2026-10-21).** `python -m src.ml.audit_robust --permutations 1000000 --placebo 0 --suffix _1e6`
(495 s). The smallest attainable p is now 1.0e-6, below the smallest BY threshold (5.8e-6), so the
strictest variant can reject. It still rejects nothing: `by_perm` 0 slower / 0 faster and `bh_perm`
1 / 0, identical to the 100,000-permutation counts; the smallest permutation p is 3.3e-5 (4.0e-5
before), 18 corridors below 0.01 and 82 below 0.05 (81 before). So the headline 0 / 0 is **not** a
resolution artefact: it holds at ten times the resolution. The paper says both facts: at 10^5 the
strictest variant could not have rejected, and a ten-fold finer run changes nothing.

## D-098 · Pre-registration: the same four rolling-origin folds for the reported single-node model — `DECIDED`
**Post-v1.0 (upgrade B2/B6) · Mounika · written before the run, after the reported model was named**

D-076 fixed four chronological folds and refit the two Spark configurations in each. When D-077 named a
single-node LightGBM model as the reported one, the fold study did not cover it, which a reviewer would
notice. This entry adds it on the same footing and adds nothing else.

**Run.** `python -m src.ml.rolling_origin_zoo`. For each of the folds of D-076 (train through day 10, 13, 16,
19; test days 11-13, 14-16, 17-19, 20-22; days are India-time calendar days, day 1 = 2018-09-12), the
baselines are recomputed from that fold's training legs exactly as in `rolling_origin.py`, and LightGBM with
L1 loss (200 trees, depth 6, learning rate **0.03, the value chosen on validation in D-077 and frozen**; no
retuning in any fold) is fitted over the old median with the 38 v2 inputs, the reported model's setting.
**Report** per fold the MAE of that model, of the back-off bar and of the old median, and the difference to
the bar, and across folds their mean, standard deviation and the number of folds in which the model beats the
bar. **No decision rule changes:** the paper's claim about the reported model rests on the headline split and
its day-block interval; this is the check on it. If the reported model fails to beat the bar in a majority
of folds, the paper says so beside the headline.

## D-081 · Empirical-Bayes ranking and its stability across support floors — `DECIDED`
**Post-v1.0 · Mounika · B4 · written before `src/ml/eb_ranking.py` is run**

The audit's support floor changes its answer: the top-20 at 10 legs and at 30 legs are
disjoint (D-018). The hypothesis here is that this is mostly small-sample noise that
shrinkage removes. It may be wrong, and the result is reported either way.

**Model, per support floor `f` in {5, 10, 20, 30}, on exactly the corridors with at least `f`
legs (the same set for the raw and the shrunk ranking).** For corridor `c` with `n_c` legs let
`ybar_c` be the mean of `r = log(actual / osrm)`, `s_c^2` its leg-level sample variance and
`v_c = s_c^2 / n_c`. Then `ybar_c ~ N(theta_c, v_c)` and `theta_c ~ N(mu, tau^2)`.
* `mu`, `tau^2` by **REML (the headline)**, with DerSimonian-Laird method of moments and ML
  reported beside it. If REML and the moments estimate differ in `tau^2` by more than 25%, the
  top-20 overlap between the two estimators is reported too.
* Posterior mean `(1-B_c) ybar_c + B_c mu` with `B_c = v_c / (v_c + tau^2)`; posterior variance
  `(1-B_c) v_c + B_c^2 Var(mu_hat)`; 90% interval is the mean plus or minus 1.645 sd.
* Sampling variances are taken as the model says (independent legs). A pre-registered
  sensitivity row inflates `v_c` by the design effect of D-083,
  `1 + (n_c/k_c - 1) * 0.0953`, with `k_c` the corridor's schedule-cell count and 0.0953 the
  intraclass correlation in `b3_dependence_diagnostics.json`. The headline stays the model as
  written; the sensitivity row is reported in full.

**Material threshold (fixed now).** `t = m + ln 1.5`, where `m = 0.7783` is the mean of `r`
over all 26,369 legs (the network's typical overrun, `w2_audit_report.json`). A corridor is
material when `theta_c > t`, that is when its geometric-mean overrun is at least 1.5 times the
network's (`exp(t)` = 3.27 times the plan against 2.18). 1.5 is a round factor that asks for
half again the usual overrun, large enough to matter to a planner and small enough to leave
corridors above it. Sensitivity rows use factors 1.25 and 2.0.

**Rankings.** `eb_prob`, ordered by `P(theta_c > t)` (headline; ties by posterior mean);
`eb_postmean`, by posterior mean; `raw_published`, the audit's own rule re-run on the floor's
corridors (Benjamini-Hochberg Welch significant slower corridors, ordered by `excess_ratio`);
`raw_mean`, all corridors by `ybar_c`. Top-20 lists are taken within each floor's set.

**Stability metrics.** For each ranking and each of the six floor pairs: Jaccard overlap of
the two top-20 lists (the operational question: does the list depend on the floor I pick); the
Spearman correlation of rank positions over the corridors in both floors' sets; and the
Jaccard of the top-20 lists after restricting the lower floor to the higher floor's corridors
(so only the scoring differs, not the membership). A paired bootstrap, 200 resamples of legs
within each corridor, seed 20260802, gives 95% intervals for the mean pairwise Jaccard and for
the difference between rankings.

**Decision rule.** EB (`eb_prob`) is **called more stable** only if its mean pairwise Jaccard is
higher than that of both `raw_published` and `raw_mean`, with the bootstrap 95% interval of
each difference above 0. If an interval contains 0 the paper says "no detectable difference";
if EB is lower, "EB is not more stable". Section 4.3 of the paper follows this sentence
whatever the numbers are.

**Outcome (D-081).** `python -m src.ml.eb_ranking`, `b4_eb_ranking.json`, 200 bootstrap
resamples. REML `tau^2` at floors 5 / 10 / 20 / 30: 0.138 / 0.133 / 0.083 / 0.058 (corridors
1,632 / 1,130 / 268 / 99); moments 0.114 / 0.106 / 0.071 / 0.028, which differs from REML by more
than 25% only at floor 30, where the two top-20 lists are still identical. Threshold
`t = 1.1838` (3.27 times the plan). **The hypothesis that the floor effect is mostly shrinkable
noise is not supported:** the corridors' own sampling variances (about 0.002) are tiny against
`tau^2`, so the median shrink factor is only 0.009 to 0.021 at every size band, and the
posterior mean is within a few percent of the raw mean. Mean pairwise top-20 Jaccard over the
six floor pairs: `raw_published` 0.101, `raw_mean` 0.101, `eb_prob` 0.150, `eb_postmean` 0.155.
`eb_prob` minus `raw_published` is +0.049 (bootstrap 95% interval 0.006 to 0.062) and minus
`raw_mean` +0.049 (0.007 to 0.067). **By the pre-registered rule EB is called more stable** (the committed file first held a 3-resample bootstrap, a leftover of a smoke run that had overwritten it; the intervals above are from the full 200-resample run, rerun after `audit.welch_against_network` stopped rejecting a variance that rounded to -1e-17 on a constant resample, P-83), and
the margin is small: both lists still change almost completely between floors (floors 5 and 30,
and 10 and 30, share no top-20 corridor in either ranking). The reason is membership, not
noise: the Spearman correlation of rank positions over corridors present in both floors is
0.9997 to 1.0 for every ranking, and the top-20 restricted to the higher floor's corridors
overlaps at 1.0 for raw and 0.95 for `eb_prob`. A lower floor admits small corridors with
extreme means (mean top-20 corridor size 10.8 legs at floor 5, 47.7 at floor 30), which is
what moves the list. At floor 10, 102 corridors have `P(theta > t) >= 0.5`, 65 have 0.9 or more
and 60 have a 90% interval wholly above `t`, against 111 whose raw mean exceeds `t` and 273
published slower corridors; there are more material corridors than the 20 slots, which also
makes any top-20 sensitive to the floor. Sensitivity: inflating variances by the D-083 design
effect (median 1.38) gives Jaccard 0.140; threshold factors 1.25 and 2.0 give 0.161 and 0.142.
Paper: shrinkage and a probability ranking are better calibrated and slightly more stable, but
they do not remove the floor's effect on which corridors enter a top-20; report the whole
ranking and its intervals, not a top-20, and state the floor.

## D-082 · Temporal stability of the audit: split by creation date, three audit rules — `DECIDED`
**Post-v1.0 · Mounika · B5 · written before `src/ml/stability.py` is run**

**Question.** With 23 creation dates (2018-09-11 to 2018-10-03; the plan calls it 22 days, the
first date holds only 378 legs), do the corridors the audit flags in one part of the window
stay bad in another?

**Parts.** Legs are assigned to parts by the calendar date of `trip_creation_time`, in date
order, as contiguous groups of dates: halves of 12 and 11 dates (14,385 and 11,984 legs), thirds
of 8, 8 and 7 dates (9,219; 10,085; 7,065 legs). Pairs compared: the two halves; and, for
thirds, T1-T2, T1-T3, T2-T3 (earlier part first).

**Each part is audited independently**: its own network baseline, its own corridor family, its
own multiple-testing correction. Support rule, two readings: **headline = proportional floor**,
the 10-leg floor scaled to the share of the window, 5 legs per half and 4 per third, because a
10-leg floor in a half-window tests far fewer corridors than the published audit does; and the
**strict reading**, 10 legs in every part, reported beside it. Universe for a pair: corridors
testable (at or above the floor) in both parts.

**Audit rules applied to each part.** `bh_welch` (the published rule); `by_welch`; and `by_perm`
(the B3 headline of D-080, cell-permutation p-values with 100,000 permutations, seed 20260801,
Benjamini-Yekutieli). The empirical-Bayes ranking is the B4 headline, `eb_prob` with REML, and
the material threshold stays at the full-data value `t = 1.1838` for every part (D-081), so no
part sets its own bar.

**Statistics per pair, each with its n and an interval.**
1. Overlap of the significantly-slower sets: sizes, intersection, Jaccard, the overlap expected
   by chance given the sizes and the universe (hypergeometric mean) and its one-sided
   p-value, and a corridor bootstrap 95% interval for the Jaccard (2,000 resamples of the
   universe, seed 20260803).
2. Spearman correlation of corridor effects over the universe: the raw mean of `r` and the EB
   posterior mean, with a corridor bootstrap interval.
3. Persistence: of the corridors the earlier part flags, the share that are slower than the
   network in the later part, that is later-part mean of `r` above the later part's mean over
   all other legs, among those testable in the later part, and the share that are significantly
   slower there (`bh_welch`). Flagged sets: the earlier part's `bh_welch` slower set (raw), its
   top-20 by `excess_ratio` (raw top-20), and its top-20 by `eb_prob` (EB). Wilson 95%
   intervals; the base rate (the share of the whole universe slower in the later part) is
   reported as the reference, since half or more of any random set would also be slower.

**Reading rule, fixed now.** A Spearman correlation below 0.3 is called low stability, 0.3 to 0.6
moderate and above 0.6 substantial; a set overlap counts as above chance only if the
hypergeometric p is below 0.05. If the raw top-20 and the EB top-20 persistence shares have
Wilson intervals that overlap, the paper says "no detectable difference" and does not claim EB
predicts the later window better. If stability is low it is reported as a finding about how
often the audit has to be refreshed.

**Outcome (D-082).** `python -m src.ml.stability`, 100,000 permutations, 2,000 corridor
bootstrap resamples, `b5_stability.json`. Proportional floor, halves (14,385 and 11,984 legs):
1,249 and 1,004 corridors tested; significantly slower under `bh_welch` 239 and 191, under
`by_welch` 138 and 132, under `by_perm` 0 and 0 (the B3 headline finds nothing in any part,
half or third, as it found nothing in the whole window). Universe testable in both halves: 807
corridors. **Overlap of the `bh_welch` slower sets** (inside the universe, 173 and 151 corridors):
126 in common, Jaccard 0.636 (bootstrap 95% 0.57 to 0.70) against about 32 expected by chance,
hypergeometric p 9e-81; `by_welch` Jaccard 0.58 (0.50 to 0.66). **Spearman correlation of corridor
effects:** raw mean 0.908 (0.889 to 0.924), EB posterior mean 0.911, n = 807, both "substantial"
by the fixed reading. **Persistence:** of the 173 first-half `bh_welch` slower corridors, 97.7%
(Wilson 94.2% to 99.1%) are slower than the network in the second half and 72.8% significantly
so, against a base rate of 39.8% for the whole universe; of the 15 raw top-20 corridors
testable later, 100% (79.6 to 100) are slower and 93.3% significantly; of the 14 EB top-20, 100%
(78.5 to 100) and 100%. The two top-20 intervals overlap completely: **no detectable
difference** between raw and EB, as the rule requires, and with n = 14 to 15 nothing finer
could be seen. Fewer than 20 flagged corridors enter each statistic because the rest were not
testable in the later half. Thirds: Jaccard 0.548 / 0.504 / 0.566 (T1-T2, T1-T3, T2-T3),
Spearman 0.887 / 0.870 / 0.893, `bh_welch` set persistence 95.8% to 100%. The strict 10-leg
floor gives the same picture on a smaller universe (197 corridors: Jaccard 0.685, Spearman 0.899,
persistence 97.9%). **Stability is high, not low:** corridor effects reproduce on independent
trips from a different part of the window. Two cautions that stay with the result: the same
recurring services run in both parts (D-083), so this shows the corridors' pattern persists,
not that each is a distinct finding; and it is a statement about 23 dates in one season, not
about other months. It does not contradict D-080: persistence is a different question from
whether a single window's test survives a cluster-aware correction.


## D-095 · Venue shortlist: ECML PKDD 2027 Applied Data Science track and the Journal of Big Data are recommended; the owner decides — `DECIDED`
**Post-v1.0 · Mounika · upgrade work order item C2; revisits D-052**

`docs/venues.md` (researched 21 October 2026) compares 11 conferences and 13 journals on
scope fit, deadline, page limit, template, review type, indexing and cost, with every cell
marked as read on the venue's own page or as third-party. Two facts shape the outcome.
First, D-052's "ICCCI 2027, 20 February 2027" is the Tokyo conference on *Computer
Communication and the Internet* (networking and IoT topics), not *Computational Collective
Intelligence*; the latter has no 2027 call yet (see D-097). Second, no 2027 call exists yet
for most candidates, so no deadline below is a date, only a previous cycle.

**Recommended (a recommendation, not a choice): conference ECML PKDD 2027, Applied Data
Science track** - 16 pages LNCS, double-blind, "methodological novelty is not required",
reproducibility encouraged, about 24% acceptance in 2026 (90 of 381). Deadline unannounced;
the 2026 cycle was 12 March, so a March 2027 deadline is an inference. Fallback: ICCCI
(Computational Collective Intelligence) 2027, fit 3 of 5. **Journal: Journal of Big Data**
for the extended version - scope covers analytics platforms, applications and case studies;
median 47 days to first decision on its own aims page; open access, APC to be paid or waived
(about USD 1,990 per an aggregator, not confirmed). Stretch: Transportation Research Part E.

**Decision rule.** The owner picks the pair and records the choice in `HUMAN_ACTIONS.md`. The
LaTeX is kept template-neutral (shared `paper/refs.bib`, which compiles under IEEEtran,
splncs04 and elsarticle-num), so switching venue is a template swap. Each deadline is
re-checked on the venue's page in the first week of January 2027 and again before
submission. The journal's own rule on extended conference papers is read and recorded the day
of submission; the project keeps its own floor of 30% new material because no venue on the
list stated a percentage on a page that could be read.

**What this does not settle:** the author order, and whether the work is one paper or two.

## D-096 · A reference enters `refs.bib` only if title, authors, venue/year and an identifier were all confirmed — `DECIDED`
**Post-v1.0 · Mounika · upgrade work order item C4**

Rule applied to the 90 entries of `paper/refs.bib`, each confirmed on 21 October 2026 against
Crossref, the arXiv API, a proceedings or journal page, or a library catalogue, with the
source URL or DOI and the date in the entry's `note`. An item that failed any of the four
checks was left out (the Flink bulletin article for lack of volume and issue; a control-tower
review whose year the sources contradict; the Delhivery Kaggle page not opened; the Uber
engineering blog). Metadata that a record did not show (a subtitle, a page range) is added
only where it is the standard citation and the entry's note says so. Entries are tagged
`core` (33, for the page-limited paper) or `journal`. Status in `docs/references.md` is
`[metadata checked]` for all 90; **none is `[read]`**, so the paper may cite them but must not
describe their findings until a full-text pass marks them. The Model Context Protocol is cited
by its specification page, with no vendor named as author. Checked by
`tests/test_refs_bib.py` and by a test compile under three bibliography styles.

## D-097 · D-052's target venue is a networking conference; the schedule keyed to its 20 February 2027 date is withdrawn from the plan — `DECIDED`
**Post-v1.0 · Mounika · corrects D-052**

D-052 (18 September 2026) reads "ICCCI 2027 (9th Int. Conf. on Computer Communication and the
Internet)" and `iccci.org/sub.html`. Its topic list is networks, IoT, multimedia
communications, network management and security (re-read 21 October 2026). The work order and
the 14 October update treated "ICCCI" as *Computational Collective Intelligence*, whose
2027 call is not published. The two share an acronym and nothing else.

**Decided:** the 20 February 2027 date is no longer a plan date for this paper, because the
venue it belongs to is a poor scope fit (1 of 5). D-052 is left as written, as history; its
second decision (arXiv preprint posted when the draft is done, not when a venue answers)
stands unchanged. If the owner nonetheless wants the Tokyo conference, it is a 4-10 page,
double-blind submission and the paper would be cut to that scope. This is the owner's call.

## D-090 · One project name on the site, and the export reads the newest freeze — `DECIDED`
**Post-v1.0 (website phase) · Mounika**

1. The browser title, the header and the footer all use the full name, "Agentic AI Logistics
   Control Tower", from one constant (`web/lib/site.ts`). The old header said "Control Tower" and
   the title template said "· Control Tower"; a visitor saw three spellings.
2. `src.report.export_web` picks the highest `benchmarks/results_freeze_v<N>.json` by number.
   No version is typed anywhere, so a v5 is picked up by re-running the export.
3. A missing freeze key or benchmark field raises. Every `g('key', default)` and `.get(key, default)`
   that supplied a number is gone (removed: `assistant_route_accuracy` 0.9, `order_eval_run` 50,
   `order_eval_invented` 0, `lifecycle_cases/booked/ticketed` 10/5/2, and the overview defaults for
   legs, corridors, tested, bottlenecks, faster, median ratio).

## D-091 · Agent cards show metric, n, Wilson interval and trivial policy — `DECIDED`
**Post-v1.0 (website phase) · Mounika**

Every card leads with the strongest evidence, not the friendliest number: Order Entry the
held-out first run (170/200), Invoice Auditor the stratified 200 (180/200) with the 60-invoice seeded
run (precision 100%, recall 82.2%) and the 20-invoice development run kept as labelled history,
never "20 of 20" alone, and the Assistant route accuracy both ways on the same 30 questions
(93.3% model-phrased, `w7_assistant_run_llm.json`; 90.0% rules only). Intervals are recomputed
from counts with `src.ml.stats.wilson`, and the export raises if counts disagree with the freeze by
more than 0.0006. The orchestrator card is the 100-lifecycle run. The B7 ablation panel and the B3 `robust`
and B4 `EB rank` corridor columns render only when their result files exist.

## D-092 · The alert page is a replay, and says what the table is — `DECIDED`
**Post-v1.0 (website phase) · Mounika**

The page is titled "Alert replay". The table is the 60 worst corridors as examples, not the
1,347 alerts the run raised, and the page says so. It also states D-071: three alerts per channel
reached a real Telegram chat and mailbox, receipts kept with identifiers masked. No AWS (D-074).

## D-093 · Cold start is a state, not an error — `DECIDED`
**Post-v1.0 (website phase) · Mounika**

All four live surfaces wait up to 90 s (the keep-alive workflow's own limit), treat 502/503/504 as
"still waking" and retry, show "Waking the free server (up to ~1 min)" after 3 s, and end in a
notice with a Try again button, never a blank panel.

## D-094 · Quality bar: what was fixed and what is recorded, not fixed — `DECIDED`
**Post-v1.0 (website phase) · Mounika**

Charts and the hero map load when scrolled near (first-load JS 302 kB to 110 kB). Accessibility
reached 96-100 on every page (contrast tokens raised, form labels). Mobile-throttled performance
on the map pages stays below 90 and is recorded in `docs/deploy_web.md`; shipping less map was
judged worse than the number.

## D-085 · Exception precision gets intervals, a valid test and a trend test; the rule is fixed before the run — `DECIDED`
**Post-v1.0 · Mounika · B8, D-047, D-054**

The agent's 58.6% as-of notification precision (1,007 of 1,720 alerts) is compared in the
paper with a 54.1% trivial policy (alert every leg: 1,082 of 2,000 legs delayed). Neither
number has an interval, and the severity claim ("precision rises with grade") has no test.
`src/ml/exception_stats.py` adds them. It reads only counts already in
`w8_replay_leakage.json` (as-of and superseded end-of-data-history replay), so it needs no
Spark and no model run.

**Which test is valid, decided before running.** The two policies are scored on the *same*
2,000 legs, and the agent's alerted set is a subset of the trivial policy's set. A
two-proportion test treating 1,720 and 2,000 as independent samples is therefore not valid
(the samples overlap by 1,720 legs). The gap is an identity: with w = alerted share,
trivial = w·p_alerted + (1−w)·p_not_alerted, so
gain = (1−w)·(p_alerted − p_not_alerted). Testing "gain = 0" is exactly testing that the
alerted legs are delayed at the same rate as the 280 not-alerted legs, two *disjoint*
groups.

* **Primary test:** pooled two-proportion z-test, alerted vs not alerted (two-sided), with
  Fisher's exact test beside it as a check.
* **Second test:** a nonparametric bootstrap over the 2,000 legs (10,000 resamples, seed
  20260, percentile 95% interval for the gain, and the share of resamples with gain ≤ 0 as a
  one-sided p). Both groups are resampled together, so the pairing is respected.
* **Reported for reference only, flagged invalid:** the naive independent two-proportion
  z-test, so a reader who would run it sees why it is not the headline.
* Wilson 95% intervals for 58.6%, 54.1% and every per-severity precision (n = 453 / 667 /
  308 / 292), for the as-of run and the superseded replay run.
* **Trend:** Cochran–Armitage test of precision against severity grade (scores 1..4,
  two-sided), implemented in the module and unit-tested against a hand computation.

**Decision rule.** The gain is significant if the primary test gives p < 0.05 *and* the
bootstrap interval excludes 0. If either fails, the write-up must say "directionally better;
not significant at n = 2,000 legs (1,720 alerts)" and may not call the gain an improvement.
If the trend test gives p ≥ 0.05, the monotonic-severity claim is withdrawn to "the point
estimates rise". Applied as written, whatever the outcome.

**Limits stated in advance.** Legs share corridors, so legs are not independent and the
intervals are somewhat optimistic; the counts file has no leg-level corridor ids, so a
cluster bootstrap is not possible without re-running the replay. The 2,000 legs are the
earliest legs by creation time, 1,290 of them corridor-cold, so this is the hardest case for
the model and not a typical day. I had read the counts (1,007 / 1,720 and 1,082 / 2,000)
before writing this entry; the test choice follows from the sampling structure, not from the
outcome.

## D-086 · The deterministic-core vs LLM-decides ablation, pre-registered — `DECIDED`
**Post-v1.0 · Mounika · B7, D-041, D-028, D-043**

D-041 says the agents decide with arithmetic and the model only writes the sentence. Nothing
in the project has tested that position against the obvious alternative: let a language model
make the decision. This entry fixes the experiment before any model call is made for it.

**Agents and sets (existing sets, not new ones).**

| agent | set | full size | LLM subset | stratified by |
|---|---|---|---|---|
| order entry | `w9_order_eval_set.json` | 200 emails, 20 templates | 40 | 2 per template |
| invoice audit | `w9_invoice_eval_set.json` | 200 invoices, 10 kinds | 40 | 4 per kind |
| exception severity | `w6_exception_eval_cases.csv` (superseded end-of-data replay alerts; only the decision rule is compared, so the history leak is common to both arms) | 1,347 alerts | 40 | 10 per deterministic grade |

The deterministic arm is run on the full set and on the same subset, and the comparison uses
the subset. Subsets are drawn with seed 8602, then ordered round-robin across strata, so any
prefix is balanced. If provider quota binds, cases are completed in that order and the
completed prefix is reported with its n; no case is half-run.

**The LLM-decides variant.** The model receives exactly the inputs the code receives, plus
the policy written out in prose (the rate card, the other-charge share, the tolerance, the
severity cut-offs, the ask/file rules). The prose is written independently of the code and is
versioned in `src/agents/prompts/<agent>/llm_verdict_v1.md`. Giving the policy to the model
means the ablation isolates *who executes the policy*, not who knows it. It must answer in a
strict JSON schema: order entry `file | ask | reject` plus fields; exception severity
`low | medium | high | critical`; invoice `approve | dispute` plus a reason code. Parsing is
strict (one JSON object, a closed vocabulary); anything else is an error and is counted, not
repaired. An `ask` maps to the code's `clarify`; a `reject` is scored as wrong because the
sets contain no non-orders. Invoice duplicate checking uses a ledger of 20 prior invoice
numbers (the duplicate's source when one exists plus fixed decoys), identical for both arms,
because the full history would not fit the provider's token limit.

**Model.** The deployed prose model is a Gemini model with a free-tier cap of about 20 calls a
day (D-032); this design needs about 900. The LLM arm therefore uses an open model through
Groq's free tier: `openai/gpt-oss-120b`, the largest open model the key lists (the other
models listed were gpt-oss-20b, qwen3.8-27b and allam-2-7b; no Llama model is available).
Reasoning effort `low`, completion cap 600 tokens. **It is not the model that writes the
project's prose**, and the paper must say so. A Gemini subset (order entry only, temperature 0,
the first 20 subset cases) is attempted only if its daily cap allows, and reported separately,
never merged.

**Runs.** Per case: 5 calls at temperature 0.7 (a stochastic setting; the code's own default
is 0.0, which would make "5 runs" one run repeated), plus 2 calls at temperature 0 (the
determinism check). Every response is cached on disk by (agent, case, run, temperature,
prompt hash, model), so a rerun costs nothing. A token, latency and call ledger is written.
Rate limits are obeyed with backoff, never worked around.

**Metrics, each with a Wilson 95% interval where it is a proportion.** Order entry: accuracy
as `order_eval_scale` scores it (action, fields, and the field asked about), the invented-value
rate (an order filed with a field the case never stated, or a centre code that does not appear
verbatim in the email), clarification recall. Invoice: verdict accuracy, dispute recall,
false-dispute count, right reason code. Exception: exact agreement with the code's grade,
agreement within one grade, and the area under the ROC curve of grade against the leg really
being late (reported for both arms, wide interval at this n). All agents: unanimity across the
5 sampled runs, Fleiss' kappa across them, share of cases whose two temperature-0 verdicts
match, parse-error count, latency, tokens. Cost is $0 on the free tier; a paid-equivalent
cost per 1,000 verdicts is computed from the provider's published price and labelled an
estimate.

**Decision rule.** Report whatever happens. Accuracy is compared on the same cases: the
difference LLM minus deterministic, per-run pooled, with a case-level bootstrap interval. If
the LLM-decides arm's accuracy is greater than or equal to the deterministic arm's, the paper
says so. If the interval contains 0 the paper says the arms are not distinguishable at this n.
The case for deterministic verdicts is then made, or not made, on reproducibility and cost
alone, and only if the numbers show a difference there.

**Harder sets, held out.** The existing order set has contradiction, two-consignment,
pounds-vs-kg, Hinglish and city-only cases but no missing-unit, wrong-centre-code or
second Hinglish-style stress, and the invoice set has no case at the 15% tolerance edge on
either side. New small sets (`b7_order_hard_set.json`, `b7_invoice_boundary_set.json`) fill
only those gaps. They are written by code that shares nothing with the agents' rules (D-028),
are still synthetic, and are scored once on first run: deterministic arm on all cases, LLM arm
once at temperature 0 on the same cases. Nothing is tuned against them; if a rule is fixed
afterwards both numbers are reported.

## D-087 · The hard sets are held out; the first-run result stands and nothing is tuned — `DECIDED`
**Post-v1.0 · Mounika · B7, D-086, D-028, P-76**

`src/ml/b7_hard_sets.py` builds two sets the existing 200-case sets did not cover:
**100 order emails** (10 templates: weight with no unit, three kinds of malformed centre
code, conflicting piece counts, conflicting service level, two Hindi-English bookings in one
mail, and three Hindi-English phrasings) and **100 invoices at the tolerance edges** (freight
2% inside and outside both ends of the tolerated rate band, other-charge share just inside and
outside both ends, a total off by half a paisa versus two paise). Seeds are 9031 and 9033
(9032 hits P-77). The builder imports none of the agents' rules and restates the rate model and
tolerances itself. Both sets are synthetic, and the invoice labels use the same 15% tolerance
the auditor uses, so what is measured is behaviour at the edge, not whether 15% is right.

**First run of the unmodified deterministic agents, before any model call touched these
sets** (`b7_hard_sets_deterministic.json`):

| agent | correct | 95% interval |
|---|---|---|
| order entry | 70 / 100 | 60.4% to 78.1% |
| invoice audit | 100 / 100 | 96.3% to 100.0% |

Order entry scored 0 of 10 on `conflict_pieces`, `hinglish_file` and `hinglish_tonnes` and
10 of 10 on the other seven templates. The invoice auditor was right on every edge case,
which is what an arithmetic check with a stated tolerance should do.

**Decided.** The agents are not modified in response. The order result is the held-out number
and it is lower than the 100.0% the paper quotes for the 200-email set, which was measured
after fixing what that set found (85.0% on first run, `w9_order_eval.json`). The paper reports 85.0% on the
first run of the 200, 100.0% after the fix, and 70 of 100 on this set. If the reader is fixed
later, both numbers on this set are reported, and the set is then spent. The LLM-decides arm
is run once at temperature 0 on a balanced prefix of the same cases (`b7_hard_sets_llm.json`).

## D-088 · The free tier caps the ablation at pilot scale; the design is kept and the n is stated — `DECIDED`
**Post-v1.0 · Mounika · B7, D-086, docs/cost.md**

D-086 assumed the provider's limit was requests and tokens per minute. The limit that binds
is **tokens per day: 200,000 for `openai/gpt-oss-120b` on this key** (the provider's own 429:
"Limit 200000, Used 199374, Requested 1072"), refilling continuously, about 8 calls an hour once
spent. One verdict costs about 1,100 tokens (order entry), 900 (invoice) or 500 (exception),
and a case is 7 verdicts, so the day's allowance is about 30 cases across all three agents,
not the 120 the design needs. The full D-086 sample would take about four days of quota.

**Decided, before any further call is made:**

1. The primary arm keeps its design and model (`openai/gpt-oss-120b`, 5 runs at 0.7 plus 2 at
   temperature 0) and is reported at the **completed balanced prefix**, with its n and Wilson
   intervals, which D-086's subset policy already allows. The first launch ran agents one
   after another before this was visible, so the prefixes are unequal (order entry 18 cases,
   invoice 8, exception 8); later launches interleave agents case by case. The word
   "pilot" is used for these results, and no claim of a difference is made where the interval
   on the difference contains 0.
2. A second model, `openai/gpt-oss-20b` (its own daily allowance), runs the same design
   interleaved at 8 cases per agent, and the held-out hard sets run once at temperature 0 on
   it (20 cases per agent, balanced prefix). Its numbers are written to separate files with the
   model id in the name and are **never merged** with the 120b arm. It answers a different
   question (does a smaller open model do worse) and is not a substitute for the 120b sample.
3. Responses are cached on disk, so resuming on a later day continues from where this stopped
   (`python -m src.ml.agent_ablation --llm-verdict`), and the n in every file grows with no
   re-spend. The decision rule of D-086 is unchanged and is applied to whatever n exists when
   the files are frozen.
4. Document extraction rows 21 to 40 were attempted on the same Gemini model and the free tier
   allowed five more clean extractions (P-75); rows 21 to 40 stay unreported and no model is
   mixed.

## D-089 · What the pilot ablation supports, and what it does not — `DECIDED`
**Post-v1.0 · Mounika · B7, D-086, D-088**

The decision rule of D-086 applied to the files as they stand (`b7_agent_ablation.json`,
`openai/gpt-oss-120b`, n = 18 / 8 / 8 cases; `b7_agent_ablation_gpt-oss-20b.json`, n = 8 / 8 / 8):

* **Order entry.** The model scored 87.8% pooled over 5 runs at temperature 0.7 (79 of 90,
  Wilson 79.4% to 93.0%) against the rule route's 100% on the same 18 emails; the case-level
  bootstrap interval for the difference is -25.6 to -2.2 points, so the arms are
  distinguishable and the code is ahead. 83.3% of cases drew the same verdict on all 5 runs
  (Fleiss kappa 0.82), 17 of 18 matched across two temperature-0 runs, and 6 of 50 orders the
  model filed (12.0%, 5.6% to 23.8%) carried a value the email did not support, against 0 for
  the rules. **Caveat that goes with it:** the rules' 100% is on a set they were fixed against
  (85.0% on first run); on the held-out hard set they score 70% (D-087). The model arm was not
  fixed against any set. The 20b model scored 72.5% (8 cases).
* **Invoice audit.** Both arms scored 87.5% on the same 8 invoices (the one error is the
  designed tolerance miss `overcharge_hidden`), the model gave identical verdicts on all runs
  and no false disputes. n = 8 supports no comparison.
* **Exception severity.** Given the cut-offs in prose, the model reproduced the code's grade on
  40 of 40 verdicts (8 cases). Arithmetic on two numbers is within its reach; this too is
  n = 8 and says nothing about harder inputs.

**What the paper may say.** That a deterministic core is at least as accurate where the policy
is arithmetic (invoice, severity), and ahead and reproducible on order entry at pilot scale,
where the model's extra failures were invented values and 1 in 6 cases drawing different
verdicts on re-run. That this is one open model on 8 to 18 cases per agent, not the Gemini
model used for prose. It may not say the LLM arm is generally worse, nor claim a cost advantage
beyond latency and the tokens measured. The full 40-case design is resumable from cache.
