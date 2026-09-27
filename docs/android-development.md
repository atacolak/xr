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
scripts/xrctl device status
scripts/xrctl adb ensure
scripts/xrctl deploy path/to/app-debug.apk --package com.example
scripts/xrctl smoke com.example
scripts/xrctl logs com.example
scripts/xrctl screenshot
scripts/xrctl display
```

`xrctl` does not build UxSpace or any other app. Wrappers may call it.

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

Canonical extra-key row for the human Mosh session:

```
extra-keys = [['ESC','/','-','HOME','UP','END','PGUP'],['TAB','CTRL','ALT','LEFT','DOWN','RIGHT','PGDN']]
```

Then `termux-reload-settings`. This is Termux UX, not an Android app
feature.

## Pairing (rare)

Only when the identity is actually missing:

1. Fold: Developer options -> Wireless debugging -> Pair with pairing code
2. `scripts/xrctl adb pair <code> <pairing-port>`

Do not ask for this because a script deleted `~/.android` in Termux.
