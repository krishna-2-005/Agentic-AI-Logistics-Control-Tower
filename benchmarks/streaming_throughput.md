# Streaming throughput and latency

**Owner: Mounika.** Populated Week 5 (first measurements) and Week 7 (final stress run).

This file carries the project's big-data architecture claim (blueprint §12), so the
measurement conditions matter as much as the numbers.

## Status: awaiting Week 5

| Metric | Value | Conditions |
|---|---|---|
| Sustained throughput (events/sec) | _pending_ | |
| p50 event→alert latency (ms) | _pending_ | |
| p95 event→alert latency (ms) | _pending_ | |
| p99 event→alert latency (ms) | _pending_ | |
| Total events replayed | _pending_ | |
| Trigger interval | _pending_ | |
| Cores / driver memory | _pending_ | |
| Source | _pending_ | Kafka, or the file-source fallback |

## Recording rules

- State whether Kafka or the file-source fallback produced the number. They are not
  interchangeable, and the 3-day rule (GIT_RULES / execution plan W5) permits the
  fallback — but only if the report says which was used.
- Report **sustained** throughput over a run long enough to pass warm-up, not a peak.
- Give the machine: cores, driver memory, whether anything else was running.
- Latency is measured event-produced → alert-emitted, not batch duration.
