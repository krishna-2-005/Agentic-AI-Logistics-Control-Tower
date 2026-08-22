"""Project logger. Console output is human-readable; every run also appends to
``logs/<name>.log`` so a failed overnight batch can be read the next morning.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from src.common.config import REPO_ROOT

LOG_DIR = REPO_ROOT / "logs"


def _console() -> Console:
    """A rich console that survives a terminal which is not UTF-8.

    A Windows console defaults to cp1252, and a single non-Latin-1 character in a log
    message — the `→` this codebase uses in half its "wrote file" lines — raises
    UnicodeEncodeError *inside the handler*. The run carries on, but the message is
    replaced by a traceback, so the one line that says where the output went is the
    one line that gets lost. Asking the stream to substitute what it cannot encode
    keeps the message and costs a `?`.
    """
    stream = sys.stdout
    try:
        stream.reconfigure(errors="replace")
    except (AttributeError, ValueError, OSError):
        pass  # not a reconfigurable text stream (pytest capture, a pipe)
    return Console(file=stream)


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Return a configured logger. Repeated calls with the same name are cheap."""
    logger = logging.getLogger(name)
    if logger.handlers:  # already configured
        return logger

    logger.setLevel(level)
    logger.propagate = False

    console = RichHandler(
        console=_console(), rich_tracebacks=True, show_path=False, markup=False
    )
    console.setFormatter(logging.Formatter("%(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(console)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(
        LOG_DIR / f"{name.replace('.', '_')}.log", encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s")
    )
    logger.addHandler(file_handler)

    return logger


def log_path(name: str) -> Path:
    return LOG_DIR / f"{name.replace('.', '_')}.log"
