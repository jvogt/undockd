"""dockd-meeting — report Zoom / Google Meet meeting + mute state.

Examples:
    dockd-meeting status
    dockd-meeting status --watch     # JSON line on every state change
"""

from __future__ import annotations

import argparse
import time

from ..cliutil import emit
from ..meeting import detect, toggle_mute


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="dockd-meeting", description=__doc__)
    sub = parser.add_subparsers(dest="cmd")
    p_status = sub.add_parser("status", help="meeting/mute state (default)")
    p_status.add_argument("--watch", action="store_true", help="emit on every change")
    p_status.add_argument("--interval", type=float, default=0.5)
    sub.add_parser("toggle-mute", help="toggle mute in the active Zoom/Meet meeting")
    args = parser.parse_args(argv)

    if args.cmd == "toggle-mute":
        emit({"ok": True, **toggle_mute()})
        return

    watch = getattr(args, "watch", False)
    if not watch:
        emit({"ok": True, **detect()})
        return

    last = None
    while True:
        state = detect()
        if state != last:
            emit({"ok": True, **state})
            last = state
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
