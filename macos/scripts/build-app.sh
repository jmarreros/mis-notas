#!/bin/zsh
# Compila y empaqueta MisNotas.app sin Xcode.
#   scripts/build-app.sh            → build/MisNotas.app
#   scripts/build-app.sh --install  → además la copia a /Applications
#   scripts/build-app.sh --debug    → compilación incremental, mucho más rápida para probar cambios
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/sdk.sh

CONFIG=release
[[ " $* " == *" --debug "* ]] && CONFIG=debug
swift build -c $CONFIG --product MisNotas
BIN="$(swift build -c $CONFIG --product MisNotas --show-bin-path)/MisNotas"

APP=build/MisNotas.app
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/Fonts"
cp "$BIN" "$APP/Contents/MacOS/MisNotas"
cp Sources/MisNotas/Resources/Fonts/* "$APP/Contents/Resources/Fonts/"

ICONSET="$(swift scripts/make-icon.swift build)"
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
rm -rf "$ICONSET"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Mis Notas</string>
  <key>CFBundleDisplayName</key><string>Mis Notas</string>
  <key>CFBundleIdentifier</key><string>com.jmarreros.misnotas</string>
  <key>CFBundleExecutable</key><string>MisNotas</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${VERSION:-1.0}</string>
  <key>CFBundleVersion</key><string>$(date +%Y%m%d%H%M)</string>
  <key>CFBundleDevelopmentRegion</key><string>es</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key>
  <dict>
    <!-- Permite probar contra http://127.0.0.1 o la red local; en producción usa HTTPS. -->
    <key>NSAllowsLocalNetworking</key><true/>
  </dict>
</dict>
</plist>
PLIST

codesign --force --deep --sign - "$APP"
echo "Listo: $APP"

if [[ " $* " == *" --install "* ]]; then
  rm -rf "/Applications/MisNotas.app"
  cp -R "$APP" /Applications/
  echo "Instalada en /Applications/MisNotas.app"
fi
