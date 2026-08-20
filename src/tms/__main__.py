"""Run the mock TMS.

    python -m src.tms                    # http://localhost:8000
    python -m src.tms --reload           # auto-restart while editing
    python -m src.tms --port 8100

Seeding is a separate step (`python -m src.tms.seed`) so a restart never overwrites
the facility table.
"""

from __future__ import annotations

import argparse

import uvicorn

from src.common import config
from src.common.logging_setup import get_logger

log = get_logger("tms.serve")


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the mock TMS")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="restart on source changes")
    args = parser.parse_args()

    log.info(
        "Mock TMS on http://%s:%d  (docs at /docs, database %s, auth %s)",
        args.host,
        args.port,
        config.TMS_DB_PATH,
        "on" if config.TMS_API_KEY else "off",
    )
    uvicorn.run("src.tms.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
