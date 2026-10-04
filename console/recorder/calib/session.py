"""Load xr-carina-sensor-v1 sessions. No Android types."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SESSION_FORMAT = "xr-carina-sensor-v1"


def _load_jsonl(p: Path) -> list[dict]:
    rows = []
    if not p.exists():
        return rows
    with p.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


@dataclass
class Frame:
    seq: int
    sdk_ts: float
    host_ns: int
    w: int
    h: int
    l0: np.ndarray | None
    r0: np.ndarray | None
    l1: np.ndarray | None
    r1: np.ndarray | None


class Session:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.meta = json.loads((self.path / "metadata.json").read_text())
        fmt = self.meta.get("format")
        if fmt != SESSION_FORMAT:
            raise ValueError(f"expected {SESSION_FORMAT}, got {fmt}")
        self.idx = _load_jsonl(self.path / "camera.index.jsonl")
        gray_path = self.path / "camera.gray8"
        self.gray = np.memmap(gray_path, dtype=np.uint8, mode="r") if gray_path.exists() else None
        self.pose = _load_jsonl(self.path / "pose.jsonl")
        self.vsync = _load_jsonl(self.path / "vsync.jsonl")

    @property
    def sn_hash(self) -> str:
        return str(self.meta.get("sn_hash") or "")

    @property
    def size(self) -> tuple[int, int]:
        if self.idx:
            return int(self.idx[0]["w"]), int(self.idx[0]["h"])
        return int(self.meta.get("width") or 0), int(self.meta.get("height") or 0)

    def _plane(self, row: dict, start: int, n: int) -> np.ndarray | None:
        if self.gray is None or n <= 0:
            return None
        w, h = int(row["w"]), int(row["h"])
        if n != w * h:
            return None
        buf = np.array(self.gray[start : start + n])
        return buf.reshape(h, w)

    def frame(self, row: dict) -> Frame:
        off = int(row.get("off", 0))
        l0n = int(row.get("l0", 0))
        r0n = int(row.get("r0", 0))
        l1n = int(row.get("l1", 0))
        r1n = int(row.get("r1", 0))
        l0 = self._plane(row, off, l0n)
        r0 = self._plane(row, off + l0n, r0n)
        l1 = self._plane(row, off + l0n + r0n, l1n)
        r1 = self._plane(row, off + l0n + r0n + l1n, r1n)
        return Frame(
            seq=int(row.get("seq", 0)),
            sdk_ts=float(row.get("sdk_ts", 0)),
            host_ns=int(row.get("host_ns", 0)),
            w=int(row["w"]),
            h=int(row["h"]),
            l0=l0,
            r0=r0,
            l1=l1,
            r1=r1,
        )

    def iter_frames(self, every: int = 1, limit: int | None = None):
        n = 0
        for i, row in enumerate(self.idx):
            if every > 1 and i % every:
                continue
            yield self.frame(row)
            n += 1
            if limit is not None and n >= limit:
                return

    def summary(self) -> dict:
        w, h = self.size
        l1 = sum(1 for r in self.idx if int(r.get("l1") or 0))
        r1 = sum(1 for r in self.idx if int(r.get("r1") or 0))
        dts = []
        prev = None
        for r in self.idx:
            ts = float(r["sdk_ts"])
            if prev is not None:
                dts.append(ts - prev)
            prev = ts
        dts_s = sorted(d for d in dts if d < 10)
        return {
            "path": str(self.path),
            "format": self.meta.get("format"),
            "closed": self.meta.get("closed"),
            "sn_hash": self.sn_hash,
            "n_cam": len(self.idx),
            "n_pose": len(self.pose),
            "n_vsync": len(self.vsync),
            "width": w,
            "height": h,
            "l1_nonzero": l1,
            "r1_nonzero": r1,
            "sdk_dt_p50": dts_s[len(dts_s) // 2] if dts_s else None,
            "sdk_dt_max": max(dts) if dts else None,
        }
