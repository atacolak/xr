# fold-thinclient

Preserved Fold-side glue. Not a place to absorb Voicecat, UxSpace, or Herdr.

- `scripts/herdr-sfub` — `mosh -p 60022 sfub -- herdr`
- `scripts/mosh` — pin UDP 60022 for Host sfub
- `scripts/termux-url-opener` — Play Store Termux FileReceiver execute path (HERDR sentinel)
- `scripts/herdr-paste` / `fold-herdr-paste` — semantic paste into Herdr
- `scripts/start-services` — Play-Termux boot (do not install F-Droid Termux:Boot)
- `wadb-helper/` — tiny app to re-enable `adb_wifi_enabled` after boot and Wi-Fi reconnect.
  Source in-tree; APK untracked. Package `sh.colak.fold.wadb`. One-time:
  `adb shell pm grant sh.colak.fold.wadb android.permission.WRITE_SECURE_SETTINGS`
  then open the app once. Does not skip Android's per-network Allow dialog.
