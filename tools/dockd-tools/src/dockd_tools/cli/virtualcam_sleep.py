"""dockd-virtualcam-sleep — stop the OBS virtual camera when the system idles.

Stops the virtual camera once the system has been idle longer than the
screensaver timeout (minus a margin), and starts it again on activity. Never
stops the camera while a Zoom / Google Meet meeting is detected. Tolerates
OBS restarts.

Examples:
    dockd-virtualcam-sleep run
    dockd-virtualcam-sleep status
"""

from __future__ import annotations

import argparse
import signal
import time

from .. import config as cfg
from ..cliutil import Heartbeat, emit, heartbeat_healthy, read_heartbeat
from ..idle import idle_seconds, screensaver_timeout
from ..log import get_logger
from ..meeting import detect
from ..obs import Obs, ObsError

log = get_logger("dockd-virtualcam-sleep")


def _threshold(config: dict) -> int:
    timeout = screensaver_timeout() or int(
        cfg.get(config, "virtualcam_sleep.fallback_timeout_seconds", 1200)
    )
    margin = int(cfg.get(config, "virtualcam_sleep.margin_seconds", 10))
    return max(timeout - margin, 30)


def run(config: dict) -> None:
    interval = float(cfg.get(config, "virtualcam_sleep.poll_interval", 5))
    respect_meetings = bool(cfg.get(config, "virtualcam_sleep.respect_meetings", True))
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
        "virtualcam-sleep started (threshold=%ss, interval=%ss, respect_meetings=%s)",
        threshold,
        interval,
        respect_meetings,
    )

    while True:
        idle = idle_seconds()
        # Re-read cheaply so a changed screensaver setting is picked up
        threshold = _threshold(config)
        status: dict = {"idle_seconds": round(idle, 1), "threshold": threshold}
        try:
            active = obs.virtualcam_active()
            if obs_connected is not True:
                log.info("OBS connected")
                obs_connected = True

            if idle > threshold:
                in_meeting = respect_meetings and detect()["in_meeting"]
                if active and not in_meeting:
                    log.info("system idle for %.0fs; stopping virtual camera", idle)
                    obs.virtualcam_stop()
                    active = False
                elif active and in_meeting:
                    log.debug("idle but in a meeting; leaving virtual camera on")
            else:
                if not active:
                    log.info("system active; starting virtual camera")
                    obs.virtualcam_start()
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
