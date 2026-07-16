"""Zoom / Google Meet meeting and mute-state detection.

osascript is used as minimally as possible: one short System Events query for
Zoom (only when the zoom.us process exists) and one Chrome query for Meet
(only when Chrome is running). Everything else is Python.

States: "muted", "unmuted", "unknown". ``app`` is "zoom", "meet", or None
when no meeting is detected.

Permissions needed by the *calling* app (granted once, on first prompt):
- Automation → System Events (Zoom detection)
- Automation → Google Chrome, plus Chrome's
  View → Developer → Allow JavaScript from Apple Events (Meet mute state;
  without it we still detect the meeting tab but report "unknown")
"""

from __future__ import annotations

import subprocess
from typing import Any

_ZOOM_SCRIPT = """
tell application "System Events"
    if not (exists application process "zoom.us") then return "none"
    try
        tell application process "zoom.us"
            if exists (menu item "Unmute audio" of menu 1 of menu bar item "Meeting" of menu bar 1) then return "muted"
            if exists (menu item "Mute audio" of menu 1 of menu bar item "Meeting" of menu bar 1) then return "unmuted"
        end tell
    end try
    return "none"
end tell
"""

_MEET_JS = """
(() => {
  for (const b of document.querySelectorAll('button,[role=button]')) {
    const label = b.getAttribute('aria-label') || b.getAttribute('data-tooltip') || '';
    if (label.includes('Turn on microphone')) return 'muted';
    if (label.includes('Turn off microphone')) return 'unmuted';
  }
  return 'unknown';
})();
"""

_MEET_SCRIPT = f"""
tell application "Google Chrome"
    repeat with w in windows
        repeat with t in tabs of w
            try
                if URL of t contains "meet.google.com/" and URL of t does not end with "meet.google.com/" and URL of t does not contain "/landing" then
                    try
                        return execute t javascript "{_MEET_JS.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34)).replace(chr(10), ' ')}"
                    on error
                        return "unknown"
                    end try
                end if
            end try
        end repeat
    end repeat
    return "none"
end tell
"""


def _process_running(pattern: str) -> bool:
    """True if any process's full command line contains ``pattern``.

    Uses ``pgrep -f`` (substring of the argv), NOT ``-xf``: the app binaries
    live at paths like ``/Applications/zoom.us.app/Contents/MacOS/zoom.us``, so
    an exact whole-command-line match never fires.
    """
    return (
        subprocess.run(
            ["pgrep", "-f", pattern], capture_output=True, check=False
        ).returncode
        == 0
    )


def _osascript(script: str, timeout: float = 5) -> str | None:
    """Run an AppleScript; returns stdout or None on error/denied permission."""
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def zoom_state() -> str:
    """"muted" | "unmuted" | "none".

    "none" covers both "no meeting" and "cannot tell" (e.g. the Automation
    permission for System Events was denied) — no signal means no meeting.
    """
    if not _process_running("zoom.us"):
        return "none"
    result = _osascript(_ZOOM_SCRIPT)
    if result in ("muted", "unmuted"):
        return result
    return "none"


def meet_state() -> str:
    if not _process_running("Google Chrome") and not _process_running(
        "Google Chrome.app/Contents/MacOS/Google Chrome"
    ):
        return "none"
    result = _osascript(_MEET_SCRIPT, timeout=10)
    if result in ("muted", "unmuted", "none", "unknown"):
        return result
    return "none"


_ZOOM_TOGGLE_SCRIPT = """
tell application "System Events"
    if not (exists application process "zoom.us") then return "none"
    try
        tell application process "zoom.us"
            if exists (menu item "Mute audio" of menu 1 of menu bar item "Meeting" of menu bar 1) then
                click (menu item "Mute audio" of menu 1 of menu bar item "Meeting" of menu bar 1)
                return "muted"
            end if
            if exists (menu item "Unmute audio" of menu 1 of menu bar item "Meeting" of menu bar 1) then
                click (menu item "Unmute audio" of menu 1 of menu bar item "Meeting" of menu bar 1)
                return "unmuted"
            end if
        end tell
    end try
    return "none"
end tell
"""

_MEET_TOGGLE_JS = """
(() => {
  for (const b of document.querySelectorAll('button,[role=button]')) {
    const label = b.getAttribute('aria-label') || b.getAttribute('data-tooltip') || '';
    if (label.includes('Turn on microphone')) { b.click(); return 'unmuted'; }
    if (label.includes('Turn off microphone')) { b.click(); return 'muted'; }
  }
  return 'unknown';
})();
"""

_MEET_TOGGLE_SCRIPT = _MEET_SCRIPT.replace(
    _MEET_JS.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34)).replace(chr(10), " "),
    _MEET_TOGGLE_JS.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34)).replace(chr(10), " "),
)


def toggle_mute() -> dict[str, Any]:
    """Toggle mute in whichever meeting is active; returns the new state."""
    if _process_running("zoom.us"):
        result = _osascript(_ZOOM_TOGGLE_SCRIPT)
        if result in ("muted", "unmuted"):
            return {"app": "zoom", "state": result, "in_meeting": True}
    result = _osascript(_MEET_TOGGLE_SCRIPT, timeout=10)
    if result in ("muted", "unmuted"):
        return {"app": "meet", "state": result, "in_meeting": True}
    return {"app": None, "state": "none", "in_meeting": False}


def detect() -> dict[str, Any]:
    """Overall meeting state. Zoom wins if both are somehow active.

    Meet can report "unknown": a meeting tab is open but Chrome's
    "Allow JavaScript from Apple Events" is off, so mute state is unreadable.
    """
    zoom = zoom_state()
    if zoom in ("muted", "unmuted"):
        return {"app": "zoom", "state": zoom, "in_meeting": True}
    meet = meet_state()
    if meet in ("muted", "unmuted", "unknown"):
        return {"app": "meet", "state": meet, "in_meeting": True}
    return {"app": None, "state": "none", "in_meeting": False}
