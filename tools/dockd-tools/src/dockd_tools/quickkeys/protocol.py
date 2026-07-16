"""Xencelabs Quick Keys USB HID protocol — pure byte building/parsing, no I/O.

Ported from https://github.com/Julusian/node-xencelabs-quick-keys
(packages/core/src/device.ts, wireless-device.ts, ids.ts and
packages/node/src/manager.ts). Every byte layout below mirrors the
TypeScript source; nothing here is invented.

Conventions
-----------
* Output reports are 32 bytes long *including* the leading report id
  ``0x02``.  This is the exact buffer node-hid ``write()`` receives, and it
  is what should be passed to hidapi's ``device.write()``.
* Input reports arrive with the report id as the first byte when read via
  hidapi.  The parse helpers in this module take the *payload* — the bytes
  **after** the report id — so their offsets match the node source
  one-to-one (node strips the report id before ``handleData``).
* Wireless devices behind the dongle are addressed by a 6-byte device id
  (12 hex chars) written at offset 10 of every output report.
"""

from __future__ import annotations

from enum import IntEnum

# --- Identifiers (packages/core/src/ids.ts, packages/node/src/manager.ts,
# --- packages/webhid/src/manager.ts) ---------------------------------------

VENDOR_ID = 0x28BD
PRODUCT_IDS_WIRED = (0x5202,)
PRODUCT_IDS_WIRELESS = (0x5203,)  # the USB dongle
PRODUCT_IDS = PRODUCT_IDS_WIRED + PRODUCT_IDS_WIRELESS

#: USB interface number carrying the vendor protocol (node manager.ts).
DEVICE_INTERFACE = 2
#: WebHID equivalent filter (webhid manager.ts): usagePage 0xFF0A, usage 0x01.
USAGE_PAGE = 0xFF0A
USAGE = 0x01

REPORT_ID = 0x02
REPORT_LENGTH = 32  # including the report id byte

KEY_COUNT = 10  # 8 text keys + 2 extra buttons (bits 8/9 of the key bitmask)
TEXT_KEY_COUNT = 8
MAX_TEXT_CHARS = 8
MAX_OVERLAY_CHARS = 32

#: Offset (within the full 32-byte report) of the 6-byte wireless device id.
DEVICE_ID_OFFSET = 10


class DisplayOrientation(IntEnum):
    ROTATE_0 = 1
    ROTATE_90 = 2
    ROTATE_180 = 3
    ROTATE_270 = 4


class DisplayBrightness(IntEnum):
    OFF = 0
    LOW = 1
    MEDIUM = 2
    FULL = 3


class WheelSpeed(IntEnum):
    SLOWEST = 5
    SLOWER = 4
    NORMAL = 3
    FASTER = 2
    FASTEST = 1


# --- Report builders --------------------------------------------------------


def _new_report() -> bytearray:
    buf = bytearray(REPORT_LENGTH)
    buf[0] = REPORT_ID
    return buf


def _insert_device_id(buf: bytearray, device_id: str | None) -> None:
    """Write the wireless device id (12 hex chars) at offset 10.

    Mirrors ``insertDeviceId`` / ``WirelessSubHIDDevice.sendReports``:
    ``buffer.write(deviceId, 10, 6, 'hex')``.  No-op for wired devices.
    """
    if not device_id:
        return
    raw = bytes.fromhex(device_id)
    if len(raw) != 6:
        raise ValueError("device_id must be 12 hex characters (6 bytes)")
    buf[DEVICE_ID_OFFSET : DEVICE_ID_OFFSET + 6] = raw


def subscribe_keys_report(device_id: str | None = None) -> bytes:
    """Report enabling key/wheel event streaming (subscribeToEventStreams)."""
    buf = _new_report()
    buf[1] = 0xB0
    buf[2] = 0x04
    _insert_device_id(buf, device_id)
    return bytes(buf)


def subscribe_battery_report(device_id: str | None = None) -> bytes:
    """Report enabling battery level events (subscribeToEventStreams)."""
    buf = _new_report()
    buf[1] = 0xB4
    buf[2] = 0x10
    _insert_device_id(buf, device_id)
    return bytes(buf)


def wireless_discover_report() -> bytes:
    """Dongle report asking for already-connected surfaces (wireless-device.ts)."""
    buf = _new_report()
    buf[1] = 0xB8
    buf[2] = 0x01
    return bytes(buf)


def set_key_text_report(key_index: int, text: str, device_id: str | None = None) -> bytes:
    """Set the 8-char label of one of the 8 text keys.

    Layout (device.ts setKeyText): [1]=0xB1, [3]=key+1, [5]=len(text)*2,
    UTF-16LE text at offset 16.
    """
    if not 0 <= key_index < TEXT_KEY_COUNT:
        raise ValueError(f"key_index must be 0 - {TEXT_KEY_COUNT - 1}")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"text must be at most {MAX_TEXT_CHARS} characters")

    encoded = text.encode("utf-16-le")
    buf = _new_report()
    buf[1] = 0xB1
    buf[3] = key_index + 1
    buf[5] = len(text) * 2
    _insert_device_id(buf, device_id)
    buf[16 : 16 + len(encoded)] = encoded
    return bytes(buf)


def set_wheel_color_report(r: int, g: int, b: int, device_id: str | None = None) -> bytes:
    """Set the wheel ring RGB color.

    Layout (device.ts setWheelColor): [1]=0xB4, [2]=0x01, [3]=0x01,
    [6]=r, [7]=g, [8]=b.
    """
    for value in (r, g, b):
        if not 0 <= value <= 255:
            raise ValueError("RGB values must be 0 - 255")
    buf = _new_report()
    buf[1] = 0xB4
    buf[2] = 0x01
    buf[3] = 0x01
    buf[6] = r
    buf[7] = g
    buf[8] = b
    _insert_device_id(buf, device_id)
    return bytes(buf)


def set_display_orientation_report(
    orientation: DisplayOrientation | int, device_id: str | None = None
) -> bytes:
    """Rotate the text labels. Layout: [1]=0xB1, [2]=orientation (1-4)."""
    orientation = DisplayOrientation(orientation)
    buf = _new_report()
    buf[1] = 0xB1
    buf[2] = int(orientation)
    _insert_device_id(buf, device_id)
    return bytes(buf)


def set_display_brightness_report(
    brightness: DisplayBrightness | int, device_id: str | None = None
) -> bytes:
    """Set display backlight. Layout: [1]=0xB1, [2]=0x0A, [3]=0x01, [4]=level (0-3)."""
    brightness = DisplayBrightness(brightness)
    buf = _new_report()
    buf[1] = 0xB1
    buf[2] = 0x0A
    buf[3] = 0x01
    buf[4] = int(brightness)
    _insert_device_id(buf, device_id)
    return bytes(buf)


def set_wheel_speed_report(speed: WheelSpeed | int, device_id: str | None = None) -> bytes:
    """Set wheel sensitivity. Layout: [1]=0xB4, [2]=0x04, [3]=0x01, [4]=0x01, [5]=speed."""
    speed = WheelSpeed(speed)
    buf = _new_report()
    buf[1] = 0xB4
    buf[2] = 0x04
    buf[3] = 0x01
    buf[4] = 0x01
    buf[5] = int(speed)
    _insert_device_id(buf, device_id)
    return bytes(buf)


def set_sleep_timeout_report(minutes: int, device_id: str | None = None) -> bytes:
    """Set the sleep timeout in minutes. Layout: [1]=0xB4, [2]=0x08, [3]=0x01, [4]=minutes."""
    if not 0 <= minutes <= 255:
        raise ValueError("minutes must be 0 - 255")
    buf = _new_report()
    buf[1] = 0xB4
    buf[2] = 0x08
    buf[3] = 0x01
    buf[4] = minutes
    _insert_device_id(buf, device_id)
    return bytes(buf)


def _overlay_chunk(
    special_byte: int, duration: int, chars: str, has_more: bool, device_id: str | None
) -> bytes:
    buf = _new_report()
    buf[1] = 0xB1
    buf[2] = special_byte
    buf[3] = duration
    buf[5] = len(chars) * 2
    buf[6] = 0x01 if has_more else 0x00
    _insert_device_id(buf, device_id)
    encoded = chars.encode("utf-16-le")
    buf[16 : 16 + len(encoded)] = encoded
    return bytes(buf)


def show_overlay_text_reports(
    duration: int, text: str, device_id: str | None = None
) -> list[bytes]:
    """Show up to 32 chars across the whole display for ``duration`` seconds.

    Sent as 8-char chunks: first chunk uses special byte 0x05, subsequent
    chunks 0x06, byte 6 flags whether more chunks follow (device.ts
    showOverlayText / createOverlayChunk).
    """
    if not 0 < duration <= 255:
        raise ValueError("duration must be 1 - 255 seconds")
    if len(text) > MAX_OVERLAY_CHARS:
        raise ValueError(f"text must be at most {MAX_OVERLAY_CHARS} characters")

    reports = [
        _overlay_chunk(0x05, duration, text[0:8], False, device_id),
        _overlay_chunk(0x06, duration, text[8:16], len(text) > 16, device_id),
    ]
    for offset in range(16, len(text), 8):
        reports.append(
            _overlay_chunk(
                0x06, duration, text[offset : offset + 8], len(text) > offset + 8, device_id
            )
        )
    return reports


# --- Input report parsing ---------------------------------------------------
#
# Offsets below are into the payload *after* the 0x02 report id byte,
# matching XencelabsQuickKeysDevice.handleData / the dongle data handler.


def parse_input_payload(payload: bytes) -> dict | None:
    """Parse one input-report payload (report id already stripped).

    Returns one of:
      {"kind": "keys", "mask": int}                       key bitmask snapshot
      {"kind": "wheel", "direction": "cw" | "ccw"}        wheel rotation
      {"kind": "battery", "percent": int}                 battery level
      {"kind": "status", "device_id": str, "state": int}  dongle connect status
    or None for anything unrecognised.

    Key/wheel: payload[0] == 0xF0; payload[6] non-zero means wheel
    (bit0 = right/cw, bit1 = left/ccw), otherwise payload[1:3] is a
    little-endian bitmask of the 10 keys.
    Battery: payload[0] == 0xF2 and payload[1] == 0x01, percent at payload[2].
    Dongle status: payload[0] == 0xF8, state at payload[1]
    (2 = newly connected, 3 = already connected, 4 = lost), device id hex
    at payload[9:15].
    """
    if len(payload) < 7:
        return None

    first = payload[0]
    if first == 0xF0:
        wheel_byte = payload[6]
        if wheel_byte > 0:
            if wheel_byte & 0x01:
                return {"kind": "wheel", "direction": "cw"}
            if wheel_byte & 0x02:
                return {"kind": "wheel", "direction": "ccw"}
            return None
        mask = int.from_bytes(payload[1:3], "little")
        return {"kind": "keys", "mask": mask}

    if first == 0xF2 and payload[1] == 0x01:
        return {"kind": "battery", "percent": payload[2]}

    if first == 0xF8 and len(payload) >= 15:
        return {
            "kind": "status",
            "device_id": payload[9:15].hex(),
            "state": payload[1],
        }

    return None


def extract_wireless_device_id(payload: bytes) -> str | None:
    """Device id routing a non-status dongle packet (payload[11:17] as hex)."""
    if len(payload) < 17:
        return None
    return payload[11:17].hex()


def key_events_from_masks(previous: int, current: int) -> list[tuple[int, bool]]:
    """Diff two key bitmasks into ``(key_index, is_down)`` events."""
    events: list[tuple[int, bool]] = []
    for key in range(KEY_COUNT):
        bit = 1 << key
        was_down = bool(previous & bit)
        is_down = bool(current & bit)
        if was_down != is_down:
            events.append((key, is_down))
    return events
