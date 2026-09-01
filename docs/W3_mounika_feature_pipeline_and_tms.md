# W3 · Mounika — leak-free feature pipeline, frozen `features_v1`, TMS extension

## What I built

**Stage 4 — `src/pipeline/features.py`.** Reads the 26,369 OD legs from `trips_v1` and
writes `features_v1`: one row per leg, carrying only values that were **knowable at
the moment the shipment was created**, plus the three targets Lahari's baselines and
Week 4's models train against.

```bash
python -m src.pipeline.features               # build features_v1
python -m src.pipeline.features --validate     # + leakage checks + naive-leak measurement
```

## D1–D2 · Why this stage exists at all

D-018 widened the audited set and closed with an open item addressed to me: the
corridor audit's `excess_ratio` is the single most predictive number in the project —
it says how badly a corridor overruns — and it is fitted over the **whole** 26-day
observation window. Handed to a model as a feature exactly as it stands, it would be
training on a column that already contains part of the answer for every leg the model
is later asked to predict (D-005). Beating OSRM with that column in the table would
not be a result, it would be a leak with a headline number attached.

So corridor (and hub) history is recomputed from scratch here, **as of each leg's own
`trip_creation_time`** — nothing in this table may hand a model a statistic fitted on
the full period.

## D1–D2 · Two clocks, and the difference between them is the whole trap

A leg is predicted when the shipment is created. Checked across all 26,369 legs:
`trip_creation_time <= od_start_time`, without exception — a genuine decision point,
not a column that quietly post-dates dispatch.

But a *prior* leg's outcome is not usable the moment that leg starts; it becomes
usable when it **finishes**, at `od_end_time`, because that is the earliest anyone
could know how long it actually took. Ordering a corridor's history by
`od_start_time` — the natural thing to write — leaks a departing leg's own future
into itself. I built that version first and measured it before trusting it:

| What the naive clock (`od_start_time`) leaks | Legs | % of table |
|---|---|---|
| Reads its own departure as already-known history | 12,245 | **46.4%** |
| Handed another journey's duration before it landed | 2,216 | **8.4%** |
| Affected either way | 12,818 | **48.6%** |

Caught before it reached Lahari's baselines, not after — this is P-25, and D-020
carries the decision it forced: history is ordered on `od_end_time`.

## D1–D2 · Computing it without a self-join

The direct implementation is a self-join on `corridor_id` with an inequality
predicate — a cross join per corridor. The busiest corridor in this data runs 151
legs, which is 22,801 pairwise comparisons for one corridor alone, and the cost grows
with the square of traffic rather than with it — it would not survive contact with
production volumes, the thing Layer 1 is supposed to demonstrate it can do (blueprint
§12).

Instead every leg emits a **fact** at `od_end_time` ("this outcome is now known") and
a **query** at `trip_creation_time` ("what was known here?"). Both are unioned,
partitioned by key, ordered by `(event_time, kind)` with facts sorting first so a fact
known at exactly T counts for a query at T, and a running window accumulates the fact
columns from the start of the partition to the current row. Reading off the query rows
gives every leg its own past in one pass. The same shape gives hub history by
partitioning on `source_center` / `destination_center` instead of `corridor_id`.

## D3–D4 · What is in the table, and what refuses to be

**Base features, knowable at creation time:** `corridor_id`, `source_center`,
`destination_center`, `route_type`, `trip_creation_time`, `planned_min` (OSRM's own
estimate), `planned_km`, `created_hour`, `created_dayofweek`, `created_is_weekend`.

**History, three keys, five columns each** (`corr_*`, `src_*`, `dst_*`):
`n_prior`, `mean_log_ratio`, `std_log_ratio`, `mean_gap_min`, `last_log_ratio`,
`hours_since_last` — 33 columns in total.

**Both hub ends get their own history, closing D-015's open note.** Week 2 found hub
friction and corridor friction are close to independent — idle time at a facility and
the planner being wrong about the road between facilities are not the same
phenomenon — and said Week 3 should carry hub friction as its own feature rather than
assume corridor history already encodes it. `src_*`/`dst_*` are exactly that: the same
as-of join, keyed on the centre code instead of the corridor.

**What is deliberately not in the table:** `actual_time`, `start_scan_to_end_scan`,
`dwell_min`, `factor`, `gap_ratio`, `n_segments`, every `segment_*` sum,
`actual_distance_to_destination`, and the OD window itself — every column that only
exists because the journey happened. These are listed in `BANNED_FEATURES`, and the
writer raises rather than emit a table containing any of them, so the leakage rule is
enforced by the code rather than remembered by whoever edits it next. `gap_min`,
`log_gap_ratio` and `is_delayed` are carried through only as `TARGETS`.

**`leg_id` replaces `trips_v1`'s three-column key** because a trip can legitimately
repeat a corridor on a different day — `trip_uuid|od_start_time|corridor_id` stays
unique where `(trip_uuid, corridor_id)` would not.

## D3–D4 · Three checks that run inside the build, not after it

1. **No banned column survived** — checked against `BANNED_FEATURES` before the write.
2. **A leg never sees its own outcome** — the first leg on any corridor must have a
   null mean, not a zero. Zero would silently tell a model "this corridor never
   overruns" instead of "nothing is known yet".
3. **Every counted prior leg had actually finished** — recomputed independently on a
   200-row sample with the predicate spelled out longhand
   (`od_end_time <= trip_creation_time`), compared to the window's own output.
   `sample_mismatches: 0`.

Plus one adversarial test built by hand rather than hoped for in a random sample
(`tests/test_features.py::test_in_flight_leg_is_excluded`): three synthetic legs where
one departs early but lands late, asserting it does not count as known history at the
moment a later leg queries the same corridor. `pytest tests/test_features.py -q` — 11
passed.

## D3–D4 · Frozen as `features_v1` (D-016)

Registered in `src/pipeline/contracts.py` as a new `Contract`, following the
versioning rule exactly — added, not repointed:

```bash
python -m src.pipeline.contracts --keys
# features_v1 OK v1, 33 columns, 26,369 rows
```

## Numbers

From `data/processed/features_v1/_feature_report.json`:

| Property | Value |
|---|---|
| Legs in → feature rows out | 26,369 → **26,369** (no leg dropped) |
| Feature columns | 33 |
| Observation window | 2018-09-12 → 2018-10-03 |
| Mean / median prior legs per corridor | 10.77 / 6 |
| Legs with corridor history at creation time | **88.91%** |
| Legs with source-hub history | **93.44%** |
| Cold-start legs (corridor's first sighting) | 11.09% — nulled, not defaulted to zero |
| Naive clock: reads its own record | 46.44% |
| Naive clock: handed an unfinished journey | 8.40% |
| Naive clock: affected either way | 48.61% |

**D-018 is why 88.91% is possible at all.** At the old 30-leg audit floor's
18.9%-of-legs coverage, a feature this central to the project would have started life
mostly null. The wider floor's biggest payoff was never the audit table itself — it
was making the feature pipeline usable on the majority of the network.

## D5 · Mock TMS extended: shipment status, exception tickets, invoices

Week 2 scope was orders and shipments; this closes the rest of D-017's endpoint list.

```bash
python -m src.tms                    # http://localhost:8000/docs
pytest tests/test_tms.py -q          # 41 passed
```

**`PATCH /shipments/{ref}`** — moves a shipment through
`created -> in_transit -> delivered`, or flags it `exception`. `delivered` is terminal,
the same way a cancelled order is: nothing in the plan needs a delivered shipment to
un-deliver.

**`POST /exceptions`** — files a ticket against a shipment (`severity`, `reason`,
optional `notes`) and, deliberately, **flips the shipment to `exception`** at the same
time — the same reasoning D-017 already uses for booking a shipment confirming its
order. The Week 6 lifecycle should not end with an open ticket against a shipment that
still reads `in_transit`. `GET /exceptions` filters by `status`/`severity`;
`PATCH /exceptions/{ref}` moves `open -> acknowledged -> resolved` and stamps
`resolved_at` itself rather than trusting a client-supplied timestamp.

**`POST /invoices`** — submits a freight invoice against a shipment
(`freight_charge`, `other_charges`, `total_amount`, `currency`,
`external_invoice_number`). **Charges are stored exactly as submitted** —
`total_amount` is not reconciled against `freight_charge + other_charges` on the way
in. That reconciliation is the Week 6 Invoice Auditor's whole job; an API that
silently fixed the arithmetic would make D-021's (Krishna's doc-corpus decision)
`total_mismatch` seeded error unevaluable once it reaches the TMS side.
`PATCH /invoices/{ref}` moves `submitted -> approved` or `submitted -> disputed`, and
disputing without a `dispute_reason` is rejected (422) — a disputed invoice always
says why.

Both new tables carry a business reference in the existing style: `EXC-000001`,
`INV-000001`. 15 new tests cover the lifecycle transitions, the five 404 paths, the
corridor-filterable listings, and the dispute-reason requirement.

## Environment

Rebuilt from `trips_v1` on this machine, JDK 17 + `HADOOP_HOME=C:\hadoop` (D-012).
Full suite: `pytest tests/ -q` — 52 passed. `ruff check src/pipeline/ src/tms/
tests/` — clean.

## For Lahari

- `features_v1` is what your split and baselines read. Every `corr_*`/`src_*`/`dst_*`
  column is null (not zero) where `n_prior == 0` — cold start needs its own handling
  in whatever model reads it, not a silent default.
- `gap_min`, `log_gap_ratio`, `is_delayed` are in the table only as targets — they are
  not eligible as features for the reason the whole stage exists.
- D-020 is logged as decided from my side; if anything about the as-of history should
  behave differently for a baseline (e.g. a different cold-start fallback), it is a
  new decision on top of this one, not a change to the stage.

## For Krishna

- The TMS's new `EXC-`/`INV-` references and the `total_amount` pass-through are built
  with the Week 6 Invoice Auditor and Exception Agent as the intended callers — shout
  if the fields you'll actually need from either don't match what's here yet, it costs
  a migration now and a rewrite later.
