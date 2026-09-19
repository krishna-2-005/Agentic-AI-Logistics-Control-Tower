# W8 · Mounika — reproducibility, release assets, and what it cost

Week 8's job on my side is to make the repository work on a machine that has never seen
it, and to package what a reader cannot regenerate in an afternoon.

```bash
python -m src.common.boot --check          # the first thing a new machine should run
python -m src.report.release --manifest-only   # what the release archives would contain
python -m src.report.release --out dist/       # build them
```

## 1. The reproducibility pass, and the one thing it found

Method: clone the repository to a directory it had never been in, with no `data/`, no
`.env`, and nothing warm, then follow the README as written.

**Nine of the dashboard's nine pages render** on a clone with no data at all — each one
reports what is missing instead of raising. That was not luck; it is the `load_csv(...) is
None → pending(...)` pattern from Week 1, and this is the first time it has been tested
under the conditions it was written for.

**The finding: `boot --check` was confidently wrong (P-59).** On a fresh clone it printed a
tidy list — cleaned parquet missing, run `python -m src.pipeline.clean`. Following that
advice fails, because there is no raw dataset to clean. `preflight()` checked four
generated artefacts and never checked the 55 MB input they are generated *from*: on every
machine where the check was written, the CSV had been there since Week 1.

A missing check is found at the first failure. A confident, incomplete check sends someone
to debug `clean.py` when what they needed was a download link. The raw dataset is now the
first preflight line, verified against `config.RAW_BYTES`, with `data/README.md` as its
fix:

```
[MISS] raw dataset: missing ...\data\raw\delhivery_data.csv   -> download it — see data/README.md
[MISS] cleaned parquet: clean_v1   -> python -m src.pipeline.clean
```

**The full rebuild, from nothing.** The README's run order stopped at Stage 3 (P-63), so
`scripts/rebuild_all.sh` now runs every module's own command in dependency order and ends by
recomputing the frozen results. It was run on a clone that had never been built, with only
the raw CSV added (`benchmarks/raw/w8_fresh_clone_rebuild.json`):

- **71 minutes, 14 stages**; the champion model (28 min) and the adopted model's validation
  (30 min) are most of it, every data stage is under 40 seconds.
- **Of 37 frozen numbers, 35 came back exactly** — 273 slower corridors of 1,130, every Week 7
  model MAE including the adopted **30.90**, the same step size, the same adoption outcome. The
  two that moved are extraction accuracy and rows scored, which the rebuild does not re-run:
  the committed evaluation grew from 11 to 20 rows after the freeze was taken.
- **The document corpus regenerated with an identical manifest and identical text**, but
  every committed sample PDF showed as modified — ReportLab stamps a creation date. Krishna's
  corpus now renders with `invariant=1`, and two generations are byte-identical.

That is the reproducibility claim the project can now make: someone with the raw CSV and one
command gets the same numbers the paper reports.

## 2. Release assets

`src/report/release.py` bundles what a reader cannot practically rebuild:

| bundle | contents | size |
|---|---|---|
| `parquet-caches` | Stage 1-4 outputs: cleaned legs, trips, hub dwell, `features_v1`, `features_v2` | 24 MB |
| `models` | every fitted model — Week 4's champion and Week 7's adopted residual model | 7.6 MB |
| `documents` | the 120-consignment corpus: 240 PDFs, 240 degraded scans, 240 label files | 23 MB |
| `tms-database` | the mock TMS SQLite, with the orders and tickets the agents actually filed | 0.3 MB |

Each archive is listed in `release_manifest.json` with its SHA-256, so a download can be
checked rather than trusted. Four things are deliberately **not** in there: the Delhivery
CSV (someone else's dataset — linked, not redistributed), 914 MB of public NYC taxi parquet
(the script that used it downloads it), secrets, and the Chroma index (90 seconds to
rebuild, and version-locked to the library that wrote it).

## 3. Cost

**$0.00**, written out in `docs/cost.md` with what the zero bought. The short version: the
20-calls-a-day LLM cap is why agent verdicts are computed rather than generated, one laptop
with one disk is why the scale curve flattens past four cores, and no Docker is why Kafka
has never met a broker. Those three constraints did more to shape the architecture than any
design meeting, and Phase 3's $40 credit should be spent on removing them in that order.

## 4. Carried into Phase 3

- **G-05**, a live broker: the compose file and `scripts/kafka_live.sh` are one command on
  any machine with Docker; this one has none.
- **Serving the adopted model**: the streaming job carries the corridor *mean* in its
  history snapshots and the adopted model is a residual over the *median* (D-050). Until
  that lookup exists, the reported model and the served model are different models, and
  both the decision log and the paper outline say so.

Problems logged this week: P-59.
