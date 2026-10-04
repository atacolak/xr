"""xr-carina-calib-v1 JSON + Monado calibration_v2 sidecar."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import DISTORTION_MODEL, FORMAT, MONADO_DISTORTION
from .board import BoardSpec
from .solve import StereoCalib

SCHEMA = "xr-carina-calib-v1"


def _mat(a) -> list:
    return np.asarray(a, dtype=float).tolist()


def _vec(a) -> list:
    return np.asarray(a, dtype=float).reshape(-1).tolist()


def to_dict(
    cal: StereoCalib,
    spec: BoardSpec,
    *,
    sn_hash: str = "",
    source_sessions: list[str] | None = None,
    extra_metrics: dict | None = None,
) -> dict:
    metrics = {
        "rms_left": cal.left.rms,
        "rms_right": cal.right.rms,
        "rms_stereo": cal.rms,
        "holdout_reproj_left": cal.holdout_reproj_l,
        "holdout_reproj_right": cal.holdout_reproj_r,
        "epipolar_mean_px": cal.epipolar_mean_px,
        "n_views_left": cal.left.n_views,
        "n_views_right": cal.right.n_views,
        "n_stereo": cal.n_stereo,
        "n_holdout": cal.n_holdout,
    }
    if extra_metrics:
        metrics.update(extra_metrics)
    return {
        "format": FORMAT,
        "schema": SCHEMA,
        "distortion_model": DISTORTION_MODEL,
        "monado_distortion_model": MONADO_DISTORTION,
        "opencv_model": "cv2.fisheye / Kannala-Brandt 4",
        "image_size": {"width": cal.width, "height": cal.height},
        "board": spec.to_json(),
        "units": "board_squares",
        "scale_note": (
            "T is in ChArUco square lengths, not metres. "
            "Do not treat as metric. xr-wdw.5 is the physical-scale gate."
        ),
        "sn_hash": sn_hash,
        "source_sessions": source_sessions or [],
        "left": {"K": _mat(cal.left.K), "D": _vec(cal.left.D)},
        "right": {"K": _mat(cal.right.K), "D": _vec(cal.right.D)},
        "stereo": {
            "R": _mat(cal.R),
            "T": _vec(cal.T),
            "E": _mat(cal.E),
            "F": _mat(cal.F),
        },
        "metrics": metrics,
    }


def to_monado_v2(cal: StereoCalib) -> dict:
    """Monado t_stereo_camera_calibration JSON v2. Not a Mercury validation."""

    def cam(K, D, w, h):
        D = _vec(D)
        names = ["k1", "k2", "k3", "k4"]
        return {
            "model": "fisheye_equidistant4",
            "intrinsics": {
                "fx": float(K[0, 0]),
                "fy": float(K[1, 1]),
                "cx": float(K[0, 2]),
                "cy": float(K[1, 2]),
            },
            "distortion": {names[i]: float(D[i]) for i in range(4)},
            "resolution": {"width": int(w), "height": int(h)},
        }

    def flat(a):
        return [float(x) for x in np.asarray(a, dtype=float).reshape(-1)]

    return {
        "$schema": "https://monado.pages.freedesktop.org/monado/calibration_v2.schema.json",
        "metadata": {"version": 2},
        "cameras": [
            cam(cal.left.K, cal.left.D, cal.width, cal.height),
            cam(cal.right.K, cal.right.D, cal.width, cal.height),
        ],
        "opencv_stereo_calibrate": {
            "rotation": flat(cal.R),
            "translation": flat(cal.T),
            "essential": flat(cal.E),
            "fundamental": flat(cal.F),
        },
    }


def save(path: Path, payload: dict) -> None:
    path = Path(path)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text())
