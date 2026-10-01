# Carina callback and clocks

Sensor lab: `console/recorder`. Acquisition: `CarinaSession` + `carina_bridge.cpp`.
These are stereo **tracking** cameras. Depth is not a camera stream.

Status: **measured** on Fold + Luma Ultra, session `20261001-171206`
(15 s SENSOR, `xr-carina-sensor-v1`).

## Callback

```
XRCameraCallback(image_left0, image_right0, image_left1, image_right1,
                 timestamp, width, height)
```

| buffer | 2026-09-30 | 2026-10-01 this build |
|---|---|---|
| L0 | non-null, 640×480 | 307200 B every frame, unique FNV per frame |
| R0 | non-null, 640×480 | 307200 B every frame, unique FNV per frame, **never** equal L0 |
| L1 | null (`0x0`) | **always 0** (359/359) |
| R1 | null (`0x0`) | **always 0** (359/359) |

L1/R1 are unused on this firmware. Not a second live pair, not an alias of
L0/R0 (`ptr_l0_eq_l1=0`, `hash_l0_eq_l1=0`). Semantics beyond "unused" stay
unknown.

L0 and R0 are distinct fisheye views (left sees window/room; right sees a
darker downward frustum). `repeat_hash_pair=0` — no consecutive duplicate
stereo frames in this capture.

## Clocks

`host_ns` = `clock_gettime(CLOCK_MONOTONIC)` at native receive.

| stream | n (15.05 s) | sdk dt | host dt | sdk vs host |
|---|---|---|---|---|
| camera | 359 | 40.0 ms (~25 Hz) after settle | 39.9 ms | see jump below |
| pose | 351 | 40.0 ms | ~41.6 ms | sdk ≈ host (first sample 12 µs; later ~25–30 ms callback lag) |
| vsync | 845 | 16.7 ms (~60 Hz) | ~17.2 ms | sdk ≈ host (sub-ms to a few ms) |
| imu | 14087 | 1.00 ms (~1 kHz) | ~1.00 ms mean | sdk ≈ host |

Camera `sdk_ts` is **not** one domain from frame 0:

- seq 0–5: `sdk_ts ≈ 3028.6` while `host_s ≈ 10094.0` (offset **+7065.2 s**)
- seq 6 onward: `sdk_ts` jumps to `10094.23` and then tracks CLOCK_MONOTONIC
  with a stable **~24 ms** host lag (callback delay, not a second clock)

Pose / IMU / vsync used the monotonic-seconds domain from the first sample.
Do not mix the first six camera timestamps with pose/IMU without applying
the jump. After seq 6, camera/pose/imu/vsync share one seconds timeline
aligned with `CLOCK_MONOTONIC`.

Unknown:

- L/R sync inside one callback (same exposure / same time) — same
  `sdk_ts` per pair, not a proven shared shutter
- whether vsync is panel scanout
- why the first six camera timestamps use the 3028 epoch

## Exposure

SDK: auto, or manual `exposure_time_ms` in [0.01, 8.0] and `gain` in [0, 15].
This capture used `set_auto_exposure_carina` (rc=0). First frames are very
dark; later L0 has a usable fisheye scene after AE. Manual presets were
**not** run this session.

## Device identity

`get_sn_hash` = SHA-256 of board serial, not the raw SN.

```
3d4b878d897b1e1cf0ee62357f3e663627cb21e4a2e06a2af78e4e46235a4558
```

USB: `pid=0x1104`, `xr_device_provider_get_device_type=2` (Carina).

## SENSOR session

`Movies/XRConsole/Sensor/20261001-171206/`:

- `camera.gray8` 220569600 B = 359 × (L0+R0) 8-bit 640×480
- `camera.index.jsonl` plane sizes, ptrs, FNV hashes, sdk_ts, host_ns
- `pose.jsonl` 351 samples (`p,y,z,qw,qx,qy,qz`)
- `imu.bin` 14087 × `{host_ns i64, sdk_ts f64, ax ay az gx gy gz f32}`
- `vsync.jsonl` 845 samples
- `metadata.json` `format=xr-carina-sensor-v1`, `closed=true`

Replay: `console/recorder/sensor_replay.py <dir>`.

## Factory calibration

See `docs/carina-calibration.md`. `cache/carina` was passed as
`cache_file_dir`; after a successful initialize it stayed **empty**.
