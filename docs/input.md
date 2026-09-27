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
