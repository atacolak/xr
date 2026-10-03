#!/usr/bin/env python3
"""Generate the side-by-side stereo test pattern used for panel bring-up.

Three squares, one per disparity, so a human looking through the glasses can
answer "is this actually stereo?" without any code running:

  yellow  disparity -56 px  -> appears nearer than the panel plane
  green   disparity   0 px  -> appears at the panel plane
  magenta disparity +56 px  -> appears farther than the panel plane

plus a white bar at each outer edge, which is only visible in both eyes at once
if each eye really is getting its own half of the frame.

Convention: the right half draws its copy of a square at
`x_left + half_width + disparity`. Negative disparity (crossed) reads as nearer.

Usage:
    tools/make-stereo-pattern.py [out.png]        # default docs/stereo-test-pattern.png
"""

from __future__ import annotations

import pathlib
import struct
import sys
import zlib

W, H = 3840, 1200
MID = W // 2
BG = (28, 30, 34)

SQUARES = [
    # colour,             x in left half, y,  side, disparity px
    ((255, 210, 60), 330, 440, 240, -56),   # yellow, nearer
    ((120, 255, 140), 1490, 440, 240, 0),   # green, at panel plane
    ((255, 130, 220), 2660, 440, 240, 56),  # magenta, farther
]
EDGE_BAR_W = 18


def rect(img: list[bytearray], x0: int, y0: int, w: int, h: int, colour: tuple[int, int, int]) -> None:
    c = bytes(colour)
    x0c, x1 = max(0, x0), min(x0 + w, W)
    if x1 <= x0c:
        return
    span = x1 - x0c
    for y in range(max(0, y0), min(y0 + h, H)):
        img[y][x0c * 3 : x1 * 3] = c * span


def build() -> list[bytearray]:
    img = [bytearray(BG * W) for _ in range(H)]
    for colour, x_left, y, side, d in SQUARES:
        rect(img, x_left, y, side, side, colour)              # left eye
        rect(img, x_left + MID + d, y, side, side, colour)    # right eye
    rect(img, 0, 0, EDGE_BAR_W, H, (255, 255, 255))
    rect(img, W - EDGE_BAR_W, 0, EDGE_BAR_W, H, (255, 255, 255))
    return img


def write_png(path: pathlib.Path, img: list[bytearray]) -> None:
    raw = b"".join(b"\x00" + bytes(r) for r in img)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)  # 8-bit truecolour
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def main() -> int:
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "docs/stereo-test-pattern.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    write_png(out, build())
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    print("  yellow d=-56 (nearer), green d=0 (panel plane), magenta d=+56 (farther), white edge bars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
