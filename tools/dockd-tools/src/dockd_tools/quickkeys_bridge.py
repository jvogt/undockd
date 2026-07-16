"""Bridge between the on-air watcher and a Xencelabs Quick Keys device.

Keeps a device open (reconnecting as needed), clears every key label on
connect, then drives up to three keys (roles assigned in
``quickkeys.buttons``):

- ``toggle_mute``: "Muted"/"Unmuted" while a Zoom/Meet meeting is in session
  (blank otherwise); pressing toggles the meeting mute. External mute changes
  flow back in via :meth:`set_meeting_state`.
- ``cycle_output``: "Out: <label>" for the current default output; pressing
  cycles through the ``audio.output_cycle`` allow-list. Fewer than two
  present choices → flashes "No Output Choices".
- ``cycle_input``: "In: <label>" for the current default input; cycles
  ``audio.input_cycle``; flashes "No Input Choices" when there is nothing to
  cycle to.
- ``toggle_obs_scene_collection``: shows the current OBS scene collection
  name (8-char key limit, so "Docked"/"Undocked" rather than "OBS: Docked")
  and flips between the scene collections mapped to the docked/undocked
  slots. "No OBS" when OBS is unreachable.

The wheel ring mirrors on-air state (unmuted/muted/idle colors). On daemon
shutdown (e.g. undocking stops the on-air watcher) every key label and the
wheel color are cleared so the pad goes dark.

Threading: the pump thread only does fast HID polling and label sync; a
separate refresher thread owns the slow calls (IOBluetooth, CoreAudio device
walks) and publishes a snapshot, so button presses react instantly from
cached state instead of waiting on Bluetooth.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from . import audiocycle, config as cfg, coreaudio, meeting
from .bluetooth import BluetoothUnavailable
from .obs import Obs

TEXT_MUTED = "Muted"
TEXT_UNMUTED = "Unmuted"
TEXT_MUTE_UNKNOWN = "Mute ?"
TEXT_NO_OBS = "No OBS"
OVERLAY_NO_OUTPUTS = "No Output Choices"
OVERLAY_NO_INPUTS = "No Input Choices"

REFRESH_SECONDS = 3


def _key_label(prefix: str, label: str) -> str:
    """Fit "Out: Sys" style text into the 8-char hardware limit."""
    text = f"{prefix} {label}"
    if len(text) > 8:
        text = f"{prefix}{label}"[:8]
    return text


class QuickKeysBridge:
    def __init__(self, config: dict[str, Any], log: logging.Logger):
        self.config = config
        self.log = log
        self.enabled = bool(cfg.get(config, "quickkeys.enabled", True))
        buttons = cfg.get(config, "quickkeys.buttons", {}) or {}
        self._keys = {str(v): int(k) for k, v in buttons.items()}   # role -> key
        self._actions = {int(k): str(v) for k, v in buttons.items()}  # key -> role
        self._lock = threading.Lock()
        self._dev_lock = threading.Lock()
        self._meeting: dict[str, Any] = {"app": None, "state": "none", "in_meeting": False}
        # Snapshot maintained by the refresher thread
        self._airpods: dict[str, Any] | None = None
        self._default_output: coreaudio.AudioDevice | None = None
        self._default_input: coreaudio.AudioDevice | None = None
        self._obs_scene_collection: str | None = None
        self._obs: Obs | None = None  # refresher-thread only
        self._applied: dict[Any, Any] = {}
        # Active = docked. When inactive the pad is blanked and presses ignored,
        # but the device stays open so re-docking relights it instantly.
        self._active = True
        self._repaint = False  # pump repaints from scratch after an active flip
        self._device = None
        self._stop = threading.Event()
        self._kick = threading.Event()  # wake the refresher early
        self._pump_thread: threading.Thread | None = None
        self._refresh_thread: threading.Thread | None = None
        self._action_thread: threading.Thread | None = None

    # -- public API ----------------------------------------------------------

    def start(self) -> None:
        if not self.enabled:
            return
        self._refresh_thread = threading.Thread(
            target=self._refresher, name="quickkeys-refresh", daemon=True
        )
        self._refresh_thread.start()
        self._pump_thread = threading.Thread(target=self._run, name="quickkeys", daemon=True)
        self._pump_thread.start()

    def stop(self) -> None:
        """Orderly shutdown: stop the threads, blank the pad, close the device.

        The device MUST be closed with no read in flight before the
        interpreter exits — hidapi's atexit teardown (IOHIDManagerClose)
        crashes the process otherwise ("Python quit unexpectedly").
        """
        self._stop.set()
        self._kick.set()
        for thread in (self._pump_thread, self._refresh_thread):
            if thread and thread.is_alive():
                thread.join(timeout=3)
        device = self._device
        self._device = None
        if device is not None:
            try:
                for key in range(8):
                    device.set_key_text(key, "")
                device.set_wheel_color(0, 0, 0)
            except Exception as exc:
                self.log.debug("could not blank quickkeys on stop: %s", exc)
            device.close()

    def set_meeting_state(self, state: dict[str, Any]) -> None:
        """Called from the daemon loop on every poll (0.5s cadence)."""
        with self._lock:
            self._meeting = dict(state)

    def set_active(self, active: bool) -> None:
        """Enable/disable pad output + input based on dock state.

        Inactive (undocked): the next sync blanks every key and the wheel, and
        button presses are ignored. Active (docked): force a full repaint so the
        labels/colors come back immediately.
        """
        if active == self._active:
            return
        self._active = active
        self._repaint = True  # picked up by the pump thread's _sync
        self.log.info(
            "quickkeys %s", "active (docked)" if active else "inactive (undocked) — pad dark"
        )

    @property
    def active(self) -> bool:
        return self._active

    @property
    def connected(self) -> bool:
        return self._device is not None

    # -- refresher thread (owns all slow status calls) -------------------------

    def _refresher(self) -> None:
        from . import airpods

        match = cfg.get(self.config, "audio.airpods_match", "AirPods")
        while not self._stop.is_set():
            pods: dict[str, Any] | None
            try:
                pods = airpods.status(match)
            except Exception as exc:
                self.log.debug("airpods status failed: %s", exc)
                pods = None
            try:
                out_dev = coreaudio.get_default("output")
                in_dev = coreaudio.get_default("input")
            except Exception as exc:
                self.log.debug("coreaudio defaults failed: %s", exc)
                out_dev = in_dev = None
            collection: str | None = None
            if self._keys.get("toggle_obs_scene_collection") is not None:
                try:
                    if self._obs is None:
                        self._obs = Obs(self.config, timeout=2)
                    collection = self._obs.scene_collections()["current_scene_collection"]
                except Exception:
                    if self._obs is not None:
                        self._obs.close()
                        self._obs = None
            with self._lock:
                self._airpods = pods
                self._default_output = out_dev
                self._default_input = in_dev
                self._obs_scene_collection = collection
            self._kick.wait(REFRESH_SECONDS)
            self._kick.clear()

    def _snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "meeting": dict(self._meeting),
                "airpods": dict(self._airpods) if self._airpods else None,
                "output": self._default_output,
                "input": self._default_input,
                "obs_scene_collection": self._obs_scene_collection,
            }

    @property
    def obs_scene_collection(self) -> str | None:
        with self._lock:
            return self._obs_scene_collection

    # -- device pump -----------------------------------------------------------

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
                self._applied = {}
                # On shutdown, stop() blanks the pad and closes the device;
                # close here only on the error/disconnect path.
                if not self._stop.is_set():
                    self._device = None
                    device.close()

    def _reset_keys(self, device) -> None:
        """Clear all 8 key labels so only the keys we drive show anything."""
        with self._dev_lock:
            for key in range(8):
                try:
                    device.set_key_text(key, "")
                except Exception as exc:
                    self.log.debug("could not clear key %s: %s", key, exc)
                    return
        self._applied = {}

    def _pump(self, device) -> None:
        while not self._stop.is_set():
            # All device I/O is serialized: overlay/blank writes from other
            # threads must never interleave with a blocking read.
            with self._dev_lock:
                events = device.poll_events(timeout_ms=250)
            for event in events:
                if event["type"] == "key" and event["down"]:
                    self._handle_key(device, event["key"])
                elif event["type"] == "connected":
                    self._reset_keys(device)
            self._sync(device)

    # -- key handling ------------------------------------------------------------

    def _handle_key(self, device, key: int) -> None:
        if not self._active:
            return  # undocked: pad is dark and presses are ignored
        action = self._actions.get(key)
        if not action:
            return
        if self._action_thread and self._action_thread.is_alive():
            return  # ignore presses while an action is in flight
        if action == "toggle_mute":
            target = self._do_toggle_mute
        elif action == "cycle_output":
            target = lambda: self._do_cycle(device, "output")  # noqa: E731
        elif action == "cycle_input":
            target = lambda: self._do_cycle(device, "input")  # noqa: E731
        elif action == "toggle_obs_scene_collection":
            target = lambda: self._do_toggle_obs_scene_collection(device)  # noqa: E731
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

    def _overlay(self, device, text: str) -> None:
        try:
            with self._dev_lock:
                device.show_overlay_text(2, text)
        except Exception as exc:
            self.log.debug("overlay failed: %s", exc)

    def _do_toggle_obs_scene_collection(self, device) -> None:
        docked = str(cfg.get(self.config, "obs.scene_collections.docked", "Docked"))
        undocked = str(cfg.get(self.config, "obs.scene_collections.undocked", "Undocked"))
        with self._lock:
            current = self._obs_scene_collection
        target = undocked if current == docked else docked
        # Fresh connection: the refresher thread owns the shared client.
        obs = Obs(self.config, timeout=3)
        try:
            obs.set_scene_collection(target)
            self.log.info("toggle_obs_scene_collection -> %s", target)
            with self._lock:
                self._obs_scene_collection = target
            self._kick.set()
        except Exception as exc:
            self.log.warning("obs scene collection toggle failed: %s", exc)
            self._overlay(device, TEXT_NO_OBS)
        finally:
            obs.close()

    def _do_cycle(self, device, direction: str) -> None:
        snapshot = self._snapshot()
        no_choices = OVERLAY_NO_OUTPUTS if direction == "output" else OVERLAY_NO_INPUTS
        try:
            result = audiocycle.cycle(
                self.config, direction, airpods_status=snapshot["airpods"]
            )
            self.log.info("cycle_%s -> %s", direction, result["device"]["name"] if result["device"] else "?")
            # Publish the new default immediately so the label flips now.
            device_obj = coreaudio.get_default(direction)
            with self._lock:
                if direction == "output":
                    self._default_output = device_obj
                else:
                    self._default_input = device_obj
            self._kick.set()
        except audiocycle.NoChoicesError:
            self.log.info("cycle_%s: %s", direction, no_choices)
            self._overlay(device, no_choices)
        except BluetoothUnavailable as exc:
            # e.g. AirPods that are paired but grabbed by a phone — a page
            # timeout, not "no choices". Say so instead of "No Output Choices".
            self.log.info("cycle_%s: %s", direction, exc)
            self._overlay(device, "AirPods unavailable")
        except Exception as exc:
            self.log.warning("cycle_%s failed: %s", direction, exc)
            self._overlay(device, no_choices)

    # -- hardware sync -------------------------------------------------------------

    def _sync(self, device) -> None:
        if self._repaint:
            # Active state just flipped — forget what's on the pad so we either
            # fully blank it (going inactive) or fully repaint it (going active).
            self._applied = {}
            self._repaint = False

        if not self._active:
            # Undocked: everything dark. Blank once, then the _applied diff
            # below makes subsequent syncs no-ops until we go active again.
            desired: dict[Any, Any] = {("text", k): "" for k in range(8)}
            desired["color"] = (0, 0, 0)
            for item, value in desired.items():
                if self._applied.get(item) == value:
                    continue
                with self._dev_lock:
                    if item == "color":
                        device.set_wheel_color(*value)
                    else:
                        device.set_key_text(item[1], value)
                self._applied[item] = value
            return

        snapshot = self._snapshot()
        m = snapshot["meeting"]
        desired = {}

        mute_key = self._keys.get("toggle_mute")
        if mute_key is not None:
            if m.get("in_meeting"):
                desired[("text", mute_key)] = {
                    "muted": TEXT_MUTED,
                    "unmuted": TEXT_UNMUTED,
                }.get(m.get("state"), TEXT_MUTE_UNKNOWN)
            else:
                desired[("text", mute_key)] = ""

        out_key = self._keys.get("cycle_output")
        if out_key is not None:
            label = audiocycle.label_for(self.config, "output", snapshot["output"])
            desired[("text", out_key)] = _key_label("Out:", label)

        in_key = self._keys.get("cycle_input")
        if in_key is not None:
            label = audiocycle.label_for(self.config, "input", snapshot["input"])
            desired[("text", in_key)] = _key_label("In:", label)

        obs_key = self._keys.get("toggle_obs_scene_collection")
        if obs_key is not None:
            collection = snapshot["obs_scene_collection"]
            # 8-char key limit: "OBS: Docked" can't fit — show the collection name
            desired[("text", obs_key)] = collection[:8] if collection else TEXT_NO_OBS

        color_key = {"unmuted": "onair_color", "muted": "offair_color"}.get(
            m.get("state"), "idle_color"
        )
        color = cfg.get(self.config, f"quickkeys.{color_key}", [0, 0, 0])
        desired["color"] = tuple(int(c) for c in color[:3])

        for item, value in desired.items():
            if self._applied.get(item) == value:
                continue
            with self._dev_lock:
                if item == "color":
                    device.set_wheel_color(*value)
                else:
                    device.set_key_text(item[1], value)
            self._applied[item] = value
