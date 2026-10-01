#!/usr/bin/env python3
"""Replay an xr-carina-sensor-v1 session without glasses.

Usage:
  console/recorder/sensor_replay.py <session-dir> [--png-dir DIR]
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


IMU_REC = struct.Struct("<qdffffff")  # host_ns, sdk_ts, 6 floats


def load_index(p: Path) -> list[dict]:
    rows = []
    with p.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def maybe_png(gray: bytes, w: int, h: int, dest: Path) -> None:
    try:
        from PIL import Image
    except ImportError:
        return
    if len(gray) < w * h:
        return
    Image.frombytes("L", (w, h), gray[: w * h]).save(dest)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--png-dir")
    args = ap.parse_args()
    d = Path(args.session)
    meta = json.loads((d / "metadata.json").read_text())
    idx = load_index(d / "camera.index.jsonl")
    gray = (d / "camera.gray8").read_bytes()
    pose = load_index(d / "pose.jsonl") if (d / "pose.jsonl").exists() else []
    vsync = load_index(d / "vsync.jsonl") if (d / "vsync.jsonl").exists() else []
    imu_n = 0
    imu_path = d / "imu.bin"
    if imu_path.exists():
        blob = imu_path.read_bytes()
        imu_n = len(blob) // IMU_REC.size

    print("format", meta.get("format"))
    print("closed", meta.get("closed"))
    print("sn_hash", (meta.get("sn_hash") or "")[:16])
    print("cam frames", len(idx), "gray_bytes", len(gray), "meta.gray_bytes", meta.get("gray_bytes"))
    print("pose", len(pose), "imu", imu_n, "vsync", len(vsync))

    if not idx:
        print("no camera index")
        return 1

    recon = 0
    l1 = r1 = 0
    dts = []
    prev = None
    hashes = []
    for i, row in enumerate(idx):
        n = int(row.get("l0", 0)) + int(row.get("r0", 0)) + int(row.get("l1", 0)) + int(row.get("r1", 0))
        recon += n
        if int(row.get("l1", 0)):
            l1 += 1
        if int(row.get("r1", 0)):
            r1 += 1
        ts = float(row["sdk_ts"])
        if prev is not None:
            dts.append(ts - prev)
        prev = ts
        hashes.append((row.get("l0_hash"), row.get("r0_hash"), row.get("l1_hash"), row.get("r1_hash")))

    print("sum plane bytes vs file", recon, len(gray), "match" if recon == len(gray) else "MISMATCH")
    print("frames with L1", l1, "R1", r1)
    if dts:
        dts.sort()
        print("cam sdk dt s: min", round(dts[0], 5), "p50", round(dts[len(dts)//2], 5),
              "max", round(dts[-1], 5), "n", len(dts))
    # identical consecutive stereo hashes
    repeats = 0
    for a, b in zip(hashes, hashes[1:]):
        if a == b:
            repeats += 1
    print("consecutive identical hash tuples", repeats)

    if args.png_dir and idx:
        out = Path(args.png_dir)
        out.mkdir(parents=True, exist_ok=True)
        first = idx[0]
        w, h = int(first["w"]), int(first["h"])
        off = 0
        maybe_png(gray[off:off + int(first.get("l0", 0))], w, h, out / "first_l0.png")
        off += int(first.get("l0", 0))
        maybe_png(gray[off:off + int(first.get("r0", 0))], w, h, out / "first_r0.png")
        last = idx[-1]
        off = int(last["off"])
        maybe_png(gray[off:off + int(last.get("l0", 0))], w, h, out / "last_l0.png")
        print("png dir", out)

    return 0 if recon == len(gray) else 2


if __name__ == "__main__":
    raise SystemExit(main())
