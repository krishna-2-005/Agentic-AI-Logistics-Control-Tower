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

## Kafka — measured on a live broker (G-05, Week 8)

Source: a single-node **Apache Kafka 4.1.2** broker in KRaft mode, run natively on the JVM
(`scripts/kafka_native.ps1`); producer → broker → `src.streaming.job --kafka` → alert sink.
`benchmarks/raw/w7_kafka_live.json`, `w7_kafka_source_equivalence.json`.

| Metric | Value | Conditions |
|---|---|---|
| Events through the broker | **4,000** | 2,000 legs, the same earliest-2,000 replay the Exception agent was evaluated on |
| Alerts | **1,347** | |
| p50 event→alert latency | **20.2 s** | broker append time → alert row written |
| p95 event→alert latency | **28.0 s** | |
| Scoring rate | **86.7 events/sec** | 11 micro-batches; per-batch overhead dominates at this size |
| Source | **Kafka**, 4 partitions, keyed by corridor | localhost broker, same machine as the job |

**The result that matters is not the speed.** Replaying the same 2,000 legs through Kafka
and through the file source produced **the same 1,347 alerts on the same legs with the same
predicted gaps — maximum difference 0.0 minutes.** The source swap is one `readStream`, and
this is the evidence that it is only that: everything after it behaves identically whichever
source fed it.

**Not comparable to the full-replay row above, and not meant to be.** The file-source table
is the full 26,369-leg replay compressed into 60 s (886 events/sec offered); this run is 2,000
legs, 67 events/sec offered. Throughput here is bounded by what the producer offers, not by
the pipeline. A full-replay Kafka run is a one-line change to `--limit` and belongs in
Phase 3's cost comparison.

**Why no Docker.** G-05 was blocked for two weeks on "no Docker on this machine" (D-035).
Kafka is a Java program, and the machine has had a JDK since Week 1. The one Windows trap —
`kafka-server-start.bat` calls `wmic`, which Windows 11 no longer ships — is handled by
setting `KAFKA_HEAP_OPTS` first. `docker-compose.kafka.yml` remains for machines that have
Docker.

**The replay caveat applies here too** (D-054): both sources join each query to end-of-data
history, so these alerts carry the same leak the file-source ones did. Source equivalence
is unaffected — the leak is identical on both sides.

## Recording rules

- State whether Kafka or the file-source fallback produced the number. They are not
  interchangeable, and the 3-day rule (GIT_RULES / execution plan W5) permits the
  fallback — but only if the report says which was used.
- Report **sustained** throughput over a run long enough to pass warm-up, not a peak.
- Give the machine: cores, driver memory, whether anything else was running.
- Latency is measured event-produced → alert-emitted, not batch duration.
