from dockd_tools.cli import virtualcam_sleep as vcs
from dockd_tools.obs import ObsError


class FakeObs:
    def __init__(self, current, collections=("Docked", "Undocked", "Sleep")):
        self.current = current
        self.collections = list(collections)
        self.set_calls = []

    def scene_collections(self):
        return {
            "current_scene_collection": self.current,
            "scene_collections": self.collections,
        }

    def set_scene_collection(self, name):
        if name not in self.collections:
            raise ObsError(f"no such OBS scene collection: {name!r}")
        if self.current != name:
            self.set_calls.append(name)
            self.current = name


def test_enter_sleep_switches_to_configured_collection():
    obs = FakeObs(current="Docked")
    vcs.enter_sleep_collection(obs, {})
    assert obs.current == "Sleep"

    obs = FakeObs(current="Nap", collections=["Nap", "Docked"])
    vcs.enter_sleep_collection(obs, {"obs": {"scene_collections": {"sleep": "Nap"}}})
    assert obs.set_calls == []  # already there


def test_enter_sleep_tolerates_missing_collection():
    obs = FakeObs(current="Docked", collections=["Docked", "Undocked"])
    vcs.enter_sleep_collection(obs, {})  # no "Sleep" in OBS: warn, don't raise
    assert obs.current == "Docked"


def test_leave_sleep_noop_when_not_sleeping():
    obs = FakeObs(current="Docked")
    vcs.leave_sleep_collection(obs, {})
    assert obs.set_calls == []


def test_leave_sleep_restores_dock_mapped_collection(monkeypatch):
    for flag, expected in [(True, "Docked"), (None, "Docked"), (False, "Undocked")]:
        monkeypatch.setattr(vcs, "read_dock_flag", lambda _f=flag: _f)
        obs = FakeObs(current="Sleep")
        vcs.leave_sleep_collection(obs, {})
        assert obs.current == expected, flag


def test_leave_sleep_tolerates_missing_target(monkeypatch):
    monkeypatch.setattr(vcs, "read_dock_flag", lambda: True)
    obs = FakeObs(current="Sleep", collections=["Sleep", "Undocked"])
    vcs.leave_sleep_collection(obs, {})  # "Docked" missing: warn, don't raise
    assert obs.current == "Sleep"
