#!/usr/bin/env bash
# Tiny Fold WADB helper APK (no Gradle). APK stays untracked.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/.local/opt/android-sdk}}"
BT="$(ls -d "$SDK"/build-tools/*/ 2>/dev/null | sort | tail -1)"
[ -n "$BT" ] || { echo "no build-tools in $SDK" >&2; exit 1; }
ANDROID_JAR="$SDK/platforms/android-34/android.jar"
[ -f "$ANDROID_JAR" ] || ANDROID_JAR="$SDK/platforms/android-36/android.jar"
[ -f "$ANDROID_JAR" ] || { echo "no android.jar" >&2; exit 1; }
JAVA_HOME="${JAVA_HOME:-$HOME/.local/opt/jdk}"
export JAVA_HOME PATH="$JAVA_HOME/bin:$BT:$PATH"

KS="${XRCTL_KEYSTORE:-$HOME/.android/debug.keystore}"
KSPASS="${XRCTL_KEYSTORE_PASS:-android}"
ALIAS="${XRCTL_KEY_ALIAS:-androiddebugkey}"

cd "$ROOT"
rm -rf build
mkdir -p build/gen build/classes build/dex

aapt package -f -m -J build/gen -M AndroidManifest.xml -S res -I "$ANDROID_JAR"
find src build/gen -name '*.java' >build/sources.list
javac -source 8 -target 8 -bootclasspath "$ANDROID_JAR" -classpath "$ANDROID_JAR" \
  -d build/classes @"build/sources.list"
d8 --lib "$ANDROID_JAR" --output build/dex $(find build/classes -name '*.class')
aapt package -f -M AndroidManifest.xml -S res -I "$ANDROID_JAR" -F build/unsigned.apk
( cd build/dex && zip -q -u ../unsigned.apk classes.dex )
zipalign -f -p 4 build/unsigned.apk build/aligned.apk
apksigner sign --ks "$KS" --ks-pass "pass:$KSPASS" --ks-key-alias "$ALIAS" \
  --key-pass "pass:$KSPASS" --out build/wadb-helper.apk build/aligned.apk
apksigner verify --verbose build/wadb-helper.apk >/dev/null
echo "apk $ROOT/build/wadb-helper.apk"
ls -l "$ROOT/build/wadb-helper.apk"
