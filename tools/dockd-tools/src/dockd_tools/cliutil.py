"""Small helpers shared by the dockd CLIs."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .config import STATE_DIR


def emit(payload: dict[str, Any]) -> None:
    """Print a JSON object to stdout — the only thing CLIs write to stdout."""
    try:
        json.dump(payload, sys.stdout)
        sys.stdout.write("\n")
        sys.stdout.flush()
    except BrokenPipeError:
        # Downstream consumer (| head, closed pipe) went away — not an error.
        try:
            sys.stdout.close()
        except BrokenPipeError:
            pass


def fail(message: str, *, code: int = 1, **extra: Any) -> "SystemExit":
    """Emit a JSON error object and exit non-zero."""
    emit({"ok": False, "error": message, **extra})
    return SystemExit(code)


class Heartbeat:
    """Daemon liveness file: ``state/<name>.json`` with pid + timestamp.

    The menubar app treats a heartbeat older than ``2 * interval + 5`` seconds
    (or a dead pid) as unhealthy.
    """

    def __init__(self, name: str, interval: float):
        self.path = STATE_DIR / f"{name}.json"
        self.interval = interval
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def beat(self, **status: Any) -> None:
        payload = {
            "pid": os.getpid(),
            "ts": time.time(),
            "interval": self.interval,
            **status,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(self.path)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def read_heartbeat(name: str) -> dict[str, Any] | None:
    path = Path(STATE_DIR / f"{name}.json")
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data


def heartbeat_healthy(data: dict[str, Any] | None) -> bool:
    if not data:
        return False
    interval = float(data.get("interval", 5))
    if time.time() - float(data.get("ts", 0)) > interval * 2 + 5:
        return False
    pid = int(data.get("pid", 0))
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True
