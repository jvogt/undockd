"""Cycle the default audio input/output through a configured allow-list.

The allow-lists live in config as ``audio.output_cycle`` / ``audio.input_cycle``:
lists of ``{"match": <uid | name | substring>, "label": <short display name>}``.
Only entries whose device is actually present participate in the cycle, with
one exception: an output entry matching the AirPods is included when the
AirPods are available (paired, in range) but not yet connected — selecting it
connects them.
"""

from __future__ import annotations

from typing import Any

from . import airpods, config as cfg, coreaudio


class NoChoicesError(RuntimeError):
    """Fewer than two allow-listed devices are present."""


def _matches(match: str, device: coreaudio.AudioDevice) -> bool:
    return (
        match == device.uid
        or match == device.name
        or match.lower() in device.name.lower()
    )


def entries(config: dict[str, Any], direction: str) -> list[dict[str, Any]]:
    return cfg.get(config, f"audio.{direction}_cycle", []) or []


def resolve(
    config: dict[str, Any],
    direction: str,
    airpods_status: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Allow-list entries that are usable right now.

    Returns ``{"entry": ..., "device": AudioDevice | None, "connectable": bool}``
    per usable entry; ``device`` is None for the available-but-disconnected
    AirPods case. Pass a cached ``airpods_status`` to avoid an IOBluetooth call.
    """
    airpods_match = cfg.get(config, "audio.airpods_match", "AirPods")
    resolved = []
    for entry in entries(config, direction):
        match = str(entry.get("match", ""))
        if not match:
            continue
        device = coreaudio.find_device(match, direction)
        if device is not None:
            resolved.append({"entry": entry, "device": device, "connectable": False})
        elif direction == "output" and airpods_match.lower() in match.lower():
            status = airpods_status
            if status is None:
                try:
                    status = airpods.status(airpods_match)
                except Exception:
                    status = {}
            if status.get("available"):
                resolved.append({"entry": entry, "device": None, "connectable": True})
    return resolved


def label_for(
    config: dict[str, Any], direction: str, device: coreaudio.AudioDevice | None
) -> str:
    """Short display label for the current device (allow-list label, or a
    prefix of the device name when it isn't allow-listed)."""
    if device is None:
        return "?"
    for entry in entries(config, direction):
        match = str(entry.get("match", ""))
        if match and _matches(match, device):
            return str(entry.get("label") or device.name)[:5]
    return device.name[:5]


def cycle(
    config: dict[str, Any],
    direction: str,
    airpods_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Switch the default device to the next allow-listed candidate."""
    candidates = resolve(config, direction, airpods_status)
    if len(candidates) < 2:
        raise NoChoicesError(f"fewer than two {direction} choices present")

    current = coreaudio.get_default(direction)
    index = -1
    if current is not None:
        for i, candidate in enumerate(candidates):
            if candidate["device"] is not None and candidate["device"].id == current.id:
                index = i
                break
    target = candidates[(index + 1) % len(candidates)]

    airpods_match = cfg.get(config, "audio.airpods_match", "AirPods")
    is_airpods_target = target["connectable"] or (
        target["device"] is not None
        and airpods_match.lower() in target["device"].name.lower()
    )
    if direction == "output" and is_airpods_target:
        keep_input = bool(cfg.get(config, "audio.keep_input", True))
        airpods.activate(airpods_match, keep_input=keep_input)
        device = coreaudio.find_device(airpods_match, "output")
    else:
        device = target["device"]
        coreaudio.set_default(direction, device)

    return {
        "direction": direction,
        "device": device.as_dict() if device else None,
        "label": label_for(config, direction, device),
    }
