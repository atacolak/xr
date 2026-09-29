# Automated Android development loop

Origin: UxSpace `scripts/fold-dev`. The reusable parts now live in
`scripts/xrctl`. Project-specific Gradle lives in the project, not here.

## Preferred loop

    modify
      -> build          (project)
      -> deploy         (xrctl deploy <apk> --package <pkg>)
      -> launch         (xrctl launch <pkg>)
      -> observe        (pid, ActivityManager, logcat, screenshot, dumpsys)
      -> classify
      -> fix
      -> repeat

The human does not enter this loop until a perceptual or physical test
is required (glasses on face, world-lock, fusion, comfort, OS consent).

If an agent can observe a failure mechanically, the human must not be
the iteration loop.

## Commands

```sh
scripts/repo-sanity
scripts/xrctl device status
scripts/xrctl adb ensure
scripts/xrctl deploy path/to/app-debug.apk --package com.example
scripts/xrctl smoke com.example
scripts/xrctl logs com.example
scripts/xrctl screenshot
scripts/xrctl display
scripts/xrctl pull /sdcard/... ./local
scripts/xrctl cursor status    # read-only pointer settings
```

`scripts/repo-sanity` is local-tree hygiene. Run it before merge readiness.
It does not replace `xrctl` device checks.

Recorder V1 (`console/recorder`, package `sh.colak.xrconsole.recorder`) uses
the same harness. `console/recorder/smoke.sh` builds, `xrctl deploy`s, auto-
records ≥30s, pulls a sample, and ffprobes it. Do not ask the human to
install that APK or paste logcat.

Wrappers may call `xrctl`; project Gradle stays in the project.

## Diagnostics the agent should collect

- package / launcher activity resolution
- process PID (`pidof` / `dumpsys activity processes`)
- ActivityManager resumed/focused activity
- logcat since launch (`FATAL EXCEPTION`, `Fatal signal`, `FORTIFY`)
- native tombstones when a native abort is indicated
- screenshot (phone display; glasses Presentation may be a different display)
- dumpsys display / USB when the bug is glasses-related
- crash files the app itself writes, if any

Classification should be explicit: launch failed, process died, not
resumed, crashed, or stage-A alive.

## State preservation

- stable package name
- stable signing certificate (debug keystore is still an identity)
- `adb install -r -d -t` for iteration
- never uninstall/reinstall just to deploy
- never `pm clear` unless the task is an explicit state reset
- keep Wireless Debugging pairing identities

## Termux extra keys (Fold interactive)

Play Store Termux loads `~/.config/termux/termux.properties` when that
file exists. Put settings there (canonical copy:
`fold-thinclient/termux.properties`).

```
allow-external-apps = true
extra-keys = [['ESC','/','-','HOME','UP','END','PGUP'],['TAB','CTRL','ALT','LEFT','DOWN','RIGHT','PGDN']]
```

`allow-external-apps` is required for the DeX HERDR launcher
(FileReceiver `ACTION_RUN`). Then `termux-reload-settings`. Some
properties still need a Termux process restart.

## Pairing (rare)

Only when the identity is actually missing:

1. Fold: Developer options -> Wireless debugging -> Pair with pairing code
2. `scripts/xrctl adb pair <code> <pairing-port>`

Do not ask for this because a script deleted `~/.android` in Termux.
