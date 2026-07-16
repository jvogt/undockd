"""HID transport for the Xencelabs Quick Keys.

Thin I/O layer over the ``hid`` module (hidapi pip package); all byte
layouts live in :mod:`dockd_tools.quickkeys.protocol`.

Supports both the wired device (PID 0x5202) and the wireless dongle
(PID 0x5203).  Wireless surfaces behind the dongle are addressed by a
6-byte device id which the dongle announces in 0xF8 status packets; we
send a discover report on open and pick up the id from the first status
packet before commands can be routed.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from . import protocol

try:
    import hid  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - depends on environment
    hid = None


class QuickKeysError(RuntimeError):
    """Raised for missing hid module / device not found / I/O problems."""


def _require_hid() -> None:
    if hid is None:
        raise QuickKeysError(
            "the 'hid' module is not installed (pip/uv package 'hidapi')"
        )


def enumerate_devices() -> list[dict[str, Any]]:
    """List attached Quick Keys devices/dongles (vendor interface only)."""
    _require_hid()
    found: list[dict[str, Any]] = []
    for info in hid.enumerate(protocol.VENDOR_ID):
        if info.get("product_id") not in protocol.PRODUCT_IDS:
            continue
        # The vendor protocol lives on interface 2 (usage page 0xFF0A).
        # Some platforms report interface_number as -1; fall back to the
        # usage page filter used by the webhid implementation.
        if (
            info.get("interface_number") != protocol.DEVICE_INTERFACE
            and info.get("usage_page") != protocol.USAGE_PAGE
        ):
            continue
        found.append(
            {
                "path": (info.get("path") or b"").decode(errors="replace"),
                "vendor_id": info.get("vendor_id"),
                "product_id": info.get("product_id"),
                "product": info.get("product_string"),
                "serial": info.get("serial_number"),
                "wireless": info.get("product_id") in protocol.PRODUCT_IDS_WIRELESS,
                "interface_number": info.get("interface_number"),
            }
        )
    return found


class QuickKeysDevice:
    """One opened Quick Keys (wired) or dongle (wireless)."""

    def __init__(self, handle: Any, *, wireless: bool, info: dict[str, Any] | None = None):
        self._handle = handle
        self.wireless = wireless
        self.info = info or {}
        #: Wireless surface id (12 hex chars) once the dongle announces it.
        self.device_id: str | None = None
        self._key_mask = 0
        self._subscribed = False

    # -- lifecycle -----------------------------------------------------------

    @classmethod
    def open_first(cls) -> "QuickKeysDevice":
        """Open the first attached Quick Keys device."""
        _require_hid()
        devices = enumerate_devices()
        if not devices:
            raise QuickKeysError("no Xencelabs Quick Keys device found")
        info = devices[0]
        handle = hid.device()
        try:
            handle.open_path(info["path"].encode())
        except (OSError, ValueError, IOError) as exc:
            raise QuickKeysError(f"could not open device: {exc}") from exc
        dev = cls(handle, wireless=info["wireless"], info=info)
        dev._initialize()
        return dev

    def _initialize(self) -> None:
        if self.wireless:
            # Ask the dongle whether a surface is already connected; its
            # 0xF8 status reply carries the device id we must address.
            self._write(protocol.wireless_discover_report())
        else:
            self._subscribe()

    def _subscribe(self) -> None:
        self._write(protocol.subscribe_keys_report(self.device_id))
        self._write(protocol.subscribe_battery_report(self.device_id))
        self._subscribed = True

    def close(self) -> None:
        try:
            self._handle.close()
        except Exception:  # noqa: BLE001 - best effort
            pass

    def __enter__(self) -> "QuickKeysDevice":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- output --------------------------------------------------------------

    def _write(self, report: bytes) -> None:
        if self._handle.write(report) < 0:
            raise QuickKeysError("HID write failed")

    def _wait_for_device_id(self, timeout: float = 3.0) -> None:
        """Wireless only: pump events until the dongle announces a surface."""
        if not self.wireless or self.device_id is not None:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._poll_once(timeout_ms=250)
            if self.device_id is not None:
                return
        raise QuickKeysError(
            "no Quick Keys surface paired/awake on the wireless dongle"
        )

    def set_key_text(self, key_index: int, text: str) -> None:
        """Set the label of one of the 8 text keys (up to 8 characters)."""
        self._wait_for_device_id()
        self._write(protocol.set_key_text_report(key_index, text, self.device_id))

    def set_wheel_color(self, r: int, g: int, b: int) -> None:
        """Set the wheel ring RGB color."""
        self._wait_for_device_id()
        self._write(protocol.set_wheel_color_report(r, g, b, self.device_id))

    def set_brightness(self, brightness: int) -> None:
        """Set display backlight: 0=off, 1=low, 2=medium, 3=full."""
        self._wait_for_device_id()
        self._write(protocol.set_display_brightness_report(brightness, self.device_id))

    def set_sleep_timeout(self, minutes: int) -> None:
        """Set the device sleep timeout in minutes (0-255)."""
        self._wait_for_device_id()
        self._write(protocol.set_sleep_timeout_report(minutes, self.device_id))

    def set_wheel_speed(self, speed: int) -> None:
        """Set wheel sensitivity (1=fastest .. 5=slowest)."""
        self._wait_for_device_id()
        self._write(protocol.set_wheel_speed_report(speed, self.device_id))

    def set_display_orientation(self, orientation: int) -> None:
        """Rotate the text display (1=0deg, 2=90, 3=180, 4=270)."""
        self._wait_for_device_id()
        self._write(protocol.set_display_orientation_report(orientation, self.device_id))

    def show_overlay_text(self, duration: int, text: str) -> None:
        """Show up to 32 chars across the display for ``duration`` seconds."""
        self._wait_for_device_id()
        for report in protocol.show_overlay_text_reports(duration, text, self.device_id):
            self._write(report)

    # -- input ---------------------------------------------------------------

    def _poll_once(self, timeout_ms: int = 500) -> list[dict[str, Any]]:
        """Read and parse one HID report; returns zero or more event dicts."""
        data = self._handle.read(64, timeout_ms)
        if not data:
            return []
        buf = bytes(data)
        if buf[0] != protocol.REPORT_ID:
            return []
        payload = buf[1:]
        parsed = protocol.parse_input_payload(payload)
        if parsed is None:
            return []

        events: list[dict[str, Any]] = []
        kind = parsed["kind"]
        if kind == "status":
            # Dongle told us about a surface (state 2/3 = connected, 4 = lost).
            state = parsed["state"]
            if state in (2, 3):
                new = parsed["device_id"] != self.device_id or not self._subscribed
                self.device_id = parsed["device_id"]
                if new:
                    self._subscribe()
                    events.append(
                        {"type": "connected", "device_id": self.device_id}
                    )
            elif state == 4:
                events.append({"type": "disconnected", "device_id": parsed["device_id"]})
        elif kind == "keys":
            for key, down in protocol.key_events_from_masks(self._key_mask, parsed["mask"]):
                events.append({"type": "key", "key": key, "down": down})
            self._key_mask = parsed["mask"]
        elif kind == "wheel":
            events.append({"type": "wheel", "direction": parsed["direction"]})
        elif kind == "battery":
            events.append({"type": "battery", "percent": parsed["percent"]})
        return events

    def poll_events(self, timeout_ms: int = 500) -> list[dict[str, Any]]:
        """Read one HID report (or time out) and return parsed events.

        Unlike :meth:`read_events` this returns after at most ``timeout_ms``
        even when nothing happened, so callers can interleave other work.
        """
        try:
            return self._poll_once(timeout_ms=timeout_ms)
        except (OSError, ValueError, IOError) as exc:
            raise QuickKeysError(f"device read failed: {exc}") from exc

    def read_events(self, timeout_ms: int = 500) -> Iterator[dict[str, Any]]:
        """Yield event dicts forever.

        Shapes:
          {"type": "key", "key": 0-9, "down": bool}
          {"type": "wheel", "direction": "cw" | "ccw"}
          {"type": "battery", "percent": 0-100}
          {"type": "connected" | "disconnected", "device_id": str}  (wireless)
        """
        while True:
            try:
                events = self._poll_once(timeout_ms=timeout_ms)
            except (OSError, ValueError, IOError) as exc:
                raise QuickKeysError(f"device read failed: {exc}") from exc
            yield from events
