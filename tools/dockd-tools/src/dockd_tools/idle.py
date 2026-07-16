"""System idle time and screensaver timeout."""

from __future__ import annotations

import re
import subprocess


def idle_seconds() -> float:
    """Seconds since last keyboard/mouse input, from IOKit's HIDIdleTime."""
    proc = subprocess.run(
        ["ioreg", "-c", "IOHIDSystem", "-d", "4"],
        capture_output=True,
        text=True,
        check=True,
    )
    match = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', proc.stdout)
    if not match:
        raise RuntimeError("HIDIdleTime not found in ioreg output")
    return int(match.group(1)) / 1_000_000_000


def screensaver_timeout() -> int | None:
    """The user's screensaver idle timeout in seconds; None if unset/never."""
    proc = subprocess.run(
        ["defaults", "-currentHost", "read", "com.apple.screensaver", "idleTime"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    try:
        value = int(proc.stdout.strip())
    except ValueError:
        return None
    return value or None  # 0 means "never"
