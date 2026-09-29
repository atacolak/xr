# console/

Small XR-specific operational surfaces that belong to this XR system itself.

This is not a place to absorb independently useful software. Voicecat,
speech-core, Herdr, OMP, and UxSpace stay in their own repositories
(`components.toml`, `integrations/`).

## What belongs here

- Tiny Android/DeX utilities that only make sense on the Fold + glasses
  stack (field recorder, later XR-native overlays, etc.).
- Code that is operated through `scripts/xrctl` on the current machine
  development path: sfub → SSH `Host fold` → Termux → Fold-local adb.

## What does not belong here

- UxSpace feature work (preserved under `experiments/uxspace.md`)
- Voice / ASR / TTS (Voicecat, speech-core)
- Herdr / OMP agent harnesses
- Stardust, DisplayXR, hand tracking, or other next-frontier runtimes

## Contents

- [`recorder/`](recorder/) — V1 field recorder: Luma Ultra front RGB + selectable
  microphone. Package `sh.colak.xrconsole.recorder`. Recordings land in Gallery
  under `Movies/XRConsole/Recorder/` and keep a recoverable app-private copy.
