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
    ((255, 210, 60), 260, 440, 240, -32),    # yellow, nearer
    ((120, 255, 140), 840, 440, 240, 0),     # green, at panel plane
    ((255, 130, 220), 1420, 440, 240, 32),   # magenta, farther
]
EDGE_BAR_W = 18


def check_layout() -> None:
    """Every copy must land inside its own half, or an eye sees the wrong picture.

    This check exists because the first version of this pattern put the magenta
    square's left-eye copy at x=2660 -- outside the left half -- so the left eye saw
    two squares instead of three while a stray copy leaked into the right eye's half.
    """
    problems = []
    for colour, x_left, y, side, d in SQUARES:
        if x_left < 0 or x_left + side > MID:
            problems.append(f"left copy of {colour} spans {x_left}..{x_left + side}, outside 0..{MID}")
        x_right = x_left + MID + d
        if x_right < MID or x_right + side > W:
            problems.append(f"right copy of {colour} spans {x_right}..{x_right + side}, outside {MID}..{W}")
    if problems:
        for p in problems:
            print(f"  LAYOUT ERROR: {p}")
        raise SystemExit(1)


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
    check_layout()
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "docs/stereo-test-pattern.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    write_png(out, build())
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    for colour, x, y, side, d in SQUARES:
        print(f"  left x={x:<5} right x={x + MID + d:<5} disparity {d:+d} px")
    print("  white bars at both outer edges; every copy checked to sit inside its own half")
    return 0


if __name__ == "__main__":
    sys.exit(main())
