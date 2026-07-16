"""dockd-obs — control OBS profiles and virtual camera.

Examples:
    dockd-obs status
    dockd-obs profiles
    dockd-obs profile get
    dockd-obs profile set Docked
    dockd-obs profile set --slot docked      # use the configured mapping
    dockd-obs virtualcam status|start|stop|toggle
    dockd-obs ensure-running
"""

from __future__ import annotations

import argparse

from .. import config as cfg
from ..cliutil import emit, fail
from ..log import get_logger
from ..obs import Obs, ObsError, ensure_running, is_running

log = get_logger("dockd-obs")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="dockd-obs", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="running state, current profile, virtualcam state")
    sub.add_parser("profiles", help="list profiles and current profile")
    sub.add_parser("ensure-running", help="start OBS if it is not running")

    p_profile = sub.add_parser("profile", help="get or set the current profile")
    profile_sub = p_profile.add_subparsers(dest="profile_cmd", required=True)
    profile_sub.add_parser("get")
    p_set = profile_sub.add_parser("set")
    p_set.add_argument("name", nargs="?", help="profile name")
    p_set.add_argument(
        "--slot",
        choices=["docked", "undocked"],
        help="use the profile mapped to this slot in dockd config",
    )

    p_cam = sub.add_parser("virtualcam", help="virtual camera control")
    p_cam.add_argument("action", choices=["status", "start", "stop", "toggle"])

    args = parser.parse_args(argv)
    config = cfg.load()

    if args.cmd == "ensure-running":
        was_running = ensure_running(cfg.get(config, "obs.app_name", "OBS"))
        if not was_running:
            log.info("launched OBS")
        emit({"ok": True, "running": True, "launched": not was_running})
        return

    try:
        obs = Obs(config)
        if args.cmd == "status":
            running = is_running(cfg.get(config, "obs.app_name", "OBS"))
            payload: dict = {"ok": True, "running": running}
            if running:
                payload.update(obs.profiles())
                payload["virtualcam_active"] = obs.virtualcam_active()
            emit(payload)
        elif args.cmd == "profiles":
            emit({"ok": True, **obs.profiles()})
        elif args.cmd == "profile":
            if args.profile_cmd == "get":
                emit({"ok": True, "current": obs.profiles()["current"]})
            else:
                name = args.name
                if args.slot:
                    name = cfg.get(config, f"obs.profiles.{args.slot}")
                if not name:
                    raise fail("profile set requires a name or --slot")
                obs.set_profile(name)
                log.info("profile set to %s", name)
                emit({"ok": True, "current": name})
        elif args.cmd == "virtualcam":
            if args.action == "status":
                emit({"ok": True, "active": obs.virtualcam_active()})
            elif args.action == "start":
                obs.virtualcam_start()
                log.info("virtualcam started")
                emit({"ok": True, "active": True})
            elif args.action == "stop":
                obs.virtualcam_stop()
                log.info("virtualcam stopped")
                emit({"ok": True, "active": False})
            else:
                active = obs.virtualcam_toggle()
                log.info("virtualcam toggled to %s", active)
                emit({"ok": True, "active": active})
    except ObsError as exc:
        raise fail(str(exc))


if __name__ == "__main__":
    main()
