"""Xencelabs Quick Keys support (USB HID protocol + device transport).

Protocol port of https://github.com/Julusian/node-xencelabs-quick-keys.
"""

from __future__ import annotations

from .device import QuickKeysDevice, QuickKeysError, enumerate_devices
from .protocol import (
    DisplayBrightness,
    DisplayOrientation,
    PRODUCT_IDS_WIRED,
    PRODUCT_IDS_WIRELESS,
    VENDOR_ID,
    WheelSpeed,
)

__all__ = [
    "QuickKeysDevice",
    "QuickKeysError",
    "enumerate_devices",
    "DisplayBrightness",
    "DisplayOrientation",
    "WheelSpeed",
    "VENDOR_ID",
    "PRODUCT_IDS_WIRED",
    "PRODUCT_IDS_WIRELESS",
]
