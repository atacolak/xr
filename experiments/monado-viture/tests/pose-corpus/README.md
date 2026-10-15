# Pose replay corpus

Recorded sessions used to regression-test the pose path with no hardware. Replay them with:

    tools/headtrack-demo.py --pose-file <file> --6dof --world room

What replay proves and does not prove is in `docs/verification.md`: it exercises the *consumer*
(the validity gate, the quaternion conversion, the reference grounding) deterministically. It can
never say anything about the device — the poses are recorded, so the VIO's own accuracy still
needs the physical known-answer tests.

## What is here

- `still-6dof.jsonl` — 60 s, glasses untouched on the desk, 6DoF polled, 120 Hz. The VIO's quiet
  baseline: position sd 0.4 mm on x, orientation sd 0.007 deg on pitch, drift +0.0 deg/min after
  the startup transient. Useful as a regression baseline for the gate and the conversion.

## What is still missing, and why it matters

The corpus needs the awkward cases, and those have to be recorded while someone is wearing the
glasses:

- a **startup placeholder burst** (the SDK emits ~120 zeroed samples in the first second, and a
  burst on every replug) — this is what the gate exists for;
- a **fast turn past 180 deg**, and a **stall** — the pair that used to latch the gate and make the
  view refuse to turn past a certain angle;
- **sustained translation**, so the forward-axis sign stays fixed. The sign was inverted until it
  was measured on hardware; nothing offline can catch a regression in it.

Record with `tools/headtrack-demo.py --record <file> ...` while doing those things.
