#!/usr/bin/env bash
# G-05 — the replay through a real Kafka broker, end to end, in one command.
#
#   docker compose -f docker-compose.kafka.yml up -d
#   bash scripts/kafka_live.sh                 # producer -> broker -> streaming job -> sink
#
# Writes benchmarks/raw/w7_kafka_live.json: sustained events/sec and event-to-alert p50,
# measured the same way the file-source numbers in benchmarks/streaming_throughput.md
# were, so the two are comparable rather than merely both present.
#
# Why this exists as a script rather than a paragraph in the README: D-035 records that
# the Kafka path had never been run against a live broker, and the reason was always
# "no Docker on this machine", never a missing step. Anywhere with Docker -- a laptop, a
# GitHub Codespace -- this closes that gap without a decision to make.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python}"
SERVERS="${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}"
TOPIC="${KAFKA_TOPIC_TRIPS:-delhivery.trips}"
DURATION="${DURATION:-60}"
LIMIT="${LIMIT:-2000}"
OUT="benchmarks/raw/w7_kafka_live.json"

# Spark's Kafka connector is not in the base install; it is resolved at submit time.
# Pinned to the running PySpark's own version, because a mismatched connector fails at
# the first batch with a class-not-found that reads like a broker problem.
SPARK_VERSION="$($PYTHON -c 'import pyspark; print(pyspark.__version__)')"
export PYSPARK_SUBMIT_ARGS="--packages org.apache.spark:spark-sql-kafka-0-10_2.13:${SPARK_VERSION} pyspark-shell"

echo "waiting for the broker on ${SERVERS}"
for _ in $(seq 1 60); do
  if $PYTHON - <<PY
import socket, sys
host, port = "${SERVERS}".split(":")
sys.exit(0 if socket.socket().connect_ex((host, int(port))) == 0 else 1)
PY
  then break; fi
  sleep 2
done

echo "starting the streaming job (kafka source)"
$PYTHON -m src.streaming.job --kafka --kafka-servers "$SERVERS" --kafka-topic "$TOPIC" \
        --duration "$DURATION" --clean --stats-out "$OUT" &
JOB_PID=$!
trap 'kill $JOB_PID 2>/dev/null || true' EXIT

sleep 25   # the job loads the champion model and three history snapshots before it reads

echo "replaying ${LIMIT} legs into ${TOPIC}"
$PYTHON -m src.streaming.producer --sink kafka --limit "$LIMIT" --duration "$DURATION" --validate

wait $JOB_PID
echo "wrote ${OUT}"
