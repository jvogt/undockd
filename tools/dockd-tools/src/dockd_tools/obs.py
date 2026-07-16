"""OBS control over obs-websocket, via obsws-python.

The websocket password is auto-discovered from OBS's own plugin config when
not set in the dockd config, so no manual setup is needed on a standard OBS
install.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import obsws_python as obsws

OBS_WEBSOCKET_CONFIG = (
    Path.home()
    / "Library"
    / "Application Support"
    / "obs-studio"
    / "plugin_config"
    / "obs-websocket"
    / "config.json"
)


class ObsError(RuntimeError):
    pass


def discover_password() -> str | None:
    try:
        data = json.loads(OBS_WEBSOCKET_CONFIG.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not data.get("auth_required", False):
        return ""
    return data.get("server_password")


def is_running(app_name: str = "OBS") -> bool:
    return (
        subprocess.run(
            ["pgrep", "-x", app_name], capture_output=True, check=False
        ).returncode
        == 0
    )


def ensure_running(app_name: str = "OBS", wait_seconds: float = 20) -> bool:
    """Start OBS if needed; wait until its websocket accepts connections.

    Returns True if OBS was already running, False if we launched it.
    """
    already = is_running(app_name)
    if not already:
        subprocess.run(["open", "-gja", app_name], check=True)
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            try:
                Obs().client.get_version()
                break
            except Exception:
                time.sleep(0.5)
    return already


class Obs:
    """Thin request-client wrapper with lazy connection."""

    def __init__(self, config: dict[str, Any] | None = None, timeout: float = 3):
        obs_cfg = (config or {}).get("obs", {})
        self.host = obs_cfg.get("host", "127.0.0.1")
        self.port = obs_cfg.get("port", 4455)
        password = obs_cfg.get("password")
        if password is None:
            password = discover_password()
        self.password = password or ""
        self.timeout = timeout
        self._client: obsws.ReqClient | None = None

    @property
    def client(self) -> obsws.ReqClient:
        if self._client is None:
            try:
                self._client = obsws.ReqClient(
                    host=self.host,
                    port=self.port,
                    password=self.password,
                    timeout=self.timeout,
                )
            except Exception as exc:
                raise ObsError(f"cannot connect to OBS websocket at {self.host}:{self.port}: {exc}") from exc
        return self._client

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None

    # -- scene collections ---------------------------------------------------

    def scene_collections(self) -> dict[str, Any]:
        resp = self.client.get_scene_collection_list()
        return {
            "current_scene_collection": resp.current_scene_collection_name,
            "scene_collections": resp.scene_collections,
        }

    def set_scene_collection(self, name: str) -> None:
        current = self.scene_collections()
        if name not in current["scene_collections"]:
            raise ObsError(
                f"no such OBS scene collection: {name!r} "
                f"(have: {current['scene_collections']})"
            )
        if current["current_scene_collection"] != name:
            self.client.set_current_scene_collection(name)

    # -- virtual camera ----------------------------------------------------

    def virtualcam_active(self) -> bool:
        return bool(self.client.get_virtual_cam_status().output_active)

    def virtualcam_start(self) -> None:
        if not self.virtualcam_active():
            self.client.start_virtual_cam()

    def virtualcam_stop(self) -> None:
        if self.virtualcam_active():
            self.client.stop_virtual_cam()

    def virtualcam_toggle(self) -> bool:
        self.client.toggle_virtual_cam()
        return self.virtualcam_active()
