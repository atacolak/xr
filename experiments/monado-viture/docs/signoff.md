# Sign-off status

What is proven, what is not, and what remains — for the driver and the hardware-to-OpenXR
presentation path. Every claim here names the evidence; the *method* is in `verification.md`.

Last updated after the session that fixed the camera/VIO chain and ran hello_xr end to end.

## Signed off

**Display and presentation.** The panels take a true stereo pair and the runtime drives them.

- Panel mode applied and confirmed by the vendor API: `set(0x45, 3840x1200@90-sbs) -> ok`, X
  driving `3840x1200@90`.
- `hello_xr` reaches `XR_SESSION_STATE_FOCUSED`; Monado creates swapchains for **view 0 and view
  1** at 2688x1680 (the recommended size for 1920x1200 per eye at 1.4x).
- Captured mid-session from the panels: 99.7% lit, both halves populated, `|L-R| 25.7` — two
  genuinely distinct views, not a duplicated frame.
- Independent of Monado, the standalone presenter was verified the same way earlier (both halves
  populated, parallax present, band structure matching the scene).

**Pose, 6DoF.** The VIO runs and its output reaches OpenXR.

- Stereo camera frames reach the VIO: 743 frames at 24.8 fps in the corpus baseline; the driver
  logs `6DoF: 910 camera frames, 6600 samples, tracked=yes`.
- Translation is live and moves with the head: `pos -0.009 +0.277 +0.256 m` changing between
  samples while worn.
- Quiet baseline (30 s, glasses untouched): position sd 0.4 mm on x, orientation sd 0.007 deg on
  pitch, drift **+0.0 deg/min** after the startup transient. The apparent 26 deg "drift" is the
  transient: the origin is identity at t=0 and the VIO reports its true gravity-referenced
  attitude by t=1.2 s.
- `tracked=yes` is advertised, from evidence (frames arriving) rather than from the SDK flag.

**Orientation correctness.** Quaternion end to end; the Euler reconstruction is gone.

- Offline guard: yaw 180 and pitch ±90 pass the conversion unchanged, and an unnormalised
  quaternion lands on the unit sphere without rotating — 35 checks, 0 failures, no hardware.
- `--flip-xy` and the axis-remap enum exist for measurement; identity is the configured default.

**Driver behaviour.**

- Selects 6DoF (`set_dof_type_carina(1)`), sets the panel mode, registers the Carina callbacks
  **before** `start()` and calls auto-exposure after it, recenters the origin on request.
- Advertises position tracking only when 6DoF is configured — it does not claim what it cannot do.
- Counters exposed as debug variables: pose samples, pose errors, unstable samples, last status,
  reported display mode.

**Environment and hygiene.**

- udev: the glasses (35ca) and the camera (0c45:636b) are both usable by the seat user; uvcvideo
  is unbound from the camera interface.
- Display layout: the glasses and the desktop never share an origin, and `display-mode off` leaves
  the glasses dark with the desktop as the only active output.
- `scripts/repo-sanity` clean; all work pushed.

## Open — blocked on the operator

1. **Translation direction.** Forward/back was reported inverted from inside the headset; only the
   forward component is now negated (orientation was verified correct, so negating the whole vector
   would have flipped left/right too). Needs one walk forward to confirm, plus a left/right check.
   `VITURE_FLIP_FORWARD=0` / `--no-flip-forward` give the raw value for comparison.
2. **One OpenXR game end to end** (BeamNG). The launcher's own gate asks for M0–M3; M0–M2 were
   demonstrated earlier and M3 is closed, so it is satisfied. This is the test that turns "hello_xr
   works" into "OpenXR support for these glasses exists".

## Open — known, not blocking

- **`status` never reports "stable" in 6DoF** (0 in 7198 samples). Vendor behaviour, not a defect
  of ours; handled by making TRACKED evidence-based.
- **Dynamic drift is unmeasured.** Every number above is with the glasses stationary. The corpus
  needs a session with real motion.
- **VIO scale is unverified.** `--pos-gain` (demo) exists to measure it against the floor
  graduations; a gain far from 1.0 would be a finding about the SDK, not a preference.
- **The presenter's window is override-redirect at 0,0.** It works because the layout keeps the
  outputs apart, but it should take an explicit position instead of relying on that.
- **The demo dies if the display layout changes under it** (its surface goes away mid-session).
- **`--src cb` is unused**: gravity-stable, placeholder-free, rock steady, but its quaternion is in
  the IMU's frame. Converting that basis is the shortest route to less drift.
- **`scripts/patch-monado.sh` reports "patch applied" without leaving the copies in Monado's tree**
  — a git operation after the copy reverts them, so the build silently uses stale sources. Copy
  `src/viture/*` into `src/xrt/drivers/viture/` explicitly and check the object timestamp.

## The claim being made

> OpenXR support for the VITURE Luma Ultra on Linux: a Monado driver that presents a real OpenXR
> application stereoscopically to the panels with working 6DoF head tracking.

Verified for `hello_xr`. The game run is the last item that stands between this and being stated
without qualification.
