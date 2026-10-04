"""Synthetic ChArUco observations. No glasses. No metres."""
from __future__ import annotations

import cv2
import numpy as np

from .board import BoardSpec, generate_image
from .detect import DetectionSet, StereoObs, View, detect_image, match_points
from .solve import StereoCalib, solve, Rejected


def true_cameras(w=640, h=480):
    K = np.array([[290.0, 0.0, w / 2.0], [0.0, 288.0, h / 2.0], [0.0, 0.0, 1.0]])
    D = np.array([[0.07], [-0.025], [0.008], [-0.004]], dtype=np.float64)
    R, _ = cv2.Rodrigues(np.array([0.02, -0.04, 0.01], dtype=np.float64))
    T = np.array([[-4.8], [0.12], [0.05]], dtype=np.float64)
    return K, D, K.copy(), D.copy(), R, T


def _in_front_and_in_frame(pts, w, h, margin=6):
    xy = pts.reshape(-1, 2)
    ok = (
        (xy[:, 0] >= margin)
        & (xy[:, 0] < w - margin)
        & (xy[:, 1] >= margin)
        & (xy[:, 1] < h - margin)
        & np.isfinite(xy).all(axis=1)
    )
    return ok


def _project(obj, rvec, tvec, K, D, w, h):
    img, _ = cv2.fisheye.projectPoints(obj, rvec, tvec, K, D)
    ok = _in_front_and_in_frame(img, w, h)
    return img, ok


def synthetic_detections(
    spec: BoardSpec | None = None,
    n: int = 20,
    noise: float = 0.35,
    seed: int = 0,
    w: int = 640,
    h: int = 480,
) -> tuple[DetectionSet, dict]:
    spec = spec or BoardSpec()
    board = spec.opencv()
    obj_all = np.asarray(board.getChessboardCorners(), dtype=np.float64).reshape(-1, 1, 3)
    ids_all = np.arange(obj_all.shape[0])
    Kl, Dl, Kr, Dr, R, T = true_cameras(w, h)
    rng = np.random.default_rng(seed)
    ds = DetectionSet(spec=spec, width=w, height=h)
    ds.n_scanned = n

    # camera looks at board origin from +Z
    for i in range(n):
        z = float(rng.uniform(9.0, 18.0))
        x = float(rng.uniform(-3.0, 3.0))
        y = float(rng.uniform(-2.0, 2.0))
        rvec_l = rng.normal(0, 0.18, size=3).astype(np.float64)
        tvec_l = np.array([[x], [y], [z]], dtype=np.float64)
        Rl, _ = cv2.Rodrigues(rvec_l)
        Rr = R @ Rl
        tvec_r = R @ tvec_l + T
        rvec_r, _ = cv2.Rodrigues(Rr)
        imgl, okl = _project(obj_all, rvec_l, tvec_l, Kl, Dl, w, h)
        imgr, okr = _project(obj_all, rvec_r, tvec_r, Kr, Dr, w, h)
        both = okl & okr
        if int(both.sum()) < 12:
            continue
        imgl = imgl.copy()
        imgr = imgr.copy()
        imgl[both] += rng.normal(0, noise, size=imgl[both].shape)
        imgr[both] += rng.normal(0, noise, size=imgr[both].shape)
        ids = ids_all[both]
        obj = obj_all[both]
        pl = imgl[both]
        pr = imgr[both]
        vl = View(seq=i, side="l0", ids=ids, corners=pl.astype(np.float32), obj=obj, img=pl)
        vr = View(seq=i, side="r0", ids=ids, corners=pr.astype(np.float32), obj=obj, img=pr)
        ds.views_l.append(vl)
        ds.views_r.append(vr)
        ds.stereo.append(StereoObs(seq=i, left=vl, right=vr, ids=ids, obj=obj, img_l=pl, img_r=pr))

    truth = {"K_left": Kl, "D_left": Dl, "K_right": Kr, "D_right": Dr, "R": R, "T": T}
    return ds, truth


def rel_f(a, b) -> float:
    return abs(float(a) - float(b)) / max(abs(float(b)), 1e-9)


def dir_cos(a, b) -> float:
    a = np.asarray(a, dtype=float).reshape(-1)
    b = np.asarray(b, dtype=float).reshape(-1)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def selftest() -> int:
    errors: list[str] = []

    spec = BoardSpec()
    img = generate_image(spec, px_per_square=80)
    hit = detect_image(img, spec)
    if hit is None:
        errors.append("detect_image failed on generated board")
    else:
        corners, ids = hit
        matched = match_points(spec, corners, ids)
        if matched is None or len(matched[0]) < 12:
            errors.append(f"match_points too few: {None if matched is None else len(matched[0])}")

    ds, truth = synthetic_detections(spec, n=22, noise=0.25, seed=1)
    if len(ds.stereo) < 12:
        errors.append(f"synth produced only {len(ds.stereo)} stereo views")
        print("SELFTEST FAIL")
        for e in errors:
            print(" -", e)
        return 1

    cal = solve(ds, hold=0.2, seed=1)
    checks = {
        "fx_left": rel_f(cal.left.K[0, 0], truth["K_left"][0, 0]) < 0.08,
        "fx_right": rel_f(cal.right.K[0, 0], truth["K_right"][0, 0]) < 0.08,
        "T_dir": dir_cos(cal.T, truth["T"]) > 0.97,
        "T_scale": rel_f(np.linalg.norm(cal.T), np.linalg.norm(truth["T"])) < 0.12,
        "holdout_l": cal.holdout_reproj_l is not None and cal.holdout_reproj_l < 1.5,
        "holdout_r": cal.holdout_reproj_r is not None and cal.holdout_reproj_r < 1.5,
        "epipolar": cal.epipolar_mean_px is not None and cal.epipolar_mean_px < 1.5,
        "rms": cal.rms < 1.0,
    }
    for k, ok in checks.items():
        if not ok:
            errors.append(f"{k} failed: { {**checks, 'hold_l': cal.holdout_reproj_l, 'hold_r': cal.holdout_reproj_r, 'epi': cal.epipolar_mean_px, 'rms': cal.rms, 'T': cal.T.reshape(-1).tolist(), 'fxL': float(cal.left.K[0,0]), 'fxR': float(cal.right.K[0,0])} }")
            break

    ds2, _ = synthetic_detections(spec, n=22, noise=0.25, seed=2)
    cal2 = solve(ds2, hold=0.2, seed=2)
    if rel_f(cal.left.K[0, 0], cal2.left.K[0, 0]) > 0.06:
        errors.append(f"stability fx drift {cal.left.K[0,0]} vs {cal2.left.K[0,0]}")

    poor = DetectionSet(spec=spec, width=640, height=480)
    poor.stereo = ds.stereo[:2]
    try:
        solve(poor)
        errors.append("2-view solve should have been rejected")
    except Rejected:
        pass

    empty = DetectionSet(spec=spec, width=640, height=480)
    try:
        solve(empty)
        errors.append("empty solve should have been rejected")
    except Rejected:
        pass

    print("synth stereo views", len(ds.stereo))
    print("rms", round(cal.rms, 4), "holdout L/R", cal.holdout_reproj_l, cal.holdout_reproj_r)
    print("epipolar_mean_px", cal.epipolar_mean_px)
    print("fx L/R", float(cal.left.K[0, 0]), float(cal.right.K[0, 0]), "true", float(truth["K_left"][0, 0]))
    print("T", cal.T.reshape(-1).tolist(), "true", truth["T"].reshape(-1).tolist())
    print("T dir cos", dir_cos(cal.T, truth["T"]))
    if errors:
        print("SELFTEST FAIL")
        for e in errors:
            print(" -", e)
        return 1
    print("SELFTEST PASS")
    return 0
