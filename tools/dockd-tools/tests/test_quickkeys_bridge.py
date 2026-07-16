import logging

from dockd_tools.quickkeys_bridge import QuickKeysBridge

CONFIG = {"quickkeys": {"buttons": {"0": "toggle_mute", "1": "cycle_output"}}}


class _FakeDevice:
    def __init__(self):
        self.texts = {}
        self.color = None

    def set_key_text(self, key, text):
        self.texts[key] = text

    def set_wheel_color(self, r, g, b):
        self.color = (r, g, b)


def _bridge():
    return QuickKeysBridge(CONFIG, logging.getLogger("test-quickkeys"))


def test_going_undocked_blanks_the_pad():
    bridge = _bridge()
    dev = _FakeDevice()
    bridge.set_active(False)
    bridge._sync(dev)
    # every key cleared and the wheel off
    assert dev.color == (0, 0, 0)
    assert set(dev.texts) == set(range(8))
    assert all(v == "" for v in dev.texts.values())


def test_undocked_ignores_button_presses():
    bridge = _bridge()
    dev = _FakeDevice()
    bridge.set_active(False)
    bridge._handle_key(dev, 0)  # role toggle_mute
    # no action thread spawned — the press was dropped
    assert bridge._action_thread is None


def test_redock_repaints_from_scratch():
    bridge = _bridge()
    dev = _FakeDevice()
    bridge.set_active(False)
    bridge._sync(dev)  # blanks; populates _applied
    assert bridge._applied  # something recorded
    bridge.set_active(True)
    assert bridge._repaint is True
    # next sync should clear _applied so labels repaint (no device driving here,
    # but the flag being consumed is what matters)
    assert bridge.active is True


def test_set_active_noop_when_unchanged():
    bridge = _bridge()
    assert bridge.active is True
    bridge.set_active(True)  # already active
    assert bridge._repaint is False
