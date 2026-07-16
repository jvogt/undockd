# PyInstaller spec — freezes the dockd-* CLIs into a self-contained macOS
# helper app so Dockd.app is portable (no system Python, no brew).
#
#   uv run pyinstaller dockd-tools.spec --noconfirm
#
# Produces dist/dockd-tools.app (onedir). The single executable `dockd`
# dispatches by argv[0] basename (see dockd_tools/dispatch.py); bundle.sh adds
# the dockd-<name> symlinks next to it inside Contents/MacOS.
#
# The bundle carries NSBluetoothAlwaysUsageDescription: any process that touches
# IOBluetooth without it is hard-killed by TCC (SIGABRT, uncatchable), so the
# frozen tool must declare it in its own Info.plist.

from PyInstaller.utils.hooks import collect_all, collect_submodules

hiddenimports = [
    # dispatch.py imports these dynamically (importlib), so PyInstaller's
    # static analysis can't see them — list every CLI module explicitly.
    "dockd_tools.cli.obs",
    "dockd_tools.cli.audio",
    "dockd_tools.cli.dock",
    "dockd_tools.cli.idle",
    "dockd_tools.cli.meeting",
    "dockd_tools.cli.onair",
    "dockd_tools.cli.virtualcam_sleep",
    "dockd_tools.cli.quickkeys",
]
hiddenimports += collect_submodules("obsws_python")

datas = []
binaries = []
# pyobjc (objc + Cocoa/Foundation + IOBluetooth) and hidapi ship native
# extensions and lazy-loaded submodules; collect_all grabs all three parts.
for pkg in ("objc", "Foundation", "IOBluetooth", "hid"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    ["src/dockd_tools/dispatch.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="dockd",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="dockd-tools",
)

app = BUNDLE(
    coll,
    name="dockd-tools.app",
    icon=None,
    bundle_identifier="com.jvogt.dockd.tools",
    info_plist={
        "CFBundleName": "dockd-tools",
        "CFBundleDisplayName": "dockd-tools",
        "LSUIElement": True,
        "LSBackgroundOnly": True,
        "NSBluetoothAlwaysUsageDescription":
            "Dockd connects your AirPods and switches audio devices.",
        # Meeting detection drives osascript (System Events for Zoom, Chrome JS
        # for Meet); declare Apple Events use so automation isn't blocked when
        # this helper is the responsible process.
        "NSAppleEventsUsageDescription":
            "Dockd reads Zoom and Google Meet mute state to drive the on-air light.",
    },
)
