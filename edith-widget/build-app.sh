#!/bin/bash
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

IDENTITY="${EDITH_SIGN_IDENTITY:-Edith Widget Local Signing}"
if security find-certificate -c "$IDENTITY" >/dev/null 2>&1; then
    codesign --force --deep --sign "$IDENTITY" "$APP"
    SIGNED_WITH="$IDENTITY"
else
    codesign --force --deep --sign - "$APP"
    SIGNED_WITH="ad-hoc (permissions reset on every rebuild — see header)"
fi

INSTALLED="/Applications/$APP"
if [ -d "$INSTALLED" ]; then
    rm -rf "$INSTALLED"
    cp -R "$APP" "$INSTALLED"
    echo "Updated $INSTALLED"
fi

echo "Built $APP ($CONFIG, signed: $SIGNED_WITH)"
