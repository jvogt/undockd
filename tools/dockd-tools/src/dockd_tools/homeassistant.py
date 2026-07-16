"""Minimal Home Assistant REST client (stdlib only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class HomeAssistantError(RuntimeError):
    pass


class HomeAssistant:
    def __init__(self, url: str, token: str | None, timeout: float = 5):
        if not token:
            raise HomeAssistantError(
                "no Home Assistant token configured (set onair.home_assistant.token "
                "in the dockd config file)"
            )
        self.base = url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _post(self, path: str, payload: dict) -> dict | list:
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                return json.loads(resp.read() or "{}")
        except urllib.error.HTTPError as exc:
            raise HomeAssistantError(f"HA {path} failed: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HomeAssistantError(f"HA unreachable at {self.base}: {exc}") from exc

    def turn_on_scene(self, entity_id: str) -> None:
        self._post("/api/services/scene/turn_on", {"entity_id": entity_id})
