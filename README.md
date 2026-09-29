# xr

This repository is the control workspace and experimental lab for building a
portable spatial-computing environment around optical XR glasses and
mobile/Linux compute.

The long-term hardware shape is:

    glasses + phone + optional small physical input + power bank

with voice and agents eventually reducing or eliminating the keyboard.

This repo holds device knowledge, reusable development tooling, experiments,
architecture notes, and integration contracts. Individual components stay in
their own repositories. XR refers to them; it does not absorb them.

## What is here

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
- `console/` — small XR operational surfaces (field recorder, not a component dump)
- `console/recorder/` — Fold + Luma Ultra field recorder (`sh.colak.xrconsole.recorder`)

## Next frontier

See [NEXT.md](NEXT.md).

Active line of work is now **`experiments/monado-viture/`**: presenting the Luma Ultra
as a real OpenXR HMD through Monado on Linux, which is NEXT.md item 4 made concrete.
Stardust XR remains the frontier after that.

## Layout rule

UxSpace, Voicecat, speech-core, Herdr, and OMP remain independent projects.
This repository documents how XR uses them. `console/` is for tiny utilities
that only exist for this glasses+Fold stack; it does not absorb those repos.
