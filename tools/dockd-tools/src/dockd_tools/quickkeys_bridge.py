"""Bridge between the on-air watcher and a Xencelabs Quick Keys device.

Runs a background thread that keeps a device open (reconnecting as needed).
On connect it clears every key label, then drives exactly two keys:

- mute key (``quickkeys.buttons`` role ``toggle_mute``): shows "Muted" /
  "Unmuted" while a Zoom/Meet meeting is in session (empty otherwise);
  pressing it toggles the meeting mute. External mute changes flow back in
  via :meth:`set_meeting_state` from the on-air poll loop.
- output key (role ``toggle_airpods``): shows "Out: Sys" or "Out:Pods".
  Pressing it switches the system output to AirPods (or back). If no
  AirPods are available it briefly overlays "No AirPods" and stays on
  "Out: Sys".

The wheel ring mirrors on-air state (unmuted/muted/idle colors). Everything
is best-effort: no hardware attached simply means the bridge stays dormant.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from . import airpods, config as cfg, meeting

TEXT_MUTED = "Muted"
TEXT_UNMUTED = "Unmuted"
TEXT_MUTE_UNKNOWN = "Mute ?"
TEXT_OUT_SYS = "Out: Sys"
TEXT_OUT_PODS = "Out:Pods"  # key labels are limited to 8 characters
OVERLAY_NO_AIRPODS = "No AirPods"

AIRPODS_REFRESH_SECONDS = 5


class QuickKeysBridge:
    def __init__(self, config: dict[str, Any], log: logging.Logger):
        self.config = config
        self.log = log
        self.enabled = bool(cfg.get(config, "quickkeys.enabled", True))
        buttons = cfg.get(config, "quickkeys.buttons", {}) or {}
        # role -> key index (e.g. {"toggle_mute": 0, "toggle_airpods": 1})
        self._keys = {str(v): int(k) for k, v in buttons.items()}
        self._actions = {int(k): str(v) for k, v in buttons.items()}
        self._lock = threading.Lock()
        self._meeting: dict[str, Any] = {"app": None, "state": "none", "in_meeting": False}
        self._airpods: dict[str, Any] | None = None
        self._airpods_ts = 0.0
        self._applied: dict[Any, Any] = {}
        self._device = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._action_thread: threading.Thread | None = None

    # -- public API ----------------------------------------------------------

    def start(self) -> None:
        if not self.enabled:
            return
        self._thread = threading.Thread(target=self._run, name="quickkeys", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def set_meeting_state(self, state: dict[str, Any]) -> None:
        """Called from the on-air loop on every poll (0.5s cadence)."""
        with self._lock:
            self._meeting = dict(state)

    @property
    def connected(self) -> bool:
        return self._device is not None

    # -- worker --------------------------------------------------------------

    def _run(self) -> None:
        from .quickkeys.device import QuickKeysDevice, QuickKeysError

        while not self._stop.is_set():
            try:
                device = QuickKeysDevice.open_first()
            except QuickKeysError:
                self._device = None
                if self._stop.wait(15):
                    return
                continue

            self._device = device
            self.log.info("quickkeys connected: %s", device.info.get("product"))
            try:
                self._reset_keys(device)
                self._pump(device)
            except QuickKeysError as exc:
                self.log.warning("quickkeys disconnected: %s", exc)
            finally:
                self._device = None
                self._applied = {}
                device.close()

    def _reset_keys(self, device) -> None:
        """Clear all 8 key labels so only the keys we drive show anything."""
        for key in range(8):
            try:
                device.set_key_text(key, "")
            except Exception as exc:
                self.log.debug("could not clear key %s: %s", key, exc)
                return
        self._applied = {}

    def _pump(self, device) -> None:
        while not self._stop.is_set():
            for event in device.poll_events(timeout_ms=250):
                if event["type"] == "key" and event["down"]:
                    self._handle_key(device, event["key"])
                elif event["type"] == "connected":
                    self._reset_keys(device)
            self._refresh_airpods()
            self._sync(device)

    # -- airpods snapshot ------------------------------------------------------

    def _refresh_airpods(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._airpods_ts < AIRPODS_REFRESH_SECONDS:
            return
        self._airpods_ts = now
        match = cfg.get(self.config, "audio.airpods_match", "AirPods")
        try:
            self._airpods = airpods.status(match)
        except Exception as exc:
            self.log.debug("airpods status failed: %s", exc)
            self._airpods = None

    # -- key handling ----------------------------------------------------------

    def _handle_key(self, device, key: int) -> None:
        action = self._actions.get(key)
        if not action:
            return
        if self._action_thread and self._action_thread.is_alive():
            return  # ignore presses while an action is in flight
        if action == "toggle_mute":
            target = self._do_toggle_mute
        elif action == "toggle_airpods":
            target = lambda: self._do_toggle_airpods(device)  # noqa: E731
        else:
            self.log.warning("unknown quickkeys action: %s", action)
            return
        self.log.info("quickkeys key %s -> %s", key, action)
        self._action_thread = threading.Thread(target=target, daemon=True)
        self._action_thread.start()

    def _do_toggle_mute(self) -> None:
        with self._lock:
            in_meeting = bool(self._meeting.get("in_meeting"))
        if not in_meeting:
            self.log.info("mute key pressed but no meeting in session")
            return
        try:
            result = meeting.toggle_mute()
        except Exception as exc:
            self.log.warning("toggle_mute failed: %s", exc)
            return
        self.log.info("toggle_mute -> %s", result["state"])
        # Instant feedback; the on-air loop re-detects within 0.5s anyway.
        self.set_meeting_state(result)

    def _do_toggle_airpods(self, device) -> None:
        match = cfg.get(self.config, "audio.airpods_match", "AirPods")
        fallback = cfg.get(self.config, "audio.fallback_output")
        self._refresh_airpods(force=True)
        status = self._airpods or {}
        if not (status.get("available") or status.get("connected")):
            self.log.info("output key pressed but no AirPods available")
            try:
                device.show_overlay_text(2, OVERLAY_NO_AIRPODS)
            except Exception:
                pass
            return
        try:
            keep_input = bool(cfg.get(self.config, "audio.keep_input", True))
            if status.get("active_output"):
                result = airpods.deactivate(match, fallback)
            else:
                result = airpods.activate(match, keep_input=keep_input)
            self.log.info("toggle_airpods -> active_output=%s", result["active_output"])
            self._airpods = result
            self._airpods_ts = time.monotonic()
        except Exception as exc:
            self.log.warning("airpods toggle failed: %s", exc)
            try:
                device.show_overlay_text(2, OVERLAY_NO_AIRPODS)
            except Exception:
                pass

    # -- hardware sync ---------------------------------------------------------

    def _sync(self, device) -> None:
        with self._lock:
            m = dict(self._meeting)

        desired: dict[Any, Any] = {}

        mute_key = self._keys.get("toggle_mute")
        if mute_key is not None:
            if m.get("in_meeting"):
                desired[("text", mute_key)] = {
                    "muted": TEXT_MUTED,
                    "unmuted": TEXT_UNMUTED,
                }.get(m.get("state"), TEXT_MUTE_UNKNOWN)
            else:
                desired[("text", mute_key)] = ""

        out_key = self._keys.get("toggle_airpods")
        if out_key is not None:
            pods = self._airpods or {}
            desired[("text", out_key)] = (
                TEXT_OUT_PODS if pods.get("active_output") else TEXT_OUT_SYS
            )

        color_key = {"unmuted": "onair_color", "muted": "offair_color"}.get(
            m.get("state"), "idle_color"
        )
        color = cfg.get(self.config, f"quickkeys.{color_key}", [0, 0, 0])
        desired["color"] = tuple(int(c) for c in color[:3])

        for item, value in desired.items():
            if self._applied.get(item) == value:
                continue
            if item == "color":
                device.set_wheel_color(*value)
            else:
                device.set_key_text(item[1], value)
            self._applied[item] = value
