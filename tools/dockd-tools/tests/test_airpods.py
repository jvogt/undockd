import pytest

from dockd_tools import airpods, bluetooth
from dockd_tools.bluetooth import BluetoothUnavailable


def test_ioreturn_timeout_is_human_readable():
    # kIOReturnTimeout — the code seen when AirPods are bonded to a phone.
    text = bluetooth._ioreturn_text(-536870186)
    assert "no response" in text
    assert "IOReturn" not in text  # mapped, not the raw code


def test_ioreturn_unknown_falls_back_to_code():
    assert bluetooth._ioreturn_text(0x12345678) == "IOReturn 305419896"


def test_connect_failure_points_at_the_sound_menu(monkeypatch):
    monkeypatch.setattr(
        airpods,
        "paired_airpods",
        lambda match: {"name": "AirPods", "address": "aa", "connected": False},
    )

    def boom(address, *a, **k):
        raise BluetoothUnavailable("no response — it may be connected to another device")

    monkeypatch.setattr(airpods.bluetooth, "connect", boom)

    with pytest.raises(BluetoothUnavailable) as exc:
        airpods.connect("AirPods")
    assert "macOS Sound menu" in str(exc.value)


def test_activate_surfaces_connect_failure(monkeypatch):
    # AirPods not present as an audio device (phone grabbed them) → connect,
    # which fails → activate raises the guidance, never touching the default.
    monkeypatch.setattr(airpods, "_audio_device", lambda match, direction: None)
    monkeypatch.setattr(
        airpods,
        "paired_airpods",
        lambda match: {"name": "AirPods", "address": "aa", "connected": False},
    )
    monkeypatch.setattr(
        airpods.bluetooth,
        "connect",
        lambda *a, **k: (_ for _ in ()).throw(BluetoothUnavailable("no response")),
    )
    called = []
    monkeypatch.setattr(airpods.coreaudio, "set_default", lambda *a: called.append(a))
    monkeypatch.setattr(airpods.coreaudio, "get_default", lambda direction: None)

    with pytest.raises(BluetoothUnavailable):
        airpods.activate("AirPods")
    assert called == []  # current output left untouched


def test_bluetooth_unavailable_is_reexported():
    # cli/audio.py and callers catch airpods.BluetoothUnavailable.
    assert airpods.BluetoothUnavailable is BluetoothUnavailable


def test_paired_airpods_matches_by_name_substring(monkeypatch):
    monkeypatch.setattr(
        airpods.bluetooth,
        "paired_devices",
        lambda: [
            {"name": "Magic Keyboard", "address": "aa", "connected": False},
            {"name": "Jeff's AirPods Pro", "address": "bb", "connected": True},
        ],
    )
    match = airpods.paired_airpods("AirPods")
    assert match is not None
    assert match["address"] == "bb"
    assert match["connected"] is True


def test_paired_airpods_returns_none_when_no_match(monkeypatch):
    monkeypatch.setattr(
        airpods.bluetooth,
        "paired_devices",
        lambda: [{"name": "Magic Mouse", "address": "cc", "connected": True}],
    )
    assert airpods.paired_airpods("AirPods") is None


def test_status_degrades_when_bluetooth_unreadable(monkeypatch):
    def boom():
        raise BluetoothUnavailable("permission denied")

    monkeypatch.setattr(airpods.bluetooth, "paired_devices", boom)
    # No AirPods present as audio devices either.
    monkeypatch.setattr(airpods, "_audio_device", lambda match, direction: None)

    result = airpods.status("AirPods")
    assert result["available"] is None  # unknown, not False
    assert result["connected"] is False
    assert result["bluetooth_error"] == "permission denied"


def test_status_fast_skips_bluetooth(monkeypatch):
    def boom():  # would raise if called
        raise AssertionError("bluetooth must not be queried in fast mode")

    monkeypatch.setattr(airpods.bluetooth, "paired_devices", boom)
    monkeypatch.setattr(airpods, "_audio_device", lambda match, direction: None)

    result = airpods.status("AirPods", include_bluetooth=False)
    assert result["available"] is None
    assert result["bluetooth_error"] is None
