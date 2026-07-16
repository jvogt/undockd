import json

from dockd_tools import config as cfg


def test_defaults_when_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCKD_CONFIG", str(tmp_path / "nope.json"))
    config = cfg.load()
    assert config["obs"]["port"] == 4455
    assert cfg.get(config, "obs.scene_collections.docked") == "Docked"


def test_user_overrides_merge_deeply(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"obs": {"port": 4444}, "dock": {"match": "CalDigit"}}))
    monkeypatch.setenv("DOCKD_CONFIG", str(path))
    config = cfg.load()
    assert config["obs"]["port"] == 4444
    assert config["obs"]["host"] == "127.0.0.1"  # default preserved
    assert cfg.get(config, "dock.match") == "CalDigit"
    assert cfg.get(config, "onair.home_assistant.scenes.muted") == "scene.zoom_muted"


def test_get_missing_returns_default():
    assert cfg.get({}, "a.b.c", 42) == 42
