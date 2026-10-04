# Offline Carina fisheye stereo calibration

Child `xr-wdw.4`. Factory K/R/T are unavailable (outcome **B**,
`docs/carina-calibration.md`). This is a ChArUco + OpenCV fisheye path
around `xr-carina-sensor-v1`. Translation is in **board-square units**,
not metres. Metric scale is `xr-wdw.5`.

Recorder stays the capture surface. This code is not Android View.

```
console/recorder/carina_calib.py
console/recorder/calib/
```

Venv: `console/recorder/calib/.venv` (gitignored).
`carina_calib.py` re-execs it when present.

## Workflow

1. Fullscreen target on an ordinary monitor (no print required):

   ```sh
   console/recorder/carina_calib.py target
   # Esc quits. squares stay square (letterboxed).
   console/recorder/carina_calib.py target --png board.png --no-show
   ```

2. Wear the Luma. Look at the target from varied distance / tilt /
   image coverage, **both eyes**. On the Fold:

   ```sh
   scripts/xrctl adb shell am start -n sh.colak.xrconsole.recorder/.MainActivity \
     --es preview gray --ei sensor_s 30
   ```

3. Pull the session, then:

   ```sh
   console/recorder/carina_calib.py detect <session>
   console/recorder/carina_calib.py solve <session> --out calib.json
   console/recorder/carina_calib.py validate <session> --png rectify.png
   console/recorder/carina_calib.py monado calib.json
   ```

`detect` prints prompts (`move closer`, `cover upper-right`, `add
stronger tilt`, both-eyes) and drops redundant views. `solve` rejects
captures with fewer than 12 diverse stereo pairs.

## Target

Default: ChArUco **8×5** squares, marker 0.75 of square, `DICT_4X4_50`,
`square_length = 1` board unit. 28 inner corners. OpenCV ≥4.6 pattern
(not legacy). Exact square pixels; the fullscreen path letterboxes
instead of stretching.

## Camera model

**OpenCV fisheye / Kannala-Brandt 4** (`k1..k4`).

Why: Carina tracking cameras are wide fisheye 640×480 (measured).
Monado consumes this as `T_DISTORTION_FISHEYE_KB4`. Vendor YAML is
opaque grids, not public KB4, so we estimate from observations rather
than inventing factory K.

OpenCV 5 `cv2.fisheye.calibrate` wants object/image points as
`(1, N, 3)` / `(1, N, 2)`.

## Artifact (`xr-carina-calib-v1`)

```
format, distortion_model=fisheye_kb4, monado_distortion_model
image_size, board, units=board_squares, scale_note
sn_hash, source_sessions
left.{K,D}  right.{K,D}
stereo.{R,T,E,F}
metrics: rms_left/right/stereo, holdout_reproj_*, epipolar_mean_px, n_*
```

Sidecar: Monado calibration JSON v2 (`fisheye_equidistant4`,
`opencv_stereo_calibrate.{rotation,translation,essential,fundamental}`).
**Not** a Mercury / OpenXR hand-tracking validation.

## Validation without a ruler

Proven on synthetic observations (`carina_calib.py selftest`, 2026-10-04):

| check | result |
|---|---|
| held-out reprojection | ~0.29 px L / 0.31 px R |
| stereo RMS | 0.35 |
| epipolar after rectify | ~0 px |
| T direction vs truth | cos 0.99988 |
| T scale vs truth | <1% (board units) |
| fx vs truth | 286.6 / 282.9 vs 290 (~2–3%) |
| repeat seed stability | pass |
| 2-view / empty capture | REJECTED |
| 15 s room/hand trace `20261001-171206` | 0 ChArUco in 72 scanned frames; solve must reject |

That 15 s session is replay infrastructure, **not** a calibration
dataset. A real target capture waits until Carina USB is free
(`xr-wdw.10` / `xr-bi6` hardware rule).

## Parity

`carina_calib.py compare SESS_A [SESS_B]` diffs two traces offline
(size, L1/R1, cadence, plane stats). It does **not** open
`0x35CA:0x1104`. Whether an Android-derived calibration is reusable on
Linux frames is **UNKNOWN** until `xr-wdw.10` runs on the same unit.

## Metric scale (not this child)

`carina_calib.py edid` may print xrandr millimetres. **Do not trust
them.** Close `xr-wdw.5` only with an independently measured length.
