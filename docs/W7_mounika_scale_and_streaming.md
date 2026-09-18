# W7 · Mounika — feature table v2, the finish-time fix, Kafka, and the scale appendix

My Week 7 was the data side of the correction sprint (feature table v2, so Lahari had
something new to train on), the streaming bug her diagnostics turned up, and the two
things the blueprint's big-data claim rests on: a real broker and a run at scale.

```bash
python -m src.pipeline.features_v2                      # D1-D2, the new feature table
python -m src.pipeline.contracts --keys                 # the contract, bumped to v2
python -m src.pipeline.scale_benchmark --months 17      # D4, 56.4M rows
docker compose -f docker-compose.kafka.yml up -d && bash scripts/kafka_live.sh   # G-05
```

## 1. Feature table v2 (D1-D2)

Eight new columns, all past-only, all rebuilt through the same leakage checks Week 3's
table passes:

| column | why |
|---|---|
| `corr_median_gap_min` | the baseline the sprint learns a residual against (D-048) |
| `corr_p90_gap_min`, `corr_iqr_gap_min`, `corr_std_gap_min` | a high-variance corridor deserves a different prediction from a stable one; a mean hides that |
| `corr_mean_gap_7d`, `corr_n_prior_7d` | drift the all-time mean smooths away, with its own support count |
| `src_dwell_by_hour_min`, `dst_dwell_by_hour_min` | median dwell is 49 min — 34.6% of wall clock — and it is a queueing effect that varies by hour more than by corridor |

`corr_mean_gap_7d`, `src_dwell_by_hour_min` and `dst_dwell_by_hour_min` can be empty on a
warm corridor, so each carries a `_is_cold` indicator: D-023's rule is that a zero fill
must say "unknown", never "known and zero".

The contract is a **new version**, `FEATURES_V2`, not a repointed v1 (D-016): v1 stays
exactly where it was so anything mid-flight keeps reading what it was built against.

**G-11 closed without a feature.** The plan asked for `is_festival_window` if the data
covers Navratri–Dussehra. It does not: the extract runs 11 September to 3 October 2018,
and Navratri began 10 October. Ganesh Chaturthi (13 September) is inside the window but
falls only in the training period, so the flag would be constant in test and could never be
validated. Nothing was added, and D-048 records why.

**The one cross-check worth its cost.** My Spark median and Lahari's independent pandas
recomputation agree on **100% of 23,444 warm legs**. Her script refuses to train if they
ever disagree — two implementations of a baseline that quietly diverge would make every
number after it meaningless.

## 2. The finish-time bug (P-52)

Lahari's as-of reconstruction agreed with Stage 4 on 95.2% of legs, not 100%, and tracking
that down found a bug in my streaming schema: a fact event's time was
`od_start_time + actual_time`, with a comment calling it exact.

It is not. `actual_time` is *moving* time — `reconstruct.py` computes dwell as
`start_scan_to_end_scan − actual_time` — so the derived finish excludes every minute the
truck sat at a hub. Measured against the real `od_end_time`:

- the derived time was **early on 26,298 of 26,369 legs**;
- median **49.6 minutes** early, mean 98.1, p95 345.2.

49.6 minutes is the median hub dwell Week 2 reported. The bug was re-deriving a column the
data already contains.

Facts are dropped by the streaming job today (D-037), so nothing published was wrong yet —
but the moment live history is built from fact events, a leg still on the road would be
counted as finished history, which is the leakage the whole as-of design exists to prevent.
`fact_event` now refuses a row with no finish time rather than deriving one, and both the
producer and the sample-event writer join `od_end_time` from `trips_v1`. The join is exact
on all 26,369 legs.

## 3. Kafka (G-05) — everything except the broker

The job can now read from a topic as well as from files: one `readStream` swap, with the
broker's append time playing the part `file_modification_time` plays for the file source,
so event-to-alert latency means the same thing whichever source produced it. A compose file
brings up a single-broker KRaft Kafka, and `scripts/kafka_live.sh` runs producer → broker →
job → sink and writes `benchmarks/raw/w7_kafka_live.json`.

**It has still never run against a broker, because this machine has no Docker.** Every
streaming number in this repository comes from the file source, and the honest-scope
section says so in those words. What changed this week is that the gap is now one command
on any machine that has Docker, rather than an afternoon of wiring.

The file-source numbers are now written up properly in
`benchmarks/streaming_throughput.md`: **886 events/sec** sustained over the full
52,738-event replay, **740 events/sec** of saturated scoring, event-to-alert **p50 28.9 s**
and **p95 38.0 s**, on 20 cores and a 4 g driver. The page also carries the batching
comparison — capping `maxFilesPerTrigger` at 4 made the same job fall behind where 1000
kept up, because per-batch overhead is paid once per batch whatever its size.

## 4. The scale appendix (D4) — 56.4M rows

`src/pipeline/scale_benchmark.py` imports `network_baseline` and `corridor_aggregate` from
`src.ml.audit` and calls them **unchanged** on NYC TLC yellow-taxi records mapped into the
leg shape. A re-implementation would prove something about the benchmark instead of about
the project.

| Dataset | Rows | Cores | Wall time | Rows/sec |
|---|---|---|---|---|
| Delhivery `trips_v1` | 26,369 | 20 | 2.37 s | 11,112 |
| NYC TLC, 1 month | 2,904,141 | 20 | 2.38 s | 1,219,346 |
| NYC TLC, 6 months | 19,967,144 | 20 | 7.45 s | 2,680,847 |
| **NYC TLC, 17 months** | **56,353,613** | 20 | **14.32 s** | 3,936,022 |
| NYC TLC, 17 months | 56,353,613 | 4 | 17.75 s | 3,175,407 |

**Two things this table says that are not flattering, and belong in the paper anyway.**

26,369 legs and 2,904,141 taxi trips both take 2.4 seconds. At this project's own size the
entire runtime is Spark's fixed cost, so **Spark is not what makes the Delhivery numbers
possible** — the justification for the architecture is the 56M-row row, not the 26k-row
one.

And five times the cores bought 1.24 times the speed. The job reads 914 MB of parquet off
one local disk; past about four concurrent readers the disk sets the pace, not the CPU. A
cluster with data spread across nodes would not have that ceiling, and publishing the
20-core number without the 4-core one beside it would imply a scaling story this machine
cannot support.

The mapping from taxi trips to legs, including the stand-in for `osrm_time` and why no gap
statistic is reported from it, is in `benchmarks/scale_appendix.md`.

Problems logged this week: P-52 (fixed here). Decisions touched: D-016 (contract
versioning), D-023 (cold-start indicators), D-035 (the Kafka caveat), D-048 (G-11).
