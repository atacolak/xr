# Carina callback and clocks

Sensor lab: `console/recorder`. Acquisition: `CarinaSession` + `carina_bridge.cpp`.
These are stereo **tracking** cameras. Depth is not a camera stream.

Status: **partial**. Buffer identity and timestamp domain need a device run
of this build. Pre-existing 2026-09-30 evidence is cited as such.

## Callback

```
XRCameraCallback(image_left0, image_right0, image_left1, image_right1,
                 timestamp, width, height)
```

| buffer | 2026-09-30 pointers | this-build (fill) |
|---|---|---|
| L0 | non-null, 640×480 | |
| R0 | non-null, 640×480 | |
| L1 | null (`0x0`) | |
| R1 | null (`0x0`) | |

L1/R1 semantics: **unknown until this-build dump**. Prior run never delivered
non-null L1/R1, so they are not a second live stereo pair on that session.
Not proven: duplicate alias, temporal neighbor, alternate exposure.

The overlay now reports plane byte sizes, pointer-equality counts
(`ptr L0==L1`, `R0==R1`), FNV hashes, and consecutive identical L0^R0 hashes.

## Clocks

SDK comments: pose timestamp is "monotonic timestamp in seconds"; IMU
"timestamp in seconds"; VSync "when VSync occurred". Camera timestamp
unit is unspecified in the header.

2026-09-30 **rates** (callback counts, not proven shared domain):

| stream | count ratio | log dt |
|---|---|---|
| camera | 1 | ~40 ms (~25 Hz) |
| pose | ~1:1 with cam | ~40 ms |
| vsync | ~2.4× cam | ~16.7 ms (~60 Hz) |
| imu | ~40× cam | ~1 ms (~1 kHz) |

Same-session logcat showed camera `ts≈5354` while pose/imu/vsync were
`ts≈5370` on the first burst, then later camera frames jumped onto the
5370 epoch. **Similar magnitude is not a shared timestamp domain.**

This build stamps every callback with `clock_gettime(CLOCK_MONOTONIC)`
(`host_ns`) at native receive, plus the SDK `timestamp`. Overlay shows
sdk dt and host dt.

Unknown until measured:

- whether camera/pose/imu/vsync share one clock
- L/R sync inside one callback (same exposure / same time)
- jitter / dropped / repeated frames
- whether vsync is panel scanout

## Exposure

SDK: auto, or manual `exposure_time_ms` in [0.01, 8.0] and `gain` in [0, 15].
Settings UI: auto / 0.5 ms g4 / 2 ms g8 / 8 ms g15. Results: **not yet run**.

## Device identity

`xr_device_provider_get_sn_hash` returns SHA-256 of the board serial, not
the raw SN. Stored as `sn_hash` in sensor metadata when the call succeeds.

## Factory calibration

See child `xr-wdw.3`. `initialize(handle, custom_config, cache_file_dir)`
can fail `CALIB_INIT` / `SERIAL_FETCH`. UxSpace passed nullptr/nullptr.
This build passes app cache `.../cache/carina` as `cache_file_dir`.
