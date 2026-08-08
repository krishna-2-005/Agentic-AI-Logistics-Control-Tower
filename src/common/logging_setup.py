"""Project logger. Console output is human-readable; every run also appends to
``logs/<name>.log`` so a failed overnight batch can be read the next morning.
"""

from __future__ import annotations

import logging
from pathlib import Path

from rich.logging import RichHandler

from src.common.config import REPO_ROOT

LOG_DIR = REPO_ROOT / "logs"


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Return a configured logger. Repeated calls with the same name are cheap."""
    logger = logging.getLogger(name)
    if logger.handlers:  # already configured
        return logger

    logger.setLevel(level)
    logger.propagate = False

    console = RichHandler(rich_tracebacks=True, show_path=False, markup=False)
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
