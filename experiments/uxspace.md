# UxSpace experiment (postmortem)

Preserved experiment and reference implementation.
Stop feature-polishing it from this workspace.

- Fork: https://github.com/atacolak/uxspace
- Preserved branch: `fold5-luma-ultra`
- Branch head (at preservation): `2a4840a3d695c3a7191846e35108b3eb8bc67994`
- Upstream base: `darkclad/uxspace` `main` `2fefa68f8e24590756e6c68cc11276386abe0bd2`
- Local checkout: `~/workspace/uxspace` (do not delete)
- Device: Samsung Galaxy Z Fold5, SM-F946B, Android 16, One UI 8.5, stock
- Glasses: VITURE Luma Ultra

## Why we evaluated it

It was a real Android + VITURE spatial-shell PoC we could run on the
actual Fold + Luma instead of theorizing. The goal was to feel tracking,
pinning vs world-relative panels, and to establish a remote Android
iteration path. That succeeded. The implementation is currently too
weak to be the long-term spatial surface.

## What worked

- Fold development path: Termux sshd, NetBird, Mosh to sfub, Fold-local adb
- Wireless Debugging pairing as durable identity
- Privileged / shell-UID bootstrap (embedded ADB helper)
- `WRITE_SECURE_SETTINGS` -> `adb_wifi_enabled` on known networks
- Remote harness (`scripts/fold-dev`) that builds, deploys, launches,
  classifies crashes without asking the human to paste stack traces
- Luma USB open (`0x35CA`/`0x1104`), libglasses 2.4.0, Carina VIO
- First pose + live pose stream; observed 3DOF then 6DOF
- PINNED vs spatial/world-relative panel behavior was experienced
- After v10: already-connected glasses claimed on privilege READY
  without a replug; process stayed alive (MainActivity resumed)

## What broke (implementation defects)

These were bugs in *this* codebase / packaging, subsequently patched
on `fold5-luma-ultra`:

- `extractNativeLibs=false` vs 16 KB ELF / zip-align caused install rollback
- Loading VITURE native SDK before privilege READY aborted launch
- `DisplayListener` never fires for an already-attached VITURE display
- Privilege listener only redrew the wizard (`renderStatus`), did not
  `syncGlasses()`
- HeadTracking `String.format` `%d` consumed a Float (first-pose crash)
- Fold RenderThread / HWUI destroyed-mutex abort on Presentation window
- API 33 exported receiver flags; FGS adaptive icon issues
- `fold-dev` `aapt | head` tripped `pipefail` and skipped install metadata

## Architectural limitations

Not "one more patch":

- UxSpace is an Android app drawing floating windows onto a Presentation
  display. It is not a spatial display server.
- No shared scene graph other apps or agents can query.
- Window management, input, and anchoring live inside one process.
- Privileged ADB helper is bring-up infrastructure, not an XR runtime.
- Vendor tracking is behind a proprietary SDK we must not redistribute.

## What felt weak

Subjective, but consistent with the architectural limits: incomplete
spatial window management, thin interaction model, no agent-native
scene access, world-lock quality still a perceptual judgement. The PoC
was useful because it let us *feel* those problems.

## Experimental / not yet investigated

- Forcing 1920x1200@120 and whether it sticks
- Linux / OpenXR path for Luma display + tracking
- Hand tracking, persistent environments, voice-first control
- Optical/world-lock quality as a measured property

## Ideas worth retaining (generic)

- Device-local Wireless Debugging discovery; never chase the port remotely
- Pair-once / preserve ADB identity
- Iterative `adb install -r` with stable signing
- Agent-owned build/deploy/launch/classify loop (`fold-dev` -> `xrctl`)
- Do not load vendor native code until the rest of the process is READY
- Claim already-connected devices; do not wait for a replug event
- Crash dumps readable without a working GUI

## How to reproduce later

```sh
cd ~/workspace/uxspace
git checkout fold5-luma-ultra
# VITURE SDK remains untracked; place libglasses per Android/glasses gitignores
./scripts/fold-dev smoke
# or, once an APK is built:
#   ~/xr/scripts/xrctl deploy Android/app/build/outputs/apk/debug/app-debug.apk \
#     --package com.uxspace
#   ~/xr/scripts/xrctl smoke com.uxspace
```

Proprietary `.so` / headers stay gitignored. APKs, logcat, and
screenshots stay under `Android/.dev/` (gitignored).
