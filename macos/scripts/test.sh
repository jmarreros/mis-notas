#!/bin/zsh
# Ejecuta los tests. Sin Xcode, hay que indicar dónde está el plugin de macros de swift-testing.
set -e
cd "$(dirname "$0")/.."
source scripts/sdk.sh
PLUGIN="$(xcode-select -p)/usr/lib/swift/host/plugins/testing"
if [[ -d "$PLUGIN" ]]; then
  swift test -Xswiftc -plugin-path -Xswiftc "$PLUGIN" "$@"
else
  swift test "$@"
fi
