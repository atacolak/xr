# How we know whether any of this works

Written to answer one question: *how do we decide if the driver is good enough?* The short
version is that "good enough" is **per criterion**, each criterion has a test that can fail,
and the tests that matter most are the ones that do not involve wearing anything.

## Who is responsible for what

This is the whole reason for the method. Every failure has exactly one home.

| layer | responsible for | not responsible for |
|---|---|---|
| **vendor SDK** (`libglasses`, closed) | fusing IMU + cameras into a 3DoF/6DoF pose; driving the panels; quality of that pose | anything OpenXR |
| **`monado-viture` driver** (`xrt_device`) | converting the SDK pose into OpenXR poses; declaring FOV, IPD, view layout, swapchain geometry, refresh | fusing sensors, compositing, rendering |
| **Monado** | the OpenXR service: session state, compositor, distortion, present | pose correctness, app behaviour |
| **the app** (hello_xr, Godot, BeamNG) | rendering, its own acceptance of the poses | everything below it |

So "is the driver good enough" is really five falsifiable questions, not one feeling.

## What each kind of test actually proves

The column that matters is the second-to-last. A test that proves nothing about the device is
still useful — but only if you know that.

| test | proves | does **not** prove | needs |
|---|---|---|---|
| `--src synth` in the demo | the demo's own render/present chain | anything about the SDK or driver | nothing |
| **`--pose-file` replay** (new) | the *consumer*: the validity gate, quaternion conversion, reference grounding, smoothing — deterministically, same input → same frames | **anything about the device.** The poses are recorded; replaying them cannot measure the VIO | a recorded session |
| demo on the headset | the pose path end to end, and whether it is *comfortable* | absolute pose accuracy | a human wearing it |
| **static known-answer** | absolute accuracy where truth is known: level the glasses on a bench → roll and pitch must read ~0 regardless of heading; face a known compass bearing → yaw error | dynamic behaviour, drift over minutes under motion | a flat surface, a compass, 10 minutes |
| **drift test** (fully automatic) | VIO drift: leave the glasses untouched for N minutes and measure pose spread | anything perceptual | nothing |
| **scale test** | VIO metric scale: walk a measured 1 m against the graduations in `--world room` | fine accuracy | a tape measure |
| **physical rig** (turntable/robot) | true dynamic accuracy: known angles in, poses out | — | hardware we do not have yet |
| hello_xr | the driver is a *valid OpenXR device*: enumeration, session states, swapchain geometry, focus transitions | whether the poses are any good | nothing beyond the runtime |
| **BeamNG** | the actual use case: stereo, correct axes, sustained session | pose precision | the app |

## What can be automated

Almost all of the numerical work, and it is the *stronger* half:

- **Replay regression.** Record a session once (`--record FILE`), then replay it
  (`--pose-file FILE`) after any change to the pose path. Deterministic, no hardware, catches
  exactly the bugs this project has actually had: the placeholder glide, the gate latch, the
  Euler singularity, the frame permutation. The corpus should include the awkward cases —
  a startup placeholder burst, a fast turn past 180°, a stall, a VIO reset.
- **Pose-conversion unit tests.** The driver's conversion is pure maths (SDK quaternion →
  `xrt_pose`). Give it literal inputs, assert literal outputs, off-device. Axis signs, units,
  handedness, and the reference behaviour are all testable this way.
- **Drift, scale and static-accuracy runs.** No perception involved; record and compare.

What genuinely cannot be automated: comfort, binocular fusion, perceived latency, and whether
the world feels locked. Those need a person, and pretending otherwise wastes effort.

## Acceptance criteria, per milestone

The driver is "good enough" when *all* of these hold, and not before:

1. **hello_xr** completes a session to `XR_SESSION_STATE_FOCUSED` with the swapchains at
   `3840x1200` (two views of `1920x1200`) and no validation errors.
2. **Axes**: yaw right, pitch up, roll clockwise all move the view the right way, at every
   heading, including past ±90° pitch and 180° yaw.
3. **Translation** is present and scaled correctly: a measured 1 m walk moves the view 1 m.
4. **Latency** added by our path is under one frame at 90 Hz, measured as pose age at the
   consumer.
5. **Stability**: a session survives N minutes of movement with no crash, no state loss, and
   a drop counter of 0 that stays 0.
6. **BeamNG** renders stereo through the driver with correct head tracking, and stays up.
7. **Drift** is characterised and written down (it will not be zero; the number is what
   matters).

Anything not on this list is presentation, and presentation is not what we are shipping.

## The ordered plan, and where the blockers are

1. **6DoF through the driver.** The SDK gives 6DoF (verified: translation of 6.3/17.2/4.6 cm
   measured for head movement). The driver must select that path and forward translation to
   `xrt_device::get_tracked_pose`. *This is the only thing standing between us and criteria
   3 and 6.*
2. **Replay corpus.** Record a handful of sessions (including the awkward ones above) and
   wire `--pose-file` into a script that runs them and diffs the outcome. Makes every later
   pose change safe.
3. **Static accuracy + drift runs.** Cheap, automatic, and the numbers go in the docs. This
   is the answer to "how accurate is it", which is currently unknown.
4. **BeamNG** as the acceptance test, because it is the use case.
5. **Then build on it**: Godot or WebXR against Monado for anything custom. Both already speak
   OpenXR, which is the entire point of the driver.

The demo is not on this list, because it has done its job: it is what found the frame
permutation, the placeholder glide, the Euler singularity and the gate latch. It stays as the
instrument for calibration and screenshots, and it should not absorb more effort than that.
