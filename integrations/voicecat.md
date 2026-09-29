# Voicecat (external)

https://github.com/atacolak/voicecat (`~/workspace/voicecat`).

## What it provides to XR

The **call**: microphone PCM in, spoken reply out. speech-core is the
ear and mouth; a headed OMP TUI is the brain. Voicecat is the phone
line between them.

Long-term, voice is primary XR input for dictation, commands, and
delegation.

## How to run

See the Voicecat README. Short form on sfub:

1. Headed OMP TUI with collab autoStart (writes a link file)
2. speech-core + speech-out already up
3. `cd python && VOICECAT_ENV=$HOME/.config/voicecat/runtime.env .venv/bin/sdc-pipecat-webrtc`

Desk is `/desk`. Phone APK is a Graphene call-route client on
`/ws-phone`, not a Fold DeX launcher.

## Interfaces XR cares about

- 16 kHz PCM in / progressive PCM out
- committed user turns (not partials as commands)
- barge-in
- one live audio path at a time (Voicecat charter)

## What XR expects

A reliable spoken turn loop that can eventually issue *semantic* XR
commands (see `docs/spatial-agent.md`), not only keystrokes into
Android.

## Owned by Voicecat

Transport, PCM hop, collab guest, desk/phone route.
