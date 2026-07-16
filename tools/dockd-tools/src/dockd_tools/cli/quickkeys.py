"""dockd-quickkeys — talk to a Xencelabs Quick Keys pad over USB HID.

Examples:
    dockd-quickkeys list                 # attached devices as JSON
    dockd-quickkeys watch                # stream key/wheel/battery events
    dockd-quickkeys set-color 255 0 64   # wheel ring RGB
    dockd-quickkeys set-text 3 "OBS"     # label for key 3 (keys 0-7)
    dockd-quickkeys demo                 # cycle wheel colors
"""

from __future__ import annotations

import argparse
import time

from ..cliutil import emit, fail
from ..log import get_logger
from ..quickkeys import QuickKeysDevice, QuickKeysError, enumerate_devices

log = get_logger("dockd-quickkeys")


def _open_device() -> QuickKeysDevice:
    try:
        return QuickKeysDevice.open_first()
    except QuickKeysError as exc:
        raise fail(str(exc))


def cmd_list(_args: argparse.Namespace) -> None:
    try:
        devices = enumerate_devices()
    except QuickKeysError as exc:
        raise fail(str(exc))
    emit({"ok": True, "devices": devices})


def cmd_watch(args: argparse.Namespace) -> None:
    with _open_device() as dev:
        log.info(
            "watching quick keys events (%s)",
            "wireless dongle" if dev.wireless else "wired",
        )
        try:
            for event in dev.read_events(timeout_ms=args.poll_ms):
                emit(event)
        except KeyboardInterrupt:
            return
        except QuickKeysError as exc:
            raise fail(str(exc))


def cmd_set_color(args: argparse.Namespace) -> None:
    for value in (args.r, args.g, args.b):
        if not 0 <= value <= 255:
            raise fail("RGB values must be 0 - 255")
    with _open_device() as dev:
        try:
            dev.set_wheel_color(args.r, args.g, args.b)
        except QuickKeysError as exc:
            raise fail(str(exc))
        emit({"ok": True, "color": [args.r, args.g, args.b]})


def cmd_set_text(args: argparse.Namespace) -> None:
    with _open_device() as dev:
        try:
            dev.set_key_text(args.key, args.text)
        except (QuickKeysError, ValueError) as exc:
            raise fail(str(exc))
        emit({"ok": True, "key": args.key, "text": args.text})


def cmd_demo(args: argparse.Namespace) -> None:
    colors = [
        (255, 0, 0),
        (255, 128, 0),
        (255, 255, 0),
        (0, 255, 0),
        (0, 255, 255),
        (0, 0, 255),
        (128, 0, 255),
        (255, 0, 128),
    ]
    with _open_device() as dev:
        log.info("cycling %d colors (%d loops)", len(colors), args.loops)
        try:
            for _ in range(args.loops):
                for r, g, b in colors:
                    dev.set_wheel_color(r, g, b)
                    time.sleep(args.delay)
        except KeyboardInterrupt:
            pass
        except QuickKeysError as exc:
            raise fail(str(exc))
        emit({"ok": True, "demo": "done"})


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="dockd-quickkeys",
        description="Control a Xencelabs Quick Keys pad (wired or wireless dongle).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="enumerate attached devices as JSON").set_defaults(
        func=cmd_list
    )

    p_watch = sub.add_parser("watch", help="stream event JSON lines to stdout")
    p_watch.add_argument(
        "--poll-ms", type=int, default=500, help="HID read timeout per poll (ms)"
    )
    p_watch.set_defaults(func=cmd_watch)

    p_color = sub.add_parser("set-color", help="set the wheel ring RGB color")
    p_color.add_argument("r", type=int)
    p_color.add_argument("g", type=int)
    p_color.add_argument("b", type=int)
    p_color.set_defaults(func=cmd_set_color)

    p_text = sub.add_parser("set-text", help="set a key label (keys 0-7, 8 chars max)")
    p_text.add_argument("key", type=int)
    p_text.add_argument("text")
    p_text.set_defaults(func=cmd_set_text)

    p_demo = sub.add_parser("demo", help="cycle the wheel ring through colors")
    p_demo.add_argument("--loops", type=int, default=3)
    p_demo.add_argument("--delay", type=float, default=0.5)
    p_demo.set_defaults(func=cmd_demo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
