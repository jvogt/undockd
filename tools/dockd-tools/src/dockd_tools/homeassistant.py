"""Minimal Home Assistant REST client (stdlib only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit


class HomeAssistantError(RuntimeError):
    pass


def _base_url(url: str) -> str:
    """Normalize a configured HA URL to its base (scheme://host[:port][/prefix]).

    Tolerates a URL that accidentally includes the REST endpoint — a common
    paste error — e.g. ``http://ha:8123/api/services/scene/turn_on`` becomes
    ``http://ha:8123``. Everything from ``/api/`` onward is dropped, since the
    client appends the full ``/api/...`` path itself; any reverse-proxy prefix
    before ``/api/`` is preserved.
    """
    parts = urlsplit(url if "//" in url else f"http://{url}")
    path = parts.path
    marker = path.find("/api/")
    if marker != -1:
        path = path[:marker]
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")


class HomeAssistant:
    def __init__(self, url: str, token: str | None, timeout: float = 5):
        if not token:
            raise HomeAssistantError(
                "no Home Assistant token configured (set onair.home_assistant.token "
                "in the dockd config file)"
            )
        self.base = _base_url(url)
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
