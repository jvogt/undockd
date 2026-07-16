import pytest

from dockd_tools import bluetooth
from dockd_tools.bluetooth import BluetoothUnavailable


class _FakeDevice:
    def __init__(self, *, timeout_result=None, plain_result=0, has_variant=True):
        self.timeout_result = timeout_result
        self.plain_result = plain_result
        self.has_variant = has_variant
        self.calls = []

    def openConnection_withPageTimeout_authenticationRequired_(self, target, slots, auth):
        if not self.has_variant:
            raise AttributeError("no such selector")
        self.calls.append(("variant", slots))
        return self.timeout_result

    def openConnection(self):
        self.calls.append(("plain", None))
        return self.plain_result


def test_open_connection_prefers_bounded_page_timeout():
    dev = _FakeDevice(timeout_result=0)
    assert bluetooth._open_connection(dev, timeout=8) == 0
    kind, slots = dev.calls[0]
    assert kind == "variant"
    # 8 s / 0.625 ms ≈ 12800 slots, clamped under 0xFFFF.
    assert 0 < slots <= 0xFFFF


def test_open_connection_falls_back_when_variant_missing():
    dev = _FakeDevice(plain_result=0, has_variant=False)
    assert bluetooth._open_connection(dev, timeout=8) == 0
    assert [c[0] for c in dev.calls] == ["plain"]


def test_connect_raises_readable_message_on_timeout(monkeypatch):
    dev = _FakeDevice(timeout_result=-536870186)  # kIOReturnTimeout

    class _FW:
        class IOBluetoothDevice:
            @staticmethod
            def deviceWithAddressString_(addr):
                return dev

    monkeypatch.setattr(bluetooth, "_require_framework", lambda: _FW)
    with pytest.raises(BluetoothUnavailable) as exc:
        bluetooth.connect("aa-bb")
    assert "no response" in str(exc.value)
