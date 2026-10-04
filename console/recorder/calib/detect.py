"""ChArUco detection + diversity scoring."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .board import BoardSpec


MIN_CORNERS = 8
BINS = 3


@dataclass
class View:
    seq: int
    side: str  # "l0" | "r0"
    ids: np.ndarray  # (N,) int
    corners: np.ndarray  # (N, 1, 2) float32
    obj: np.ndarray  # (N, 1, 3) float64
    img: np.ndarray  # (N, 1, 2) float64

    @property
    def n(self) -> int:
        return int(self.ids.size)

    def center(self) -> tuple[float, float]:
        c = self.corners.reshape(-1, 2).mean(axis=0)
        return float(c[0]), float(c[1])

    def scale(self) -> float:
        xy = self.corners.reshape(-1, 2)
        return float(np.linalg.norm(xy.max(axis=0) - xy.min(axis=0)))

    def yaw(self) -> float:
        xy = self.corners.reshape(-1, 2)
        i0 = int(np.argmin(xy[:, 0]))
        i1 = int(np.argmax(xy[:, 0]))
        d = xy[i1] - xy[i0]
        return float(np.arctan2(d[1], d[0]))


@dataclass
class StereoObs:
    seq: int
    left: View
    right: View
    ids: np.ndarray
    obj: np.ndarray
    img_l: np.ndarray
    img_r: np.ndarray


@dataclass
class DetectionSet:
    spec: BoardSpec
    width: int
    height: int
    views_l: list[View] = field(default_factory=list)
    views_r: list[View] = field(default_factory=list)
    stereo: list[StereoObs] = field(default_factory=list)
    n_scanned: int = 0
    n_rejected_sparse: int = 0
    n_rejected_dup: int = 0
    prompts: list[str] = field(default_factory=list)


def _detector(spec: BoardSpec) -> cv2.aruco.CharucoDetector:
    params = cv2.aruco.CharucoParameters()
    det_params = cv2.aruco.DetectorParameters()
    det_params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    return cv2.aruco.CharucoDetector(spec.opencv(), params, det_params)


def detect_image(gray: np.ndarray, spec: BoardSpec, detector=None) -> tuple[np.ndarray, np.ndarray] | None:
    det = detector or _detector(spec)
    corners, ids, _mc, _mi = det.detectBoard(gray)
    if ids is None or corners is None or len(ids) < MIN_CORNERS:
        return None
    ids = np.asarray(ids).reshape(-1)
    corners = np.asarray(corners, dtype=np.float32).reshape(-1, 1, 2)
    return corners, ids


def match_points(spec: BoardSpec, corners: np.ndarray, ids: np.ndarray):
    board = spec.opencv()
    obj, img = board.matchImagePoints(corners, ids.reshape(-1, 1))
    if obj is None or img is None or len(obj) < MIN_CORNERS:
        return None
    return np.asarray(obj, dtype=np.float64), np.asarray(img, dtype=np.float64)


def _bin(cx: float, cy: float, w: int, h: int) -> tuple[int, int]:
    bx = min(BINS - 1, max(0, int(cx / w * BINS)))
    by = min(BINS - 1, max(0, int(cy / h * BINS)))
    return bx, by


def _dup_key(v: View) -> tuple:
    cx, cy = v.center()
    return (int(cx / 48), int(cy / 48), int(v.scale() / 40), int(v.yaw() / (np.pi / 12)))


def detect_session(session, spec: BoardSpec, every: int = 2, limit: int | None = None) -> DetectionSet:
    w, h = session.size
    out = DetectionSet(spec=spec, width=w, height=h)
    det = _detector(spec)
    seen_l: set[tuple] = set()
    seen_r: set[tuple] = set()
    by_seq: dict[int, dict[str, View]] = {}

    for fr in session.iter_frames(every=every, limit=limit):
        out.n_scanned += 1
        for side, img in (("l0", fr.l0), ("r0", fr.r0)):
            if img is None:
                continue
            hit = detect_image(img, spec, det)
            if hit is None:
                out.n_rejected_sparse += 1
                continue
            corners, ids = hit
            matched = match_points(spec, corners, ids)
            if matched is None:
                out.n_rejected_sparse += 1
                continue
            obj, imgp = matched
            view = View(seq=fr.seq, side=side, ids=ids, corners=corners, obj=obj, img=imgp)
            key = _dup_key(view)
            bucket = seen_l if side == "l0" else seen_r
            if key in bucket:
                out.n_rejected_dup += 1
                continue
            bucket.add(key)
            (out.views_l if side == "l0" else out.views_r).append(view)
            by_seq.setdefault(fr.seq, {})[side] = view

    for seq, pair in sorted(by_seq.items()):
        if "l0" not in pair or "r0" not in pair:
            continue
        left, right = pair["l0"], pair["r0"]
        common = np.intersect1d(left.ids, right.ids)
        if common.size < MIN_CORNERS:
            continue
        # reorder both to common ids
        lmap = {int(i): k for k, i in enumerate(left.ids)}
        rmap = {int(i): k for k, i in enumerate(right.ids)}
        obj, imgl, imgr = [], [], []
        for cid in common:
            li, ri = lmap[int(cid)], rmap[int(cid)]
            obj.append(left.obj[li])
            imgl.append(left.img[li])
            imgr.append(right.img[ri])
        obj = np.asarray(obj, dtype=np.float64)
        imgl = np.asarray(imgl, dtype=np.float64)
        imgr = np.asarray(imgr, dtype=np.float64)
        out.stereo.append(
            StereoObs(seq=seq, left=left, right=right, ids=common, obj=obj, img_l=imgl, img_r=imgr)
        )

    out.prompts = prompts(out)
    return out


def prompts(ds: DetectionSet) -> list[str]:
    msgs: list[str] = []
    views = ds.views_l + ds.views_r
    if len(ds.stereo) < 12:
        msgs.append(f"need more stereo pairs ({len(ds.stereo)}/12). keep the board in BOTH eyes.")
    if not views:
        msgs.append("no ChArUco found. fill the view with the fullscreen target.")
        return msgs
    w, h = ds.width, ds.height
    scales = [v.scale() / max(w, 1) for v in views]
    if max(scales) < 0.22:
        msgs.append("move closer")
    if min(scales) > 0.55:
        msgs.append("move farther")
    if max(scales) - min(scales) < 0.12:
        msgs.append("vary distance")
    yaws = [v.yaw() for v in views]
    if max(yaws) - min(yaws) < 0.25:
        msgs.append("add stronger tilt")
    occupied = set()
    for v in views:
        cx, cy = v.center()
        occupied.add(_bin(cx, cy, w, h))
    names = {
        (0, 0): "upper-left",
        (1, 0): "upper-center",
        (2, 0): "upper-right",
        (0, 1): "mid-left",
        (1, 1): "center",
        (2, 1): "mid-right",
        (0, 2): "lower-left",
        (1, 2): "lower-center",
        (2, 2): "lower-right",
    }
    missing = [names[k] for k in names if k not in occupied]
    if missing:
        msgs.append("cover " + ", ".join(missing[:3]))
    return msgs


def summarize(ds: DetectionSet) -> dict:
    return {
        "n_scanned": ds.n_scanned,
        "n_left": len(ds.views_l),
        "n_right": len(ds.views_r),
        "n_stereo": len(ds.stereo),
        "rejected_sparse": ds.n_rejected_sparse,
        "rejected_dup": ds.n_rejected_dup,
        "prompts": ds.prompts,
        "width": ds.width,
        "height": ds.height,
        "board": ds.spec.to_json(),
    }
