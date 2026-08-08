# `data/` — how to get the data

**Nothing in this folder is committed** (GIT_RULES §7). This file is the only tracked thing here.
Every member reproduces the folder locally with the steps below.

---

## Expected layout

```
data/
├── README.md               ← tracked
├── raw/                    ← immutable. Never written to by any script.
│   └── delhivery_data.csv
├── processed/              ← Spark outputs, safe to delete and rebuild
│   ├── clean_v1/           ← Stage 1 output (partitioned Parquet)
│   ├── trips_v1/           ← Stage 2 output (Week 2)
│   └── features_v1/        ← Stage 3 output (Week 3)
├── documents/              ← synthetic BOL/invoice corpus (Week 3)
├── chroma_db/              ← vector store (Week 6)
├── tms.sqlite              ← mock TMS database (Week 2)
└── spark-tmp/              ← Spark scratch
```

Only `raw/` requires a manual download. Everything else is generated.

---

## 1. Primary source — Delhivery Logistics Dataset

<https://www.kaggle.com/datasets/devarajv88/delhivery-logistics-dataset>

Mirrors, in case the primary is pulled (the blueprint requires all three archived):
- `kaggle.com/datasets/santanukundu/delhivery-dataset`
- `kaggle.com/datasets/nayanack/delhivery`

### Via the Kaggle CLI

```bash
pip install kaggle
# put your kaggle.json in ~/.kaggle/ (Windows: %USERPROFILE%\.kaggle\)
kaggle datasets download -d devarajv88/delhivery-logistics-dataset -p data/raw --unzip
mv data/raw/delhivery_data.csv data/raw/delhivery_data.csv   # confirm the filename
```

### Manual

Download the CSV from the Kaggle page and save it as `data/raw/delhivery_data.csv`.

---

## 2. Verify you have the same file everyone else has

```bash
# Windows PowerShell
Get-FileHash data/raw/delhivery_data.csv -Algorithm SHA256

# macOS / Linux / Git Bash
sha256sum data/raw/delhivery_data.csv
```

| Property | Expected |
|---|---|
| SHA-256 | `ca654e6233912172cfde4c11fa5f194fa0b635961c0816b46b13dd71c06e78ed` |
| Size | 55,617,128 bytes (~53 MiB) |
| Rows | 144,868 physical lines (the file has no trailing newline) → **144,867 data rows** |
| Columns | 24 |

If your hash differs you have a different mirror's copy — **stop and tell the team** before running
anything. Two members computing statistics on different files is the worst kind of silent bug.

Automated check:

```bash
python -m src.common.check_env
```

---

## 3. What the raw file contains

One row per **shipment segment** (a scan-to-scan hop), not per shipment. Multiple segments share a
`trip_uuid`; Stage 2 (Week 2) aggregates them into legs. The 24 columns are profiled in
[`docs/W1_lahari_data_dictionary.md`](../docs/W1_lahari_data_dictionary.md).

The two columns the whole project hinges on:

- **`actual_time`** — cumulative realised minutes for the trip so far.
- **`osrm_time`** — what the production OSRM routing engine predicted for the same stretch.

Their gap, aggregated per corridor, is the project's core analytical claim.

---

## 4. Scale appendix data (Week 7 — Mounika only)

NYC TLC trip records, for re-running the identical corridor-aggregation Spark code on 50M+ rows:
<https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page>

Download the Parquet monthlies into `data/nyc_taxi/` — do **not** convert them to CSV. Six months of
Yellow Taxi data clears 50M rows comfortably.

---

## 5. Rules

- `raw/` is **immutable**. No script opens it in write mode. If cleaning needs to change, change the
  cleaning code and rebuild `processed/`.
- `processed/` is **disposable**. Anyone must be able to `rm -rf data/processed` and rebuild it with
  one command. If that stops being true, something has been done by hand that should have been a
  script.
- Nothing here is ever committed. If `git status` shows a file from `data/`, the `.gitignore` is
  broken — fix it, do not `git add -f`.
