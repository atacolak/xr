# xr

Control workspace and lab for a portable spatial-computing environment around
optical XR glasses and mobile/Linux compute.

Hardware shape: glasses + phone + optional small physical input + power bank.

## Camera tool

[**XR field recorder**](console/recorder/) — live viewer + record of the
VITURE Luma Ultra front RGB (measured **1080p / 2.07 MP**) and a selectable
microphone. Preview also cycles the two Carina grayscale tracking cameras
(measured **640×480** each, or **L|R** side-by-side). Package
`sh.colak.xrconsole.recorder`.

[![Luma Ultra L|R grayscale tracking cameras in XR field recorder on Fold DeX](console/recorder/docs/ui.png)](console/recorder/)

Try it:

```sh
console/recorder/build.sh
scripts/xrctl deploy console/recorder/build/outputs/apk/debug/xr-console-recorder-debug.apk \
  --package sh.colak.xrconsole.recorder
scripts/xrctl launch sh.colak.xrconsole.recorder
```

Needs the untracked VITURE `libglasses.so` (see `console/recorder/README.md`).
Do not commit the APK — it embeds that proprietary `.so`.

This repo also holds device knowledge, `scripts/xrctl`, experiments, and
integration contracts. Independent components are listed in `components.toml`.

## What is here

- [`console/recorder/`](console/recorder/) — Fold + Luma Ultra field recorder
- `AGENTS.md` — durable device and development invariants
- `components.toml` — pointers to the real component repositories
- `devices/` — facts about the current Fold + Luma Ultra target
- `docs/` — ADB, Android iteration, architecture, input, spatial agents
- `scripts/xrctl` — generic Fold-local Android device harness
- `experiments/` — UxSpace postmortem, next systems to study, and `monado-viture/`
  (the VITURE Luma Ultra OpenXR driver on Linux)
- `integrations/` — contracts with Voicecat, speech-core, and Herdr
- `tools/herdr-launcher/` — tiny DeX-visible HERDR launcher APK
- `fold-thinclient/` — existing Termux/WADB glue (preserved)
- `console/` — small XR operational surfaces

## Current vs next

See [NEXT.md](NEXT.md).

**Current work:** `experiments/monado-viture/` — Luma Ultra as a real OpenXR HMD
through Monado on Linux.

**Next frontier after that:** Stardust XR (`experiments/stardust.md`).
