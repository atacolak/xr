# XR field recorder (V1)

Package: `sh.colak.xrconsole.recorder`

V1 records **only**:

1. VITURE Luma Ultra **front RGB** camera (SDK MJPEG 1920×1080@30)
2. One selected Android audio input, encoded as AAC 48 kHz mono

The microphone selector enumerates current Android input devices and offers an
explicit **Auto / System Default** choice. Explicit choices persist by semantic
identity (device type, product name, and address), are resolved again when a
recording starts, and are verified against `AudioRecord.getRoutedDevice()`.
Requested and actual routes remain distinct in metadata. A missing explicit
device blocks recording; disconnecting it stops the active recording rather
than silently substituting another microphone.

Stereo tracking cameras, pose, IMU, ASR, GPS, and annotation are out of
scope. Timestamps use one monotonic origin (`elapsedRealtimeNanos`) so
those streams can be added later without rewriting the architecture.

Do not load VITURE native code until a recording actually starts. The UI
must come up even if the glasses path fails.

## Operation

Idle: **RECORD**, microphone selector. Recording: **● REC**, elapsed time,
RGB format, requested and actual mic, remaining storage, **STOP**.

Foreground service types: `camera|microphone|connectedDevice`. Recording
survives UI background, fold, display off, DeX, Termux/Mosh. Notification
shows duration and a STOP action. Optional Quick Settings tile **XR REC**.

On fatal errors (glasses RGB gone, encoder death, mic death, storage
&lt; 500 MB) the current segment is finalized and the app stops in an
explicit error state. It does not keep writing corrupt media.

## Storage

```
Movies/XRConsole/Recorder/<yyyyMMdd-HHmmss>/
  session.json
  events.jsonl
  <yyyyMMdd-HHmmss>_000.mp4
  ...
```

Fallback if public Movies is not writable:

```
Android/data/sh.colak.xrconsole.recorder/files/Movies/XRConsole/Recorder/...
```

Segments default to **12 minutes**. Gap-minimized rollover keeps the
encoder running and starts the next MP4 on a keyframe.

## Permissions

Runtime (grant once): `CAMERA`, `RECORD_AUDIO`, `POST_NOTIFICATIONS`.

USB: system permission dialog for the Luma RGB camera
(`vid=0x0C45 pid=0x636B`). Already-attached glasses are claimed; do not
replug just because an attach callback was missed.

## Codec / bitrate

| | configured target |
|---|---|
| RGB input | VITURE SDK MJPEG ~1920×1080@30 |
| Video | hardware HEVC, fallback H.264, 12 Mbps |
| Audio | AAC-LC 48 kHz mono 128 kbps |

`session.json` records available inputs at start, selection mode, requested and
actual routed devices, route-match status, PCM sample count, peak and RMS, and
measured bitrate / MB-min / GB-hour / fps. `events.jsonl` records route changes.

As of 2026-09-29 the current APK builds, but the active hardware verification
run is blocked before ADB because the Fold Termux SSH endpoint is unreachable
from sfub (`No route to host`). Consequently the target codec/fps/bitrate,
Luma microphone exposure, segmentation, background survival, and 30-second
capture remain unverified; do not treat configured targets as measurements.

## Development

Proprietary VITURE `.so` / headers stay untracked. Build reuses the
UxSpace vendor tree:

```
VITURE_SDK_LIBS=$HOME/workspace/uxspace/Android/glasses/src/main/jniLibs
VITURE_SDK_INCLUDE=$HOME/workspace/uxspace/Android/SDK/linux-x86_64/include
```

```sh
console/recorder/build.sh
scripts/xrctl deploy console/recorder/build/outputs/apk/debug/xr-console-recorder-debug.apk \
  --package sh.colak.xrconsole.recorder
scripts/xrctl smoke sh.colak.xrconsole.recorder   # process-alive
console/recorder/smoke.sh                         # 30s record + ffprobe
```

Auto-record (agent smoke, no UI tap):

```sh
scripts/xrctl adb shell am start -n sh.colak.xrconsole.recorder/.MainActivity \
  -a sh.colak.xrconsole.recorder.SMOKE --ei duration_s 35 --ei segment_s 20
```

Never uninstall / `pm clear` to iterate. Stable package + debug
keystore + `adb install -r`.
