#!/bin/bash
# Build Dockd.app into app/dist/.
#
# Usage: scripts/bundle.sh [--install]
#   --install    also copy the bundle to /Applications
#
# The app locates the Python tools via a tools-bin symlink inside
# Resources, pointing at tools/dockd-tools/.venv/bin (run `uv sync` there
# first). Override at runtime with DOCKD_TOOLS_BIN or config tools.bin_dir.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="$(dirname "$APP_DIR")"
TOOLS_BIN="$REPO_DIR/tools/dockd-tools/.venv/bin"
DIST="$APP_DIR/dist"
BUNDLE="$DIST/Dockd.app"

cd "$APP_DIR"
swift build -c release

rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"

cp "$APP_DIR/.build/release/Dockd" "$BUNDLE/Contents/MacOS/Dockd"

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

if [ -d "$TOOLS_BIN" ]; then
    ln -s "$TOOLS_BIN" "$BUNDLE/Contents/Resources/tools-bin"
else
    echo "warning: $TOOLS_BIN not found — run 'uv sync' in tools/dockd-tools," >&2
    echo "         or set tools.bin_dir in the dockd config." >&2
fi

codesign --force --sign - "$BUNDLE"

echo "built $BUNDLE"

if [ "${1:-}" = "--install" ]; then
    rm -rf /Applications/Dockd.app
    cp -R "$BUNDLE" /Applications/Dockd.app
    echo "installed /Applications/Dockd.app"
fi
