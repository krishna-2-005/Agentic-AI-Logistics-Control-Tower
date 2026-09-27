# Scale appendix — identical Spark code on 50M+ rows

**Owner: Mounika.** Populated Week 7.

The blueprint (§12) rests the big-data claim partly on this: the same corridor
aggregation code, unchanged, run on NYC TLC trip records at two orders of magnitude
more data, with a runtime table.

## Results

Source: `python -m src.pipeline.scale_benchmark --months N --cores C` →
`benchmarks/raw/w7_scale_benchmark.json`. Machine: 20 logical cores, 4 g Spark driver,
local[N], nothing else running. Every row is the **same two functions**,
`src.ml.audit.network_baseline` and `src.ml.audit.corridor_aggregate`, imported and called
unchanged — the Delhivery row is the Week 2 audit's own aggregation step.

| Dataset | Rows | Corridors | Cores | Driver memory | Wall time | Rows/sec |
|---|---|---|---|---|---|---|
| Delhivery `trips_v1` | 26,369 | 2,783 | 20 | 4 g | 2.37 s | 11,112 |
| NYC TLC yellow, 1 month | 2,904,141 | 25,479 | 20 | 4 g | 2.38 s | 1,219,346 |
| NYC TLC yellow, 6 months | 19,967,144 | 44,209 | 20 | 4 g | 7.45 s | 2,680,847 |
| **NYC TLC yellow, 17 months** | **56,353,613** | 51,515 | 20 | 4 g | **14.32 s** | 3,936,022 |
| NYC TLC yellow, 17 months | 56,353,613 | 51,515 | **4** | 4 g | 17.75 s | 3,175,407 |

Wall time includes each measurement's own parquet scan (see "What had to change", below).

## What the table says

**The aggregation is not the bottleneck at this project's size.** 26,369 legs and
2,904,141 taxi trips take the same 2.4 seconds: at Delhivery's scale the entire runtime is
Spark's fixed cost — planning, task scheduling, shuffle setup — and the data is a rounding
error inside it. That is worth stating plainly in a project whose premise is distributed
processing: **Spark is not what makes the Delhivery numbers possible, and the honest
justification for it is the 56M-row row, not the 26k-row one.**

**It scales roughly linearly past that point.** 2.9M → 20.0M rows (6.9×) costs 3.1× the
time; 20.0M → 56.4M (2.8×) costs 1.9×. Throughput keeps climbing with size because the
fixed cost is amortised, reaching **3.9M rows/sec** at 56M rows.

**More cores bought less than expected.** The same 56.4M rows take 14.32 s on 20 cores and
17.75 s on 4 — a 1.24× speedup for 5× the parallelism. The job is reading ~914 MB of
parquet from a single local disk, and past four concurrent readers the disk, not the CPU,
sets the pace. A cluster with the data spread across nodes would not have this ceiling;
one laptop does, and the appendix would be dishonest to report the 20-core number without
the 4-core one beside it.

## What had to change, and what did not

**The code: nothing.** `network_baseline` and `corridor_aggregate` are imported. The one
Spark parameter changed is `spark.sql.shuffle.partitions`, from the project's usual 8 to
`max(8, cores × 2)`, because 8 partitions cannot use 20 cores.

**The measurement: caching was dropped.** The first version cached the input so the timer
measured compute alone. At 56M rows that exhausted the 4 g driver and the run died in the
aggregation with `SparkOutOfMemoryError`. Measuring straight from parquet is what fits on
this machine and what a real job does, so every row above includes its own scan.

## The schema mapping

A taxi trip is a leg between two zones. The mapping, in full, from
`src/pipeline/scale_benchmark.py`:

| leg column | taxi source |
|---|---|
| `corridor_id` | `PULocationID>DOLocationID` (265 zones → 51,515 observed corridors) |
| `actual_time` | dropoff − pickup, in minutes |
| `osrm_time` | `trip_distance` ÷ 24 km/h — **a stand-in for a routing plan**, not a plan any taxi was given |
| `gap_min`, `gap_ratio`, `log_gap_ratio` | derived from those two, by Stage 2's own formulas |
| `dwell_min` | 0 — taxi records carry no hub dwell |
| `route_type` | FTL above 8 km, else Carting — a bucketing, not a service class |

**The `osrm_time` stand-in is the caveat that matters.** Any *gap* statistic computed on
this data is about a synthetic plan and says nothing about New York traffic; the table
above deliberately reports no gap figures. Runtime is unaffected by what the column means,
which is why runtime is the only thing claimed.

## Rules

- **The Spark code must be genuinely identical** — same functions, imported, not
  copy-adapted. If a parameter has to change (shuffle partitions, for instance), state
  which and why. A re-implementation proves nothing about the original.
- Report cores and memory per row of the table. A runtime without them is unreadable.
- Include the schema mapping used to present taxi trips as corridor legs.
