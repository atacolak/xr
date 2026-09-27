# Tracking

Observed via VITURE libglasses **2.4.0** on Luma Ultra, USB `pid=0x1104`.

## What we actually saw

- USB open + `create ok` after privilege READY (v10 also claimed
  already-plugged glasses without a replug).
- First pose logged; "pose stream live".
- Path: Carina VIO (`deviceType=2`).
- 3DOF (orientation only) at first, then a later log of 6DOF
  (position/parallax on). That upgrade is an observation.
- UxSpace exposed PINNED vs spatial/world-relative panel modes. The
  *feeling* of world-lock is a human judgement.

## What this is not yet

- Not a characterized 6DOF accuracy study.
- Not a Linux/OpenXR Luma tracking path.
- Not SLAM we own. Carina is vendor code inside the proprietary SDK.
- Not something to re-implement in this consolidation task.

The next tracking question is in `NEXT.md`: the cleanest path from Luma
Ultra rendering/tracking into a Linux XR stack, after looking at existing
work.
