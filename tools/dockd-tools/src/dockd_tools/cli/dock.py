"""dockd-dock — report docked/undocked state.

Examples:
    dockd-dock status
    dockd-dock devices
"""

from __future__ import annotations

import argparse

from .. import config as cfg
from ..cliutil import emit, fail
from ..dock import dock_status, thunderbolt_devices


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="dockd-dock", description=__doc__)
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("status", help="docked/undocked (default)")
    sub.add_parser("devices", help="list Thunderbolt devices")
    args = parser.parse_args(argv)

    config = cfg.load()
    try:
        if args.cmd == "devices":
            emit({"ok": True, "devices": thunderbolt_devices()})
        else:
            emit({"ok": True, **dock_status(cfg.get(config, "dock.match"))})
    except Exception as exc:
        raise fail(f"dock detection failed: {exc}")


if __name__ == "__main__":
    main()
