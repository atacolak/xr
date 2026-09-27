# HERDR launcher

Tiny Android app whose only job is to appear as **HERDR** in the Samsung
DeX Apps list and start an interactive Fold -> Mosh -> sfub -> Herdr
session.

It is not an agent harness. OMP stays on sfub.

## Package

- `sh.colak.herdrlauncher`
- Activity: `sh.colak.herdrlauncher.MainActivity`
- Label: `HERDR`

## Why an APK

Termux widget / `~/.shortcuts` files are not first-class DeX Apps
entries. Play Store Termux `googleplay.2026.06.21` does **not** export
`RunCommandService`. The supported third-party execute path is:

    HERDR
      -> TermuxFileReceiverActivity ACTION_SEND
      -> extra text `https://herdr.colak.sh/launch`  (matches Patterns.WEB_URL)
      -> `~/bin/termux-url-opener`
      -> `mosh -p 60022 sfub -- herdr`

`termux-url-opener` is Fold-side glue (`fold-thinclient/scripts/termux-url-opener`).
It only treats the sentinel URL as HERDR; other URLs are not hijacked
into Herdr.

## Build / install

```sh
tools/herdr-launcher/build.sh
# then, from the XR repo root:
scripts/xrctl deploy tools/herdr-launcher/build/herdr-launcher.apk --package sh.colak.herdrlauncher
scripts/xrctl launch sh.colak.herdrlauncher
```

Uses the local Android debug keystore for iterative `adb install -r`.
Do not uninstall to redeploy. APKs are gitignored.

## Manual step

If Samsung requires dragging HERDR from DeX Apps onto the DeX desktop
or taskbar, that pin is a user action. The launcher entry itself must
already exist before asking for that.

## Verified on this Fold (stock, DeX active)

Play Store Termux `googleplay.2026.06.21` (`versionCode=141`):

- No `RunCommandService`. Execute path is FileReceiver `ACTION_SEND` of
  `https://herdr.colak.sh/launch` -> `~/bin/termux-url-opener`.
- `cmd package resolve-activity` resolves `sh.colak.herdrlauncher/.MainActivity`.
- Badging label is `HERDR`.
- Remote `am start` starts FileReceiver, then
  `TermuxActivityInternal` `ACTION_RUN` of the url-opener (`file:` URI).
- Launch happened on DeX display 8 / Desk (HoneySpace `SecondaryLauncher`
  and Dex taskbar were active). Termux came to foreground in freeform.
- TermuxActivity is `singleTask`. If Termux already has a task, RUN is
  delivered to it (`START_TASK_TO_FRONT`). A new mosh-client may not appear
  when an interactive Mosh session is already the Termux session.
- Pinning HERDR from DeX Apps onto the desktop/taskbar is a manual Samsung
  user action. The Apps entry itself is a normal MAIN/LAUNCHER activity.
