# Carina factory calibration

Child `xr-wdw.3`. No ruler. No binary patching.

## Outcome: **B** — calibration exists and is opaque

Factory per-unit calibration **is fetched from the glasses over USB** during
`xr_device_provider_initialize`. It is **not** exposed as public K / distortion
/ R / T structs. UxSpace and the previous recorder both passed
`initialize(handle, nullptr, nullptr)`.

## Evidence (libglasses.so strings, 2026-10-01)

`CalibrationManager` / `CalibrationReaderV1` / `V2`:

- `"GlassesProtocolController: Starting calibration data reading"`
- `"CalibrationReaderV1: CRC32 verification successful"`
- `"CalibrationManager: no cache directory specified, skipping file cache"`
- `"CalibrationManager: cache data saved successfully"`
- `"session successfully restored from cache"`
- `"xr_device_provider_initialize: failed to initialize calibration manager"`
- `"CalibrationManager: serial number is empty"`

YAML parser `viture::xr::calibration::YamlCalibrationParser` expects:

- `OptData`
- `OptData.display`
- `OptData.display.frustum_left`
- `OptData.display.frustum_right`
- `OptData.display.T_left_imu`
- `OptData.display.T_right_imu`
- `Imu.gyro_bias`
- `Imu.acc_bias`

Binary optical packets:

- `"Parsed camera calibration - version=%u, resolution=%ux%u, camera_model=%u, distortion_model=%u"`
- left/right **distortion grids**: `"Parsed left distortion - version=%u, %ux%u, %ux%u points"`
- IMU blob expected **124 bytes**
- mag / acc temp drift tables

`libcarina_vio.so` contains OpenCV fisheye (`fisheye.cpp`),
`distortion_coeffs`, `camera_model`, `carina_compute_distortion`,
`VioManager(): invalid camera_model`. That is the VIO consumer, not a
public export.

`get_sn_hash` is the only public identity API (SHA-256 of board serial).

## What this means

| want | public API | vendor path |
|---|---|---|
| K_left / K_right | no | inside YAML OptData / camera_model packet |
| distortion | no | grid maps, not documented KB4 coeffs |
| R/T stereo | no | possibly `T_left_imu` / `T_right_imu` |
| camera-to-IMU | likely | those T_*_imu nodes |
| cache | `cache_file_dir` on initialize | skipped if null |

This build passes app cache `cache/carina` as `cache_file_dir` and
enables SDK debug logs. Device run 2026-10-01 17:12 (`sn_hash` 3d4b878d…):
initialize succeeded in ~0.46 s with `CarinaDeviceProvider initialized
(6DOF=true)`. **No** `CalibrationManager` / `cache data saved` log lines.
`cache/carina` stayed empty (no YAML, no grids). Outcome remains **B**.
Treat factory K/R/T as unavailable until a cache dump or public API appears.

Offline ChArUco + OpenCV fisheye tooling: `docs/carina-calib.md` / `xr-wdw.4`.
Do not substitute a model-default K/R/T for a solved artifact.
