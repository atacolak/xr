# Measurements

The scoreboard. Every entry is either `measured` with the command and the output
next to it, or `UNVERIFIED`. Nothing in between.

## Hardware / SDK identity

| fact | value | how |
|---|---|---|
| glasses | VITURE Luma Ultra (Carina generation) | vendor `viture_protocol_public.h` market names |
| SDK | libglasses **2.4.0** | `tools/viture-pose-dump` prints `GetVersionString()`; observed at runtime |
| USB vendor id | `0x35CA` | sysfs scan, matches XRLinuxDriver's udev rules |
| Luma Ultra product ids | `0x1101`, `0x1104` | vendor SDK `is_product_id_valid`; Luma Pro is `0x1121`/`0x1141` |
| RGB camera (not used here) | `0x0C45:0x636B` | enumerated on the Fold |
| host | RTX 4070, NVIDIA 595.84, X11 `:1` | `nvidia-smi`, `DISPLAY` |

Verified without any hardware:

- `tools/viture-pose-dump` links, loads `libglasses.so`, and returns
  `libglasses 2.4.0` at runtime.
- `scripts/test-coordinates` — **28 checks, 0 failures** — covers quaternion
  component order, position pass-through and scaling, the VALID/TRACKED flag
  matrix (3DoF must not claim position; unstable must not claim tracking), and
  denormal/zero quaternion handling.

## Pose stream

| question | answer | state |
|---|---|---|
| position + orientation units | `[px,py,pz,qw,qx,qy,qz]`, OpenGL frame | documented in `viture_device_carina.h` |
| quaternion order | `qw` first | documented, pinned by unit test |
| handedness / axes | x right, y up, z backward (= OpenXR) | documented; confirm by moving your head |
| pose rate | IMU pose is selectable 60/90/120/240/500/1000 Hz; the *callback* path is camera-rate (25 Hz) | documented; **driver polls instead**, so the achieved rate is the poll rate |
| prediction | `predict_time` seconds ahead, `0.0` = latest sample | documented; driver passes Monado's requested interval |
| recenter | `reset_origin_carina` resets position+yaw, leaves pitch/roll gravity-anchored; `reset_pose_carina` is a heavyweight full VIO restart | documented |
| 3DoF vs 6DoF | `set_dof_type_carina(is_6dof)`, after create, before initialize; default 6DoF | documented |
| **translation unit** | **UNVERIFIED** — the headers never state it | needs the 10 cm test below |
| linear/angular velocity | not exposed by the SDK; driver reports none | measured absence |

### Procedure: translation unit (`VITURE_POSITION_SCALE`)

1. `tools/viture-pose-dump --seconds 20 --json > still.json` — do not move.
   The position spread over the run is the VIO's noise floor.
2. Repeat while sliding the head a measured **10.0 cm** to the right, slowly.
3. Divide the observed delta by 0.10 m. If it is not ~1.0, set
   `VITURE_POSITION_SCALE` to its inverse.
4. Re-run and confirm the quieter of the two runs' spread is unchanged by the
   scale (it must be: the scale is linear).

`XRLinuxDriver` multiplies this same translation by a lens-pivot ratio for its
virtual-screen model, which is why "just copy them" is not an option here: their
factor encodes their display distance, not a unit conversion.

### Procedure: axes sanity

Wearing the glasses, with `VITURE_NO_SDK=0`:

| motion | expected in `--json` output |
|---|---|
| turn head left | `yaw` increases (sign recorded here once measured) |
| nod down | `pitch` goes negative |
| tilt right | `roll` changes, world horizon stays level in the app |

Any axis that moves the wrong way is a mapping bug, not a preference. Fix it in
`viture_pose.c` and extend `tests/test_coordinates.c`; do not paper over it with
`VITURE_POSE_AXES` (that switch exists to *characterise* a unit, not to ship a
workaround).

### Procedure: noise and rate

`tools/viture-pose-dump --seconds 60 --json` and read the summary: measured Hz,
interval min/mean/max, position spread, and the maximum inter-sample rotation
step. A maximum step that is wild relative to the mean indicates dropped samples
or a VIO reset, not noise.

## Display / panel

| fact | value | state |
|---|---|---|
| stereo mode | `VITURE_DISPLAY_MODE_3840_1200_90HZ` (`0x45`) = 3D SBS | documented; device reports its mode back on request |
| other modes | 1920x1200@{60,90,120}, 3840x1200@{60,90}, 1920x1080@{60,90,120}, 3840x1080@{60,90} | `tools/viture-pose-dump --list-modes` |
| 2D/3D toggle | `switch_dimension` only does 1920x1080@60 <-> 3840x1080@60 | documented; **not** used, `set_display_mode` is strictly better |
| per-eye resolution | 1920x1200 (half of the SBS frame) | derived from the mode table |
| panel timing actually achieved | **UNVERIFIED** — needs the glasses attached | |
| EDID/`xrandr` interaction | **UNVERIFIED** — does the host output re-enumerate as 3840x1200@90 after the USB mode switch? | the question that gates M2 |

### Procedure: display timing

1. `tools/restore-desktop save` first.
2. With the glasses attached: `xrandr --query` and record what the VITURE output
   advertises *before* any mode command.
3. `tools/viture-pose-dump --seconds 2 --set-mode 0x45` and check the printed
   `before`/`after` mode values.
4. `xrandr --query` again and record whether a 3840x1200@90 mode appeared.
   If it did not, the host must be driven at the pre-existing timing and the
   mode switch must happen first — record which order works.

## Optics unknowns

`VITURE_FOV_H_DEG` (default 42) and `VITURE_IPD_METERS` (default 0.064) are
**estimates**, not datasheet values. The vendor SDK exposes no FOV, IPD, eye
relief, or lens distortion for the Carina generation; the only geometry calls it
has (`native_get_display_size`, `native_get_display_distance`) belong to the
Gen2/Beast native-DOF path and are not applicable.

The vertical FOV is derived from the panel aspect, not measured. Consequences
until measured:

- world scale may be off,
- `u_distortion_mesh_none` is used, i.e. no lens distortion correction; for
  BirdBath optics with a well-corrected virtual image this is a defensible
  starting point, but it is an assumption.

Measuring these needs a human and a known visual target; it is an M6 task.

## Monado / compositor

| fact | value | how |
|---|---|---|
| Monado base commit | see `patches/monado-base-commit.txt` | recorded at patch generation |
| patch size | 57 added lines across 5 existing files | `git diff --stat` |
| driver registration | `XRT_BUILD_DRIVER_VITURE` -> `drv_viture` -> `target_builder_viture.c` | build plumbing |
| out-of-tree drivers | not supported upstream (no dynamic loader) | source grep, confirmed independently |
| compositor default | **compute** (headless) on non-Android | `comp_settings.c: USE_COMPUTE_DEFAULT true` |
| compositor to glasses | NVIDIA direct mode via `VK_EXT_acquire_xlib_display`, no DRM master; or `XRT_COMPOSITOR_FORCE_XCB=1` | in-tree sources |

## Vendor SDK defect found

`viture_version.h` declares `extern "C"` and `namespace viture::version { ... }`
**without an `#ifdef __cplusplus` guard**, so the header cannot be included from
any C translation unit. `src/viture/viture_compat.h` works around it by
declaring the single exported C-linkage query (`GetVersionString`) itself instead
of copying the version macros, which would drift.
