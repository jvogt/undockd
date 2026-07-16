#!/bin/bash
# Build a portable Dockd.app into app/dist/.
#
# Usage: scripts/bundle.sh [--install]
#   --install    also copy the bundle to /Applications
#
# The Python tools are frozen with PyInstaller into a self-contained helper app
# (dockd-tools.app) and embedded under Resources, so the bundle carries its own
# interpreter and native deps — no system Python, no Homebrew, no dev-machine
# symlinks. dockd-tools.app declares NSBluetoothAlwaysUsageDescription because
# any process that touches IOBluetooth without it is hard-killed by TCC.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="$(dirname "$APP_DIR")"
TOOLS_DIR="$REPO_DIR/tools/dockd-tools"
DIST="$APP_DIR/dist"
BUNDLE="$DIST/Dockd.app"

# The dockd-<name> CLIs, dispatched from one frozen `dockd` executable by
# argv[0] basename (see dockd_tools/dispatch.py).
TOOL_NAMES=(obs audio dock idle meeting onair virtualcam-sleep quickkeys)

# --- 1. Swift menubar app -------------------------------------------------
cd "$APP_DIR"
swift build -c release

# --- 2. Freeze the Python tools ------------------------------------------
echo "freezing dockd-tools with PyInstaller…"
cd "$TOOLS_DIR"
uv sync
rm -rf build dist
uv run pyinstaller dockd-tools.spec --noconfirm --distpath dist --workpath build
TOOLS_APP="$TOOLS_DIR/dist/dockd-tools.app"
TOOLS_MACOS="$TOOLS_APP/Contents/MacOS"
# Busybox symlinks so each dockd-<name> resolves to the shared executable.
for name in "${TOOL_NAMES[@]}"; do
    ln -sf dockd "$TOOLS_MACOS/dockd-$name"
done

# --- 3. Assemble Dockd.app ------------------------------------------------
cd "$APP_DIR"
# Stop any running instance first: its supervised daemons execute out of the
# bundle, so files stay open and rm -rf / cp would fail ("Operation not
# permitted") mid-rebuild.
killall Dockd 2>/dev/null || true
pkill -f 'dockd-tools.app/Contents/MacOS/dockd' 2>/dev/null || true
sleep 1
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"

cp "$APP_DIR/.build/release/Dockd" "$BUNDLE/Contents/MacOS/Dockd"
cp -R "$TOOLS_APP" "$BUNDLE/Contents/Resources/dockd-tools.app"

cat > "$BUNDLE/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.jvogt.dockd</string>
    <key>CFBundleName</key>
    <string>Dockd</string>
    <key>CFBundleDisplayName</key>
    <string>Dockd</string>
    <key>CFBundleExecutable</key>
    <string>Dockd</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSAppleEventsUsageDescription</key>
    <string>Dockd reads Zoom and Google Meet mute state to drive the on-air light.</string>
    <key>NSBluetoothAlwaysUsageDescription</key>
    <string>Dockd connects your AirPods and switches audio devices.</string>
</dict>
</plist>
PLIST

# --- 4. Codesign inside-out ----------------------------------------------
# Sign the nested tools app first (deep, so every bundled dylib is covered),
# then the outer app. Ad-hoc (`-s -`) is fine for a Mac the user owns; swap in
# a Developer ID identity for distribution.
codesign --force --deep --sign - "$BUNDLE/Contents/Resources/dockd-tools.app"
codesign --force --sign - "$BUNDLE"

echo "built $BUNDLE"

if [ "${1:-}" = "--install" ]; then
    rm -rf /Applications/Dockd.app
    cp -R "$BUNDLE" /Applications/Dockd.app
    echo "installed /Applications/Dockd.app"
fi
