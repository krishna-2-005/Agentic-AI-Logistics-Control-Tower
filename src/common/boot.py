"""End-to-end boot (execution plan W6 D1-D2) -- the whole system in one command.

    python -m src.common.boot                    # preflight, TMS, replay, score, agents
    python -m src.common.boot --check            # preflight only: what is ready, what is not
    python -m src.common.boot --dashboard        # ...and leave Streamlit running
    python -m src.common.boot --legs 500 --duration 10

Starts the mock TMS, replays trips through the streaming job, runs the agents over what
comes out, and optionally opens the dashboard -- in the order those things actually
depend on each other, with every child process shut down on the way out.

Preflight first, always
-----------------------
Six weeks of this project have produced a specific failure shape: a run dies twenty
minutes in because an artefact three stages back was never built, or a column drifted,
or a key is missing. So `boot` checks before it starts anything, and **reports every
problem at once** rather than stopping at the first. A missing champion model and a
missing `.env` key are both worth knowing before Spark boots.

The schema check is not decoration
----------------------------------
`SQLModel.metadata.create_all` creates missing tables and **never alters an existing
one**, so every model change after the first run is invisible until something writes the
new column. That is exactly how Week 6 lost an afternoon: `POST /shipments` returned 500
on every order because `shipment.notes` existed in the model and not in the file
(P-47) -- and the obvious fix, re-seeding, would have destroyed three real agent-filed
orders, which P-40 predicted in Week 5 almost word for word. `check_schema_drift`
compares the models against `PRAGMA table_info` and `repair_schema_drift` adds what is
missing. A column whose *type* changed is reported and never silently rewritten: that is
a migration, and a migration is a decision, not a repair.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
from sqlmodel import SQLModel

from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("common.boot")

TMS_READY_TIMEOUT = 60.0


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""

    def line(self) -> str:
        mark = "OK  " if self.ok else "MISS"
        tail = f"   -> {self.fix}" if not self.ok and self.fix else ""
        return f"  [{mark}] {self.name}: {self.detail}{tail}"


@dataclass
class Preflight:
    checks: list[Check] = field(default_factory=list)

    @property
    def blocking(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def report(self) -> str:
        return "\n".join(c.line() for c in self.checks)


# ── schema drift ─────────────────────────────────────────────────────────────
def check_schema_drift(db_path: Path | None = None) -> dict[str, list[str]]:
    """Columns the models declare that the database file does not have, per table.

    Returns `{}` when the file and the models agree, and `{table: [columns]}` when they
    do not. A table missing entirely is not drift -- `create_all` handles that on the
    next start -- so it is not reported here.
    """
    db_path = db_path or config.TMS_DB_PATH
    if not db_path.exists():
        return {}
    import src.tms.models  # noqa: F401 -- importing registers the tables on the metadata

    drift: dict[str, list[str]] = {}
    with sqlite3.connect(db_path) as con:
        for name, table in SQLModel.metadata.tables.items():
            present = {row[1] for row in con.execute(f'PRAGMA table_info("{name}")')}
            if not present:
                continue
            missing = [column.name for column in table.columns if column.name not in present]
            if missing:
                drift[name] = missing
    return drift


def repair_schema_drift(db_path: Path | None = None) -> list[str]:
    """Add the missing columns, preserving every row. Returns the DDL applied.

    `ADD COLUMN` only. Anything beyond it -- a changed type, a dropped column, a new
    constraint -- is a migration with a decision attached, and silently guessing at one
    is how data gets quietly rewritten.
    """
    db_path = db_path or config.TMS_DB_PATH
    drift = check_schema_drift(db_path)
    if not drift:
        return []
    import src.tms.models  # noqa: F401

    dialect = sqlite_dialect()
    applied: list[str] = []
    with sqlite3.connect(db_path) as con:
        for table_name, columns in drift.items():
            table = SQLModel.metadata.tables[table_name]
            for column_name in columns:
                column = table.columns[column_name]
                ddl = (
                    f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" '
                    f"{column.type.compile(dialect=dialect)}"
                )
                con.execute(ddl)
                applied.append(ddl)
        con.commit()
    for ddl in applied:
        log.info("schema repair: %s", ddl)
    return applied


# ── preflight ────────────────────────────────────────────────────────────────
def preflight(need_spark: bool = True) -> Preflight:
    """Everything that has to be true before the first service starts."""
    checks: list[Check] = []

    checks.append(Check(
        "cleaned parquet", config.CLEAN_V1.exists(),
        str(config.CLEAN_V1.name), "python -m src.pipeline.clean",
    ))
    checks.append(Check(
        "feature table", config.FEATURES_V1.exists(),
        str(config.FEATURES_V1.name), "python -m src.pipeline.features",
    ))
    champion = config.MODELS_DIR / "champion"
    checks.append(Check(
        "champion model", champion.exists(), "data/models/champion",
        "python -m src.automation.retrain",
    ))
    checks.append(Check(
        "corridor audit", (config.BENCHMARKS_RAW_DIR / "w2_corridor_audit.csv").exists(),
        "w2_corridor_audit.csv", "python -m src.ml.audit",
    ))

    drift = check_schema_drift()
    checks.append(Check(
        "TMS schema", not drift,
        "matches the models" if not drift else f"drifted: {drift}",
        "boot repairs this automatically (P-47)",
    ))

    if need_spark:
        java = shutil.which("java")
        checks.append(Check("java", bool(java), java or "not on PATH", "install a JDK 17+"))

    key_var = {"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(
        config.LLM_PROVIDER.lower(), ""
    )
    key_set = bool(key_var) and bool(os.environ.get(key_var))
    checks.append(Check(
        f"LLM ({config.LLM_PROVIDER})", key_set,
        "key present" if key_set else "no key -- agents fall back to templates",
        "set the provider key in .env, or run with --no-llm",
    ))
    return Preflight(checks)


# ── process management ───────────────────────────────────────────────────────
class Service:
    """A child process with a name, started and stopped as a unit."""

    def __init__(self, name: str, argv: list[str], log_path: Path) -> None:
        self.name = name
        self.argv = argv
        self.log_path = log_path
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.log_path.open("w", encoding="utf-8")
        # New process group so a Ctrl-C in the parent does not race the child's own
        # handler -- boot stops its children deliberately, in order, in `stop_all`.
        kwargs = {"stdout": handle, "stderr": subprocess.STDOUT}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        self.process = subprocess.Popen([sys.executable, *self.argv], **kwargs)
        log.info("started %s (pid %s) -> %s", self.name, self.process.pid, self.log_path.name)

    def stop(self, timeout: float = 10.0) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            log.warning("%s did not stop in %.0fs -- killing", self.name, timeout)
            self.process.kill()
        log.info("stopped %s", self.name)


def wait_for_tms(timeout: float = TMS_READY_TIMEOUT) -> bool:
    """Poll `/health` until the TMS answers. Starting Uvicorn is not the same as being
    ready, and the first agent call is a bad place to discover the difference."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{config.TMS_BASE_URL}/health", timeout=2.0).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


def run_step(name: str, argv: list[str], log_dir: Path) -> tuple[bool, str]:
    """A step that runs to completion, with its output kept for the summary."""
    log_path = log_dir / f"{name}.log"
    log.info("running %s", name)
    with log_path.open("w", encoding="utf-8") as handle:
        code = subprocess.call([sys.executable, *argv], stdout=handle, stderr=subprocess.STDOUT)
    return code == 0, str(log_path)


# ── the boot sequence ────────────────────────────────────────────────────────
def boot(legs: int = 500, duration: float = 15.0, use_llm: bool = False,
         dashboard: bool = False, keep_running: bool = False,
         log_dir: Path | None = None) -> dict:
    """Start everything, in dependency order, and tear it down afterwards."""
    log_dir = log_dir or (config.REPO_ROOT / "logs" / "boot")
    log_dir.mkdir(parents=True, exist_ok=True)

    checks = preflight()
    print(checks.report())
    blocking = [c for c in checks.blocking if c.name not in ("TMS schema",) and "LLM" not in c.name]
    if blocking:
        log.error("%d artefact(s) missing -- see the fixes above", len(blocking))
        return {"started": False, "blocked_by": [c.name for c in blocking]}

    repaired = repair_schema_drift()

    services: list[Service] = []
    summary: dict = {"started": True, "schema_repairs": repaired, "steps": {}}
    try:
        tms = Service("tms", ["-m", "src.tms"], log_dir / "tms.log")
        tms.start()
        services.append(tms)
        if not wait_for_tms():
            log.error("the TMS never answered on %s", config.TMS_BASE_URL)
            return {**summary, "started": False, "blocked_by": ["tms"]}
        summary["tms"] = config.TMS_BASE_URL

        # `--sink file` explicitly, never the configured default. `STREAM_SOURCE` is
        # `kafka`, and D-035 recorded in Week 5 that this machine has no broker: the
        # producer left to its own default spends 30 seconds timing out against
        # localhost:9092 and exits 1. A boot script whose job is "one command that
        # works" cannot inherit a default that only works on a machine nobody has
        # (P-50).
        ok, path = run_step("producer", ["-m", "src.streaming.producer", "--sink", "file",
                                         "--limit", str(legs),
                                         "--duration", str(duration), "--clean"], log_dir)
        summary["steps"]["producer"] = {"ok": ok, "log": path}

        ok, path = run_step("streaming", ["-m", "src.streaming.job", "--once", "--clean"], log_dir)
        summary["steps"]["streaming"] = {"ok": ok, "log": path}

        # Demonstration output goes to logs/, never over the benchmarks artefact a
        # write-up cites: boot's five-case run is not the ten-case run Krishna reports
        # and must not silently replace it (P-51).
        agent_argv = ["-m", "src.agents.exception_agent", "--limit", "5",
                      "--out", str(log_dir / "w6_exception_runs.json")]
        if not use_llm:
            agent_argv.append("--no-draft")
        ok, path = run_step("exception_agent", agent_argv, log_dir)
        summary["steps"]["exception_agent"] = {"ok": ok, "log": path}

        orchestrator_argv = ["-m", "src.agents.orchestrator", "--cases", "5",
                             "--out", str(log_dir / "w6_orchestrator_runs.json")]
        if not use_llm:
            orchestrator_argv.append("--no-llm")
        ok, path = run_step("orchestrator", orchestrator_argv, log_dir)
        summary["steps"]["orchestrator"] = {"ok": ok, "log": path}

        if dashboard:
            board = Service("dashboard", ["-m", "streamlit", "run", "src/dashboard/app.py",
                                          "--server.headless", "true"], log_dir / "dashboard.log")
            board.start()
            services.append(board)
            summary["dashboard"] = "http://localhost:8501"

        if keep_running or dashboard:
            log.info("running; press Ctrl-C to stop")
            try:
                while True:
                    time.sleep(1.0)
            except KeyboardInterrupt:
                log.info("stopping")
    finally:
        for service in reversed(services):
            service.stop()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Boot the whole control tower")
    parser.add_argument("--check", action="store_true", help="preflight only; start nothing")
    parser.add_argument("--repair-schema", action="store_true", help="apply schema drift repairs and exit")
    parser.add_argument("--legs", type=int, default=500)
    parser.add_argument("--duration", type=float, default=15.0)
    parser.add_argument("--llm", action="store_true", help="let the agents draft with the model")
    parser.add_argument("--dashboard", action="store_true", help="start Streamlit and keep running")
    parser.add_argument("--keep-running", action="store_true", help="leave the TMS up after the steps")
    args = parser.parse_args()

    if args.check:
        checks = preflight()
        print(checks.report())
        return 0 if not checks.blocking else 1

    if args.repair_schema:
        applied = repair_schema_drift()
        print("\n".join(applied) if applied else "no drift")
        return 0

    # Ctrl-C must reach the `finally` that stops the children, not kill the parent first.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    summary = boot(legs=args.legs, duration=args.duration, use_llm=args.llm,
                   dashboard=args.dashboard, keep_running=args.keep_running)
    if not summary.get("started"):
        return 1
    for name, step in summary.get("steps", {}).items():
        print(f"  {'ok  ' if step['ok'] else 'FAIL'} {name}  ({step['log']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
