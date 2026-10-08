# The pose pipeline, and what grounds it

How a quaternion from the glasses becomes a rendered frame, what is measured versus
inferred, and where the world-lock comes from. Written to be audited: every number here has
a command beside it.

```
  libglasses (vendor SDK, closed)
        |  quaternion + position, ~120 Hz polled or ~800 Hz via callback
        v
  tools/viture-pose-dump        one JSON object per sample
        |                       {t, qw,qx,qy,qz, px,py,pz, yaw,pitch,roll, status, ok}
        v
  tools/headtrack-demo.py       the instrument
        |
        |-- sample_ok()          validity gate: drop the glitch, not the data
        |-- reference            capture pose at warm-up -> ground orientation AND position
        |-- quaternion path      q_rel = conj(q_ref) * q_now     (world-frame relative)
        |-- smoothing            15 ms exponential + 30 mdeg deadband, in quaternion space
        v
  tools/make-stereo-demo.py     the renderer (per-eye perspective, stereo pair, presenter)
        v
  tools/xpresent-gl             GPU scales the small frame into the 3840x1200 SBS surface
```

## Why there is a validity gate at all

The SDK emits **placeholder poses** — all three angles exactly zero. Measured: 120
consecutive samples in the first second of every session, all tagged `status=1`. The demo
applied every line verbatim, so a placeholder arriving while the head pointed well away from
the origin threw the view to a fixed direction for exactly one frame and then back. That is
the "split-second jump to the origin" reported from inside the headset.

`sample_ok()` keys on the glitch rather than on a flag, because the flags are not usable:

- **`status` cannot be used to reject samples.** In 3DoF the placeholders are `status=1`
  (120/120 correlated with the zeroes), but in 6DoF *every* sample is `status=1` — measured
  958/958 in a polled capture — good data included. An earlier version of this gate rejected
  on `status != 0` and therefore discarded the entire 6DoF stream: the view froze at the
  warm-up origin and the drop counter climbed at the sample rate.
- A sample within **60 deg and 1 m** of the last accepted one is taken as real. No head turns
  60 deg between samples, so a larger jump is corrupt. Measured worst genuine step in a live
  capture: 37.3 deg.
- A **sustained** different pose (20 consecutive samples) is adopted — that is a VIO reset or
  the frame moving under us, i.e. real. Placeholder runs are excluded from that path by
  requiring `status == 0` for adoption, so a 120-sample placeholder run can never become the
  new reference.

The counter is on the status line as `dropped`; a healthy run reads 0.

## Orientation: quaternions, and why the Euler path was a bug

The view rotation used to be rebuilt from `yaw, pitch, roll`. **That construction is singular
when the head pitches near ±90 deg**: yaw and roll then act on the same axis, the reported yaw
flips 180 deg and the view stops turning — reported as the head "getting stuck" looking up,
unable to pitch or roll further.

The SDK emits a quaternion (`qw, qx, qy, qz`) alongside the angles, so `Camera.from_quat()`
builds the rotation from it directly. Verified: it reproduces the Euler path **exactly**
(max matrix element difference 0.0000 over 478 real samples) and is exact across the singular
band where Euler collapses.

The rotation is also taken **relative to the reference in the world frame**
(`q_rel = conj(q_ref) * q_now`) rather than by subtracting Euler angles per axis. Per-axis
subtraction distorts the rotation whenever yaw and pitch are both large, which is a real
contributor to the view not feeling world-locked.

## Position, and how the world is grounded

Position comes straight from the SDK's VIO. Two things anchor it:

1. **`--reset`** puts the VIO origin at the head (`tools/viture-pose-dump --reset`).
2. **Reference grounding** subtracts the reference position captured at warm-up, exactly as
   the orientation is referenced. Without it a source that reports absolute height (the
   callback reports y ≈ 1.0 m) floats the whole scene under the viewer.

Live measurement, polled 6DoF, standing still then moving:
`pos -0.003 -0.170 -0.048 m`, `dropped 0`, `errs 0`, 85.9–90.0 fps, pose age 15–17 ms.

### The honest limits of grounding

**VIO is relative.** Visual-inertial odometry integrates; it has no absolute reference, so it
drifts, and there is no configuration of this code that removes that. What exists today:

| mechanism | status |
|---|---|
| re-anchor on demand (`SIGUSR1`, `--reset`) | works, instant, no warm-up flash |
| gravity stabilisation | the callback source is gravity-stable; the polled one is not observed stable |
| loop closure / absolute markers | **not implemented** |
| callback source (~800 Hz, gravity-stable, no placeholders) | frame is the IMU's, so orientation is permuted — see next |

The callback source is measured better in every way except one: 600/600 samples valid (no
placeholders), rock-steady while still, gravity-anchored at y ≈ 1.0 m. But its quaternion is in
the IMU's own frame, which is why switching to it made the view "move in weird places". Fixing
that basis change is the highest-value remaining work for world-lock, because it is the only
source that is observed not to drift.

For **BeamNG specifically** the requirement is weaker than it looks: a seated simulator needs
the head pose *relative to the cockpit*, re-referenced on demand, not absolute world position.
Drift then shows as slow motion of the cockpit rather than as a broken world. Repeated
`SIGUSR1` re-anchoring is the honest answer until cb is fixed or an absolute reference exists.

## Smoothing

15 ms exponential, plus a **30 mdeg deadband**. The deadband is the important half: it removes
sensor micro-jitter with *zero* lag, because ignoring a change smaller than the deadband costs
nothing. Smoothing is lag by definition, so it is kept light. Both now operate on the
quaternion.

Consequence worth knowing: the deadband is hysteresis. Small movements away and back can leave
the view a fraction of a degree from where it was. That is by construction, not drift, and
`--smooth 0 --deadband 0` removes it if the trade is not wanted.

## Measuring things on the panels

The panels are not required to test most of this. `--src synth` drives the whole chain with no
device, and a virtual display gives a real framebuffer to capture:

```sh
Xvfb :9 -screen 0 3840x1200x24 +extension GLX &
DISPLAY=:9 tools/headtrack-demo.py --seconds 30 --src synth --world room
# the presenter prints its window id; capture exactly that window
DISPLAY=:9 xwd -id <wid> -silent > /tmp/cap.xwd
```

Drawn coordinates and both halves can then be checked numerically. This is how the two
failures that only looked like "the renderer is broken" were found:

- a vertex behind the camera projected millions of pixels away because `project()` clamps z,
  and Pillow painted that face over the whole frame — the flat grey wash;
- refactoring the projection to numpy changed its return type to an `ndarray`, and Pillow's
  `polygon()` on this version draws a numpy-coordinate polygon as an **outline only, no fill,
  and no error** — every filled surface silently became a thin line. Coordinates and culling
  were all provably correct; it took rendering a frame and *looking at it* to find.

## What is measured vs inferred

Measured on hardware: swapchain/session geometry (M0/M1), panel mode and SBS timing, pose rate
and age, dropped/error counters, translation magnitudes, the placeholder statistics above, and
the parity of the quaternion and Euler paths on real samples.

Inferred: that the Euler singularity is what the operator hit when looking up. The capture
never reached past 29.5 deg pitch, so the mechanism is argued from the symptom plus the known
singularity, not reproduced. The fix removes the class regardless.
