#!/usr/bin/env python3
"""Render a side-by-side stereo demo whose depth is meant to be obvious.

Why not squares with fixed disparity: absolute disparity alone is a weak cue -- the
eye cannot tell "nearer" from "merely smaller" without context, which is exactly what
the operator reported seeing. This renderer builds the cues that remove the ambiguity:

  perspective     objects are drawn at their true projected size (f/z), so "nearer"
                  and "bigger" agree instead of competing
  motion in depth each box's depth oscillates, so its disparity *changes* over time --
                  the one cue that reads as approach rather than as size
  occlusion       nearer boxes are drawn last, so they visibly pass in front of farther
                  ones and of the floor grid
  plane anchor    a static frame drawn at Z_PLANE, the glasses' virtual image distance,
                  which marks zero disparity for comparison

Geometry is physically real, not hand-tuned: two cameras separated by IPD, standard
perspective projection, and the scene set so the disparity spread stays inside the
comfortable fusion range (roughly +/-1 deg), which this script prints.

Output is a looping H.264 SBS video meant for mpv on the 3840x1200 side-by-side mode.

Usage:
    tools/make-stereo-demo.py [out.mp4] [--frames 120] [--fps 30]
"""

from __future__ import annotations

import argparse
import math
import pathlib
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

EYE_W, EYE_H = 1920, 1200
IPD = 0.064          # metres; the driver's default lens separation
FOV_H_DEG = 42.0     # per eye; from the driver's view setup
Z_PLANE = 2.5        # the glasses' virtual image distance: disparity 0 sits here
FLOOR_Y = -0.62      # metres below the eye line


def focal_px() -> float:
    return (EYE_W / 2) / math.tan(math.radians(FOV_H_DEG) / 2.0)


def project(x: float, y: float, z: float, eye: int) -> tuple[float, float]:
    """eye: -1 left, +1 right. x,y,z in metres relative to the eye line, z ahead."""
    f = focal_px()
    return (EYE_W / 2 + f * (x - eye * IPD / 2.0) / z, EYE_H / 2 - f * y / z)


def disparity_px(z: float) -> float:
    """Horizontal disparity relative to the plane, in pixels.

    Negative = nearer (crossed: the right eye's image sits left of the left eye's),
    the same convention as the flat test pattern. Uncrossed (positive) saturates, so
    a few positive pixels already reads as "at infinity" -- hence most of the usable
    range lives on the negative side.
    """
    return focal_px() * IPD * (1.0 / Z_PLANE - 1.0 / z)


# Boxes: x, y, depth range (near, far), half size, colour, phase offset.
BOXES = [
    (-0.55, 0.00, (1.45, 3.60), 0.16, (255, 96, 96), 0.00),
    (0.00, -0.18, (1.70, 4.20), 0.14, (110, 255, 150), 0.33),
    (0.58, 0.14, (1.90, 4.60), 0.12, (140, 200, 255), 0.66),
]


def box_depth(t: float, near: float, far: float, phase: float) -> float:
    """Smooth approach and recession; loops seamlessly with t in [0,1)."""
    mid, amp = (near + far) / 2.0, (far - near) / 2.0
    return mid + amp * math.cos(2.0 * math.pi * (t + phase))


def draw_floor(d: ImageDraw.ImageDraw, z_near: float, z_far: float, eye: int) -> None:
    """Receding grid lines: the perspective cue, drawn for one eye."""
    for i in range(14):  # lines of constant depth
        z = z_near * (z_far / z_near) ** (i / 13.0)
        x0, y0 = project(-4.0, FLOOR_Y, z, eye)
        x1, y1 = project(4.0, FLOOR_Y, z, eye)
        shade = int(150 * (z_near / z) ** 0.5)
        d.line([(x0, y0), (x1, y1)], fill=(shade, shade, shade), width=2)
    for j in range(-6, 7):  # lines of constant x, converging on the vanishing point
        x = j * 0.6
        x0, y0 = project(x, FLOOR_Y, z_near, eye)
        x1, y1 = project(x, FLOOR_Y, z_far, eye)
        shade = int(120 * (z_near / ((z_near + z_far) / 2)) ** 0.5)
        d.line([(x0, y0), (x1, y1)], fill=(shade, shade, shade), width=2)


def draw_box(d: ImageDraw.ImageDraw, x: float, y: float, z: float, half: float,
             colour: tuple[int, int, int], eye: int) -> None:
    """A filled front face plus two shaded faces, so it reads as a solid, not a card."""
    near = z - half
    if near < 0.3:
        return
    fx0, fy0 = project(x - half, y + half, near, eye)
    fx1, fy1 = project(x + half, y - half, near, eye)
    bx0, by0 = project(x - half, y + half, z + half, eye)
    bx1, by1 = project(x + half, y - half, z + half, eye)
    dark = tuple(int(c * 0.45) for c in colour)
    mid = tuple(int(c * 0.7) for c in colour)
    d.polygon([(fx1, fy0), (bx1, by0), (bx1, by1), (fx1, fy1)], fill=dark)   # right side
    d.polygon([(fx0, fy0), (bx0, by0), (bx1, by0), (fx1, fy0)], fill=mid)    # top
    d.rectangle([min(fx0, fx1), min(fy0, fy1), max(fx0, fx1), max(fy0, fy1)], fill=colour)


def draw_plane_frame(d: ImageDraw.ImageDraw, eye: int) -> None:
    """Static outline at Z_PLANE: zero disparity by definition, the depth reference."""
    hw, hh = 0.52, 0.26   # at 2.5 m this is ~520x260 px: visible, unlike the first try
    corners = [(-hw, hh), (hw, hh), (hw, -hh), (-hw, -hh)]
    pts = [project(x, y, Z_PLANE, eye) for x, y in corners]
    d.line(pts + [pts[0]], fill=(255, 255, 255), width=4)


def render_eye(t: float, eye: int) -> Image.Image:
    img = Image.new("RGB", (EYE_W, EYE_H), (0, 0, 0))  # black = transparent on the OLED
    d = ImageDraw.Draw(img)
    draw_floor(d, 1.2, 9.0, eye)
    draw_plane_frame(d, eye)

    order = sorted(BOXES, key=lambda b: -box_depth(t, b[2][0], b[2][1], b[5]))  # far first
    for x, y, (near, far), half, colour, phase in order:
        draw_box(d, x, y, box_depth(t, near, far, phase), half, colour, eye)
    return img


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="docs/stereo-demo.mp4")
    ap.add_argument("--frames", type=int, default=120)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--crf", type=int, default=18)
    a = ap.parse_args()

    depths = [box_depth(i / a.frames, b[2][0], b[2][1], b[5]) for i in range(a.frames) for b in BOXES]
    disp = [disparity_px(z) for z in depths]
    print(f"SBS {EYE_W*2}x{EYE_H} @ {a.fps} fps, {a.frames} frames "
          f"({a.frames / a.fps:.1f} s loop), eye FOV {FOV_H_DEG} deg, IPD {IPD*1000:.0f} mm")
    print(f"  disparity range {min(disp):+.1f}..{max(disp):+.1f} px (negative = nearer) "
          f"({min(disp)/focal_px()*180/math.pi:+.2f}..{max(disp)/focal_px()*180/math.pi:+.2f} deg), "
          f"plane at {Z_PLANE} m")
    print(f"  depth range {min(depths):.2f}..{max(depths):.2f} m")

    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{EYE_W*2}x{EYE_H}", "-r", str(a.fps), "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", str(a.crf),
           "-pix_fmt", "yuv420p", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    for i in range(a.frames):
        t = i / a.frames
        frame = np.zeros((EYE_H, EYE_W * 2, 3), dtype=np.uint8)
        frame[:, :EYE_W] = np.asarray(render_eye(t, -1))
        frame[:, EYE_W:] = np.asarray(render_eye(t, +1))
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        print("ffmpeg failed", file=sys.stderr)
        return 1
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    print(f"play it with:  mpv --fullscreen --loop --no-audio {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
