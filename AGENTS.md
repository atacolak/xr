# XR workspace rules

This is the control repository for XR work. It is not a monorepo for every
XR-adjacent project. Keep independently useful software in its own repository
and point at it from `components.toml` and `integrations/`.

Do not resume UxSpace feature development from this workspace. UxSpace is a
preserved experiment and reference implementation. See `experiments/uxspace.md`.

Do not start Stardust installation, compositor work, hand tracking, or ASR
unless the current task explicitly says to.

`scripts/xrctl` is the machine-development channel to the Fold. Prefer it over
ad-hoc SSH/ADB one-liners so transport assumptions stay in one place.

---

## XR DEVICE / DEVELOPMENT INVARIANTS

- The primary mobile XR target is a stock Samsung Fold + optical XR glasses.
- Do not root, wipe, unlock, or replace the operating system unless explicitly instructed.

- Android Wireless Debugging pairing is DURABLE STATE.
- Pair once per ADB identity and preserve that identity.
- Do not repeatedly ask the human for pairing codes because the development process
  discarded its own credentials.

- NEVER casually delete:
  - ADB private identities / certificates
  - app-private persisted pairing state
  - Android development signing identities

- Iterative APK development must preserve application state whenever possible:
  - stable package name
  - stable signing certificate
  - `adb install -r`
  - never uninstall/reinstall merely to deploy an iteration
  - never `pm clear` unless an explicit state reset is required

- An application that has legitimately received WRITE_SECURE_SETTINGS from shell may
  manage `adb_wifi_enabled`.
- The desired bootstrap model on this development device is:
  PAIR ONCE -> PRESERVE IDENTITY -> ENABLE WIRELESS DEBUGGING WHEN NEEDED ->
  DISCOVER THE CURRENT ENDPOINT -> RECONNECT.

- The rotating Wireless Debugging connection port is a LOCAL DEVICE CONCERN.
- Remote agents must not chase Android's rotating port across the network.
- Discovery and reconnection belong beside the Android device.

- Never use high-process-count localhost port scanning to discover Android ADB.
- Never recreate the parallel scanner that previously caused Android/Samsung to kill the
  Termux UID.
- Prefer persisted state, mDNS/platform discovery, bounded retries, and sequential
  fallback behavior.

- Current human terminal channel:
      Fold -> Mosh -> sfub -> OMP / Herdr

- Current machine-development channel:
      sfub -> XR device harness -> Android

- The exact transport is replaceable.
- Do not leak transport-specific assumptions into every XR project.

- IF AN AGENT CAN OBSERVE A FAILURE MECHANICALLY, THE HUMAN MUST NOT BE THE ITERATION LOOP.

- Agents own:
  - build
  - deploy
  - install/update
  - launch
  - process-health checks
  - logcat collection
  - dumpsys inspection
  - screenshots
  - crash classification
  - patch/rebuild/redeploy iteration

- Do not tell the human to install an APK, open it, discover that it crashes, and paste a
  stack trace when the device is remotely addressable.

- Human involvement begins where genuine human involvement is required:
  - Android trust / consent boundaries
  - physical manipulation of hardware
  - wearing the glasses
  - subjective optical/perceptual judgement
  - comfort
  - perceived world-lock stability
  - binocular fusion
  - other observations not recoverable through instrumentation

- Proprietary SDKs and private device credentials remain untracked.

---

## Console / recorder

- `console/` is for small XR operational surfaces. Do not dump Voicecat,
  speech-core, Herdr, or OMP into it.
- The field recorder package `sh.colak.xrconsole.recorder` is a durable
  identity (stable name + debug signing + `adb install -r`).
- Load VITURE native code only when a recording starts. A failed glasses
  path must not kill process launch.
- V1 records Luma Ultra front RGB + microphone only. Do not add tracking
  cameras, pose, IMU, ASR, or annotation unless the task says so.
