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
