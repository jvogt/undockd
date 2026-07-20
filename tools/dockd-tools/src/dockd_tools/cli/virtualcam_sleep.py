"""dockd-virtualcam-sleep — keep the OBS virtual camera on only when needed.

Two modes (``virtualcam_sleep.mode``):

- ``meeting`` (default): the virtual camera runs only while a Zoom / Google
  Meet meeting — or a join/preview screen — is detected.
- ``always``: the virtual camera runs whenever the system is awake, stopping
  once the system has been idle longer than the screensaver timeout (minus a
  margin) and restarting on activity. Never stops during a detected meeting.

With ``virtualcam_sleep.use_sleep_collection`` enabled, every camera stop the
daemon itself performs also switches OBS to the ``obs.scene_collections.sleep``
collection (a scene with no inputs, releasing the camera hardware), and the
dock-mapped collection is restored before the camera starts again. Camera
stops from anywhere else (menubar toggle, OBS UI) never trigger the switch.

Tolerates OBS restarts.

Examples:
    dockd-virtualcam-sleep run
    dockd-virtualcam-sleep status
"""

from __future__ import annotations

import argparse
import signal
import time

from .. import config as cfg
from ..cliutil import Heartbeat, emit, heartbeat_healthy, read_dock_flag, read_heartbeat
from ..idle import idle_seconds, screensaver_timeout
from ..log import get_logger
from ..meeting import detect, meeting_or_joining
from ..obs import Obs, ObsError

log = get_logger("dockd-virtualcam-sleep")


def _threshold(config: dict) -> int:
    timeout = screensaver_timeout() or int(
        cfg.get(config, "virtualcam_sleep.fallback_timeout_seconds", 1200)
    )
    margin = int(cfg.get(config, "virtualcam_sleep.margin_seconds", 10))
    return max(timeout - margin, 30)


def _sleep_name(config: dict) -> str:
    return str(cfg.get(config, "obs.scene_collections.sleep", "Sleep"))


def enter_sleep_collection(obs: Obs, config: dict) -> None:
    """Switch OBS to the (input-free) sleep collection after a camera stop.

    A missing/misnamed collection degrades to a plain camera stop rather than
    tainting the loop's OBS-connected state.
    """
    try:
        obs.set_scene_collection(_sleep_name(config))
    except ObsError as exc:
        log.warning("cannot switch to sleep scene collection: %s", exc)


def leave_sleep_collection(obs: Obs, config: dict) -> None:
    """Restore the dock-mapped collection if OBS sits in the sleep one.

    The dock flag file is the source of truth for which slot to restore —
    it survives daemon restarts and dock changes while asleep. Unknown dock
    state defaults to the docked slot.
    """
    try:
        if obs.scene_collections()["current_scene_collection"] != _sleep_name(config):
            return
        slot = "undocked" if read_dock_flag() is False else "docked"
        target = str(cfg.get(config, f"obs.scene_collections.{slot}", slot.capitalize()))
        log.info("waking from sleep scene collection to %r (%s)", target, slot)
        obs.set_scene_collection(target)
    except ObsError as exc:
        log.warning("cannot restore scene collection from sleep: %s", exc)


def run(config: dict) -> None:
    interval = float(cfg.get(config, "virtualcam_sleep.poll_interval", 5))
    respect_meetings = bool(cfg.get(config, "virtualcam_sleep.respect_meetings", True))
    mode = str(cfg.get(config, "virtualcam_sleep.mode", "meeting")).lower()
    if mode not in ("meeting", "always"):
        log.warning("unknown virtualcam_sleep.mode %r; using 'meeting'", mode)
        mode = "meeting"
    use_sleep = bool(cfg.get(config, "virtualcam_sleep.use_sleep_collection", False))

    # Camera transitions the daemon itself decides on. Only these touch the
    # sleep scene collection — external stops/starts never do.
    def cam_stop() -> None:
        obs.virtualcam_stop()
        if use_sleep:
            enter_sleep_collection(obs, config)

    def cam_start() -> None:
        if use_sleep:
            leave_sleep_collection(obs, config)
        obs.virtualcam_start()
    heartbeat = Heartbeat("virtualcam-sleep", interval)
    obs = Obs(config)
    obs_connected: bool | None = None

    def stop(signum=None, frame=None):
        heartbeat.clear()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    threshold = _threshold(config)
    log.info(
        "virtualcam-sleep started (mode=%s, threshold=%ss, interval=%ss, "
        "respect_meetings=%s, use_sleep_collection=%s)",
        mode,
        threshold,
        interval,
        respect_meetings,
        use_sleep,
    )

    while True:
        idle = idle_seconds()
        # Re-read cheaply so a changed screensaver setting is picked up
        threshold = _threshold(config)
        status: dict = {"idle_seconds": round(idle, 1), "threshold": threshold, "mode": mode}
        try:
            active = obs.virtualcam_active()
            if obs_connected is not True:
                log.info("OBS connected")
                obs_connected = True

            if mode == "meeting":
                present = meeting_or_joining()["in_meeting"]
                status["meeting_present"] = present
                if active and not present:
                    log.info("no meeting detected; stopping virtual camera")
                    cam_stop()
                    active = False
                elif not active and present:
                    log.info("meeting detected; starting virtual camera")
                    cam_start()
                    active = True
            elif idle > threshold:
                in_meeting = respect_meetings and detect()["in_meeting"]
                if active and not in_meeting:
                    log.info("system idle for %.0fs; stopping virtual camera", idle)
                    cam_stop()
                    active = False
                elif active and in_meeting:
                    log.debug("idle but in a meeting; leaving virtual camera on")
            else:
                if not active:
                    log.info("system active; starting virtual camera")
                    cam_start()
                    active = True
            status.update(obs_connected=True, virtualcam_active=active)
        except Exception as exc:  # obsws raises bare Exception subclasses on drops
            obs.close()
            if obs_connected is not False:
                log.info("OBS disconnected (%s)", exc)
                obs_connected = False
            status.update(obs_connected=False)

        heartbeat.beat(**status)
        time.sleep(interval)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="dockd-virtualcam-sleep", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="run the daemon")
    sub.add_parser("status", help="last daemon state")
    args = parser.parse_args(argv)

    if args.cmd == "run":
        run(cfg.load())
    else:
        data = read_heartbeat("virtualcam-sleep")
        emit(
            {
                "ok": True,
                "healthy": heartbeat_healthy(data),
                **{k: v for k, v in (data or {}).items()},
            }
        )


if __name__ == "__main__":
    main()
