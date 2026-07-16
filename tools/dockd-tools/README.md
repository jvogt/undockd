# dockd-tools

Shell-scriptable Python CLIs backing the Dockd menubar app. One uv package,
one console script per concern. Status commands print a single JSON object
to stdout; human logs go to stderr and `~/Library/Logs/dockd/<tool>.jsonl`.

```bash
uv sync          # install into .venv for local development
uv run <tool>    # or .venv/bin/<tool>
```

For the shipped app these CLIs are frozen with PyInstaller into a
self-contained `dockd-tools.app` embedded in `Dockd.app` (see
`app/scripts/bundle.sh` and `dockd-tools.spec`) — no system Python required on
the target machine. A single `dockd` executable dispatches by argv[0] basename
(`dockd_tools/dispatch.py`).

| Tool | Purpose |
| --- | --- |
| `dockd-obs` | OBS scene collections + virtual camera over obs-websocket (`status`, `scene-collections`, `scene-collection get/set [--slot docked\|undocked]`, `virtualcam status/start/stop/toggle`, `ensure-running`). The websocket password is auto-discovered from OBS's own config when unset. |
| `dockd-audio` | Audio devices via CoreAudio ctypes (`list`, `get/set input\|output`) and AirPods via IOBluetooth (`airpods status/connect/activate/deactivate/toggle`). |
| `dockd-dock` | Docked/undocked: matches `dock.match` against Thunderbolt devices (`status`, `devices`). |
| `dockd-idle` | Seconds since last input (HIDIdleTime) + screensaver timeout. |
| `dockd-meeting` | Zoom / Google Meet meeting + mute state (`status [--watch]`, `toggle-mute`). Zoom via one System Events menu query; Meet via Chrome tab JavaScript. |
| `dockd-onair` | Daemon: mute state → Home Assistant scenes (`run`, `set <state>`, `status`). |
| `dockd-virtualcam-sleep` | Daemon: stops the OBS virtual camera when idle past the screensaver timeout, never during a meeting (`run`, `status`). |
| `dockd-quickkeys` | Xencelabs Quick Keys pad: `run` is the always-on daemon that drives the wheel/keys and handles presses (mute, audio cycle, OBS scene collection); also `status`, `list`, `watch`, `set-color`, `set-text`, `demo`. Protocol ported from node-xencelabs-quick-keys; wired + wireless dongle. |

Daemons write heartbeat files to
`~/Library/Application Support/dockd/state/<name>.json`; `<tool> status`
reports `healthy` from them (fresh timestamp + live pid), which is what the
menubar app shows as service health.

Config: `~/Library/Application Support/dockd/config.json` — see
`src/dockd_tools/config.py` for every key and its default. Notably
`onair.home_assistant.token` must be set there (never committed).

Tests: `uv run --group dev pytest`
