"""Tests for the end-to-end boot script (execution plan W6 D1-D2).

    pytest tests/test_boot.py -q

Starts no services: what is pinned is the preflight report and the schema-drift check,
which is the part that had to exist because `create_all` never alters a table (P-47).
"""

from __future__ import annotations

import sqlite3

from sqlmodel import SQLModel

import src.tms.models  # noqa: F401 -- registers the tables on the metadata
from src.common import boot


def _db_with_shrunken_shipment(path) -> None:
    """A database whose `shipment` table is missing every column but `id` -- the same
    shape of drift as a model that gained a field after the file was created."""
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE "shipment" (id INTEGER PRIMARY KEY)')
        con.execute('CREATE TABLE "facility" (centre_code VARCHAR PRIMARY KEY)')
        con.commit()


# ── the preflight report ────────────────────────────────────────────────────
def test_a_passing_check_reads_ok():
    assert "[OK  ]" in boot.Check("thing", True, "present").line()


def test_a_failing_check_shows_the_fix():
    line = boot.Check("champion model", False, "missing", "python -m src.automation.retrain").line()
    assert "[MISS]" in line and "python -m src.automation.retrain" in line


def test_blocking_lists_only_the_failures():
    report = boot.Preflight([
        boot.Check("a", True, ""), boot.Check("b", False, ""), boot.Check("c", False, ""),
    ])
    assert [c.name for c in report.blocking] == ["b", "c"]


def test_preflight_reports_every_problem_not_just_the_first():
    # A run that dies at the first missing artefact makes you rediscover the second one
    # twenty minutes later.
    checks = boot.preflight()
    names = {c.name for c in checks.checks}
    assert {"cleaned parquet", "feature table", "champion model", "TMS schema"} <= names
    assert len(checks.report().splitlines()) == len(checks.checks)


# ── schema drift, which is why this module exists ───────────────────────────
def test_no_drift_when_the_file_does_not_exist(tmp_path):
    assert boot.check_schema_drift(tmp_path / "absent.sqlite") == {}


def test_missing_columns_are_found(tmp_path):
    path = tmp_path / "tms.sqlite"
    _db_with_shrunken_shipment(path)
    drift = boot.check_schema_drift(path)
    assert "shipment" in drift
    assert "notes" in drift["shipment"]  # the column that actually broke Week 6
    assert "id" not in drift["shipment"]


def test_a_table_that_does_not_exist_at_all_is_not_drift(tmp_path):
    # `create_all` makes missing tables on the next start; only a *present* table that
    # lacks a column needs repairing.
    path = tmp_path / "tms.sqlite"
    _db_with_shrunken_shipment(path)
    assert "invoice" not in boot.check_schema_drift(path)


def test_repair_adds_the_columns_and_is_idempotent(tmp_path):
    path = tmp_path / "tms.sqlite"
    _db_with_shrunken_shipment(path)
    applied = boot.repair_schema_drift(path)
    assert applied and all(ddl.startswith("ALTER TABLE") for ddl in applied)
    assert boot.check_schema_drift(path) == {}
    assert boot.repair_schema_drift(path) == []


def test_repair_preserves_existing_rows(tmp_path):
    # The whole point: P-40 predicted the obvious fix would be a re-seed, which would
    # have destroyed three real agent-filed orders.
    path = tmp_path / "tms.sqlite"
    _db_with_shrunken_shipment(path)
    with sqlite3.connect(path) as con:
        con.execute('INSERT INTO "shipment" (id) VALUES (7)')
        con.commit()
    boot.repair_schema_drift(path)
    with sqlite3.connect(path) as con:
        assert con.execute('SELECT id FROM "shipment"').fetchall() == [(7,)]


def test_repair_only_ever_adds(tmp_path):
    path = tmp_path / "tms.sqlite"
    _db_with_shrunken_shipment(path)
    for ddl in boot.repair_schema_drift(path):
        assert "ADD COLUMN" in ddl
        assert "DROP" not in ddl and "ALTER COLUMN" not in ddl


def test_every_model_table_is_known_to_the_check():
    # If a table is added to the models and this list is not regenerated, the check
    # silently stops covering it.
    assert {"order", "shipment", "facility", "invoice", "exceptionticket"} <= set(
        SQLModel.metadata.tables
    )
