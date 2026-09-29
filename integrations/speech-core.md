# speech-core (external)

https://github.com/atacolak/speech-core (`~/workspace/speech-core`).

## What it provides to XR

Speech runtime: VAD, ASR, turn-close, leftover TTS. The ear and mouth
behind Voicecat.

## How to run

Host units on sfub (see speech-core README): `ata-speech-core.service`,
`ata-speech-out.service`, `ata-speech-tts.service`, optional aligner.

## Interfaces XR cares about

- `transcript_committed` as the command/dictation boundary
- barge-cut of leftover speech
- speech-out leftover websocket

## What XR expects

Stable turn semantics (a closed turn is immutable) so spatial commands
are not issued from flickering partials.

## Owned by speech-core

Models, daemons, protocol, TTS.
