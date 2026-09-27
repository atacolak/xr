# Input direction

Long-term input is multimodal:

    voice
    direct hand interaction
    physical pointer / touchpad
    keyboard when useful
    agent delegation

Voice is expected to become primary for dictation, commands, and
delegation. Do not implement ASR in the XR repo.

## What exists today (elsewhere)

- **Voicecat** — the call. PCM in, spoken reply out. Own repository.
- **speech-core** — ear and mouth (VAD, ASR, turn-close, TTS leftover).
  Own repository.
- **Herdr** — terminal runtime on sfub. Fold reaches it with
  `mosh -p 60022 sfub -- herdr`.
- **herdr-paste** — semantic paste into a Herdr pane (clipboard / later
  STT), not synthesized keystrokes. Lives under `fold-thinclient/scripts/`.
- Fold Termux extra-keys for the human keyboard row.

Hand tracking is eventual, not now.

## XR's job

XR should consume voice and agent interfaces, not absorb those codebases.
Contracts: `integrations/voicecat.md`, `integrations/speech-core.md`,
`integrations/herdr.md`.

Pixel/touch synthesis remains an escape hatch for legacy 2D apps. Prefer
semantic scene actions once a spatial runtime exists (`docs/spatial-agent.md`).

## Sunlight cursor (Luma Ultra, optical see-through)

Observed outdoors: the stock Android / DeX mouse cursor becomes extremely
hard or impossible to acquire in bright sunlight.

### Stock Samsung / DeX (current workaround)

On this Fold / One UI 8.5:

    Settings
      → Accessibility
      → Vision enhancements
      → Pointer size and colour

For first human tests, use the **largest** pointer and a **highly
saturated, high-luminance** colour (yellow, lime, or magenta — not a
thin black-outlined arrow).

On optical see-through OLED, black pixels emit nothing and do not
occlude the real scene. A conventional black outline does not create a
local hole in the world; visibility is emitted luminance, area, and
motion.

`pointer_speed` (AOSP `Settings.System`) is acceleration, not size. Do
not treat it as a visibility control.

`scripts/xrctl cursor status` dumps pointer-related secure/system/global
keys **read-only**. Do not wire `xrctl cursor sunlight` until a specific
Samsung key is identified and shown reversible on this device. Blind
writes to private SettingsProvider keys are not allowed.

### Future XR-native cursor (do not build in the recorder task)

A normal tiny desktop arrow is not sufficient outdoors. A custom XR
cursor should investigate:

- significantly larger angular size
- high-emission *area* rather than thin lines
- ring / reticle option
- bright saturated colour
- motion-acquisition bloom/halo
- temporary enlargement while moving
- temporary emphasis after reacquisition / inactivity
- optional trailing/comet cue during motion
- brightness tied to ambient/perceptual conditions where possible
- interaction with global electrochromic dimming

Visibility on optical see-through comes from emitted luminance, area,
motion, and contrast — not from a black backing.
