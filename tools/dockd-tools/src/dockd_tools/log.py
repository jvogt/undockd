"""Logging for dockd tools.

Every tool logs human-readable lines to stderr and appends structured JSON
lines to ``~/Library/Logs/dockd/<tool>.jsonl``. When a tool runs as a child of
the Dockd menubar app, the app forwards stderr into the macOS unified log
(subsystem ``com.jvogt.dockd``), so everything is visible in Console.app.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import time

from .config import LOG_DIR

SUBSYSTEM = "com.jvogt.dockd"


class _JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(record.created)),
            "level": record.levelname.lower(),
            "tool": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "data", None)
        if extra:
            payload["data"] = extra
        return json.dumps(payload, default=str)


def get_logger(tool: str, *, verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger(tool)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    stderr = logging.StreamHandler(sys.stderr)
    stderr.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logger.addHandler(stderr)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_DIR / f"{tool}.jsonl", maxBytes=2_000_000, backupCount=3
        )
        file_handler.setFormatter(_JsonLineFormatter())
        logger.addHandler(file_handler)
    except OSError:
        logger.warning("could not open log file in %s; logging to stderr only", LOG_DIR)

    return logger
