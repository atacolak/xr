#!/usr/bin/env bash
# Build the XR field recorder APK. Proprietary VITURE SDK stays untracked.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export JAVA_HOME="${JAVA_HOME:-$HOME/.local/opt/jdk}"
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/.local/opt/android-sdk}}"
export ANDROID_HOME="$ANDROID_SDK_ROOT"
export PATH="$JAVA_HOME/bin:$PATH"
export VITURE_SDK_LIBS="${VITURE_SDK_LIBS:-$HOME/workspace/uxspace/Android/glasses/src/main/jniLibs}"
export VITURE_SDK_INCLUDE="${VITURE_SDK_INCLUDE:-$HOME/workspace/uxspace/Android/SDK/linux-x86_64/include}"
if [ ! -f "$VITURE_SDK_LIBS/arm64-v8a/libglasses.so" ]; then
  echo "VITURE SDK missing at $VITURE_SDK_LIBS/arm64-v8a/libglasses.so" >&2
  exit 1
fi
cd "$ROOT"
./gradlew --quiet assembleDebug
APK="$ROOT/build/outputs/apk/debug/xr-console-recorder-debug.apk"
ls -l "$APK"
echo "apk $APK"
