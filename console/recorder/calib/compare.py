"""Offline session comparison. Does not open Carina USB."""
from __future__ import annotations

import json

import numpy as np

from .session import Session


def _mean_plane(session: Session, side: str, n: int = 5) -> dict | None:
    acc = []
    for i, fr in enumerate(session.iter_frames(every=max(1, len(session.idx) // 20 or 1), limit=n)):
        img = fr.l0 if side == "l0" else fr.r0
        if img is None:
            continue
        acc.append((float(img.mean()), float(img.std()), int(img.min()), int(img.max())))
    if not acc:
        return None
    a = np.array(acc, dtype=float)
    return {
        "mean": float(a[:, 0].mean()),
        "std": float(a[:, 1].mean()),
        "min": int(a[:, 2].min()),
        "max": int(a[:, 3].max()),
        "n": len(acc),
    }


def compare(a: Session, b: Session | None = None) -> dict:
    sa = a.summary()
    sa["l0"] = _mean_plane(a, "l0")
    sa["r0"] = _mean_plane(a, "r0")
    out = {"a": sa, "b": None, "delta": None, "notes": []}
    if b is None:
        out["notes"].append("single session; Linux counterpart not provided")
        out["notes"].append(
            "Android-derived calibration reusable on Linux frames: UNKNOWN until xr-wdw.10 hardware"
        )
        return out
    sb = b.summary()
    sb["l0"] = _mean_plane(b, "l0")
    sb["r0"] = _mean_plane(b, "r0")
    out["b"] = sb
    keys = ["width", "height", "l1_nonzero", "r1_nonzero"]
    delta = {k: {"a": sa.get(k), "b": sb.get(k), "match": sa.get(k) == sb.get(k)} for k in keys}
    delta["sn_hash"] = {"a": sa.get("sn_hash"), "b": sb.get("sn_hash"), "match": sa.get("sn_hash") == sb.get("sn_hash")}
    out["delta"] = delta
    if sa.get("width") != sb.get("width") or sa.get("height") != sb.get("height"):
        out["notes"].append("SIZE MISMATCH — Android calib is NOT directly reusable")
    elif sa.get("l1_nonzero") != sb.get("l1_nonzero") or sa.get("r1_nonzero") != sb.get("r1_nonzero"):
        out["notes"].append("L1/R1 presence differs — inspect before reuse")
    else:
        out["notes"].append("size/plane presence match; still need orientation/frustum/timestamp compare")
    out["notes"].append(
        "Android-derived calibration reusable on Linux frames: UNKNOWN until a Linux live capture exists"
    )
    return out


def dumps(report: dict) -> str:
    return json.dumps(report, indent=2)
