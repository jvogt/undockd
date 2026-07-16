"""dockd-quickkeys — talk to a Xencelabs Quick Keys pad over USB HID.

Examples:
    dockd-quickkeys run                  # always-on daemon driving the pad
    dockd-quickkeys status               # daemon health + connection (JSON)
    dockd-quickkeys list                 # attached devices as JSON
    dockd-quickkeys watch                # stream key/wheel/battery events
    dockd-quickkeys set-color 255 0 64   # wheel ring RGB
    dockd-quickkeys set-text 3 "OBS"     # label for key 3 (keys 0-7)
    dockd-quickkeys demo                 # cycle wheel colors
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import time

from .. import config as cfg, meeting
from ..cliutil import (
    Heartbeat,
    emit,
    fail,
    heartbeat_healthy,
    read_dock_flag,
    read_heartbeat,
)
from ..log import get_logger
from ..quickkeys import QuickKeysDevice, QuickKeysError, enumerate_devices
from ..quickkeys_bridge import QuickKeysBridge

log = get_logger("dockd-quickkeys")


def _open_device() -> QuickKeysDevice:
    try:
        return QuickKeysDevice.open_first()
    except QuickKeysError as exc:
        raise fail(str(exc))


def cmd_run(_args: argparse.Namespace) -> None:
    """Always-on daemon: drive the pad whenever it is attached.

    Independent of dock/on-air state — this is a USB desk peripheral. The
    bridge owns its own audio/OBS refresh; here we only feed it meeting state
    for the mute key (skipped entirely when no toggle_mute key is mapped) and
    publish a heartbeat the menubar app reads.
    """
    config = cfg.load()
    interval = float(cfg.get(config, "quickkeys.poll_interval", 0.5))
    buttons = cfg.get(config, "quickkeys.buttons", {}) or {}
    need_meeting = "toggle_mute" in {str(v) for v in buttons.values()}
    heartbeat = Heartbeat("quickkeys", max(interval, 1))
    bridge = QuickKeysBridge(config, log)
    bridge.start()

    def reset(signum=None, frame=None):
        bridge.stop()
        heartbeat.clear()
        # Exit without running Python's atexit handlers: cython-hidapi
        # registers hid_exit there, and its IOHIDManager teardown crashes
        # ("Python quit unexpectedly") once HID was used from a worker thread
        # whose run loop is gone. bridge.stop() already closed the device.
        logging.shutdown()
        os._exit(0)

    signal.signal(signal.SIGTERM, reset)
    signal.signal(signal.SIGINT, reset)
    log.info("quickkeys daemon started (interval=%ss, meeting=%s)", interval, need_meeting)

    state = {"app": None, "state": "none", "in_meeting": False}
    while True:
        # Docked drives whether the pad is lit and responsive. Unknown (app not
        # running / hasn't written yet) is treated as docked so the pad still
        # works when driven standalone.
        docked = read_dock_flag()
        bridge.set_active(docked is not False)
        if need_meeting and bridge.active:
            state = meeting.detect()
            bridge.set_meeting_state(state)
        heartbeat.beat(
            connected=bridge.connected,
            docked=docked,
            active=bridge.active,
            in_meeting=state["in_meeting"],
            state=state["state"],
            obs_scene_collection=bridge.obs_scene_collection,
        )
        # No mute key → nothing here needs sub-second cadence; idle slower.
        time.sleep(interval if need_meeting else max(interval, 2))


def cmd_status(_args: argparse.Namespace) -> None:
    data = read_heartbeat("quickkeys")
    emit(
        {
            "ok": True,
            "healthy": heartbeat_healthy(data),
            **{k: v for k, v in (data or {}).items()},
        }
    )


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

    sub.add_parser("run", help="always-on daemon that drives the pad").set_defaults(
        func=cmd_run
    )
    sub.add_parser("status", help="daemon health + connection (JSON)").set_defaults(
        func=cmd_status
    )
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
