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

Carina is vendor code inside the proprietary SDK. Accuracy is not yet
characterized. Linux/OpenXR tracking is the next question in `NEXT.md`.
