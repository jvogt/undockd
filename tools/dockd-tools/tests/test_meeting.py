from dockd_tools import meeting


def test_process_running_uses_substring_pgrep_not_exact(monkeypatch):
    calls = []

    class _Result:
        returncode = 0

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _Result()

    monkeypatch.setattr(meeting.subprocess, "run", fake_run)
    assert meeting._process_running("zoom.us") is True

    argv = calls[0]
    # Must match a substring of the full argv (the app binaries live at
    # /Applications/.../MacOS/zoom.us), so -f without -x. -xf never matches.
    assert argv[0] == "pgrep"
    assert "-f" in argv
    assert "-xf" not in argv
    assert "-x" not in argv
    assert argv[-1] == "zoom.us"


def test_process_running_false_on_nonzero(monkeypatch):
    class _Result:
        returncode = 1

    monkeypatch.setattr(meeting.subprocess, "run", lambda *a, **k: _Result())
    assert meeting._process_running("nope") is False


def test_zoom_join_screen_false_when_zoom_not_running(monkeypatch):
    monkeypatch.setattr(meeting, "_process_running", lambda pattern: False)
    assert meeting.zoom_join_screen() is False


def test_zoom_join_screen_matches_window_titles(monkeypatch):
    monkeypatch.setattr(meeting, "_process_running", lambda pattern: True)
    for names, expected in [
        ("Zoom Workplace\n", False),
        ("Zoom Workplace\nVideo Preview\n", True),
        ("Zoom Meeting\n", True),
        ("Waiting for the host to start this meeting\n", True),
        ("", False),
        (None, False),  # osascript failed / permission denied
    ]:
        monkeypatch.setattr(meeting, "_osascript", lambda script, timeout=5, _n=names: _n)
        assert meeting.zoom_join_screen() is expected, names


def test_meeting_or_joining_passes_through_active_meeting(monkeypatch):
    active = {"app": "meet", "state": "unmuted", "in_meeting": True}
    monkeypatch.setattr(meeting, "detect", lambda: active)
    monkeypatch.setattr(
        meeting, "zoom_join_screen", lambda: (_ for _ in ()).throw(AssertionError)
    )
    assert meeting.meeting_or_joining() == active


def test_meeting_or_joining_counts_zoom_join_screen(monkeypatch):
    none = {"app": None, "state": "none", "in_meeting": False}
    monkeypatch.setattr(meeting, "detect", lambda: none)
    monkeypatch.setattr(meeting, "zoom_join_screen", lambda: True)
    assert meeting.meeting_or_joining()["in_meeting"] is True

    monkeypatch.setattr(meeting, "zoom_join_screen", lambda: False)
    assert meeting.meeting_or_joining() == none
