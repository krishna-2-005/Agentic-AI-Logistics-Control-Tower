# Data card: Delhivery trip records, as used by this project

**What this is.** A description of the one real dataset under every network result in this
repository: where it comes from, what was done to it, what a "leg" is, and what it cannot
support. Every number below is read from a committed file, named in brackets, and
`tests/test_cards.py` checks them against those files.

**Owner:** Mounika (data and pipeline). **Licence and provenance:** `DATA_LICENSE.md`.

---

## Source

| | |
|---|---|
| **Dataset** | Delhivery logistics trip records, public release on Kaggle |
| **Link** | <https://www.kaggle.com/datasets/devarajv88/delhivery-logistics-dataset> |
| **Operator** | Delhivery, an Indian road-freight and parcel carrier: one operator, one country |
| **Unit of the raw file** | a scan-level **segment**: one row per movement between consecutive scans within a trip |
| **Raw rows** | **144,867** segments across **14,817** trips `[w1_clean_quality_report.json]` |
| **Window** | segments from 12 September to 8 October 2018 (by OD window); legs *created* 12 September to 3 October 2018 `[w1_clean_quality_report.json]` |
| **Redistributed here?** | **No.** `data/` is gitignored. The public site and API carry aggregates and model output only (D-073). |

**The field that makes the project possible.** Each row carries the production routing
engine's planned time and distance (`osrm_time`, `osrm_distance`, from OSRM) beside the
realised time. The planner's error is therefore measurable directly, not simulated.

## What was done to it

### Stage 1: clean (no row is dropped) `[w1_clean_quality_report.json]`

| step | count |
|---|---|
| rows in | 144,867 |
| rows dropped (any reason) | **0** |
| exact duplicates dropped | 0 |
| timestamp cast failures | 0 in each of the four timestamp columns |
| null sentinels converted to nulls | 293 `source_name`, 261 `destination_name` |
| state inferred from a PIN code | 551 |
| rows out | 144,867 |

Cleaning repairs types and keys and **flags** suspect rows rather than removing them:

| flag | rows |
|---|---|
| `is_negative_segment` | 1,973 |
| `is_zero_osrm_segment` | 2,347 |
| `is_suspect` (either) | 2,600 |

Distinct values after cleaning: 14,817 trips, 2,783 corridors, 1,508 source centres, 1,481
destination centres. Route type at segment level: 99,660 FTL, 45,207 Carting.

### Stage 2: reconstruct legs `[w2_reconstruction_report.json]`

144,867 segments become **26,369 origin–destination legs** on **2,783 corridors**.

### Stage 3: hubs

The legs touch **1,657 distinct facilities**; **121** of them have at least 30 legs and are
ranked for dwell `[w2_hub_report.json]`, `[w2_hub_dwell.csv]`.

## What a "leg" is

A **leg** is one trip's movement from one facility to the next: one `trip_uuid`, one
`source_center → destination_center`, from the first scan out to the last scan in. A trip
with three stops has two legs. Its key is `trip_uuid | od_start_time | corridor_id`, because
the same trip can repeat a corridor on another day.

A **corridor** is an ordered pair of facilities (`source > destination`). Of 2,783
corridors, **1,130 have at least ten legs** and are the ones the audit tests
`[w2_audit_report.json]`.

Each leg carries:

| quantity | meaning |
|---|---|
| `planned_min`, `planned_km` | OSRM's estimate (the plan) |
| `actual_time` | realised **moving** time |
| `start_scan_to_end_scan` | realised wall-clock time, scan to scan |
| dwell | `start_scan_to_end_scan − actual_time`: time parked at the hub |
| `gap_min` | `actual_time − planned_min`: how late the leg ran, the quantity the model predicts |

**Two definitions that cost the project time, recorded so they cost nobody else:**

* **A leg finishes at its last scan (`od_end_time`), not at departure plus moving time.**
  The second places every finish a median 49.6 minutes early, because it forgets dwell, and
  counts unfinished legs as history (P-52).
* **"Delayed" means more than 2.0× the planned time** (D-003). The `is_delayed` column in
  the processed data was written at the rejected 1.25× threshold and is stale (P-42). At
  2.0×, **13,093 legs (49.65%)** are delayed; at 1.25×, 24,687 (93.62%)
  `[w1_delay_threshold_sensitivity.csv]`.

## What the data shows at a glance `[w2_reconstruction_report.json]`

| | |
|---|---|
| legs running over plan | **98.3%** |
| median gap ratio (actual ÷ planned) | **2.0** |
| median gap | 42 min |
| mean gap | 110.0 min |
| median dwell | 49 min |

## As-of history, and what is cold

Every corridor and hub history feature uses only legs **finished before the leg was
created** (D-020). With that rule, **11.09%** of legs have no prior leg on their corridor, and
6.56% / 6.33% none at their source / destination hub `[w3_baseline_report.json]`. The model
receives an explicit cold indicator for each, not a zero that would read as "known to be
on time".

## What this data cannot support

* **Generalisation beyond one carrier, one country and three weeks.** Every network result
  is about Delhivery's network in September–October 2018.
* **Seasonality.** Twenty-two days of leg creation cannot show weekly-to-seasonal drift.
  The trailing 30-day feature the plan proposed would equal the all-time mean.
* **Causes.** The data records *that* a leg ran late, not why (traffic, loading, paperwork,
  weather). The audit localises; it does not explain.
* **Real documents and orders.** The agents' documents, emails and TMS are synthetic
  scaffolding generated by this project (`DATA_LICENSE.md`); only the network data is real.

## Regenerate

```bash
python -m src.pipeline.clean          # -> clean_v1 + _quality_report.json
python -m src.pipeline.reconstruct    # -> trips_v1 + _reconstruction_report.json
python -m src.pipeline.hubs           # -> hubs_v1
```

The three stage reports are copied, with local paths removed, to
`benchmarks/raw/w1_clean_quality_report.json`, `w2_reconstruction_report.json` and
`w2_hub_report.json`.
