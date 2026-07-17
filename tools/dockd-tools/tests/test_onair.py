from dockd_tools.cli import onair


class _FakeHA:
    def __init__(self):
        self.calls = []

    def turn_on_light(self, entity, rgb):
        self.calls.append(("light_on", entity, tuple(rgb)))

    def turn_off_light(self, entity):
        self.calls.append(("light_off", entity))

    def turn_on_scene(self, entity):
        self.calls.append(("scene", entity))


LIGHT_CONFIG = {
    "onair": {"home_assistant": {"light": "light.on_air"}},
    "quickkeys": {"onair_color": [255, 0, 0], "offair_color": [0, 255, 0]},
}

SCENE_CONFIG = {
    "onair": {
        "home_assistant": {
            "light": None,
            "scenes": {
                "unmuted": "scene.zoom_unmuted",
                "muted": "scene.zoom_muted",
                "unknown": "scene.zoom_unknown",
            },
        }
    }
}


def test_light_mode_matches_quickkeys_colors():
    ha = _FakeHA()
    onair._apply(LIGHT_CONFIG, ha, "unmuted")
    onair._apply(LIGHT_CONFIG, ha, "muted")
    onair._apply(LIGHT_CONFIG, ha, "none")
    assert ha.calls == [
        ("light_on", "light.on_air", (255, 0, 0)),  # red = on air
        ("light_on", "light.on_air", (0, 255, 0)),  # green = muted
        ("light_off", "light.on_air"),              # not in a meeting → off
    ]


def test_scene_mode_used_when_no_light():
    ha = _FakeHA()
    onair._apply(SCENE_CONFIG, ha, "unmuted")
    onair._apply(SCENE_CONFIG, ha, "none")
    assert ha.calls == [
        ("scene", "scene.zoom_unmuted"),
        ("scene", "scene.zoom_unknown"),
    ]


def test_indicator_key_dedupes_off_states_in_light_mode():
    # "none" and "unknown" both mean "off" — same key, so no redundant calls.
    assert onair._indicator_key(LIGHT_CONFIG, "none") == onair._indicator_key(
        LIGHT_CONFIG, "unknown"
    )
    assert onair._indicator_key(LIGHT_CONFIG, "unmuted") != onair._indicator_key(
        LIGHT_CONFIG, "muted"
    )
