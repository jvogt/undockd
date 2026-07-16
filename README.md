# Dockd — macOS menubar app for conferencing automations

Menubar app that manages active input/output devices (mic, camera, speakers,
AirPods) and runs teleconferencing automations around OBS, Zoom / Google
Meet, a Home Assistant on-air light, and a Xencelabs Quick Keys pad.

## Architecture

Two layers:

- **`tools/dockd-tools/`** — a single uv-managed Python package providing
  small, shell-scriptable CLIs (`dockd-obs`, `dockd-audio`, `dockd-dock`,
  `dockd-idle`, `dockd-meeting`, `dockd-onair`, `dockd-virtualcam-sleep`,
  `dockd-quickkeys`). Status commands print one JSON object to stdout; logs
  go to stderr and `~/Library/Logs/dockd/*.jsonl`. OBS is driven over
  obs-websocket via `obsws-python` (no more `obs-cli`).
- **`app/`** — the Swift (AppKit/SwiftUI) menubar app. It polls the CLIs for
  state, applies the docked/undocked automations, supervises the two Python
  daemons (restart with backoff), forwards their stderr into the macOS
  unified log (subsystem `com.jvogt.dockd`), and renders the status icon and
  menu.

Both layers share one JSON config:
`~/Library/Application Support/dockd/config.json` (override with the
`DOCKD_CONFIG` env var). Defaults live in
`tools/dockd-tools/src/dockd_tools/config.py`; the file only needs the keys
you want to override. **The Home Assistant token lives only in this local
file — never in the repo.**

## Quick start

```bash
# 1. Python tools
cd tools/dockd-tools
uv sync
uv run dockd-obs status          # sanity check against a running OBS

# 2. Menubar app
cd ../../app
scripts/bundle.sh                # builds app/dist/Dockd.app
open dist/Dockd.app              # or: scripts/bundle.sh --install
```

On first run, grant the permission prompts (Automation → System Events and
Google Chrome for mute detection, Bluetooth for AirPods control). For Google
Meet mute state, enable Chrome's View → Developer → *Allow JavaScript from
Apple Events*.

## Behavior

- **Docked** (the configured Thunderbolt hub is present): the OBS scene
  collection is set to the mapped "Docked" collection, the on-air watcher
  runs.
- **Undocked**: OBS scene collection set to the mapped "Undocked"
  collection, on-air watcher stopped.
- **If OBS should be running but isn't, it is started** (`dockd-obs
  ensure-running`).
- **virtualcam-sleep** (always on): stops the OBS virtual camera when the
  system has been idle longer than the screensaver timeout (minus a margin),
  restarts it on activity, and never stops it during an active meeting.
- **on-air** (while docked): watches Zoom / Google Meet mute state and
  switches Home Assistant scenes (`unmuted` / `muted` / `unknown`); also
  drives the Quick Keys pad. On connect every key label is cleared, then:
  - key 0 — "Muted"/"Unmuted" while in a meeting (blank otherwise);
    pressing toggles the meeting mute, and muting inside Zoom/Meet updates
    the key within ~0.5s.
  - key 1 — "Out: <label>" for the current output; pressing cycles through
    the `audio.output_cycle` allow-list (configured in Settings, with short
    custom labels). Fewer than two present choices flashes
    "No Output Choices". AirPods in the list are included when available
    but disconnected — selecting them connects them.
  - key 2 — "In: <label>" for the current input; cycles
    `audio.input_cycle`; flashes "No Input Choices" when there is nothing
    to switch to.
  - key 3 — the current OBS scene collection name ("Docked"/"Undocked";
    the key text is limited to 8 characters, so no "OBS:" prefix); pressing
    flips between the docked/undocked mapped scene collections. Shows
    "No OBS" when OBS is unreachable.

  When the on-air watcher stops (e.g. on undock), all key labels and the
  wheel ring are cleared so the pad goes dark.

  Switching output to AirPods pins the default *input* device so macOS
  can't hijack it onto the AirPods mic (`audio.keep_input`). The wheel ring
  mirrors on-air state (red = on air, green = muted, dim blue = idle).

### Menubar icon

| State | Icon |
| --- | --- |
| AirPods active output *and* input | AirPods + mic badge |
| AirPods active output | AirPods |
| AirPods available, output elsewhere | speaker |
| No AirPods available | dim speaker |
| On air | red dot overlay |

Left click: toggle AirPods as output (connects them first if needed); when
no AirPods are available (dim speaker) it opens the menu instead. Right
click: menu with status lines (docked, AirPods, on air, virtual camera,
daemon health), virtual-camera and AirPods toggles, and Settings.

### Settings

OBS scene-collection dropdowns for the Docked/Undocked slots (fetched live
from OBS),
dock-detection match string, Home Assistant URL/token, the Quick Keys
output/input cycle lists (device picker + short custom label per entry —
the pad fits ~5 characters after the "Out:"/"In:" prefix), tools location,
and an "Open Logs in Console" button. Saving restarts the daemons so
changes apply immediately. Logs are also queryable with:

```bash
log stream --predicate 'subsystem == "com.jvogt.dockd"' --info
```

## Design decisions (previously open questions)

- **Python for all tools, Swift only for the menubar app.** Each tool is
  independently shell-scriptable; the app is a thin orchestrator.
- **Settings** cover the OBS scene-collection mapping, dock match string, HA
  URL/token, and tools path; everything else is config-file-only
  (`config.py` documents all keys).
- **Menubar icon** shows the active-output state (AirPods vs speaker) rather
  than docked state, per the README's original instinct; docked state is a
  menu status line.
- **Dock detection**: presence of a Thunderbolt device whose name matches
  `dock.match` (default "Thunderbolt 5 Hub") in
  `system_profiler SPThunderboltDataType`.
- **Xencelabs Quick Keys** stayed in Python: the HID protocol was ported
  from [node-xencelabs-quick-keys](https://github.com/Julusian/node-xencelabs-quick-keys)
  onto `hidapi` (see `dockd_tools/quickkeys/`).

## Assumptions (unchanged)

- Zoom and Google Meet always use the system default mic/speaker; we control
  the system defaults.
- OBS is always started when in use; when used, the virtual camera is used;
  Zoom/Meet always consume the virtual camera.

## Development

```bash
cd tools/dockd-tools && uv run --group dev pytest   # unit tests
cd app && swift build                               # compile the app
```

See [TODO.md](TODO.md) for open items and testing blockers.
