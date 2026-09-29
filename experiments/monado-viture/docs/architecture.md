# Architecture

## The shape

```
  OpenXR application (hello_xr, BeamNG, ...)
        |
        |  OpenXR API
        v
  Monado
    state_trackers/oxr          OpenXR API -> xrt_device
    compositor (Vulkan)         owns the swapchain and presentation
    xrt_device  <--- this driver
        |
        |  C API, no protocol parsing
        v
  libglasses.so (vendor, 2.4.0)  USB transport + Carina VIO
        |
        |  libusb (embedded in the vendor library)
        v
  VITURE Luma Ultra              panels + IMU + cameras
```

## What this driver is

A **policy layer**, not a protocol implementation. The vendor SDK already owns
the USB transport and the VIO and hands back a fused pose with a prediction
parameter, so the driver decides:

- when to ask for a pose and how far ahead to predict,
- what panel geometry to declare to the compositor,
- how to map the vendor pose into Monado's frames and flags.

## What it is not

- No HID packet parser and no CRC handling. The comparable in-tree drivers
  (`xreal_air`, `rokid`) implement both, because for those glasses the IMU is
  raw and the host must fuse it (`m_imu_3dof`). VITURE hands us the fused pose.
- No IMU fusion filter.
- No tracking claim we did not receive.

## Files

| file | responsibility |
|---|---|
| `src/viture/viture_hmd.c/.h` | the `xrt_device`: lifecycle, pose polling, view/panel setup, config |
| `src/viture/viture_pose.c/.h` | vendor pose -> `xrt_space_relation`, no Monado state |
| `src/viture/viture_pose_layout.h` | vendor pose layout + axis selector, Monado-free so diagnostics can use it |
| `src/viture/viture_modes.c/.h` | panel timing / stereo mode table |
| `src/viture/viture_probe.c` | sysfs discovery and product policy |
| `src/viture/viture_compat.h` | C-safe access to the vendor version query |
| `src/monado/target_builder_viture.c` | Monado builder: detection, head role assignment |
| `patches/0001-monado-add-viture-driver.patch` | the six build-plumbing edits to Monado |

## Why a patch and not a plugin

Monado has no dynamic driver loading: `dlopen` appears only for tracking
libraries and the SteamVR wrapper, and drivers are built as static archives and
registered in `targets/common/target_lists.c`. An out-of-tree driver is
therefore not possible without patching. The patch is additive (57 lines across
five existing files) and shaped to be upstreamable:

- option `XRT_BUILD_DRIVER_VITURE`, **default OFF** because it needs a
  proprietary SDK,
- `VITURE_SDK_DIR` cache variable with a clear fatal message when unset,
- no entry in `target_entry_list`, so Monado's prober never tries to claim the
  HID interfaces that the vendor library opens itself.

## Detection

`viture_probe.c` scans `/sys/bus/usb/devices` for vendor `0x35CA` and then asks
the vendor SDK (`xr_device_provider_is_product_id_valid`) which product ids are
real. Product ids are **not** hardcoded: the SDK owns that list and it grows
(Luma Ultra alone reports as `0x1101`/`0x1104`; Luma Pro is `0x1121`/`0x1141`).

Policy lives in one function, `viture_is_supported_product()`: only Carina
generation devices are accepted, because only Carina has a host-side pose
source. A Gen1/Gen2 device is rejected loudly rather than given a fabricated
identity pose. `VITURE_ALLOW_ANY_PRODUCT=1` overrides this for experiments.

## Bring-up mode

`VITURE_NO_SDK=1` creates the device, declares full stereo panel geometry, and
reports an identity pose without touching the vendor library at all. This exists
so compositor and OpenXR enumeration can be validated before any tracking code
runs, and so that a crash in vendor code cannot be confused with a bug in the
Monado integration. It is a bring-up tool, not a tracking path, and it says so
in the log.

## Threading

One mutex (`hmd->mutex`) serialises every vendor call against teardown. Pose
polling happens on the caller's thread inside `update_inputs`/`get_tracked_pose`
— Monado calls both from the frame loop, so there is no driver-owned sampling
thread to keep alive, and nothing to leak if the process tears down mid-frame.

## Compositor

Untouched by this driver. Monado defaults to its **compute** compositor on Linux
(`USE_COMPUTE_DEFAULT true`), which renders without a display target, so
milestones M0/M1 need no display or X11 changes at all. For real output to the
glasses the options are NVIDIA direct mode via `VK_EXT_acquire_xlib_display`
(needs an allowlist match or `XRT_COMPOSITOR_FORCE_NVIDIA_DISPLAY`, and no DRM
master), or windowed XCB output with `XRT_COMPOSITOR_FORCE_XCB=1`.
