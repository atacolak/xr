# monado-viture

Make the VITURE Luma Ultra appear to Linux as a **real OpenXR HMD** through
Monado, with stereo presentation and tracked head pose, so that OpenXR
applications (hello_xr, BeamNG's native Linux OpenXR mode) get a head and two
eyes from the glasses.

Breezy/Stardust-style spatial displays are references.

```
  BeamNG / hello_xr
        |  OpenXR
        v
  Monado (xrt_device)
        v
  VITURE Luma Ultra
```

## Where this sits

`~/xr` is the control repo; this directory holds the experiment. Monado itself
is an external dependency and is **not** vendored here:

    MONADO_DIR   default ~/workspace/monado        (gitlab.freedesktop.org/monado/monado)
    VITURE_SDK_DIR default ~/workspace/uxspace/Android/SDK/linux-x86_64
    MONADO_SYSROOT default ~/workspace/monado-deps  (build deps, rootless)

See `components.toml` and `docs/architecture.md`.

## Milestones

| | milestone | state |
|---|---|---|
| M0 | Monado instantiates a static "VITURE Luma Ultra" HMD | **measured** (no hardware needed, `VITURE_NO_SDK=1`) |
| M1 | hello_xr enumerates it and renders stereo | **measured** (2 views, session FOCUSED 15 s, 0 errors) |
| M2 | frames reach the glasses correctly in stereo | needs glasses attached |
| M3 | Carina rotation drives HMD orientation (3DoF) | needs glasses attached |
| M4 | BeamNG native Linux OpenXR starts and tracks | not started (`scripts/run-beamng` refuses) |
| M5 | Carina translation enabled (6DoF) | 6DoF is the default path, unit unverified |
| M6 | recentering, prediction, latency tuning | not started |

`docs/measurements.md` is the honest scoreboard. Do not claim a milestone that
is not in there as `measured` with the evidence next to it.

## Commands

```sh
scripts/install-deps-local.sh     # once: build deps into a private sysroot (no root)
scripts/test-coordinates          # offline pose/axis unit tests, no glasses needed
scripts/build                     # patch Monado, configure, build
scripts/patch-monado.sh status    # is the patch applied? against which base?
scripts/display-mode 2d|sbs       # match the glasses and X in the order that works
scripts/display-mode sbs --pattern  # ... and throw the stereo test pattern up
tools/make-stereo-pattern.py      # regenerate that pattern (3 squares, 3 disparities)
tools/kms-probe.py --enumerate    # DRM/KMS view, and custom timings without X
tools/x-edid.py --output DP-2     # decode the EDID an X output presents
tools/build-pose-dump.sh          # characterise the pose stream, no Monado needed
tools/viture-pose-dump --get-mode # what display mode the glasses are actually in
tools/viture-pose-dump --seconds 10 --json
scripts/run-service               # start monado-service (clears a stale IPC socket)
scripts/run-hello-xr              # run hello_xr against the built runtime
scripts/run-beamng                # gated until M0-M3 are measured
scripts/restore-display save      # ALWAYS do this before touching displays
```

**Display modes are order-sensitive.** A mode change on the glasses makes the sink
re-present its EDID, and X only re-reads the sink on hotplug. Set the device first,
wait for X to *offer* the timing, then point the output at it — `scripts/display-mode`
does exactly that. Doing it the other way round leaves X driving a timing the sink no
longer offers; after that every `xrandr` call fails with `BadMatch` and the GPU
display engine wedges (`nvidia-modeset: Idling display engine timed out`), which needs
an X restart to clear (see beads `xr-bi6.8`).

`tools/viture-pose-dump` needs the SDK's own libraries on the loader path, because
`libcarina_vio` is `dlopen`ed and the caller's `DT_RUNPATH` is not transitive:
`LD_LIBRARY_PATH=$VITURE_SDK_DIR/x86_64 tools/viture-pose-dump --seconds 10 --json`.
`--native-probe` is opt-in because the native-mode queries never return on Carina.

## Reproducing the M2 result (runtime stereo on the panels)

Verified end to end on 2026-10-04. The ordering matters, and the environment
variables are the ones that worked:

```sh
scripts/display-mode sbs                    # glasses to 0x45, X onto 3840x1200@90
VITURE_NO_SDK=0 XRT_COMPOSITOR_COMPUTE=0 XRT_COMPOSITOR_FORCE_XCB=1 \
  XRT_COMPOSITOR_XCB_FULLSCREEN=1 XRT_COMPOSITOR_LOG=info DISPLAY=:1 scripts/run-service
VITURE_XR_HOLD=15 scripts/run-hello-xr -g Vulkan --space Local
```

Landmarks on the way through, all observed:
- `viture_sdk_configure_display: display mode 0x45 (3840x1200@90-sbs) confirmed`
- `viture_hmd_create: created: Luma Ultra, panel 3840x1200@90-sbs (3840x1200 total, 2 view(s), 90 Hz)`
- `views[0].viewport x=0 w=1920 h=1200`, `views[1] x=1920 w=1920 h=1200`, target `xcb` with extents `3840x1200`
- the Monado window is 3840x1200 and hello_xr reaches `XR_SESSION_STATE_FOCUSED`

Two caveats that cost real time here: `XRT_COMPOSITOR_LOG=debug` selects the deferred
windowed target and the window then stays **black** even though the client is focused
(use `info`), and the XCB target may log `Selected display 0 has no size -- Falling
back to display 3: DP-2`, which is normal and not an error.

## The head-tracked demo (`tools/headtrack-demo.py`)

Shows the stereo scene from the glasses' own orientation: device pose -> camera
yaw/pitch/roll -> per-eye render -> fullscreen presenter. Rotation-only (3DoF): the camera
position stays at the origin, but it *takes* a position, so a 6DoF pose drops in unchanged.

### pose sources (`--src`)

| | what | caveat |
|---|---|---|
| `poll` (default) | `get_gl_pose_carina` | correct OpenGL frame, gravity-anchored pitch/roll, but it **drifts**: measured 30 deg of pitch while the glasses sat untouched. ~30 pose updates/s |
| `cb` | the device's pose callback | ~800 Hz and rock steady, but its quaternion is in the IMU's North-West-Up frame and disagrees with the gravity-anchored attitude, so the axes come out permuted |
| `synth` | a known sinusoid, no device at all | verifies the render/present chain with the glasses unplugged; its reported pose age is meaningless by construction |

### presenters (`--presenter auto|gl|shm`)

- `shm` = `tools/xpresent`: XShmPutImage, full-size frames, ffmpeg does the scale. 78 fps
  measured in the demo.
- `gl` = `tools/xpresent-gl`: small frames over the pipe, GPU scales. 89 fps measured at a
  90 Hz target, even on llvmpipe, and the default (`auto`) once built. It paces the swap to
  the panel when `GLX_EXT_swap_control` is there, and **measures its own frame interval**: if
  that interval is slower than any attached display could be (a window whose output is
  disconnected waits on a dummy vblank at roughly 1 Hz), it drops the throttle instead of
  leaving a demo that looks hung. Measured on the unplugged server: 1.5 fps -> 336 fps.
- XRender scaling is not an option on this X server: `ShmCreatePixmap` returns
  `BadImplementation`, and a picture-transform composite renders *nothing* (both measured).

### knobs that matter

- `--fps` (90 default): the panel's own refresh. The GL presenter paces the swap to it, so
  this and the panel agree; the CPU path cannot follow it.
- `--fov` (44.9 default): the Luma Ultra is 52 deg diagonal, ~44.9 horizontal on an 8:5 panel.
  If head motion feels too fast or too slow, this is the number to calibrate against the room.
- `--smooth` (0.015 s) and `--deadband` (0.03 deg): the deadband kills sensor micro-jitter
  with no lag at all; smoothing is lag by definition, so it stays light.
- `--flip-xy` (on): the SDK's GL pose has z pointing backward while this renderer looks down
  +z; without it yaw and pitch drive the scene backwards.
- `SIGUSR1` re-anchors: `kill -USR1 $(pgrep -f headtrack-demo)`. IMU yaw drifts inherently.
- `--res` (640x400 per eye): 119 fps of render headroom at 3x upscale. Raise it for sharpness
  and expect the frame rate to fall.

### verifying without the glasses

The glasses spend most of their life unplugged, and with no output attached the X server
has no 3840x1200 framebuffer at all — a window capture then returns an 8x8 image, which
looks like a broken renderer rather than a missing display. So:

```sh
Xvfb :9 -screen 0 3840x1200x24 +extension GLX &        # a real 3840x1200 framebuffer
DISPLAY=:9 tools/headtrack-demo.py --seconds 30 --src synth   # no device needed
# the presenter prints its window id; capture exactly that window:
DISPLAY=:9 xwd -id <wid> -silent > /tmp/cap.xwd
```

Then check both halves have lit pixels and that the bands match the scene (dim walls, a
brighter floor). This is how the pipeline is verified between hardware sessions; it caught a
presenter that rendered nothing at all while cheerfully reporting fps.

## Hazard: on this workstation, restarting X kills the agent sessions

Every omp / herdr session on sfub descends from the X session
(`kitty` -> `herdr` server -> the hcom-launched agents), so `systemctl restart gdm`
or a reboot takes down the operator's terminal *and* the agent sessions with it, not
just the desktop. Wedging the GPU display engine therefore costs a session teardown
to recover. Drive display experiments from a channel that survives X (a mosh/ssh
session), and relaunch agents afterwards from their `--resume` ids.

`scripts/run-service` defaults to the no-hardware static HMD
(`VITURE_NO_SDK=1`); use `VITURE_NO_SDK=0 scripts/run-service` for the real
vendor path once the glasses are attached. `scripts/run-hello-xr` takes the
*application's* arguments, not a path -- pick the binary with `VITURE_XR_APP` or
`HELLO_XR`, and set `VITURE_XR_HOLD=<seconds>` to keep stdin open so the app
runs its frame loop instead of exiting on EOF:

```sh
scripts/run-service &                            # or a supervised pty
VITURE_XR_HOLD=15 scripts/run-hello-xr -g Vulkan --space Local
```

## Operational gotcha: stale IPC socket

`monado-service` binds `/run/user/1000/monado_comp_ipc`. If it is killed rather
than shut down cleanly, the socket is left behind and the next start fails with
`Address already in use`. Recover with:

```sh
rm -f /run/user/1000/monado_comp_ipc
```

Also note the service must run with a real PTY: it registers stdin in `epoll`,
so a redirected/closed stdin makes it die with `epoll_ctl(stdin) failed`.

`scripts/run-service` handles both cases: it refuses to start a second instance,
removes a socket no live process owns, and warns when stdin is not a terminal.

### Watch for a display-metadata flap after GPU work

After a Vulkan/DRM-touching run this host has twice reported odd X connector
metadata: `DP-0 disconnected ... 0mm x 0mm`, and once a transient
`3440/910x1440/381` where the EDID says `797x333`. The kernel disagreed
(`card1-DP-1 connected`, 256-byte EDID present), and the mode, refresh, layout,
primary flag and effective 110x110 dpi were all unaffected -- only X's per-output
metadata was stale. Cause not established; the correlation is with the
compositor/Vulkan work these milestones require, so expect it again at M2.

Recovery if something reads that metadata:

```sh
DISPLAY=:1 xrandr --output DP-0 --auto     # re-probe the connector
scripts/restore-display known-good         # last resort: ultrawide only
```

A build against the default settings produces an *out-of-process* runtime
(`libopenxr_monado.so` talks to `monado-service` over that socket), so the
service must already be running before launching an OpenXR application.

## Environment knobs

All read once at device creation. Defaults are documented in
`docs/measurements.md` where they are unverified.

| variable | default | meaning |
|---|---|---|
| `VITURE_NO_SDK` | 0 | static HMD, never touch the vendor library (M0 bring-up) |
| `VITURE_6DOF` | 1 | 6DoF vs 3DoF (`set_dof_type_carina`) |
| `VITURE_DISPLAY_MODE` | `3840x1200@90-sbs` | panel timing, by name or vendor id (`--list-modes` to see all) |
| `VITURE_SET_DISPLAY_MODE` | 1 | command the timing over USB at start |
| `VITURE_RESET_ORIGIN` | 1 | reset VIO origin at start (OpenXR LOCAL-like) |
| `VITURE_POSE_AXES` | identity | `identity`/`flip-x`/`flip-y`/`flip-z` |
| `VITURE_POSITION_SCALE` | 1.0 | translation multiplier; the SDK does not document the unit |
| `VITURE_FOV_H_DEG` | 42 | per-eye horizontal FOV; **unverified**, see measurements |
| `VITURE_IPD_METERS` | 0.064 | lens separation used for the FOV geometry |
| `VITURE_LOG` | info | driver log level |
| `OXR_DEBUG_IPD_MM` | 63 | Monado's session IPD, i.e. the eye separation the app renders with |

## Safety

XR compositor work can leave X11 output state cursed — on this machine a stale
1920x1200 framebuffer is already parked on a *disconnected* `HDMI-0` output.

```sh
tools/restore-desktop save      # before any display experiment
tools/restore-desktop restore   # replay the snapshot
tools/restore-desktop known-good # ultrawide primary, glasses off
```

Only runtime `xrandr` state is touched; no permanent NVIDIA/X11 config is
written. M0/M1 use Monado's compute compositor and need no display change at all.

## One-time root steps

These are genuine consent boundaries, not iteration steps:

1. `udev/70-viture-xr.rules` -> `/etc/udev/rules.d/` so the seat user can open
   the glasses over libusb. Without it only root can, and the driver cannot run
   in a normal session.
2. Install the VITURE Linux SDK if it is not already on disk (the SDK itself
   stays untracked).

Milestones stay sequential: static stereo, then 3DoF, then 6DoF.
No fake hardcoded tracking presented as done.
