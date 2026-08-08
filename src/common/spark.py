"""Spark session factory.

One builder for the whole project so batch, streaming, and ML all get identical
settings. Import `get_spark()`; never call `SparkSession.builder` directly.
"""

from __future__ import annotations

import os
import sys

from pyspark.sql import SparkSession

from src.common import config


def get_spark(app_name: str = "control-tower", shuffle_partitions: int = 8) -> SparkSession:
    """Return the shared SparkSession, creating it on first call.

    Args:
        app_name: shows up in the Spark UI at http://localhost:4040 — use the
            stage name so a running job is identifiable.
        shuffle_partitions: 8 suits a laptop. The default of 200 produces hundreds
            of tiny tasks on a 145K-row dataset and makes every job slower. Raise
            this for the Week 7 scale appendix.
    """
    config.ensure_dirs()

    # PySpark launches the driver by shelling out to a Python interpreter. On
    # Windows, and inside any venv, that lookup is unreliable unless pinned.
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

    builder = (
        SparkSession.builder.appName(f"control-tower/{app_name}")
        .master("local[*]")
        .config("spark.driver.memory", config.SPARK_DRIVER_MEMORY)
        .config("spark.sql.shuffle.partitions", str(shuffle_partitions))
        .config("spark.local.dir", str(config.SPARK_LOCAL_DIR))
        .config("spark.sql.session.timeZone", "Asia/Kolkata")
        # Delhivery timestamps predate Spark 3's Proleptic Gregorian switch in a
        # few rows; CORRECTED makes the rebase explicit instead of throwing.
        .config("spark.sql.parquet.datetimeRebaseModeInWrite", "CORRECTED")
        .config("spark.sql.parquet.datetimeRebaseModeInRead", "CORRECTED")
        .config("spark.ui.showConsoleProgress", "true")
    )

    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark


def stop_spark(spark: SparkSession) -> None:
    """Stop a session. Worth calling in scripts so the JVM exits cleanly."""
    spark.stop()
