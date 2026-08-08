"""Gate 1 environment check — run this on every machine before Week 1 work starts.

    python -m src.common.check_env            # full check
    python -m src.common.check_env --quick    # skip the file hash and the Spark boot

Prints a pass/fail table. Gate 1 is not passed until the REQUIRED rows are green on
all three members' machines. OPTIONAL rows are for later weeks and may be red now.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from src.common import config

console = Console()

PASS, FAIL, WARN, SKIP = "[green]PASS[/]", "[red]FAIL[/]", "[yellow]WARN[/]", "[dim]SKIP[/]"


class Results:
    """Collects check outcomes; tracks whether any required check failed."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []
        self.required_failed = False

    def add(self, group: str, check: str, status: str, detail: str, required: bool = True) -> None:
        self.rows.append((group, check, status, detail))
        if required and status == FAIL:
            self.required_failed = True


def _run(cmd: list[str]) -> tuple[bool, str]:
    """Run a command, return (ok, first line of output). Never raises."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, type(exc).__name__
    out = (proc.stdout or "") + (proc.stderr or "")
    first = next((ln.strip() for ln in out.splitlines() if ln.strip()), "")
    return proc.returncode == 0, first


def check_python(r: Results) -> None:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 11)
    r.add(
        "Core",
        "Python >= 3.11",
        PASS if ok else FAIL,
        f"{v.major}.{v.minor}.{v.micro} at {sys.executable}",
    )

    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    r.add(
        "Core",
        "virtualenv active",
        PASS if in_venv else WARN,
        sys.prefix if in_venv else "not in a venv — installs land in the global interpreter",
        required=False,
    )


def check_java(r: Results) -> None:
    java_home = os.environ.get("JAVA_HOME", "")
    exe_name = "java.exe" if os.name == "nt" else "java"
    home_ok = bool(java_home) and (Path(java_home) / "bin" / exe_name).exists()

    if java_home and not home_ok:
        detail = f"JAVA_HOME points at a path with no bin/{exe_name}: {java_home}"
    elif not java_home:
        detail = "JAVA_HOME not set"
    else:
        detail = java_home
    r.add("Spark", "JAVA_HOME", PASS if home_ok else FAIL, detail)

    on_path = shutil.which("java")
    if on_path:
        _, line = _run(["java", "-version"])
        version_ok = any(f'"{v}' in line for v in ("17.", "11.")) or "17" in line
        r.add(
            "Spark",
            "java on PATH",
            PASS if version_ok else WARN,
            line or on_path,
            required=False,
        )
    else:
        r.add(
            "Spark",
            "java on PATH",
            FAIL,
            "install JDK 17 (Temurin/Adoptium) and set JAVA_HOME — PySpark cannot start without it",
        )


def check_pyspark(r: Results, quick: bool) -> None:
    try:
        import pyspark  # noqa: PLC0415
    except ImportError:
        r.add("Spark", "pyspark importable", FAIL, "pip install -r requirements.txt")
        return
    r.add("Spark", "pyspark importable", PASS, f"pyspark {pyspark.__version__}")

    if quick:
        r.add("Spark", "SparkSession starts", SKIP, "--quick", required=False)
        return

    try:
        from src.common.spark import get_spark, stop_spark  # noqa: PLC0415

        spark = get_spark("check-env")
        n = spark.range(1000).count()
        version = spark.version
        stop_spark(spark)
        ok = n == 1000
        r.add(
            "Spark",
            "SparkSession starts",
            PASS if ok else FAIL,
            f"Spark {version}, counted {n:,} rows on local[*]",
        )
    except Exception as exc:  # noqa: BLE001 — we want the message, whatever it is
        r.add("Spark", "SparkSession starts", FAIL, f"{type(exc).__name__}: {exc}"[:160])


def check_dataset(r: Results, quick: bool) -> None:
    path = config.RAW_CSV
    if not path.exists():
        r.add("Data", "raw CSV present", FAIL, f"missing {path} — see data/README.md")
        return

    size = path.stat().st_size
    size_ok = size == config.RAW_BYTES
    r.add(
        "Data",
        "raw CSV present",
        PASS if size_ok else WARN,
        f"{size:,} bytes" + ("" if size_ok else f" (expected {config.RAW_BYTES:,})"),
        required=False,
    )

    if quick:
        r.add("Data", "SHA-256 matches", SKIP, "--quick", required=False)
        return

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    ok = actual == config.RAW_SHA256
    r.add(
        "Data",
        "SHA-256 matches",
        PASS if ok else FAIL,
        actual[:16] + "…" if ok else f"got {actual[:16]}… expected {config.RAW_SHA256[:16]}…",
    )


def check_llm(r: Results) -> None:
    keys = {
        "gemini": "GEMINI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    provider = config.LLM_PROVIDER
    present = [name for name, var in keys.items() if os.environ.get(var)]

    if provider == "ollama":
        ok, line = _run(["ollama", "list"])
        r.add("Agents", "LLM provider", PASS if ok else FAIL, "ollama" if ok else "ollama not reachable")
    else:
        var = keys.get(provider, "GEMINI_API_KEY")
        has_key = bool(os.environ.get(var))
        r.add(
            "Agents",
            "LLM provider",
            PASS if has_key else FAIL,
            f"{provider}: {var} set" if has_key else f"{provider}: {var} missing from .env",
        )

    r.add(
        "Agents",
        "fallback provider",
        PASS if len(present) > 1 else WARN,
        ", ".join(present) if present else "no keys in .env",
        required=False,
    )

    try:
        import langgraph  # noqa: PLC0415, F401

        r.add("Agents", "langgraph importable", PASS, "ok")
    except ImportError:
        r.add("Agents", "langgraph importable", FAIL, "pip install -r requirements.txt")


def check_optional(r: Results) -> None:
    ok, line = _run(["tesseract", "--version"])
    r.add("Optional", "tesseract (W4 OCR)", PASS if ok else WARN, line or "not installed", required=False)

    ok, line = _run(["docker", "--version"])
    r.add(
        "Optional",
        "docker (W5 Kafka)",
        PASS if ok else WARN,
        line or "not installed — file-source streaming fallback available",
        required=False,
    )

    for mod, label in (("streamlit", "streamlit (W1 dashboard)"), ("fastapi", "fastapi (W2 TMS)"), ("chromadb", "chromadb (W6 RAG)")):
        try:
            __import__(mod)
            r.add("Optional", label, PASS, "ok", required=False)
        except ImportError:
            r.add("Optional", label, WARN, "not installed", required=False)


def check_git_identity(r: Results) -> None:
    ok_n, name = _run(["git", "config", "user.name"])
    ok_e, email = _run(["git", "config", "user.email"])
    configured = ok_n and ok_e and name and email
    r.add(
        "Git",
        "identity set (GIT_RULES §9)",
        PASS if configured else FAIL,
        f"{name} <{email}>" if configured else "run: git config user.name / user.email",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="skip the file hash and the Spark boot")
    args = parser.parse_args()

    console.rule("[bold]Agentic AI Logistics Control Tower — environment check")

    r = Results()
    check_python(r)
    check_java(r)
    check_pyspark(r, args.quick)
    check_dataset(r, args.quick)
    check_llm(r)
    check_git_identity(r)
    check_optional(r)

    table = Table(show_lines=False, header_style="bold")
    table.add_column("Group", style="cyan", no_wrap=True)
    table.add_column("Check", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail", overflow="fold")
    for row in r.rows:
        table.add_row(*row)
    console.print(table)

    if r.required_failed:
        console.print("\n[red bold]Gate 1 not passed[/] — fix the FAIL rows above, then re-run.")
        return 1
    console.print("\n[green bold]Gate 1 environment checks passed on this machine.[/]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
