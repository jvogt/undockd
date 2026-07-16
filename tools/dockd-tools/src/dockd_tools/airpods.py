"""AirPods availability and connection, via IOBluetooth + CoreAudio.

- "available": paired and in Bluetooth range (IOBluetooth sees them)
- "connected": Bluetooth-connected (they show up as audio devices)
- "active output"/"active input": they are the system default device

Querying IOBluetooth needs the Bluetooth TCC permission for the calling app;
when it is unreadable (permission denied, adapter off) we degrade to what
CoreAudio can tell us (connected + active states still work).
"""

from __future__ import annotations

import time
from typing import Any

from . import bluetooth, coreaudio
from .bluetooth import BluetoothUnavailable


def paired_airpods(match: str) -> dict[str, Any] | None:
    """First paired Bluetooth device whose name contains ``match``."""
    needle = match.lower()
    for device in bluetooth.paired_devices():
        if needle in (device.get("name") or "").lower():
            return device
    return None


def _audio_device(match: str, direction: str) -> coreaudio.AudioDevice | None:
    return coreaudio.find_device(match, direction)


def status(match: str, include_bluetooth: bool = True) -> dict[str, Any]:
    """AirPods state. ``include_bluetooth=False`` skips the IOBluetooth
    availability check and reports only what CoreAudio can tell — connected
    and active states — in a few hundred milliseconds."""
    result: dict[str, Any] = {
        "match": match,
        "available": None,  # unknown when bluetooth is unreadable/skipped
        "connected": False,
        "active_output": False,
        "active_input": False,
        "bluetooth_error": None,
    }
    if include_bluetooth:
        try:
            paired = paired_airpods(match)
            result["available"] = paired is not None
            if paired:
                result["address"] = paired.get("address")
                result["name"] = paired.get("name")
                result["connected"] = bool(paired.get("connected"))
        except BluetoothUnavailable as exc:
            result["bluetooth_error"] = str(exc)

    output_device = _audio_device(match, "output")
    if output_device:
        # Present as an audio device implies connected even without blueutil
        result["connected"] = True
        result.setdefault("name", output_device.name)
        default_out = coreaudio.get_default("output")
        result["active_output"] = bool(default_out and default_out.id == output_device.id)
    input_device = _audio_device(match, "input")
    if input_device:
        default_in = coreaudio.get_default("input")
        result["active_input"] = bool(default_in and default_in.id == input_device.id)
    return result


def connect(match: str, wait_seconds: float = 10) -> dict[str, Any]:
    """Bluetooth-connect the AirPods and wait for their audio device."""
    paired = paired_airpods(match)
    if not paired:
        raise BluetoothUnavailable(f"no paired device matching {match!r}")
    if not paired.get("connected"):
        try:
            bluetooth.connect(paired["address"])
        except BluetoothUnavailable as exc:
            # Classic paging can't pull AirPods off another active Apple device
            # (that needs the OS audio handoff). Point the user at what works.
            raise BluetoothUnavailable(
                f"{match} {exc}. If they're in use by another device, "
                f"select them from the macOS Sound menu."
            ) from exc
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if _audio_device(match, "output"):
            break
        time.sleep(0.5)
    return status(match)


def activate(match: str, keep_input: bool = True) -> dict[str, Any]:
    """Make AirPods the default output (connecting first if needed).

    With ``keep_input`` (the default), the default input device is pinned:
    macOS tends to also switch input to the AirPods mic when they connect /
    become the output, and we put it back where it was.
    """
    previous_input = coreaudio.get_default("input")
    if not _audio_device(match, "output"):
        connect(match)
    device = _audio_device(match, "output")
    if not device:
        raise BluetoothUnavailable(
            f"{match!r} did not appear as an audio output device"
        )
    coreaudio.set_default("output", device)

    if keep_input and previous_input and match.lower() not in previous_input.name.lower():
        # The input hijack happens asynchronously shortly after the output
        # switch / connect; watch for it briefly and undo it.
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            current = coreaudio.get_default("input")
            if current and current.id != previous_input.id:
                coreaudio.set_default("input", previous_input)
                break
            time.sleep(0.3)
    return status(match)


def deactivate(match: str, fallback: str | None) -> dict[str, Any]:
    """Switch default output away from AirPods (to fallback or built-in)."""
    target = None
    if fallback:
        target = coreaudio.find_device(fallback, "output")
    if target is None:
        target = next(
            (d for d in coreaudio.list_devices() if d.output and d.transport == "builtin"),
            None,
        )
    if target is None:
        raise RuntimeError("no fallback output device found")
    coreaudio.set_default("output", target)
    return status(match)


def toggle(match: str, fallback: str | None, keep_input: bool = True) -> dict[str, Any]:
    current = status(match)
    if current["active_output"]:
        return deactivate(match, fallback)
    return activate(match, keep_input=keep_input)
