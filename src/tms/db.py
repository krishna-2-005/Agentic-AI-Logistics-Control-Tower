"""SQLite engine and session handling for the mock TMS.

SQLite rather than Postgres on purpose: the whole system has to boot on three
student laptops with one command in Week 6, and a database that is a file is one
fewer service to install. The access patterns here are trivial — the agents file
tens of orders, not thousands per second.

Two SQLite settings matter and are set explicitly:

* ``check_same_thread=False`` — FastAPI serves requests on a thread pool, and the
  default forbids using a connection from any thread but the one that opened it.
* **WAL journal mode** — the Week 5 streaming job and the dashboard read the TMS
  while agents write to it. Under the default rollback journal a writer blocks every
  reader, which during the live demo looks exactly like a hung dashboard.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("tms.db")

_engine: Engine | None = None


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    """WAL plus foreign-key enforcement, on every connection.

    SQLite has foreign keys *off* by default — the `origin_centre` FK would be
    decorative without this, and an order naming a nonexistent facility would insert
    happily. The API validates centre codes itself and returns a useful 422; this is
    the backstop for anything that writes around the API.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def get_engine(db_path: Path | None = None) -> Engine:
    """Return the process-wide engine, creating it on first call."""
    global _engine
    if _engine is None:
        path = db_path or config.TMS_DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        log.info("TMS database at %s", path)
    return _engine


def set_engine(engine: Engine) -> None:
    """Point the module at a different engine — used by the tests to run against an
    in-memory database instead of the developer's real `data/tms.sqlite`."""
    global _engine
    _engine = engine


def init_db(engine: Engine | None = None) -> None:
    """Create any missing tables. Safe to call on every boot; never drops."""
    SQLModel.metadata.create_all(engine or get_engine())


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding one session per request."""
    with Session(get_engine()) as session:
        yield session
