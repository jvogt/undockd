"""dockd-audio — system audio devices and AirPods control.

Examples:
    dockd-audio list
    dockd-audio get output
    dockd-audio get input
    dockd-audio set output "MacBook Pro Speakers"
    dockd-audio airpods status
    dockd-audio airpods connect|activate|deactivate|toggle
"""

from __future__ import annotations

import argparse

from .. import airpods, config as cfg, coreaudio
from ..cliutil import emit, fail
from ..log import get_logger

log = get_logger("dockd-audio")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="dockd-audio", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list audio devices")

    p_get = sub.add_parser("get", help="show default device")
    p_get.add_argument("direction", choices=["input", "output"])

    p_set = sub.add_parser("set", help="set default device")
    p_set.add_argument("direction", choices=["input", "output"])
    p_set.add_argument("device", help="device UID, name, or name substring")

    p_air = sub.add_parser("airpods", help="AirPods status and control")
    p_air.add_argument(
        "action",
        choices=["status", "connect", "activate", "deactivate", "toggle"],
    )

    args = parser.parse_args(argv)
    config = cfg.load()

    try:
        if args.cmd == "list":
            emit({"ok": True, "devices": [d.as_dict() for d in coreaudio.list_devices()]})
        elif args.cmd == "get":
            device = coreaudio.get_default(args.direction)
            emit({"ok": True, "device": device.as_dict() if device else None})
        elif args.cmd == "set":
            device = coreaudio.find_device(args.device, args.direction)
            if device is None:
                raise fail(f"no {args.direction} device matching {args.device!r}")
            coreaudio.set_default(args.direction, device)
            log.info("default %s set to %s", args.direction, device.name)
            emit({"ok": True, "device": device.as_dict()})
        elif args.cmd == "airpods":
            match = cfg.get(config, "audio.airpods_match", "AirPods")
            fallback = cfg.get(config, "audio.fallback_output")
            keep_input = bool(cfg.get(config, "audio.keep_input", True))
            if args.action == "status":
                emit({"ok": True, **airpods.status(match)})
            elif args.action == "connect":
                emit({"ok": True, **airpods.connect(match)})
            elif args.action == "activate":
                result = airpods.activate(match, keep_input=keep_input)
                log.info("airpods activated as output")
                emit({"ok": True, **result})
            elif args.action == "deactivate":
                result = airpods.deactivate(match, fallback)
                log.info("output switched away from airpods")
                emit({"ok": True, **result})
            else:
                result = airpods.toggle(match, fallback, keep_input=keep_input)
                log.info("airpods toggled; active_output=%s", result["active_output"])
                emit({"ok": True, **result})
    except (airpods.BluetoothUnavailable, coreaudio.CoreAudioError, RuntimeError) as exc:
        raise fail(str(exc))


if __name__ == "__main__":
    main()
