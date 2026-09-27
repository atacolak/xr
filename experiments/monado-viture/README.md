# monado-viture

Make the VITURE Luma Ultra appear to Linux as a **real OpenXR HMD** through
Monado, with stereo presentation and tracked head pose, so that OpenXR
applications (hello_xr, BeamNG's native Linux OpenXR mode) get a head and two
eyes from the glasses.

Explicitly *not* another virtual-desktop or head-anchoring implementation.
Breezy/Stardust-style spatial displays are references, not the goal.

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
tools/build-pose-dump.sh          # characterise the pose stream, no Monado needed
tools/viture-pose-dump --seconds 10 --json
scripts/run-hello-xr              # run hello_xr against the built runtime
scripts/run-beamng                # gated until M0-M3 are measured
tools/restore-desktop save        # ALWAYS do this before touching displays
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

## Not in scope

No controllers, no hand tracking, no 6DoF before static stereo + 3DoF, no
SteamVR, no BeamNG file edits, no fake hardcoded tracking presented as done.
