# Device: Fold5 + Luma Ultra

Primary mobile XR target. Stock Android. Do not root, wipe, unlock, or
replace the OS unless explicitly instructed.

Do not record IMEI, serial, MAC, pairing codes, private keys, or secrets
in this file. Wireless Debugging connection ports rotate; do not treat a
port you saw in one session as durable.

## Phone

- Samsung Galaxy Z Fold5
- Model: SM-F946B (`q5q` / `q5qxxx` in ADB)
- Storage: 512 GB
- Android 16
- One UI 8.5
- Stock / no root
- Termux username (app UID name): `u0_a368`

## Glasses

- VITURE Luma Ultra
- USB vendor `0x35CA`
- Observed product IDs on this unit: `0x1104` (tracking/control, preferred)
  and `0x1102` (second VITURE interface). Luma Ultra also documents `0x1101`.
- Front RGB camera USB on this unit: vendor `0x0C45` product `0x636B`
  (Sonix Technology “USB 2.0 Camera”; VITURE SDK `xr_camera_provider`).
  Verified via Fold `lsusb` 2026-09-27. Phone camera is a different device.
- **RGB capture megapixels (measured, not marketed):** **2.07 MP**.
  VITURE does not publish a sensor MP rating, FOV, or part number. On this
  unit the USB Video Class descriptors advertise both video and still-image
  sizes up to **1920×1080** and nothing larger (no 2K/4K, no 5/8/12 MP still).
  The Android SDK stream is fixed at MJPEG 1920×1080@30. USB isochronous
  max-packet 5120 is USB 2.0 High-Speed, the usual ceiling for this Sonix
  FHD webcam-controller family (`0x0C45:0x636B` also appears on generic
  “1080P USB 2.0 Camera” products). Usable capture is therefore 1080p /
  ~2 MP. Sensor silicon could in principle be a higher-res die that is only
  exposed at 1080p; nothing on the bus, in the SDK, or in public specs
  supports that claim.
- Dual grayscale tracking cameras stay on the VITURE control USB
  (`0x35CA:0x1104`) for Carina/6DoF; they are not Android UVC RGB inputs.
- Native SDK used during UxSpace bring-up: **libglasses 2.4.0**
  (proprietary; untracked; download from VITURE developer portal).

## Network / development topology

Current channels (transport is replaceable; do not bake NetBird into
every project):

    Human terminal:
      Fold -> Mosh (UDP 60022) -> sfub -> OMP / Herdr

    Machine development:
      sfub -> SSH `Host fold` -> Termux sshd :8022 -> Fold-local adb -> Android

- Overlay: NetBird between Fold and sfub
- SSH host alias on sfub: `fold` (Termux sshd, port **8022** unless config changes)
- SSH host alias on Fold: `sfub`
- Mosh on sfub is pinned to UDP **60022** so overlay/firewall stay simple
- Fold-local `adb-wifi` discovers the *current* Wireless Debugging endpoint
  beside the device. Remote agents must not chase that port on the LAN.

Exact overlay IPs live in local SSH config, not here.

## Termux (Play Store)

- Package: `com.termux`
- Observed: `versionName=googleplay.2026.06.21` `versionCode=141`
- Boot receiver is built into this Play build. Do **not** install F-Droid Termux:Boot.
- `RunCommandService` / `com.termux.permission.RUN_COMMAND` are **not**
  present in this Play build.
- Supported external execute path: `TermuxFileReceiverActivity` `ACTION_SEND`
  of a `Patterns.WEB_URL` string, which runs `~/bin/termux-url-opener`.
- Widget shortcuts exist (`~/.shortcuts/`) and are **not** DeX Apps entries.

## Persistent identities

These are durable state. Pair once, preserve:

- Termux `adb` key under Termux home
- Android Wireless Debugging pairing with that ADB identity
- App signing certificates used for iterative `adb install -r`
- `WRITE_SECURE_SETTINGS` grant on development packages, once given from shell

New Wi-Fi networks can still show Android's "Allow wireless debugging" prompt.
That is an OS trust boundary, not a pairing-code loop.

## Display modes observed on the Luma (Android Display)

Logged during UxSpace bring-up. Current mode was **1920x1080 @ 60 Hz**.
Android advertised:

| mode | notes |
|---|---|
| 1920x1080 @ 60 | observed current |
| 1920x1080 @ 90 | advertised |
| 1920x1200 @ 60 | advertised |
| 1920x1200 @ 90 | advertised |
| 1920x1200 @ 120 | advertised |

Whether 1920x1200@120 is the mode we *should* request, and whether the
Fold + Luma actually lock it from a Presentation, is still experimental.

## Tracking observations

Carina VIO via libglasses 2.4.0:

- Opened USB `vid=0x35CA pid=0x1104` without replug once privilege was READY
  and `syncGlasses()` ran.
- First poses arrived; path logged as Carina VIO deviceType=2.
- Session upgraded 3DOF (orientation) to 6DOF (position/parallax) after
  some running time. That upgrade is observed, not fully characterized.
- PINNED vs world-relative panel behavior was experienced in UxSpace.
  Perceived world-lock quality is a human judgement, not a log line.

## Known setup quirks

- Do not scan localhost with a high-process-count port scanner to find ADB.
  That previously caused Samsung/Android to kill the Termux UID.
- `adb devices` can show a stale `offline` endpoint next to the live
  `device`. Operate on the `device` serial; drop the offline one.
- Extra-keys and boot scripts live in Termux home; they are not this git
  tree. Canonical extra-keys layout is in `docs/android-development.md`.
