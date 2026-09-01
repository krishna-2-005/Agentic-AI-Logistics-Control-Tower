"""Leakage checks for the Stage 4 feature table.

    pytest tests/test_features.py -q

Two kinds of test, deliberately:

**Invariant tests over the built artifact** read `features_v1` with pandas and assert
the properties the table claims about itself. They need no JVM and take under a
second, so they can run on every commit. They skip cleanly if the cache has not been
built on this machine.

**One adversarial test with Spark** constructs the exact case the design exists to
survive — a prior leg that *departed* before our shipment was created but was still on
the road at that moment — and asserts it is excluded. That case is rare enough in real
data (8.4% of legs) that an invariant test over the cache could pass while the window
was subtly wrong, so it is built by hand rather than hoped for.

Why these are worth having at all: a leakage bug does not raise, does not look wrong,
and makes the Week 4 headline *better*. Nothing about the output would tell us.
"""

from __future__ import annotations

import json

import pytest

from src.common import config
from src.pipeline.features import BANNED_FEATURES, TARGETS

pd = pytest.importorskip("pandas")

FEATURE_COLS_REQUIRED = (
    "leg_id",
    "trip_creation_time",
    "planned_min",
    "corr_n_prior",
    "corr_mean_log_ratio",
)


@pytest.fixture(scope="module")
def features():
    """The built feature table, or skip if this machine has not built it."""
    if not (config.FEATURES_V1 / "_SUCCESS").exists():
        pytest.skip("features_v1 not built — run `python -m src.pipeline.features`")
    return pd.read_parquet(config.FEATURES_V1)


@pytest.fixture(scope="module")
def legs():
    if not (config.TRIPS_V1 / "_SUCCESS").exists():
        pytest.skip("trips_v1 not built — run `python -m src.pipeline.reconstruct`")
    return pd.read_parquet(
        config.TRIPS_V1,
        columns=["corridor_id", "trip_creation_time", "od_start_time", "od_end_time"],
    )


# ── the table is shaped as promised ──────────────────────────────────────────
def test_no_outcome_column_survived(features):
    """The single rule the whole stage exists to enforce."""
    leaked = [c for c in BANNED_FEATURES if c in features.columns]
    assert leaked == [], f"outcome columns present in the feature table: {leaked}"


def test_targets_are_carried(features):
    for t in TARGETS:
        assert t in features.columns, f"missing target {t}"


def test_required_features_present(features):
    missing = [c for c in FEATURE_COLS_REQUIRED if c not in features.columns]
    assert missing == [], f"missing feature columns: {missing}"


def test_leg_id_is_unique(features):
    """A trip can run the same corridor twice, so the key carries the departure time."""
    assert features["leg_id"].is_unique


# ── the history is genuinely past-only ───────────────────────────────────────
def test_cold_start_legs_have_no_history(features):
    """A corridor's first leg must know nothing — not a default, nothing."""
    cold = features[features["corr_n_prior"] == 0]
    assert len(cold) > 0, "no cold-start legs at all is itself suspicious"
    assert cold["corr_mean_log_ratio"].isna().all()
    assert cold["corr_last_log_ratio"].isna().all()
    assert cold["corr_hours_since_last"].isna().all()


def test_history_counts_only_finished_legs(features, legs):
    """Recompute the as-of count independently and demand exact agreement.

    Written with the predicate spelled out — `od_end_time <= trip_creation_time` —
    rather than reusing the window, so the two implementations can disagree.
    """
    sample = features.sample(min(250, len(features)), random_state=11)
    by_corridor = dict(list(legs.groupby("corridor_id")))
    mismatches = []
    for _, row in sample.iterrows():
        prior = by_corridor[row["corridor_id"]]
        expected = int((prior["od_end_time"] <= row["trip_creation_time"]).sum())
        if expected != row["corr_n_prior"]:
            mismatches.append((row["leg_id"], expected, int(row["corr_n_prior"])))
    assert mismatches == [], f"as-of count disagrees on {len(mismatches)} legs: {mismatches[:3]}"


def test_a_leg_never_counts_itself(features, legs):
    """Its own outcome lands at `od_end_time`, strictly after it was created."""
    merged = features[["leg_id", "corridor_id", "trip_creation_time", "corr_n_prior"]]
    per_corridor = legs.groupby("corridor_id").size().rename("total")
    merged = merged.join(per_corridor, on="corridor_id")
    assert (merged["corr_n_prior"] < merged["total"]).all()


def test_prior_counts_are_never_negative(features):
    for col in ("corr_n_prior", "src_n_prior", "dst_n_prior"):
        assert (features[col] >= 0).all()


def test_std_needs_two_observations(features):
    """One prior leg cannot have a spread; the column must be null, not zero."""
    one = features[features["corr_n_prior"] == 1]
    if len(one):
        assert one["corr_std_log_ratio"].isna().all()


# ── the report says what the table did ───────────────────────────────────────
def test_report_records_the_naive_leak(features):
    """The report must carry the measured cost of the obvious wrong implementation."""
    path = config.FEATURES_V1 / "_feature_report.json"
    if not path.exists():
        pytest.skip("no feature report — run with --validate")
    report = json.loads(path.read_text(encoding="utf-8"))
    if "naive_start_time_leak" not in report:
        pytest.skip("report predates the naive-leak measurement")
    leak = report["naive_start_time_leak"]
    assert leak["legs_reading_their_own_record"] > 0
    assert leak["legs_given_other_unfinished_journeys"] > 0


# ── the adversarial case, built by hand ──────────────────────────────────────
# Boots a SparkSession, so it runs in ~30s where the rest are instant. Kept
# unmarked and always-on: it is the only test that exercises the window itself.
def test_in_flight_leg_is_excluded():
    """A leg that departed early but landed late must not count as known history.

    This is the case the whole design turns on and it cannot be trusted to appear in a
    random sample of the cache. Three legs on one corridor:

      A  created 08:00, departs 09:00, arrives 10:00
      B  created 09:00, departs 09:30, arrives 14:00  — still moving at 11:00
      C  created 11:00                                — the leg under test

    C must see exactly **one** prior leg: A finished at 10:00, but B was still on the
    road, so its duration was not knowable. An implementation ordering by departure
    time sees two.

    B is asserted too, and its answer is **zero** — at 09:00 even A had not landed yet.
    That is the same rule applied one step earlier, and it is worth pinning because it
    is the case a reader's intuition gets wrong first.
    """
    pyspark = pytest.importorskip("pyspark")
    assert pyspark
    from pyspark.sql import functions as F

    from src.common.spark import get_spark, stop_spark
    from src.pipeline.features import as_of_history

    spark = get_spark("test-features")
    try:
        # Timestamps are handed over as strings and parsed by Spark. The dataset's
        # timestamps are naive (D-013) and attaching a timezone here to satisfy a
        # linter would misrepresent the data the pipeline actually reads.
        rows = [
            # leg, corridor, created,            departed,           arrived
            ("A", "C1", "2018-09-01 08:00:00", "2018-09-01 09:00:00",
             "2018-09-01 10:00:00", 0.5, 30.0),
            ("B", "C1", "2018-09-01 09:00:00", "2018-09-01 09:30:00",
             "2018-09-01 14:00:00", 1.5, 90.0),
            ("C", "C1", "2018-09-01 11:00:00", "2018-09-01 11:30:00",
             "2018-09-01 12:00:00", 0.9, 45.0),
        ]
        df = spark.createDataFrame(
            rows,
            "leg_id string, corridor_id string, trip_creation_time string, "
            "od_start_time string, od_end_time string, log_gap_ratio double, "
            "gap_min double",
        )
        for col in ("trip_creation_time", "od_start_time", "od_end_time"):
            df = df.withColumn(col, F.to_timestamp(col))

        correct = {
            r["leg_id"]: r["corr_n_prior"]
            for r in as_of_history(df, "corridor_id", "corr").collect()
        }
        assert correct["A"] == 0, "the first leg on a corridor knows nothing"
        assert correct["B"] == 0, (
            "B is created at 09:00 and A does not land until 10:00, so at B's "
            "prediction time nothing on this corridor has finished yet"
        )
        assert correct["C"] == 1, (
            "C must see only A. B departed at 09:30 but was still on the road at "
            f"11:00, so its duration was not knowable — got {correct['C']}"
        )

        naive = {
            r["leg_id"]: r["naive_n_prior"]
            for r in as_of_history(
                df, "corridor_id", "naive", fact_time="od_start_time"
            ).collect()
        }
        assert naive["C"] == 2, (
            "the naive clock is supposed to over-count here; if it does not, this "
            "test is no longer proving anything"
        )
    finally:
        stop_spark(spark)
