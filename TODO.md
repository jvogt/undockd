# TODO

## ⚠️ Security — do this first

- [ ] **Revoke the Home Assistant long-lived token that was committed to git.**
  The old `tools/environment/on-air/zoom-ha-link.app` Automator workflow
  (initial commit `c59d7e6`) embeds a bearer token for `http://10.0.0.75:8123`.
  The file is deleted now, but the token remains in git history. Revoke it in
  HA (user profile → Long-lived access tokens), create a new one, and put it
  in `~/Library/Application Support/dockd/config.json` under
  `onair.home_assistant.token`. (Your current local config still uses the old
  token so the light keeps working until you rotate it.)

## Testing blockers (needs hardware/permissions/situations I couldn't produce)

- [ ] **Bluetooth permission**: `blueutil` aborted in my shell (no Bluetooth
  TCC permission), so `dockd-audio airpods connect/activate/toggle` and the
  "available but not connected" state are untested. Launch Dockd.app, click
  the menubar icon with AirPods nearby, and accept the Bluetooth prompt.
- [ ] **AirPods icon states**: no AirPods were connected during development;
  verify the outline → solid → mic-badge transitions and left-click toggle.
- [ ] **Zoom mute detection + toggle**: needs a real Zoom meeting and the
  Automation (System Events) permission. Menu item names ("Mute audio" /
  "Unmute audio") may differ by Zoom version/locale — check
  `dockd-meeting status` during a meeting.
- [ ] **Google Meet mute detection**: needs Chrome with View → Developer →
  "Allow JavaScript from Apple Events" enabled, and a live meeting.
- [ ] **On-air light scenes**: `scene.zoom_unknown` fired successfully during
  development, but `zoom_muted` / `zoom_unmuted` weren't observed on the
  physical light (no meeting). Also verify the light resets when undocking.
- [ ] **Undock transition**: I never unplugged the hub. Unplug/replug and
  confirm: profile switches to Undocked, on-air watcher stops, and back.
- [ ] **Quick Keys key/wheel events**: `set-color`, `set-text`, battery, and
  connect events verified live against the wireless dongle; physical key
  presses and wheel turns were not (nobody to press them). With the on-air
  daemon running: key 0 should show Muted/Unmuted in a meeting (blank
  otherwise) and toggle mute; key 1 should show "Out: Sys"/"Out:Pods" and
  toggle output. Also unknown: which bitmask bit (8 or 9) is the wheel
  click, and the wired (PID 0x5202) code path.
- [ ] **Quick Keys display details**: verify that setting an empty label
  actually blanks a key (used to clear all keys on connect) and that the
  temporary "No AirPods" overlay renders; if empty text doesn't clear, try
  a single space.
- [ ] **Input pinning**: with AirPods, activate them as output and confirm
  the default input stays on the previous mic (`audio.keep_input`, watches
  for the macOS input hijack for ~4s after the switch).

## Follow-ups / nice-to-haves

- [ ] Launch Dockd at login (SMAppService registration + Settings toggle).
- [ ] App icon (.icns) for Dockd.app — menubar uses SF Symbols already.
- [ ] Instant dock detection via IOKit notifications instead of ~12s polling.
- [ ] Subscribe to obs-websocket events in the daemons instead of polling.
- [ ] Settings: expose Quick Keys button mapping and wheel colors.
- [ ] Sign/notarize the app with a real Developer ID (currently ad-hoc).
