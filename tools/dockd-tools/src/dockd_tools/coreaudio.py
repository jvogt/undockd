"""Default audio input/output device control via CoreAudio, using ctypes.

No third-party dependencies — talks straight to CoreAudio's C API
(AudioObjectGetPropertyData / AudioObjectSetPropertyData).
"""

from __future__ import annotations

import ctypes
import ctypes.util
from dataclasses import dataclass, asdict

_ca = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
_cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")

_cf.CFStringGetCString.restype = ctypes.c_bool
_cf.CFStringGetCString.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_long,
    ctypes.c_uint32,
]
_cf.CFRelease.argtypes = [ctypes.c_void_p]

kCFStringEncodingUTF8 = 0x08000100
kAudioObjectSystemObject = 1


def _fourcc(code: str) -> int:
    return int.from_bytes(code.encode("ascii"), "big")


SEL_DEVICES = _fourcc("dev#")
SEL_DEFAULT_INPUT = _fourcc("dIn ")
SEL_DEFAULT_OUTPUT = _fourcc("dOut")
SEL_NAME = _fourcc("lnam")
SEL_UID = _fourcc("uid ")
SEL_STREAMS = _fourcc("stm#")
SEL_TRANSPORT = _fourcc("tran")

SCOPE_GLOBAL = _fourcc("glob")
SCOPE_INPUT = _fourcc("inpt")
SCOPE_OUTPUT = _fourcc("outp")
ELEMENT_MAIN = 0

TRANSPORT_NAMES = {
    _fourcc("bltn"): "builtin",
    _fourcc("blue"): "bluetooth",
    _fourcc("bltl"): "bluetooth-le",
    _fourcc("usb "): "usb",
    _fourcc("hdmi"): "hdmi",
    _fourcc("dprt"): "displayport",
    _fourcc("virt"): "virtual",
    _fourcc("aggr"): "aggregate",
    _fourcc("cont"): "continuity",
    _fourcc("airp"): "airplay",
    _fourcc("thun"): "thunderbolt",
}


class _PropertyAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


class CoreAudioError(RuntimeError):
    pass


def _get_data(object_id: int, selector: int, scope: int, buf: ctypes.Array) -> int:
    addr = _PropertyAddress(selector, scope, ELEMENT_MAIN)
    size = ctypes.c_uint32(ctypes.sizeof(buf))
    status = _ca.AudioObjectGetPropertyData(
        ctypes.c_uint32(object_id),
        ctypes.byref(addr),
        0,
        None,
        ctypes.byref(size),
        buf,
    )
    if status != 0:
        raise CoreAudioError(f"AudioObjectGetPropertyData failed: {status}")
    return size.value


def _get_data_size(object_id: int, selector: int, scope: int) -> int:
    addr = _PropertyAddress(selector, scope, ELEMENT_MAIN)
    size = ctypes.c_uint32(0)
    status = _ca.AudioObjectGetPropertyDataSize(
        ctypes.c_uint32(object_id), ctypes.byref(addr), 0, None, ctypes.byref(size)
    )
    if status != 0:
        raise CoreAudioError(f"AudioObjectGetPropertyDataSize failed: {status}")
    return size.value


def _get_cfstring(object_id: int, selector: int) -> str:
    ref = ctypes.c_void_p(0)
    buf = ctypes.cast(ctypes.byref(ref), ctypes.POINTER(ctypes.c_char * ctypes.sizeof(ref)))[0]
    _get_data(object_id, selector, SCOPE_GLOBAL, buf)
    if not ref.value:
        return ""
    out = ctypes.create_string_buffer(512)
    ok = _cf.CFStringGetCString(ref, out, len(out), kCFStringEncodingUTF8)
    _cf.CFRelease(ref)
    if not ok:
        return ""
    return out.value.decode("utf-8", "replace")


@dataclass
class AudioDevice:
    id: int
    name: str
    uid: str
    transport: str
    input: bool
    output: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _has_streams(device_id: int, scope: int) -> bool:
    try:
        return _get_data_size(device_id, SEL_STREAMS, scope) > 0
    except CoreAudioError:
        return False


def list_devices() -> list[AudioDevice]:
    size = _get_data_size(kAudioObjectSystemObject, SEL_DEVICES, SCOPE_GLOBAL)
    count = size // ctypes.sizeof(ctypes.c_uint32)
    ids = (ctypes.c_uint32 * count)()
    _get_data(kAudioObjectSystemObject, SEL_DEVICES, SCOPE_GLOBAL, ids)

    devices = []
    for device_id in ids:
        try:
            name = _get_cfstring(device_id, SEL_NAME)
            uid = _get_cfstring(device_id, SEL_UID)
            transport_raw = ctypes.c_uint32(0)
            try:
                _get_data(
                    device_id,
                    SEL_TRANSPORT,
                    SCOPE_GLOBAL,
                    ctypes.cast(
                        ctypes.byref(transport_raw),
                        ctypes.POINTER(ctypes.c_char * 4),
                    )[0],
                )
                transport = TRANSPORT_NAMES.get(transport_raw.value, "other")
            except CoreAudioError:
                transport = "unknown"
            devices.append(
                AudioDevice(
                    id=int(device_id),
                    name=name,
                    uid=uid,
                    transport=transport,
                    input=_has_streams(device_id, SCOPE_INPUT),
                    output=_has_streams(device_id, SCOPE_OUTPUT),
                )
            )
        except CoreAudioError:
            continue
    return devices


def _default_selector(direction: str) -> int:
    if direction == "input":
        return SEL_DEFAULT_INPUT
    if direction == "output":
        return SEL_DEFAULT_OUTPUT
    raise ValueError(f"direction must be input|output, got {direction!r}")


def get_default(direction: str) -> AudioDevice | None:
    device_id = ctypes.c_uint32(0)
    _get_data(
        kAudioObjectSystemObject,
        _default_selector(direction),
        SCOPE_GLOBAL,
        ctypes.cast(ctypes.byref(device_id), ctypes.POINTER(ctypes.c_char * 4))[0],
    )
    if not device_id.value:
        return None
    for device in list_devices():
        if device.id == device_id.value:
            return device
    return None


def set_default(direction: str, device: AudioDevice) -> None:
    addr = _PropertyAddress(_default_selector(direction), SCOPE_GLOBAL, ELEMENT_MAIN)
    device_id = ctypes.c_uint32(device.id)
    status = _ca.AudioObjectSetPropertyData(
        ctypes.c_uint32(kAudioObjectSystemObject),
        ctypes.byref(addr),
        0,
        None,
        ctypes.c_uint32(ctypes.sizeof(device_id)),
        ctypes.byref(device_id),
    )
    if status != 0:
        raise CoreAudioError(f"AudioObjectSetPropertyData failed: {status}")


def find_device(query: str, direction: str) -> AudioDevice | None:
    """Find a device by exact UID, exact name, or case-insensitive substring."""
    wants_input = direction == "input"
    candidates = [
        d for d in list_devices() if (d.input if wants_input else d.output)
    ]
    for d in candidates:
        if d.uid == query or d.name == query:
            return d
    needle = query.lower()
    for d in candidates:
        if needle in d.name.lower():
            return d
    return None
