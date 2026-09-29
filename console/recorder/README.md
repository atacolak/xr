# XR field recorder (V1)

Package: `sh.colak.xrconsole.recorder`

![idle recorder UI on Fold DeX](docs/ui.png)

V1 records **only**:

1. VITURE Luma Ultra **front RGB** camera (SDK MJPEG 1920×1080@30)
2. One selected Android audio input, encoded as AAC 48 kHz mono

The microphone selector enumerates capture-capable Android inputs: built-in
mics, USB, wired headset, Bluetooth SCO/LE. Telephony RX, remote submix, and
other internal mix ports are omitted. Explicit choices persist by semantic
identity (device type, product name, and address), are resolved again when a
recording starts, and are verified against `AudioRecord.getRoutedDevice()`.
Requested and actual routes remain distinct in metadata. A missing explicit
device blocks recording; disconnecting it stops the active recording rather
than silently substituting another microphone.

Stereo tracking cameras, pose, IMU, ASR, GPS, and annotation are out of
scope. Timestamps use one monotonic origin (`elapsedRealtimeNanos`) so
those streams can be added later without rewriting the architecture.

The UI comes up even if the glasses path fails. Native camera code loads when
the foreground 16:9 preview starts, or when recording starts if preview is not
running.

## Operation

Idle: 16:9 RGB viewer (foreground only), glasses/RGB presence, **RECORD**
(dimmed until an RGB camera is connected), microphone selector. Recording:
**● REC**, elapsed time, RGB format, requested and actual mic, remaining
storage, **STOP**.

The 16:9 viewer shows the live front RGB stream only while the activity is
resumed. Backgrounding stops the preview camera immediately; an in-progress
recording keeps encoding without updating the view.

The VITURE camera SDK exposes a single stream: MJPEG 1920×1080@30. There is
no API to select another resolution or framerate. On open, the recorder also
parses USB Video Class frame descriptors and records whatever the hardware
advertises under `camera_modes` in `session.json`.

The app does not register as a USB default handler. Connecting glasses
does not open a “choose an app for this USB device” prompt. Presence is
observed from the live USB device list.

Foreground service types: `camera|microphone|connectedDevice`. Recording
survives UI background, fold, display off, DeX, Termux/Mosh. Notification
shows duration and a STOP action. Optional Quick Settings tile **XR REC**.

On fatal errors (glasses RGB gone, encoder death, mic death, storage
&lt; 500 MB) the current segment is finalized and the app stops in an
explicit error state. It does not keep writing corrupt media.

## Storage

Capture writes into app-specific storage so a crash still leaves a recoverable
source file:

```
Android/data/sh.colak.xrconsole.recorder/files/Movies/XRConsole/Recorder/<yyyyMMdd-HHmmss>/
  session.json
  events.jsonl
  <yyyyMMdd-HHmmss>_000.mp4
  ...
```

Each finalized segment is then published through MediaStore so Gallery can see
it:

```
Movies/XRConsole/Recorder/<yyyyMMdd-HHmmss>_NNN.mp4
```

Gallery indexes the MediaStore copy. The app-private file remains the
recoverable original. `session.json` records both `path` and `gallery_uri`.
`scripts/xrctl pull` uses `run-as` for the app-private path.

Segments default to **12 minutes**. Gap-minimized rollover keeps the
encoder running and starts the next MP4 on a keyframe.

## Permissions

Runtime (grant once): `CAMERA`, `RECORD_AUDIO`, `POST_NOTIFICATIONS`.

USB: permission is requested when the foreground preview or a recording
opens the RGB camera, not by registering as a USB default app. Already-attached
glasses are claimed from the live device list; do not replug just because an
attach callback was missed.

## Codec / bitrate

| | configured target |
|---|---|
| RGB input | VITURE SDK MJPEG ~1920×1080@30 |
| Video | hardware HEVC, fallback H.264, 12 Mbps |
| Audio | AAC-LC 48 kHz mono 128 kbps |

`session.json` records available inputs at start, selection mode, requested and
actual routed devices, route-match status, PCM sample count, peak and RMS, and
measured bitrate / MB-min / GB-hour / fps. `events.jsonl` records route changes.

Measured on the Fold with attached Luma Ultra, 2026-09-29:

- front RGB: MJPEG 1920×1080, hardware HEVC, 29.04–29.12 measured fps
- USB Video Class descriptors advertise MJPEG up to 1920×1080@30 and many
  smaller modes (1280×1024 down to 160×120, 5–30 fps). YUY2 at 1080p is 5 fps.
  Nothing above 1080p or 30 fps. The SDK still streams only 1920×1080@30 MJPEG.
- 35.3-second auto-route run: 1,020 frames in, 1,018 encoded, 1 dropped
- measured output: approximately 13.44 Mbps, 90.05 MB/min, 5.28 GB/hour
- two reduced-duration rollover segments independently contain HEVC + AAC
- Auto routed to `USB-Audio - VITURE Microphone`
- explicit VITURE USB mic matched the requested route and captured nonzero PCM,
  but its observed level was extremely low (peak 3, RMS 1.02)
- explicit Fold rear built-in mic matched and captured strong nonzero PCM
  (peak 32768, RMS 883.18)
- DJI Mic Mini enumerates as classic Bluetooth SCO. Preferred-device routing
  alone produced digital silence; modern communication routing was rejected;
  Samsung fallback SCO activation timed out. DJI validation remains open.

Manual STOP finalizes the current segment and publishes it to Gallery. Idle
resets the timer to `00:00:00`.

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
