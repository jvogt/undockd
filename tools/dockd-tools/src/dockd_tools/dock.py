"""Dock detection.

"Docked" means the configured Thunderbolt device (default: a Thunderbolt 5
hub) is present in ``system_profiler SPThunderboltDataType``. The match is a
case-insensitive substring against device names, so it survives firmware
naming tweaks.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Iterator


def _walk_items(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for child in node.get("_items", []):
            yield from _walk_items(child)
    elif isinstance(node, list):
        for child in node:
            yield from _walk_items(child)


def thunderbolt_devices() -> list[dict[str, str]]:
    proc = subprocess.run(
        ["system_profiler", "SPThunderboltDataType", "-json"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    data = json.loads(proc.stdout)
    devices = []
    for item in _walk_items(data.get("SPThunderboltDataType", [])):
        name = item.get("device_name_key") or item.get("_name")
        if not name:
            continue
        devices.append(
            {
                "name": name,
                "vendor": item.get("vendor_name_key", ""),
                "uid": item.get("switch_uid_key", ""),
            }
        )
    return devices


def dock_status(match: str) -> dict[str, Any]:
    needle = match.lower()
    devices = thunderbolt_devices()
    hit = next((d for d in devices if needle in d["name"].lower()), None)
    return {
        "docked": hit is not None,
        "match": match,
        "device": hit,
    }
