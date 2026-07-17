"""Shared configuration for all dockd tools.

The config file is JSON, shared with the Swift menubar app. Default location:
``~/Library/Application Support/dockd/config.json``; override with the
``DOCKD_CONFIG`` environment variable. Missing file or missing keys fall back
to the defaults below, so every tool works out of the box.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

APP_DIR = Path.home() / "Library" / "Application Support" / "dockd"
STATE_DIR = APP_DIR / "state"
LOG_DIR = Path.home() / "Library" / "Logs" / "dockd"

DEFAULTS: dict[str, Any] = {
    "obs": {
        "host": "127.0.0.1",
        "port": 4455,
        # null → auto-discover from OBS's own obs-websocket config.json
        "password": None,
        "app_name": "OBS",
        "scene_collections": {
            "docked": "Docked",
            "undocked": "Undocked",
        },
    },
    "dock": {
        # Substring matched (case-insensitive) against Thunderbolt device names
        "match": "Thunderbolt 5 Hub",
    },
    "audio": {
        # Substring matched (case-insensitive) against device / bluetooth names
        "airpods_match": "AirPods",
        # Output device to fall back to when toggling away from AirPods.
        # null → built-in ("MacBook Pro Speakers" etc. chosen automatically)
        "fallback_output": None,
        # Keep the current default input device when AirPods become the
        # output (macOS likes to switch input to the AirPods mic too)
        "keep_input": True,
        # Allow-lists the Quick Keys Out:/In: buttons cycle through.
        # "match" is a device UID, exact name, or name substring; "label"
        # is the short name shown on the key (~4-5 chars fit).
        "output_cycle": [
            {"match": "AirPods", "label": "Pods"},
            {"match": "MacBook Pro Speakers", "label": "Sys"},
        ],
        "input_cycle": [
            {"match": "MacBook Pro Microphone", "label": "Sys"},
            {"match": "AirPods", "label": "Pods"},
        ],
    },
    "onair": {
        "poll_interval": 0.5,
        "home_assistant": {
            "url": "http://10.0.0.75:8123",
            # Set your Home Assistant long-lived access token here. Never
            # commit it to the repo.
            "token": None,
            # Preferred: an RGB light entity driven directly to match the Quick
            # Keys wheel — red when unmuted (on air), green when muted, off when
            # not in a meeting. Uses quickkeys.onair_color / offair_color so the
            # two always agree. When null, falls back to the scenes below.
            "light": None,
            "scenes": {
                "unmuted": "scene.zoom_unmuted",
                "muted": "scene.zoom_muted",
                "unknown": "scene.zoom_unknown",
            },
        },
    },
    "virtualcam_sleep": {
        # Seconds subtracted from the screensaver timeout
        "margin_seconds": 10,
        "poll_interval": 5,
        # Never stop the camera while a meeting is detected
        "respect_meetings": True,
        # Used if the system screensaver idle time is not configured
        "fallback_timeout_seconds": 1200,
    },
    "quickkeys": {
        # Drive the pad from its own always-on daemon (dockd-quickkeys run),
        # independent of dock/on-air state.
        "enabled": True,
        # How often the daemon refreshes meeting state for the mute key, in
        # seconds (only polled when a toggle_mute button is mapped).
        "poll_interval": 0.5,
        # Wheel ring colors, as [r, g, b]
        "onair_color": [255, 0, 0],
        "offair_color": [0, 255, 0],
        "idle_color": [0, 0, 32],
        # Key index -> role. toggle_mute shows Muted/Unmuted while in a
        # meeting (blank otherwise); cycle_output / cycle_input show
        # "Out: X" / "In: X" and cycle through the audio.output_cycle /
        # audio.input_cycle allow-lists; toggle_obs_scene_collection shows
        # the current OBS scene collection (8-char limit) and flips between
        # the docked/undocked mapped collections. All other keys are cleared.
        # Labels are managed dynamically.
        "buttons": {
            "0": "toggle_mute",
            "1": "cycle_output",
            "2": "cycle_input",
            "3": "toggle_obs_scene_collection",
        },
    },
}


def config_path() -> Path:
    env = os.environ.get("DOCKD_CONFIG")
    if env:
        return Path(env).expanduser()
    return APP_DIR / "config.json"


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load() -> dict[str, Any]:
    """Load config merged over defaults. Never raises on a missing file."""
    path = config_path()
    try:
        user = json.loads(path.read_text())
    except FileNotFoundError:
        user = {}
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"dockd: invalid config at {path}: {exc}") from exc
    if not isinstance(user, dict):
        raise SystemExit(f"dockd: config at {path} must be a JSON object")
    return _deep_merge(DEFAULTS, user)


def save(config: dict[str, Any]) -> Path:
    """Write the given config (only user overrides should be passed)."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")
    return path


def get(config: dict[str, Any], dotted: str, default: Any = None) -> Any:
    """Fetch ``a.b.c`` style keys from a nested dict."""
    node: Any = config
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node
