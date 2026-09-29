# console/

Small XR operational surfaces for the Fold + glasses stack, operated through
`scripts/xrctl` (sfub → SSH `Host fold` → Termux → Fold-local adb).

## Contents

- [`recorder/`](recorder/) — V1 field recorder: Luma Ultra front RGB
  (measured **1080p / 2.07 MP**, SDK MJPEG 1920×1080@30; foreground-only 16:9
  preview) + selectable microphone. Package `sh.colak.xrconsole.recorder`.
  Recordings land in Gallery under `Movies/XRConsole/Recorder/` and keep a
  recoverable app-private copy. The RGB camera does not expose a higher
  resolution or framerate than 1080p@30. See `recorder/README.md` and
  `devices/fold5-luma-ultra.md`.
