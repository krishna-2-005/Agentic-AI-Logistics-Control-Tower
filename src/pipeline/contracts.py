"""Frozen schema contracts for the cached Parquet datasets.

    python -m src.pipeline.contracts              # check every dataset on disk
    python -m src.pipeline.contracts --dataset trips_v1
    python -m src.pipeline.contracts --emit hubs_v1   # print a contract to paste when bumping

Three people build on these caches at once. Lahari's features read `trips_v1`,
Krishna's dashboard and MCP tools read `hubs_v1`, the streaming job will read both.
Without a contract, a column renamed in `src/pipeline/` shows up as a `KeyError` in
somebody else's notebook a day later, or — worse — as a silently missing feature.

What "frozen" means here
-----------------------
A contract is a literal in this file: the exact column set, the exact Spark type of
each column, the partition columns, and the row count the dataset had when it was
frozen. `verify()` compares the dataset on disk against it and reports every
difference. Anything that would change what a reader sees is a **breach**, including
a column that was *added* — a contract that silently tolerates new columns is not a
contract, and an added column means the version needs bumping.

Versioning rule
---------------
The version is in the path (`clean_v1`, `trips_v1`, `hubs_v1`) and in the contract.
When a stage's output changes shape:

1. add `CLEAN_V2` (etc.) to `src/common/config.py` — **do not repoint the v1 path**;
2. add a new `Contract` here with `version=2`, leaving the v1 entry in place;
3. move the producing stage's default `--output` to the new path.

Teammates' in-flight work keeps reading the version it was written against until they
choose to move, and `--check` keeps passing for both. The frozen row counts make the
check a regression test on the pipeline as a whole, not only on its column names:
the raw CSV is pinned by SHA-256 (`config.RAW_SHA256`), so the same code over the same
input must produce the same number of rows.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

from pyspark.sql import SparkSession

from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("pipeline.contracts")


@dataclass(frozen=True)
class Contract:
    """The frozen shape of one cached dataset."""

    name: str
    version: int
    path: Path
    produced_by: str
    #: column name -> Spark ``simpleString()`` type. Order is deliberately not part of
    #: the contract: Spark returns partition columns last on read regardless of the
    #: order they were written in, so comparing order would fail for no reason.
    columns: dict[str, str]
    #: Written with ``partitionBy``. These come back as columns on read.
    partition_by: tuple[str, ...] = ()
    #: Columns that uniquely identify a row. Checked with ``--keys``.
    key: tuple[str, ...] = ()
    #: Row count when frozen. ``None`` for datasets whose size legitimately varies.
    rows: int | None = None
    notes: str = ""

    @property
    def value_columns(self) -> dict[str, str]:
        """Columns excluding the partition columns."""
        return {k: v for k, v in self.columns.items() if k not in self.partition_by}


# ── clean_v1 — Stage 1 output ────────────────────────────────────────────────
CLEAN_V1 = Contract(
    name="clean_v1",
    version=1,
    path=config.CLEAN_V1,
    produced_by="src.pipeline.clean",
    partition_by=("route_type",),
    key=("source_row_index",),
    rows=config.RAW_ROWS,  # Stage 1 drops nothing on the published file
    notes=(
        "Segment grain — one row per raw CSV row. `source_row_index` preserves the "
        "source file's row order and is what Stage 2 uses to find each leg's last row "
        "(D-014); removing it breaks reconstruction."
    ),
    columns={
        "data": "string",
        "trip_creation_time": "timestamp",
        "route_schedule_uuid": "string",
        "trip_uuid": "string",
        "source_center": "string",
        "source_name": "string",
        "destination_center": "string",
        "destination_name": "string",
        "od_start_time": "timestamp",
        "od_end_time": "timestamp",
        "start_scan_to_end_scan": "double",
        "is_cutoff": "boolean",
        "cutoff_factor": "double",
        "cutoff_timestamp": "timestamp",
        "actual_distance_to_destination": "double",
        "actual_time": "double",
        "osrm_time": "double",
        "osrm_distance": "double",
        "factor": "double",
        "segment_actual_time": "double",
        "segment_osrm_time": "double",
        "segment_osrm_distance": "double",
        "segment_factor": "double",
        "source_row_index": "bigint",
        "corridor_id": "string",
        "name_backfilled": "boolean",
        "source_state": "string",
        "source_city": "string",
        "dest_state": "string",
        "dest_city": "string",
        "state_from_pin": "boolean",
        "is_negative_segment": "boolean",
        "is_zero_osrm_segment": "boolean",
        "is_suspect": "boolean",
        "od_duration_min": "double",
        "route_type": "string",
    },
)

# ── trips_v1 — Stage 2 output ────────────────────────────────────────────────
TRIPS_V1 = Contract(
    name="trips_v1",
    version=1,
    path=config.TRIPS_V1,
    produced_by="src.pipeline.reconstruct",
    partition_by=("route_type",),
    key=("trip_uuid", "od_start_time", "od_end_time"),
    rows=26_369,
    notes=(
        "OD-leg grain (D-002) — the grain every corridor statistic, feature and model "
        "is computed at. `actual_time` / `osrm_time` / `osrm_distance` are leg totals "
        "taken from the last segment row, not sums."
    ),
    columns={
        "trip_uuid": "string",
        "od_start_time": "timestamp",
        "od_end_time": "timestamp",
        "data": "string",
        "trip_creation_time": "timestamp",
        "route_schedule_uuid": "string",
        "source_center": "string",
        "source_name": "string",
        "destination_center": "string",
        "destination_name": "string",
        "source_city": "string",
        "source_state": "string",
        "dest_city": "string",
        "dest_state": "string",
        "start_scan_to_end_scan": "double",
        "corridor_id": "string",
        "actual_time": "double",
        "osrm_time": "double",
        "osrm_distance": "double",
        "actual_distance_to_destination": "double",
        "factor": "double",
        "n_segments": "bigint",
        "segment_actual_time_sum": "double",
        "segment_osrm_time_sum": "double",
        "negative_segments": "bigint",
        "zero_osrm_segments": "bigint",
        "gap_min": "double",
        "gap_ratio": "double",
        "log_gap_ratio": "double",
        "is_delayed": "boolean",
        "dwell_min": "double",
        "route_type": "string",
    },
)

# ── hubs_v1 — Stage 3 output ─────────────────────────────────────────────────
HUBS_V1 = Contract(
    name="hubs_v1",
    version=1,
    path=config.HUBS_V1,
    produced_by="src.pipeline.hubs",
    partition_by=(),
    key=("centre_code",),
    rows=1_657,
    notes=(
        "Facility grain — one row per centre code. `*_out` statistics cover legs "
        "departing the hub, `*_in` legs arriving; a leg's idle minutes cannot be split "
        "between its two ends, so both are credited and reported separately (D-015). "
        "`friction_rank` is dense 1..N over supported hubs only and is null elsewhere."
    ),
    columns={
        "centre_code": "string",
        "centre_name": "string",
        "city": "string",
        "state": "string",
        "n_legs_out": "bigint",
        "n_corridors_out": "bigint",
        "median_dwell_min_out": "double",
        "mean_dwell_min_out": "double",
        "p90_dwell_min_out": "double",
        "median_dwell_share_out": "double",
        "mean_dwell_share_out": "double",
        "median_gap_ratio_out": "double",
        "n_legs_in": "bigint",
        "n_corridors_in": "bigint",
        "median_dwell_min_in": "double",
        "mean_dwell_min_in": "double",
        "p90_dwell_min_in": "double",
        "median_dwell_share_in": "double",
        "mean_dwell_share_in": "double",
        "median_gap_ratio_in": "double",
        "n_handoffs": "bigint",
        "n_chain_breaks": "bigint",
        "median_unobserved_gap_min": "double",
        "mean_unobserved_gap_min": "double",
        "n_legs_total": "bigint",
        "chain_break_rate": "double",
        "has_support": "boolean",
        "friction_rank": "int",
    },
)

# ── features_v1 — Stage 4 output ─────────────────────────────────────────────
FEATURES_V1 = Contract(
    name="features_v1",
    version=1,
    path=config.FEATURES_V1,
    produced_by="src.pipeline.features",
    partition_by=("route_type",),
    key=("leg_id",),
    rows=26_369,
    notes=(
        "OD-leg grain, same 26,369 legs as trips_v1 — no rows dropped. Every column "
        "is knowable at `trip_creation_time` (D-005): the `corr_*`/`src_*`/`dst_*` "
        "history columns are running as-of aggregates computed from prior legs' "
        "`od_end_time`, never their `od_start_time`, and `gap_min`/`log_gap_ratio`/"
        "`is_delayed` are carried only as prediction targets. `leg_id` replaces "
        "trips_v1's three-column key because a trip can repeat a corridor on a "
        "different day. `--validate` refuses to write if any outcome column "
        "(BANNED_FEATURES) survived, so a leakage bug fails the build rather than "
        "landing in the cache."
    ),
    columns={
        "leg_id": "string",
        "trip_uuid": "string",
        "corridor_id": "string",
        "source_center": "string",
        "destination_center": "string",
        "trip_creation_time": "timestamp",
        "planned_min": "double",
        "planned_km": "double",
        "created_hour": "int",
        "created_dayofweek": "int",
        "created_is_weekend": "boolean",
        "gap_min": "double",
        "log_gap_ratio": "double",
        "is_delayed": "boolean",
        "corr_n_prior": "int",
        "corr_mean_log_ratio": "double",
        "corr_std_log_ratio": "double",
        "corr_mean_gap_min": "double",
        "corr_last_log_ratio": "double",
        "corr_hours_since_last": "double",
        "src_n_prior": "int",
        "src_mean_log_ratio": "double",
        "src_std_log_ratio": "double",
        "src_mean_gap_min": "double",
        "src_last_log_ratio": "double",
        "src_hours_since_last": "double",
        "dst_n_prior": "int",
        "dst_mean_log_ratio": "double",
        "dst_std_log_ratio": "double",
        "dst_mean_gap_min": "double",
        "dst_last_log_ratio": "double",
        "dst_hours_since_last": "double",
        "route_type": "string",
    },
)

#: Every frozen dataset, newest stage last. Add here when a stage starts caching.
CONTRACTS: dict[str, Contract] = {c.name: c for c in (CLEAN_V1, TRIPS_V1, HUBS_V1, FEATURES_V1)}


def stamp(name: str) -> dict:
    """The contract identity a stage writes into its own report.

    Lets anyone reading a `_quality_report.json` or `_reconstruction_report.json` see
    which contract the file on disk was produced against, without loading Spark.
    """
    c = CONTRACTS[name]
    return {"dataset": c.name, "version": c.version, "columns": len(c.columns)}


@dataclass
class Result:
    """The outcome of checking one dataset."""

    contract: Contract
    breaches: list[str] = field(default_factory=list)
    skipped: str | None = None

    @property
    def ok(self) -> bool:
        return not self.breaches


def verify(spark: SparkSession, contract: Contract, check_keys: bool = False) -> Result:
    """Compare the dataset on disk against its frozen contract.

    A missing path is *skipped*, not failed — a teammate who has not built Stage 3 yet
    should not see a red check for it. Everything else that differs is a breach.
    """
    result = Result(contract=contract)
    if not contract.path.exists():
        result.skipped = "not built"
        return result

    df = spark.read.parquet(str(contract.path))
    actual = {f.name: f.dataType.simpleString() for f in df.schema.fields}
    expected = contract.columns

    for col in sorted(set(expected) - set(actual)):
        result.breaches.append(f"missing column `{col}` (expected {expected[col]})")
    for col in sorted(set(actual) - set(expected)):
        result.breaches.append(
            f"unexpected column `{col}` ({actual[col]}) — bump the contract version"
        )
    for col in sorted(set(expected) & set(actual)):
        if expected[col] != actual[col]:
            result.breaches.append(
                f"type drift on `{col}`: contract {expected[col]}, on disk {actual[col]}"
            )

    for col in contract.partition_by:
        if col not in actual:
            result.breaches.append(f"partition column `{col}` is absent from the read")

    if contract.rows is not None:
        n = df.count()
        if n != contract.rows:
            result.breaches.append(
                f"row count {n:,} != frozen {contract.rows:,} — the pipeline's output "
                "changed even though the raw input is pinned by SHA-256"
            )

    if check_keys and contract.key:
        # Two counts rather than a groupBy: cheaper, and the number it reports (how
        # many duplicate keys) is what you need to start debugging.
        total = df.count()
        distinct = df.select(*contract.key).distinct().count()
        if total != distinct:
            result.breaches.append(
                f"key {tuple(contract.key)} is not unique: {total - distinct:,} duplicate rows"
            )

    return result


def emit(spark: SparkSession, path: Path) -> str:
    """Print a dataset's current schema as a contract literal, ready to paste.

    Used when bumping a version: build the new output, run `--emit`, paste the block
    as a *new* Contract. It deliberately does not rewrite this file — freezing a schema
    is a decision, and a script that edits its own contract is not a freeze.
    """
    df = spark.read.parquet(str(path))
    lines = [f'    rows={df.count()},', "    columns={"]
    lines += [f'        "{f.name}": "{f.dataType.simpleString()}",' for f in df.schema.fields]
    lines.append("    },")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify cached Parquet against the frozen contracts")
    parser.add_argument("--dataset", choices=sorted(CONTRACTS), help="check one dataset")
    parser.add_argument("--keys", action="store_true", help="also check key uniqueness (slower)")
    parser.add_argument("--emit", choices=sorted(CONTRACTS), help="print the on-disk schema as a contract")
    args = parser.parse_args()

    from src.common.spark import get_spark, stop_spark

    spark = get_spark("contracts")
    try:
        if args.emit:
            print(emit(spark, CONTRACTS[args.emit].path))
            return 0

        targets = [CONTRACTS[args.dataset]] if args.dataset else list(CONTRACTS.values())
        results = [verify(spark, c, check_keys=args.keys) for c in targets]
    finally:
        stop_spark(spark)

    failed = 0
    for r in results:
        if r.skipped:
            log.warning("%-10s SKIP  %s (%s)", r.contract.name, r.skipped, r.contract.produced_by)
        elif r.ok:
            log.info(
                "%-10s OK    v%d, %d columns%s",
                r.contract.name,
                r.contract.version,
                len(r.contract.columns),
                f", {r.contract.rows:,} rows" if r.contract.rows else "",
            )
        else:
            failed += 1
            log.error("%-10s BREACH  %d problem(s)", r.contract.name, len(r.breaches))
            for b in r.breaches:
                log.error("             %s", b)

    if failed:
        log.error(
            "%d dataset(s) no longer match their frozen contract. Either the change was "
            "unintended, or the contract needs a new version — see the module docstring.",
            failed,
        )
        return 2
    log.info("All contracts satisfied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
