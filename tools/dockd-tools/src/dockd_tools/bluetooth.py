"""Bluetooth paired-device queries and connection, via IOBluetooth (PyObjC).

Replaces the former dependency on the ``blueutil`` command-line tool: talking to
IOBluetooth in-process means nothing extra has to be installed, and the Bluetooth
TCC permission prompt is attributed to the host app (Dockd.app) the first time we
touch the framework.

Only two operations are needed — list paired devices and connect one by address —
so we stay well inside the part of IOBluetooth that is stable from Python.
"""

from __future__ import annotations

from typing import Any

try:
    import IOBluetooth  # type: ignore

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - only on a broken/headless install
    IOBluetooth = None  # type: ignore
    _IMPORT_ERROR = exc


class BluetoothUnavailable(RuntimeError):
    """Bluetooth could not be queried (framework missing, off, or not permitted)."""


# IOReturn codes worth translating for humans. kIOReturnTimeout is the common
# one: the device didn't answer the Mac's page — typically because it is bonded
# to another host (e.g. a phone), asleep, or out of range.
_IORETURN_MESSAGES = {
    0xE00002D6: "no response — it may be connected to another device, asleep, or out of range",  # kIOReturnTimeout
    0xE00002C0: "connection not permitted",  # kIOReturnNotPermitted
    0xE00002C7: "device not found",          # kIOReturnNoDevice
}


def _ioreturn_text(status: int) -> str:
    return _IORETURN_MESSAGES.get(status & 0xFFFFFFFF, f"IOReturn {status}")


def _require_framework() -> Any:
    if IOBluetooth is None:
        raise BluetoothUnavailable(
            f"IOBluetooth framework unavailable: {_IMPORT_ERROR}"
        )
    return IOBluetooth


def _call(device: Any, *names: str) -> Any:
    """Call the first available accessor on an IOBluetooth device.

    IOBluetoothDevice exposes both modern properties (``name``) and the older
    ``get*`` methods depending on the macOS/PyObjC version; try in order.
    """
    for name in names:
        method = getattr(device, name, None)
        if method is not None:
            return method()
    return None


def paired_devices() -> list[dict[str, Any]]:
    """All paired Bluetooth devices as ``{name, address, connected}`` dicts.

    The first call may block on the macOS Bluetooth permission prompt; callers
    run us in a subprocess with their own timeout, so that is safe.
    """
    framework = _require_framework()
    try:
        devices = framework.IOBluetoothDevice.pairedDevices()
    except Exception as exc:  # framework present but the call was refused
        raise BluetoothUnavailable(f"could not list paired devices: {exc}") from exc
    if devices is None:
        return []
    result: list[dict[str, Any]] = []
    for device in devices:
        result.append(
            {
                "name": _call(device, "getName", "name") or "",
                "address": _call(device, "getAddressString", "addressString") or "",
                "connected": bool(_call(device, "isConnected")),
            }
        )
    return result


def connect(address: str, timeout: float = 8) -> None:
    """Open a baseband connection to a paired device by address string.

    ``timeout`` bounds the page attempt so a device that is bonded elsewhere or
    asleep fails fast instead of hanging on the default page timeout (~15 s).

    Note: this is a classic-Bluetooth page, not Apple's AirPods audio handoff.
    AirPods actively in use by another Apple device won't answer the page — the
    caller should surface that clearly rather than treating it as a hard error.
    """
    framework = _require_framework()
    device = framework.IOBluetoothDevice.deviceWithAddressString_(address)
    if device is None:
        raise BluetoothUnavailable(f"no Bluetooth device with address {address!r}")
    status = _open_connection(device, timeout)
    # IOBluetooth returns an IOReturn code; kIOReturnSuccess is 0.
    if status != 0:
        raise BluetoothUnavailable(
            f"could not connect {address}: {_ioreturn_text(status)}"
        )


def _open_connection(device: Any, timeout: float) -> int:
    """Synchronously page ``device`` with a bounded page timeout.

    Falls back to the no-argument ``openConnection`` if the page-timeout variant
    is unavailable. Page timeout is expressed in 0.625 ms slots.
    """
    slots = max(1, min(0xFFFF, int(timeout / 0.000625)))
    try:
        return device.openConnection_withPageTimeout_authenticationRequired_(
            None, slots, False
        )
    except (TypeError, ValueError, AttributeError):
        return device.openConnection()
