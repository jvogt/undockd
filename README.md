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

- **Docked** (the configured Thunderbolt hub is present): OBS profile is set
  to the mapped "Docked" profile, the on-air watcher runs.
- **Undocked**: OBS profile set to the mapped "Undocked" profile, on-air
  watcher stopped.
- **If OBS should be running but isn't, it is started** (`dockd-obs
  ensure-running`).
- **virtualcam-sleep** (always on): stops the OBS virtual camera when the
  system has been idle longer than the screensaver timeout (minus a margin),
  restarts it on activity, and never stops it during an active meeting.
- **on-air** (while docked): watches Zoom / Google Meet mute state and
  switches Home Assistant scenes (`unmuted` / `muted` / `unknown`); also
  drives the Quick Keys pad: on connect every key label is cleared, then
  key 0 shows "Muted"/"Unmuted" while in a meeting (blank otherwise) and
  toggles the meeting mute; key 1 shows "Out: Sys"/"Out:Pods" and toggles
  the system output to AirPods (briefly overlaying "No AirPods" when none
  are available). Switching to AirPods pins the default *input* device so
  macOS can't hijack it onto the AirPods mic (`audio.keep_input`). The
  wheel ring mirrors on-air state (red = on air, green = muted,
  dim blue = idle).

### Menubar icon

| State | Icon |
| --- | --- |
| AirPods available, not active output | dimmed/outline AirPods |
| AirPods active output | solid AirPods |
| AirPods active output *and* input | AirPods + mic badge |
| No AirPods available | speaker |
| On air | red dot overlay |

Left click: toggle AirPods as output (connects them first if needed); opens
the menu instead when no AirPods are available. Right click: menu with
status lines (docked, AirPods, on air, virtual camera, daemon health),
virtual-camera and AirPods toggles, and Settings.

### Settings

OBS profile dropdowns for the Docked/Undocked slots (fetched live from OBS),
dock-detection match string, Home Assistant URL/token, tools location, and an
"Open Logs in Console" button. Logs are also queryable with:

```bash
log stream --predicate 'subsystem == "com.jvogt.dockd"' --info
```

## Design decisions (previously open questions)

- **Python for all tools, Swift only for the menubar app.** Each tool is
  independently shell-scriptable; the app is a thin orchestrator.
- **Settings** cover the OBS profile mapping, dock match string, HA
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
