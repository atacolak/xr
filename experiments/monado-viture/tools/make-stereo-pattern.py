#!/usr/bin/env python3
"""Generate the side-by-side stereo test pattern used for panel bring-up.

Designed to be judged through the glasses, on a black background: on a see-through
OLED, black is transparent, so the operator sees the real room with the test shapes
floating in it.

Two rows:

  reference row (top, white)   all at disparity 0 -> sits at the panel plane. This is
                               the anchor: nothing here should look near or far.
  depth row (bottom, coloured) a monotonic staircase, nearest on the left:
                               white 0 px, cyan -16, green -32, yellow -48, red -64.
                               Each step is ~0.35 deg of convergence, so the whole row
                               should read as a ramp receding to the right.

Negative disparity = crossed = nearer (the right eye's copy is shifted left relative
to the left eye's). Positive is capped small on purpose: uncrossed disparity saturates
(a few pixels already reads as "at infinity"), so all the usable range is on the near
side.

A white bar at each outer edge is a per-eye marker: each eye sees the bar on its own
outer edge only, which is how you tell both halves are being displayed at once.

Usage:
    tools/make-stereo-pattern.py [out.png]     # default docs/stereo-test-pattern.png
"""

from __future__ import annotations

import pathlib
import struct
import sys
import zlib

W, H = 3840, 1200
MID = W // 2
BG = (0, 0, 0)  # transparent through the glasses

# (colour, x in the LEFT half, y, side, disparity px). Left copy at x, right copy at
# x + MID + d; check_layout() refuses any entry whose copies cross the half boundary.
REFERENCE = [
    ((255, 255, 255), 300, 180, 120, 0),
    ((255, 255, 255), 960, 180, 120, 0),
    ((255, 255, 255), 1620, 180, 120, 0),
]
RAMP = [
    ((255, 255, 255), 160, 700, 180, 0),     # at the panel plane
    ((120, 220, 255), 540, 700, 180, -16),   # nearer
    ((120, 255, 140), 920, 700, 180, -32),
    ((255, 230, 120), 1300, 700, 180, -48),
    ((255, 110, 110), 1680, 700, 180, -64),  # nearest
]
EDGE_BAR_W = 18


def check_layout() -> None:
    """Every copy must sit inside its own half, or an eye sees the wrong picture.

    This exists because the first version put the magenta square's left-eye copy at
    x=2660 -- outside the left half -- so that eye saw fewer squares than the other
    while a stray copy leaked into its neighbour's half.
    """
    problems = []
    for row, entries in (("reference", REFERENCE), ("ramp", RAMP)):
        for colour, x_left, y, side, d in entries:
            if x_left < 0 or x_left + side > MID:
                problems.append(f"{row}: left copy {colour} spans {x_left}..{x_left + side}, outside 0..{MID}")
            x_right = x_left + MID + d
            if x_right < MID or x_right + side > W:
                problems.append(f"{row}: right copy {colour} spans {x_right}..{x_right + side}, outside {MID}..{W}")
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
    for colour, x_left, y, side, d in REFERENCE + RAMP:
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
    print("  reference row (white, y=180): all disparity 0 -- the panel plane")
    print("  depth row (y=700), nearest first:")
    for colour, x, y, side, d in RAMP:
        print(f"    left x={x:<5} right x={x + MID + d:<5} disparity {d:+d} px   {colour}")
    print("  black background is transparent on the OLED; white bars mark each eye's outer edge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
