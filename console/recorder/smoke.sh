#!/usr/bin/env bash
# Agent-owned recorder smoke: deploy, auto-record >=30s, pull, ffprobe.
# USB permission dialog is the one OS consent this loop cannot click.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
XR="$(cd "$ROOT/../.." && pwd)"
XRCTL="$XR/scripts/xrctl"
PKG=sh.colak.xrconsole.recorder
DURATION_S="${DURATION_S:-35}"
SEGMENT_S="${SEGMENT_S:-20}"
export JAVA_HOME="${JAVA_HOME:-$HOME/.local/opt/jdk}"
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/.local/opt/android-sdk}}"
export PATH="$JAVA_HOME/bin:$PATH"

OUT="${XRCTL_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/xrctl}/recorder-smoke"
mkdir -p "$OUT"

"$ROOT/build.sh"
APK="$ROOT/build/outputs/apk/debug/xr-console-recorder-debug.apk"
"$XRCTL" deploy "$APK" --package "$PKG"

echo "[smoke] grant runtime perms"
"$XRCTL" adb shell pm grant "$PKG" android.permission.CAMERA || true
"$XRCTL" adb shell pm grant "$PKG" android.permission.RECORD_AUDIO || true
"$XRCTL" adb shell pm grant "$PKG" android.permission.POST_NOTIFICATIONS || true

echo "[smoke] logcat -c, launch SMOKE duration=${DURATION_S}s segment=${SEGMENT_S}s"
"$XRCTL" adb shell logcat -c >/dev/null 2>&1 || true
"$XRCTL" adb shell am force-stop "$PKG" >/dev/null 2>&1 || true
sleep 1
"$XRCTL" adb shell am start -W -n "$PKG/.MainActivity" \
  -a "$PKG.SMOKE" --ei duration_s "$DURATION_S" --ei segment_s "$SEGMENT_S" \
  | tee "$OUT/launch.txt"

WAIT=$((DURATION_S + 25))
echo "[smoke] waiting ${WAIT}s for record+finalize"
sleep "$WAIT"

"$XRCTL" adb shell pidof "$PKG" | tee "$OUT/pid.txt" || true
"$XRCTL" logs "$PKG" >"$OUT/logs.txt" || true
"$XRCTL" adb shell logcat -d -v threadtime | grep -E "XRRecorder|FATAL EXCEPTION|Fatal signal" \
  | tee "$OUT/xrr.txt" >/dev/null || true

echo "[smoke] locate session"
"$XRCTL" adb shell run-as "$PKG" cat files/current-session.txt \
  >"$OUT/current-session.txt" 2>"$OUT/current-session.err" || true
cat "$OUT/current-session.txt" 2>/dev/null || true

SESSION_DIR="$(sed -n '1p' "$OUT/current-session.txt" 2>/dev/null || true)"
SESSION_DIR="${SESSION_DIR//$'\r'/}"
if [ -z "$SESSION_DIR" ]; then
  echo "[smoke] trying Movies/XRConsole/Recorder/current.txt"
  "$XRCTL" adb shell cat /sdcard/Movies/XRConsole/Recorder/current.txt \
    >"$OUT/current-session.txt" 2>/dev/null || true
  SESSION_DIR="$(sed -n '1p' "$OUT/current-session.txt" 2>/dev/null || true)"
  SESSION_DIR="${SESSION_DIR//$'\r'/}"
fi
echo "session_dir=$SESSION_DIR" | tee "$OUT/session_dir.txt"

if [ -n "$SESSION_DIR" ]; then
  "$XRCTL" adb shell ls -l "$SESSION_DIR" | tee "$OUT/ls.txt"
  "$XRCTL" pull "$SESSION_DIR/session.json" "$OUT/session.json" || true
  "$XRCTL" pull "$SESSION_DIR/events.jsonl" "$OUT/events.jsonl" || true
  "$XRCTL" adb shell ls "$SESSION_DIR" | tr -d '\r' \
    | python3 -c 'import sys; print("\\n".join(x for x in sys.stdin.read().splitlines() if x.endswith(".mp4")))' \
    >"$OUT/mp4-list.txt"
  index=0
  while IFS= read -r mp4; do
    [ -n "$mp4" ] || continue
    "$XRCTL" pull "$SESSION_DIR/$mp4" "$OUT/segment-$(printf '%03d' "$index").mp4" || true
    index=$((index + 1))
  done <"$OUT/mp4-list.txt"
  if [ -f "$OUT/segment-000.mp4" ]; then
    cp "$OUT/segment-000.mp4" "$OUT/sample.mp4"
  fi
fi

python3 "$ROOT/smoke_check.py" "$OUT"
