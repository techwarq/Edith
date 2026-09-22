#!/bin/bash
# Builds EdithWidget.app — a Swift Package executable wrapped in a real .app
# bundle so macOS TCC (mic, input monitoring) treats it as a stable identity
# instead of re-prompting on every rebuild. No Xcode project required.
set -euo pipefail
cd "$(dirname "$0")"

CONFIG="${1:-debug}"
swift build -c "$CONFIG"

BIN_PATH=$(swift build -c "$CONFIG" --show-bin-path)
APP="EdithWidget.app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$BIN_PATH/EdithWidget" "$APP/Contents/MacOS/EdithWidget"
cp Info.plist "$APP/Contents/Info.plist"

codesign --force --deep --sign - "$APP"

echo "Built $APP ($CONFIG)"
