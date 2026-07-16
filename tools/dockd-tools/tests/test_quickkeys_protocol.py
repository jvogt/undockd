"""Unit tests for the Quick Keys HID protocol byte layouts (no hardware).

Expected bytes mirror packages/core/src/device.ts and wireless-device.ts of
https://github.com/Julusian/node-xencelabs-quick-keys.
"""

from __future__ import annotations

import pytest

from dockd_tools.quickkeys import protocol


def report(*pairs: tuple[int, int]) -> bytes:
    """32-byte report with report id 0x02 and the given (offset, value) bytes."""
    buf = bytearray(protocol.REPORT_LENGTH)
    buf[0] = 0x02
    for offset, value in pairs:
        buf[offset] = value
    return bytes(buf)


# --- constants ---------------------------------------------------------------


def test_ids():
    assert protocol.VENDOR_ID == 0x28BD
    assert protocol.PRODUCT_IDS_WIRED == (0x5202,)
    assert protocol.PRODUCT_IDS_WIRELESS == (0x5203,)
    assert protocol.DEVICE_INTERFACE == 2
    assert protocol.USAGE_PAGE == 0xFF0A


# --- output reports ----------------------------------------------------------


def test_subscribe_keys_report():
    assert protocol.subscribe_keys_report() == report((1, 0xB0), (2, 0x04))


def test_subscribe_battery_report():
    assert protocol.subscribe_battery_report() == report((1, 0xB4), (2, 0x10))


def test_wireless_discover_report():
    assert protocol.wireless_discover_report() == report((1, 0xB8), (2, 0x01))


def test_set_key_text_report():
    buf = protocol.set_key_text_report(3, "AB")
    expected = bytearray(report((1, 0xB1), (3, 0x04), (5, 0x04)))
    expected[16:20] = "AB".encode("utf-16-le")
    assert buf == bytes(expected)
    assert len(buf) == 32


def test_set_key_text_full_length():
    buf = protocol.set_key_text_report(0, "ABCDEFGH")
    assert buf[3] == 1  # key index + 1
    assert buf[5] == 16  # 8 chars * 2 bytes
    assert buf[16:32] == "ABCDEFGH".encode("utf-16-le")


def test_set_key_text_validation():
    with pytest.raises(ValueError):
        protocol.set_key_text_report(8, "X")  # only 8 text keys (0-7)
    with pytest.raises(ValueError):
        protocol.set_key_text_report(-1, "X")
    with pytest.raises(ValueError):
        protocol.set_key_text_report(0, "123456789")  # 9 chars


def test_set_wheel_color_report():
    buf = protocol.set_wheel_color_report(0x11, 0x22, 0x33)
    assert buf == report((1, 0xB4), (2, 0x01), (3, 0x01), (6, 0x11), (7, 0x22), (8, 0x33))
    with pytest.raises(ValueError):
        protocol.set_wheel_color_report(256, 0, 0)
    with pytest.raises(ValueError):
        protocol.set_wheel_color_report(0, -1, 0)


def test_set_display_orientation_report():
    buf = protocol.set_display_orientation_report(protocol.DisplayOrientation.ROTATE_90)
    assert buf == report((1, 0xB1), (2, 0x02))
    with pytest.raises(ValueError):
        protocol.set_display_orientation_report(5)


def test_set_display_brightness_report():
    buf = protocol.set_display_brightness_report(protocol.DisplayBrightness.MEDIUM)
    assert buf == report((1, 0xB1), (2, 0x0A), (3, 0x01), (4, 0x02))
    with pytest.raises(ValueError):
        protocol.set_display_brightness_report(4)


def test_set_wheel_speed_report():
    buf = protocol.set_wheel_speed_report(protocol.WheelSpeed.FASTEST)
    assert buf == report((1, 0xB4), (2, 0x04), (3, 0x01), (4, 0x01), (5, 0x01))
    with pytest.raises(ValueError):
        protocol.set_wheel_speed_report(0)


def test_set_sleep_timeout_report():
    buf = protocol.set_sleep_timeout_report(15)
    assert buf == report((1, 0xB4), (2, 0x08), (3, 0x01), (4, 15))
    with pytest.raises(ValueError):
        protocol.set_sleep_timeout_report(256)


def test_device_id_insertion():
    buf = protocol.set_wheel_color_report(1, 2, 3, device_id="a1b2c3d4e5f6")
    assert buf[10:16] == bytes.fromhex("a1b2c3d4e5f6")
    # wired reports leave those bytes zeroed
    assert protocol.set_wheel_color_report(1, 2, 3)[10:16] == bytes(6)
    with pytest.raises(ValueError):
        protocol.set_wheel_color_report(1, 2, 3, device_id="abcd")


def test_overlay_text_reports_short():
    reports = protocol.show_overlay_text_reports(5, "HI")
    assert len(reports) == 2  # always at least two chunks (0x05 then 0x06)
    first, second = reports
    assert first[1] == 0xB1 and first[2] == 0x05
    assert first[3] == 5  # duration
    assert first[5] == 4  # 2 chars * 2
    assert first[6] == 0x00  # no more
    assert first[16:20] == "HI".encode("utf-16-le")
    assert second[2] == 0x06
    assert second[5] == 0  # empty chunk
    assert second[6] == 0x00


def test_overlay_text_reports_long():
    text = "ABCDEFGHIJKLMNOPQRSTUVWX"  # 24 chars -> 3 chunks
    reports = protocol.show_overlay_text_reports(3, text)
    assert len(reports) == 3
    assert reports[0][2] == 0x05
    assert reports[0][6] == 0x00
    assert reports[1][2] == 0x06
    assert reports[1][6] == 0x01  # more follows (len > 16)
    assert reports[2][6] == 0x00  # last chunk
    assert reports[0][16:32] == text[0:8].encode("utf-16-le")
    assert reports[1][16:32] == text[8:16].encode("utf-16-le")
    assert reports[2][16:32] == text[16:24].encode("utf-16-le")


def test_overlay_text_validation():
    with pytest.raises(ValueError):
        protocol.show_overlay_text_reports(0, "X")
    with pytest.raises(ValueError):
        protocol.show_overlay_text_reports(5, "X" * 33)


# --- input parsing -----------------------------------------------------------


def payload(*pairs: tuple[int, int], length: int = 31) -> bytes:
    buf = bytearray(length)
    for offset, value in pairs:
        buf[offset] = value
    return bytes(buf)


def test_parse_key_mask():
    # keys 0 and 9 pressed -> mask 0x0201 little-endian at payload[1:3]
    ev = protocol.parse_input_payload(payload((0, 0xF0), (1, 0x01), (2, 0x02)))
    assert ev == {"kind": "keys", "mask": 0x0201}


def test_parse_key_release_all():
    ev = protocol.parse_input_payload(payload((0, 0xF0)))
    assert ev == {"kind": "keys", "mask": 0}


def test_parse_wheel():
    cw = protocol.parse_input_payload(payload((0, 0xF0), (6, 0x01)))
    assert cw == {"kind": "wheel", "direction": "cw"}
    ccw = protocol.parse_input_payload(payload((0, 0xF0), (6, 0x02)))
    assert ccw == {"kind": "wheel", "direction": "ccw"}


def test_parse_battery():
    ev = protocol.parse_input_payload(payload((0, 0xF2), (1, 0x01), (2, 80)))
    assert ev == {"kind": "battery", "percent": 80}


def test_parse_dongle_status():
    buf = bytearray(31)
    buf[0] = 0xF8
    buf[1] = 3  # already connected
    buf[9:15] = bytes.fromhex("a1b2c3d4e5f6")
    ev = protocol.parse_input_payload(bytes(buf))
    assert ev == {"kind": "status", "device_id": "a1b2c3d4e5f6", "state": 3}


def test_parse_unknown():
    assert protocol.parse_input_payload(payload((0, 0x42))) is None
    assert protocol.parse_input_payload(b"\xf0") is None  # too short


def test_extract_wireless_device_id():
    buf = bytearray(31)
    buf[11:17] = bytes.fromhex("0102030405ff")
    assert protocol.extract_wireless_device_id(bytes(buf)) == "0102030405ff"
    assert protocol.extract_wireless_device_id(b"\x00" * 5) is None


def test_key_events_from_masks():
    assert protocol.key_events_from_masks(0b0000, 0b0101) == [(0, True), (2, True)]
    assert protocol.key_events_from_masks(0b0101, 0b0100) == [(0, False)]
    assert protocol.key_events_from_masks(0b0101, 0b0101) == []
    # key 9 (highest bit of the 10-key mask)
    assert protocol.key_events_from_masks(0, 1 << 9) == [(9, True)]
