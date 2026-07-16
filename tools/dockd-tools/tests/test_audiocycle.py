from dockd_tools import audiocycle
from dockd_tools.coreaudio import AudioDevice
from dockd_tools.quickkeys_bridge import _key_label


def _dev(name, uid="uid", output=True, input=False):
    return AudioDevice(id=1, name=name, uid=uid, transport="usb", input=input, output=output)


CONFIG = {
    "audio": {
        "airpods_match": "AirPods",
        "output_cycle": [
            {"match": "AirPods", "label": "Pods"},
            {"match": "MacBook Pro Speakers", "label": "Sys"},
        ],
        "input_cycle": [
            {"match": "MacBook Pro Microphone", "label": "Sys"},
            {"match": "RØDE", "label": "Rode"},
        ],
    }
}


def test_label_for_allowlisted_device():
    assert audiocycle.label_for(CONFIG, "output", _dev("Jeff's AirPods Pro")) == "Pods"
    assert audiocycle.label_for(CONFIG, "output", _dev("MacBook Pro Speakers")) == "Sys"
    assert audiocycle.label_for(CONFIG, "input", _dev("RØDE VideoMic NTG")) == "Rode"


def test_label_for_unlisted_device_uses_name_prefix():
    assert audiocycle.label_for(CONFIG, "output", _dev("MPG272UX OLED")) == "MPG27"


def test_label_for_none():
    assert audiocycle.label_for(CONFIG, "output", None) == "?"


def test_key_label_fits_hardware_limit():
    assert _key_label("Out:", "Sys") == "Out: Sys"
    assert _key_label("Out:", "Pods") == "Out:Pods"
    assert _key_label("In:", "Sys") == "In: Sys"
    assert _key_label("In:", "Pods") == "In: Pods"
    assert len(_key_label("Out:", "LongLabel")) <= 8
