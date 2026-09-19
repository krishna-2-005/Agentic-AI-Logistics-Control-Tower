"""Scale appendix (execution plan v3.1 W7 D4) -- the Week 2 aggregation on 50M+ rows.

    python -m src.pipeline.scale_benchmark --months 1            # ~3M rows, a smoke run
    python -m src.pipeline.scale_benchmark --months 17           # 50M+ rows, the appendix row
    python -m src.pipeline.scale_benchmark --months 6 --cores 4  # the same data on fewer cores

The claim under test is not "Spark is fast". It is that **this project's corridor
aggregation is the code that scales** -- so `network_baseline` and `corridor_aggregate`
are imported from `src.ml.audit` and called unchanged. Nothing here reimplements them; if
they were reimplemented, the appendix would prove something about this file instead.

The data is real: NYC TLC yellow-taxi trip records, one parquet file per month, public
and stable. A taxi trip is a leg between two zones, which is the same shape as a leg
between two centres:

| leg column | taxi source | honest note |
|---|---|---|
| `corridor_id` | `PULocationID>DOLocationID` | 265 zones -> up to ~70k corridors, against Delhivery's 1,130 |
| `actual_time` | dropoff - pickup, minutes | the realised duration, exactly as in `trips_v1` |
| `osrm_time` | `trip_distance` / `PLANNED_SPEED_KMPH` | **a stand-in for a routing engine's plan**, not a plan the taxi was given |
| `gap_min`, `gap_ratio`, `log_gap_ratio` | derived from those two | the same three lines Stage 2 uses |
| `dwell_min` | 0 | taxi records carry no hub dwell; the column exists so the aggregation runs |
| `route_type` | FTL above `FTL_KM`, else Carting | a bucketing, not a service class |

The `osrm_time` stand-in is the load-bearing caveat: the *numbers* this produces are
about a synthetic plan and say nothing about New York traffic. The *runtime* is what the
appendix reports, and that is unaffected by what the column means.

Downloads are cached under `data/raw/nyc_taxi/` and skipped if present.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from src.common import config
from src.common.logging_setup import get_logger
from src.ml.audit import corridor_aggregate, network_baseline

log = get_logger("pipeline.scale_benchmark")

TAXI_DIR = config.RAW_DIR / "nyc_taxi"
TAXI_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_{year}-{month:02d}.parquet"
#: 2023 and 2024 are complete years of the current schema; 17 months clears 50M rows.
MONTHS = [(2024, m) for m in range(1, 13)] + [(2023, m) for m in range(1, 13)]

#: The stand-in plan. 24 km/h is roughly free-flow city speed; any constant would do, as
#: the runtime does not depend on it, and the constant is stated rather than tuned.
PLANNED_SPEED_KMPH = 24.0
FTL_KM = 8.0
KM_PER_MILE = 1.609344

REPORT_JSON = config.BENCHMARKS_RAW_DIR / "w7_scale_benchmark.json"


def download(year: int, month: int) -> Path:
    TAXI_DIR.mkdir(parents=True, exist_ok=True)
    path = TAXI_DIR / f"yellow_tripdata_{year}-{month:02d}.parquet"
    if path.exists():
        return path
    url = TAXI_URL.format(year=year, month=month)
    log.info("downloading %s", url)
    tmp = path.with_suffix(".part")
    with urllib.request.urlopen(url, timeout=120) as response, tmp.open("wb") as fh:
        while chunk := response.read(1 << 20):
            fh.write(chunk)
    tmp.replace(path)
    log.info("%s (%.1f MB)", path.name, path.stat().st_size / 1e6)
    return path


def as_legs(spark: SparkSession, paths: list[Path]) -> DataFrame:
    """Taxi trips in `trips_v1`'s leg shape, so the audit's own functions accept them."""
    raw = spark.read.parquet(*[str(p) for p in paths])
    # TLC writes these as TIMESTAMP_NTZ, which Spark refuses to cast straight to a number;
    # the hop through `timestamp` is what makes the subtraction legal.
    epoch = {c: F.col(c).cast("timestamp").cast("long") for c in ("tpep_pickup_datetime", "tpep_dropoff_datetime")}
    minutes = (epoch["tpep_dropoff_datetime"] - epoch["tpep_pickup_datetime"]) / 60.0
    km = F.col("trip_distance") * F.lit(KM_PER_MILE)
    legs = (
        raw.select(
            F.concat_ws(">", F.col("PULocationID").cast("string"), F.col("DOLocationID").cast("string")).alias("corridor_id"),
            F.col("PULocationID").cast("string").alias("source_center"),
            F.col("DOLocationID").cast("string").alias("destination_center"),
            minutes.alias("actual_time"),
            (km / F.lit(PLANNED_SPEED_KMPH) * 60.0).alias("osrm_time"),
            km.alias("osrm_distance"),
            F.col("tpep_pickup_datetime").alias("od_start_time"),
        )
        .filter((F.col("actual_time") > 0) & (F.col("osrm_time") > 0))
        .withColumn("trip_uuid", F.concat_ws("-", F.col("corridor_id"), F.date_format("od_start_time", "yyyyMMddHHmmss")))
        .withColumn("gap_min", F.col("actual_time") - F.col("osrm_time"))
        .withColumn("gap_ratio", F.col("actual_time") / F.col("osrm_time"))
        .withColumn("log_gap_ratio", F.log(F.col("gap_ratio")))
        .withColumn("dwell_min", F.lit(0.0))
        .withColumn("route_type", F.when(F.col("osrm_distance") >= FTL_KM, "FTL").otherwise("Carting"))
    )
    # The audit reads names, cities and states for its report; the zone ids carry all the
    # identity a taxi trip has, so they stand in rather than being invented.
    for column in ("source_name", "destination_name", "source_city", "dest_city", "source_state", "dest_state"):
        source = "source_center" if column.startswith("source") else "destination_center"
        legs = legs.withColumn(column, F.col(source))
    return legs


def measure(spark: SparkSession, legs: DataFrame, label: str, cores: int) -> dict:
    """Time the two audit functions straight off parquet, scan included.

    An earlier version cached the input so the timer measured compute alone. At 56M rows
    that is not a choice this machine has: caching the frame exhausted the 4 g driver and
    the run died in the aggregation. Measuring from parquet is both what fits and what a
    real job does, so the wall time below includes each measurement's own scan, and the
    number is comparable across sizes because every row of the table is measured that way.
    """
    rows = legs.count()
    started = time.perf_counter()
    baseline = network_baseline(legs)
    agg = corridor_aggregate(legs)
    corridors = agg.count()
    elapsed = time.perf_counter() - started
    log.info("%s: %s rows, %s corridors, %.1f s on %d core(s)", label, f"{rows:,}", f"{corridors:,}", elapsed, cores)
    return {
        "dataset": label, "rows": rows, "corridors": corridors, "cores": cores,
        "driver_memory": config.SPARK_DRIVER_MEMORY,
        "wall_seconds": round(elapsed, 2),
        "includes_parquet_scan": True,
        "rows_per_second": round(rows / elapsed),
        "network_mean_gap_min": round(baseline["mean_gap_min"], 2),
    }


def run(months: int, cores: int | None, include_delhivery: bool = True) -> dict:
    cores = cores or multiprocessing.cpu_count()
    spark = SparkSession.builder.master(f"local[{cores}]").appName("scale-benchmark") \
        .config("spark.driver.memory", config.SPARK_DRIVER_MEMORY) \
        .config("spark.sql.shuffle.partitions", str(max(8, cores * 2))) \
        .config("spark.local.dir", str(config.SPARK_LOCAL_DIR)) \
        .config("spark.sql.session.timeZone", "Asia/Kolkata") \
        .getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    rows = []
    try:
        if include_delhivery:
            from src.ml.audit import load_legs

            rows.append(measure(spark, load_legs(spark, config.TRIPS_V1), "Delhivery trips_v1", cores))
        paths = [download(*m) for m in MONTHS[:months]]
        rows.append(measure(spark, as_legs(spark, paths), f"NYC TLC yellow, {months} month(s)", cores))
    finally:
        spark.stop()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_under_test": ["src.ml.audit.network_baseline", "src.ml.audit.corridor_aggregate"],
        "identical_code": True,
        "parameters_changed": {"spark.sql.shuffle.partitions": f"max(8, cores*2) instead of the usual 8, "
                                                               f"so a {cores}-core run is not bottlenecked on 8 tasks"},
        "planned_time_stand_in": {"speed_kmph": PLANNED_SPEED_KMPH,
                                  "note": "taxi records carry no routing-engine plan; runtimes are unaffected"},
        "runs": rows,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(REPORT_JSON.read_text(encoding="utf-8")) if REPORT_JSON.exists() else {"runs": []}
    report["runs"] = [r for r in existing.get("runs", []) if (r["dataset"], r["cores"]) not in
                      {(n["dataset"], n["cores"]) for n in rows}] + rows
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("wrote %s", REPORT_JSON)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Week 2 corridor aggregation at scale")
    parser.add_argument("--months", type=int, default=1, help=f"NYC TLC months to load (max {len(MONTHS)})")
    parser.add_argument("--cores", type=int, default=None, help="local[N]; defaults to every core")
    parser.add_argument("--no-delhivery", action="store_true", help="skip the small reference row")
    args = parser.parse_args()
    run(months=min(args.months, len(MONTHS)), cores=args.cores, include_delhivery=not args.no_delhivery)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
