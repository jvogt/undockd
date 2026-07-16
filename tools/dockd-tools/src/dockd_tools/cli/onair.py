"""dockd-onair — drive the on-air light from Zoom / Google Meet mute state.

The daemon polls meeting state and switches Home Assistant scenes on change:
unmuted → onair.home_assistant.scenes.unmuted (light on / red),
muted   → scenes.muted, no meeting or unknown → scenes.unknown.

Examples:
    dockd-onair run                # daemon; Ctrl-C resets light to unknown
    dockd-onair set unmuted        # manually fire a scene (testing)
    dockd-onair status             # last state written by the daemon
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import time

from .. import config as cfg
from ..cliutil import Heartbeat, emit, fail, read_heartbeat, heartbeat_healthy
from ..homeassistant import HomeAssistant, HomeAssistantError
from ..log import get_logger
from ..meeting import detect

log = get_logger("dockd-onair")

SCENE_KEYS = ("unmuted", "muted", "unknown")


def _scene_for(config: dict, state: str) -> str:
    key = state if state in ("unmuted", "muted") else "unknown"
    return cfg.get(config, f"onair.home_assistant.scenes.{key}")


def _ha(config: dict) -> HomeAssistant:
    return HomeAssistant(
        cfg.get(config, "onair.home_assistant.url"),
        cfg.get(config, "onair.home_assistant.token"),
    )


def run(config: dict) -> None:
    interval = float(cfg.get(config, "onair.poll_interval", 0.5))
    ha = _ha(config)
    heartbeat = Heartbeat("onair", max(interval, 1))
    current_scene: str | None = None
    ha_ok = True

    def reset(signum=None, frame=None):
        try:
            ha.turn_on_scene(_scene_for(config, "unknown"))
            log.info("reset on-air light to unknown scene")
        except HomeAssistantError as exc:
            log.warning("could not reset on-air light: %s", exc)
        heartbeat.clear()
        # Exit promptly from the signal handler; nothing else to flush.
        logging.shutdown()
        os._exit(0)

    signal.signal(signal.SIGTERM, reset)
    signal.signal(signal.SIGINT, reset)
    log.info("on-air watcher started (interval=%ss)", interval)

    while True:
        state = detect()
        scene = _scene_for(config, state["state"])
        if scene != current_scene:
            try:
                ha.turn_on_scene(scene)
                if not ha_ok:
                    log.info("Home Assistant reachable again")
                    ha_ok = True
                log.info(
                    "state %s (%s) -> %s", state["state"], state["app"], scene
                )
                current_scene = scene
            except HomeAssistantError as exc:
                if ha_ok:
                    log.warning("%s", exc)
                    ha_ok = False
        heartbeat.beat(
            state=state["state"],
            app=state["app"],
            in_meeting=state["in_meeting"],
            on_air=state["state"] == "unmuted",
            ha_ok=ha_ok,
        )
        time.sleep(interval)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="dockd-onair", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="run the watcher daemon")
    p_set = sub.add_parser("set", help="manually fire a scene")
    p_set.add_argument("state", choices=SCENE_KEYS)
    sub.add_parser("status", help="last daemon state")

    args = parser.parse_args(argv)
    config = cfg.load()

    if args.cmd == "run":
        try:
            run(config)
        except HomeAssistantError as exc:
            raise fail(str(exc))
    elif args.cmd == "set":
        try:
            _ha(config).turn_on_scene(_scene_for(config, args.state))
        except HomeAssistantError as exc:
            raise fail(str(exc))
        emit({"ok": True, "scene": _scene_for(config, args.state)})
    else:
        data = read_heartbeat("onair")
        emit(
            {
                "ok": True,
                "healthy": heartbeat_healthy(data),
                **{k: v for k, v in (data or {}).items()},
            }
        )


if __name__ == "__main__":
    main()
