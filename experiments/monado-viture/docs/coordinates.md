# Coordinate frames

Three frames matter. Getting this wrong is the single most likely way to ship a
driver that "works" but is subtly unusable, so each hop is written out.

```
  +-------------------------------+      +----------------------------+
  | VITURE Carina (vendor SDK)    |      | OpenXR / Monado            |
  | xr_device_provider_           |      | struct xrt_space_relation  |
  |   get_gl_pose_carina()        |      |                            |
  |                               |      |                            |
  |   "OpenGL coordinate system"  |      |   right-handed             |
  |   +X right                    | ===> |   +X right                 |
  |   +Y up                       | id   |   +Y up                   |
  |   +Z backward (-Z forward)    |      |   -Z forward               |
  |   [px,py,pz,qw,qx,qy,qz]      |      |   xrt_quat {x,y,z,w}       |
  +-------------------------------+      +----------------------------+
```

## Hop 1: vendor -> driver

The vendor header documents the pose as

    [px, py, pz, qw, qx, qy, qz]

in the OpenGL coordinate system, `x -> right, y -> up, z -> backward`
(`viture_device_carina.h`, `xr_device_provider_get_gl_pose_carina`).

OpenXR's convention is right-handed with `+Y` up and `-Z` forward. That is the
same axis convention, so **the mapping is the identity** and only the field
order changes, because `struct xrt_quat` is declared `{x, y, z, w}` while the
vendor buffer is `qw` first:

```c
relation.pose.orientation.x = pose[VITURE_POSE_QX];  /* pose[4] */
relation.pose.orientation.y = pose[VITURE_POSE_QY];  /* pose[5] */
relation.pose.orientation.z = pose[VITURE_POSE_QZ];  /* pose[6] */
relation.pose.orientation.w = pose[VITURE_POSE_QW];  /* pose[3] */
```

There is **no** 90-degree or handedness fixup, and deliberately so: a spurious
rotation would be invisible in logs and obvious only to a human wearing the
glasses.

### Why not copy XRLinuxDriver's remap

`XRLinuxDriver` (the independent GPL-3.0 Linux driver for these glasses)
converts the same pose to **NWU** (`x = -pz, y = -px, z = +py`) before use,
because its consumer is a shader-injection virtual-display runtime that wants a
Z-up, gravity-aligned frame. Monado does not: it wants a Y-up frame, which the
vendor already provides. Copying that remap would have introduced a 90-degree
error on two axes. This is recorded because it is a tempting thing to "reuse".

## Hop 2: driver -> compositor

`get_tracked_pose()` returns a `struct xrt_space_relation` whose
`relation_flags` say exactly which parts are known:

| flag | when set |
|---|---|
| `..._ORIENTATION_VALID_BIT` | always, on a successful sample |
| `..._ORIENTATION_TRACKED_BIT` | only when the vendor reports `pose_status == 0` (stable) |
| `..._POSITION_VALID_BIT` | only in 6DoF mode |
| `..._POSITION_TRACKED_BIT` | only in 6DoF and only when stable |

Monado models "unknown" as a **cleared** VALID bit; there are no INVALID bits
(`xrt_defines.h`). An unstable VIO sample therefore still yields a usable
orientation while honestly not claiming to be tracked. Nothing we did not
receive is ever advertised.

Not reported: linear and angular velocity. The vendor exposes no velocity, and
numerically differentiating a noisy pose to fabricate one would be worse than
reporting nothing. This is a known gap; see `docs/measurements.md`.

## Hop 3: reference space

At start the driver calls `xr_device_provider_reset_origin_carina(handle, pose)`
with the current pose. Per the vendor header this resets **position and yaw** to
whatever was passed, while **pitch and roll remain gravity-anchored** and are not
affected regardless of the pose passed.

That is exactly OpenXR `LOCAL` semantics: the user begins near the frame origin,
facing approximately `-Z`, with the horizon level and no faked tilt. Yaw reset is
therefore part of the space contract, not a hidden side effect.

Disable with `VITURE_RESET_ORIGIN=0` if a session must inherit a previous origin.

## Pose request and prediction

`get_gl_pose_carina(handle, pose, predict_time, &status)` treats `predict_time`
as a horizon in seconds from now (`0.0` = latest sample). Monado calls
`get_tracked_pose()` with a target timestamp, usually the predicted display time,
so the driver converts the interval and asks the vendor to predict:

```
predict_s = clamp((at_timestamp_ns - now) / 1e9, 0, VITURE_MAX_PREDICT_S)
```

Clamped to 50 ms, which is far beyond any sane frame interval and exists only to
stop a pathological timestamp from asking for absurd extrapolation. Prediction
stays inside the vendor's VIO rather than being reimplemented with a
Monado-side filter, and no smoothing is added: smoothing would trade correctness
for prettier logs.
