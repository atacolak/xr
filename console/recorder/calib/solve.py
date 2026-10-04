"""Fisheye KB4 mono + stereo solve. Translation in board units, not metres."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .detect import DetectionSet, MIN_CORNERS, StereoObs

MIN_STEREO = 12
HOLD_FRAC = 0.2
FLAGS_MONO = cv2.CALIB_RECOMPUTE_EXTRINSIC | cv2.CALIB_FIX_SKEW
CRIT = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 200, 1e-7)


class Rejected(RuntimeError):
    pass


@dataclass
class MonoCalib:
    K: np.ndarray
    D: np.ndarray
    rms: float
    n_views: int
    holdout_rms: float | None


@dataclass
class StereoCalib:
    left: MonoCalib
    right: MonoCalib
    R: np.ndarray
    T: np.ndarray
    E: np.ndarray
    F: np.ndarray
    rms: float
    holdout_reproj_l: float | None
    holdout_reproj_r: float | None
    epipolar_mean_px: float | None
    n_stereo: int
    n_holdout: int
    width: int
    height: int
    rejected: bool = False
    reason: str = ""


def _split(obs: list[StereoObs], hold: float, rng: np.random.Generator):
    n = len(obs)
    if n < MIN_STEREO:
        raise Rejected(f"need >= {MIN_STEREO} stereo pairs, got {n}")
    idx = np.arange(n)
    rng.shuffle(idx)
    n_hold = max(1, int(round(n * hold))) if n >= MIN_STEREO + 3 else 0
    hold_i = set(idx[:n_hold].tolist()) if n_hold else set()
    train = [obs[i] for i in range(n) if i not in hold_i]
    test = [obs[i] for i in range(n) if i in hold_i]
    if len(train) < MIN_STEREO:
        raise Rejected(f"train set too small ({len(train)})")
    return train, test


def _mono(views_obj, views_img, size, guess=None) -> MonoCalib:
    K = np.eye(3, dtype=np.float64)
    if guess is not None:
        K = guess.copy()
    else:
        K[0, 0] = K[1, 1] = 0.4 * size[0]
        K[0, 2] = size[0] / 2.0
        K[1, 2] = size[1] / 2.0
    D = np.zeros((4, 1), dtype=np.float64)
    rms, K, D, _r, _t = cv2.fisheye.calibrate(
        views_obj, views_img, size, K, D, flags=FLAGS_MONO, criteria=CRIT
    )
    return MonoCalib(K=K, D=D, rms=float(rms), n_views=len(views_obj), holdout_rms=None)


def _reproj(K, D, obj, img) -> float:
    obj = np.asarray(obj, dtype=np.float64).reshape(-1, 1, 3)
    img = np.asarray(img, dtype=np.float64).reshape(-1, 1, 2)
    ok, rvec, tvec = cv2.fisheye.solvePnP(obj, img, K, D)
    if not ok:
        return float("inf")
    proj, _ = cv2.fisheye.projectPoints(obj, rvec, tvec, K, D)
    err = np.linalg.norm(proj.reshape(-1, 2) - img.reshape(-1, 2), axis=1)
    return float(err.mean())


def _essential(R, T) -> np.ndarray:
    Tx = np.array(
        [[0, -T[2, 0], T[1, 0]], [T[2, 0], 0, -T[0, 0]], [-T[1, 0], T[0, 0], 0]],
        dtype=np.float64,
    )
    return Tx @ R


def _fundamental(E, K1, K2) -> np.ndarray:
    return np.linalg.inv(K2).T @ E @ np.linalg.inv(K1)


def _epipolar_px(cal: StereoCalib, obs: list[StereoObs]) -> float:
    R1, R2, P1, P2, _Q = cv2.fisheye.stereoRectify(
        cal.left.K,
        cal.left.D,
        cal.right.K,
        cal.right.D,
        (cal.width, cal.height),
        cal.R,
        cal.T,
        flags=cv2.CALIB_ZERO_DISPARITY,
    )
    errs = []
    for o in obs:
        pl = cv2.fisheye.undistortPoints(o.img_l.astype(np.float64), cal.left.K, cal.left.D, R=R1, P=P1)
        pr = cv2.fisheye.undistortPoints(o.img_r.astype(np.float64), cal.right.K, cal.right.D, R=R2, P=P2)
        dy = np.abs(pl.reshape(-1, 2)[:, 1] - pr.reshape(-1, 2)[:, 1])
        errs.append(float(dy.mean()))
    return float(np.mean(errs)) if errs else None  # type: ignore[return-value]


def solve(ds: DetectionSet, hold: float = HOLD_FRAC, seed: int = 0) -> StereoCalib:
    if ds.width <= 0 or ds.height <= 0:
        raise Rejected("unknown image size")
    if len(ds.stereo) < MIN_STEREO:
        raise Rejected(
            f"need >= {MIN_STEREO} diverse stereo observations, got {len(ds.stereo)}. "
            + (" ".join(ds.prompts) if ds.prompts else "")
        )
    rng = np.random.default_rng(seed)
    train, test = _split(ds.stereo, hold, rng)
    size = (ds.width, ds.height)

    def pack_obj(o: StereoObs):
        a = np.asarray(o.obj, dtype=np.float64).reshape(-1, 3)
        return a.reshape(1, -1, 3)

    def pack_img(a):
        a = np.asarray(a, dtype=np.float64).reshape(-1, 2)
        return a.reshape(1, -1, 2)

    objs = [pack_obj(o) for o in train]
    imgl = [pack_img(o.img_l) for o in train]
    imgr = [pack_img(o.img_r) for o in train]

    left = _mono(objs, imgl, size)
    right = _mono(objs, imgr, size)

    R = np.eye(3, dtype=np.float64)
    T = np.zeros((3, 1), dtype=np.float64)
    rms, K1, D1, K2, D2, R, T, _rv, _tv = cv2.fisheye.stereoCalibrate(
        objs,
        imgl,
        imgr,
        left.K,
        left.D,
        right.K,
        right.D,
        size,
        flags=cv2.CALIB_FIX_INTRINSIC,
        criteria=CRIT,
    )
    left.K, left.D = K1, D1
    right.K, right.D = K2, D2
    E = _essential(R, T)
    F = _fundamental(E, K1, K2)

    hold_l = hold_r = None
    if test:
        hold_l = float(np.mean([_reproj(K1, D1, pack_obj(o), pack_img(o.img_l)) for o in test]))
        hold_r = float(np.mean([_reproj(K2, D2, pack_obj(o), pack_img(o.img_r)) for o in test]))
        left.holdout_rms = hold_l
        right.holdout_rms = hold_r

    cal = StereoCalib(
        left=left,
        right=right,
        R=R,
        T=T,
        E=E,
        F=F,
        rms=float(rms),
        holdout_reproj_l=hold_l,
        holdout_reproj_r=hold_r,
        epipolar_mean_px=None,
        n_stereo=len(train),
        n_holdout=len(test),
        width=ds.width,
        height=ds.height,
    )
    try:
        cal.epipolar_mean_px = _epipolar_px(cal, train[: min(12, len(train))])
    except cv2.error:
        cal.epipolar_mean_px = None
    return cal


def rectify_maps(cal: StereoCalib):
    R1, R2, P1, P2, Q = cv2.fisheye.stereoRectify(
        cal.left.K,
        cal.left.D,
        cal.right.K,
        cal.right.D,
        (cal.width, cal.height),
        cal.R,
        cal.T,
        flags=cv2.CALIB_ZERO_DISPARITY,
    )
    m1l, m2l = cv2.fisheye.initUndistortRectifyMap(
        cal.left.K, cal.left.D, R1, P1, (cal.width, cal.height), cv2.CV_16SC2
    )
    m1r, m2r = cv2.fisheye.initUndistortRectifyMap(
        cal.right.K, cal.right.D, R2, P2, (cal.width, cal.height), cv2.CV_16SC2
    )
    return (m1l, m2l), (m1r, m2r), Q


def remap_pair(left_img, right_img, cal: StereoCalib):
    (m1l, m2l), (m1r, m2r), Q = rectify_maps(cal)
    rl = cv2.remap(left_img, m1l, m2l, cv2.INTER_LINEAR)
    rr = cv2.remap(right_img, m1r, m2r, cv2.INTER_LINEAR)
    return rl, rr, Q
