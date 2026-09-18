# Streaming throughput and latency

**Owner: Mounika.** Populated Week 5 (first measurements) and Week 7 (final stress run).

This file carries the project's big-data architecture claim (blueprint §12), so the
measurement conditions matter as much as the numbers.

## Results — full replay, file source (Week 5, restated Week 7)

Source: `python -m src.streaming.producer --sink file` then `python -m src.streaming.job --once`
→ `benchmarks/raw/w5_stream_throughput_full.json`.

| Metric | Value | Conditions |
|---|---|---|
| Sustained throughput (events/sec) | **886.4** | producer's own rate over the full 26,369-leg replay compressed into 60 s |
| Scoring throughput (events/sec) | **739.9** | events ÷ time actually spent in the micro-batches, excluding idle polling |
| p50 event→alert latency | **28.9 s** | tick file written → alert row written |
| p95 event→alert latency | **38.0 s** | |
| Max event→alert latency | **40.5 s** | |
| Total events replayed | **52,738** | 26,369 queries + 26,369 facts |
| Alerts emitted | **17,317** | |
| Trigger interval | 0.5 s tick files, `availableNow` drain | `maxFilesPerTrigger` 1000 |
| Cores / driver memory | 20 cores / 4 g | local[*] on the development laptop, nothing else running |
| Source | **file source**, not Kafka | no Docker on this machine (D-035) |

**The two latency numbers that matter are different.** 28.9 s p50 is dominated by the
replay's own compression — 52,738 events are offered in 60 seconds, so a queue forms at
the source and an event's wait includes the queue. The pipeline's own cost is the 739.9
events/sec scoring rate and the 19.8 s slowest batch. A dashboard-facing number would be
the first; a capacity-planning number is the second.

## Batching: the trigger cap changed whether it kept up

Two 2,000-leg runs, identical except for `maxFilesPerTrigger`
(`w5_stream_throughput.json`, `w5_stream_throughput_unbatched.json`):

| `maxFilesPerTrigger` | batches | kept up? | p50 latency |
|---|---|---|---|
| 4 | 5 | **no** | 46.8 s |
| 1000 | 2 | yes | 32.3 s |

Same data, same model, same machine: capping files per trigger to 4 made the job fall
behind, because per-batch overhead (loading the broadcast history, planning) is paid once
per batch regardless of size. The job's default is 1000 for that reason; `--max-files-per-trigger`
exists to reproduce the slower run, not to tune it down.

## Kafka

Never measured. The producer's Kafka sink, the job's `--kafka` source and
`scripts/kafka_live.sh` exist and are import-checked; there is no Docker on the
development machine, so every number on this page came from the file source (D-035). On a
machine with Docker, `docker compose -f docker-compose.kafka.yml up -d && bash
scripts/kafka_live.sh` writes `benchmarks/raw/w7_kafka_live.json` in the same shape as the
table above, and the comparison becomes a two-row table rather than a caveat.

## Recording rules

- State whether Kafka or the file-source fallback produced the number. They are not
  interchangeable, and the 3-day rule (GIT_RULES / execution plan W5) permits the
  fallback — but only if the report says which was used.
- Report **sustained** throughput over a run long enough to pass warm-up, not a peak.
- Give the machine: cores, driver memory, whether anything else was running.
- Latency is measured event-produced → alert-emitted, not batch duration.
