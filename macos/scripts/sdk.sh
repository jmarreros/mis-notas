# El SDK de macOS 27 de las Command Line Tools declara @State como macro y no incluye su plugin.
# Con el de macOS 26 SwiftUI compila sin Xcode. Se usa si no se indicó otro SDKROOT.
if [[ -z "${SDKROOT:-}" ]]; then
  for sdk in "$(xcode-select -p)/SDKs/MacOSX26.sdk" "$(xcode-select -p)/SDKs/MacOSX26.5.sdk"; do
    if [[ -d "$sdk" ]]; then export SDKROOT="$sdk"; break; fi
  done
fi
