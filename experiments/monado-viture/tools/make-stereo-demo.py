#!/usr/bin/env python3
"""Render a side-by-side stereo demo whose depth is meant to be obvious.

Why not squares with fixed disparity: absolute disparity alone is a weak cue -- the eye
cannot tell "nearer" from "merely smaller" without context. This builds the cues that
remove the ambiguity:

  perspective     objects are drawn at their true projected size (f/z)
  motion in depth each box's depth oscillates, so its disparity changes over time --
                  the cue that reads as approach rather than as size
  occlusion       faces are drawn far-to-near, so nearer boxes pass in front of farther
                  ones and of the floor grid
  plane anchor    a static frame at Z_PLANE, the glasses' virtual image distance, which
                  marks zero disparity for comparison

Geometry is real, not hand-tuned: the scene is rendered twice from two virtual cameras
separated by IPD (the same pair of eyes you have), with an ordinary perspective
projection; depth is the disparity that separation produces. The camera is a parameter
(position + yaw/pitch/roll), so a head-pose source can drive it -- that is what turns
this into the 3DoF/6DoF demo.

Output is a looping H.264 SBS video for mpv on the 3840x1200 side-by-side mode, or a
single still frame with an arbitrary head pose.

Usage:
    tools/make-stereo-demo.py docs/stereo-demo.mp4 --frames 120
    tools/make-stereo-demo.py /tmp/turned.png --still --yaw 12
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
FOG = 0.055          # how fast things dim with distance


def focal_px() -> float:
    return (EYE_W / 2) / math.tan(math.radians(FOV_H_DEG) / 2.0)


class Camera:
    """Position plus yaw/pitch/roll in degrees. Defaults look straight down +Z."""

    def __init__(self, pos=(0.0, 0.0, 0.0), yaw=0.0, pitch=0.0, roll=0.0):
        self.pos = np.array(pos, dtype=float)
        cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
        cr, sr = math.cos(math.radians(roll)), math.sin(math.radians(roll))
        # Must match the convention the pose is decomposed with, or the mapping is skewed
        # for combined motions: R = Ry(yaw) * Rx(pitch) * Rz(roll) (Y-up, as the SDK poses
        # are, and as viture-pose-dump --self-test-axes verifies).
        ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
        rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]])
        self.rot = ry @ rx @ rz
        self.eye_offset = np.array([IPD / 2.0, 0.0, 0.0])

    def to_camera(self, p, eye: int):
        """World point -> camera-space, for one eye (-1 left, +1 right)."""
        # self.rot maps camera space -> world, so the (camera-space) eye offset must be
        # rotated by rot, not rot.T: with rot.T the stereo baseline is rotated wrongly and
        # a roll tips it out of horizontal.
        eye_world = self.rot @ (self.eye_offset * eye)
        return self.rot.T @ (np.asarray(p, dtype=float) - self.pos - eye_world)

    def project(self, p, eye: int) -> tuple[float, float]:
        c = self.to_camera(p, eye)
        z = max(c[2], 1e-3)
        f = focal_px()
        return (EYE_W / 2 + f * c[0] / z, EYE_H / 2 - f * c[1] / z)


# Boxes: x, y, depth range (near, far), half size, colour, phase offset.
BOXES = [
    (-0.62, 0.00, (1.45, 3.60), 0.17, (255, 96, 96), 0.00),
    (0.00, -0.22, (1.75, 4.30), 0.15, (110, 255, 150), 0.28),
    (0.62, 0.16, (1.95, 4.70), 0.13, (140, 200, 255), 0.55),
    (-0.30, 0.28, (2.30, 5.40), 0.11, (255, 220, 120), 0.79),
    (0.34, -0.10, (2.10, 5.00), 0.12, (215, 150, 255), 0.91),
]


def box_depth(t: float, near: float, far: float, phase: float) -> float:
    """Smooth approach and recession; loops seamlessly with t in [0,1)."""
    mid, amp = (near + far) / 2.0, (far - near) / 2.0
    return mid + amp * math.cos(2.0 * math.pi * (t + phase))


def disparity_px(z: float) -> float:
    """Horizontal disparity relative to the plane, in pixels.

    Negative = nearer (crossed: the right eye's image sits left of the left eye's), the
    same convention as the flat test pattern. Uncrossed (positive) saturates, so a few
    positive pixels already reads as "at infinity" -- hence most of the usable range
    lives on the negative side.
    """
    return focal_px() * IPD * (1.0 / Z_PLANE - 1.0 / z)


def shaded(colour, factor: float, z: float) -> tuple[int, int, int]:
    dim = max(0.40, 1.0 - FOG * max(0.0, z - Z_PLANE))
    return tuple(max(0, min(255, int(c * factor * dim))) for c in colour)


def draw_floor(d: ImageDraw.ImageDraw, cam: Camera, eye: int, z_near: float, z_far: float) -> None:
    """Receding grid: the perspective cue, projected for this eye like everything else."""
    for i in range(16):
        z = z_near * (z_far / z_near) ** (i / 15.0)
        x0, y0 = cam.project((-4.0, FLOOR_Y, z), eye)
        x1, y1 = cam.project((4.0, FLOOR_Y, z), eye)
        shade = int(150 * (z_near / z) ** 0.5)
        d.line([(x0, y0), (x1, y1)], fill=(shade, shade, shade), width=2)
    for j in range(-7, 8):
        x = j * 0.55
        x0, y0 = cam.project((x, FLOOR_Y, z_near), eye)
        x1, y1 = cam.project((x, FLOOR_Y, z_far), eye)
        mid_z = (z_near + z_far) / 2.0
        shade = int(120 * (z_near / mid_z) ** 0.5)
        d.line([(x0, y0), (x1, y1)], fill=(shade, shade, shade), width=2)


def draw_box(d: ImageDraw.ImageDraw, cam: Camera, x: float, y: float, z: float, half: float,
             colour: tuple[int, int, int], eye: int) -> None:
    """Draw a real box: exact projected quads, with the faces that eye can actually see.

    Two bugs lived here and both were visible through the glasses: the front face was
    drawn as the bounding-box *rectangle* of two projected corners (a perspective quad
    is not a rectangle, so the faces did not line up and the box read as a flimsy card),
    and only the right-hand side face was ever drawn, so any box to the right of an eye
    showed no side at all.
    """
    z_near, z_far = z - half, z + half
    if z_near < 0.35:
        return
    lo, hi = -half, half

    def corner(dx, dy, dz):
        return cam.project((x + dx, y + dy, z + dz), eye)

    # Which faces this eye can see: compare the box centre with the eye in camera space.
    centre = cam.to_camera((x, y, z), eye)
    side_dx = -half if centre[0] > 0 else half          # box right of eye -> its left face
    top_dy = half if centre[1] < 0 else -half           # box below eye -> its top face

    # Side face (quad), then top/bottom face (quad), then the front face last.
    quad_side = [corner(side_dx, lo, -half), corner(side_dx, lo, half),
                 corner(side_dx, hi, half), corner(side_dx, hi, -half)]
    d.polygon(quad_side, fill=shaded(colour, 0.62, z))
    quad_top = [corner(lo, top_dy, -half), corner(hi, top_dy, -half),
                corner(hi, top_dy, half), corner(lo, top_dy, half)]
    d.polygon(quad_top, fill=shaded(colour, 1.25, z))
    quad_front = [corner(lo, hi, -half), corner(hi, hi, -half),
                  corner(hi, lo, -half), corner(lo, lo, -half)]
    d.polygon(quad_front, fill=shaded(colour, 1.0, z))


def draw_plane_frame(d: ImageDraw.ImageDraw, cam: Camera, eye: int) -> None:
    """Static outline at Z_PLANE: zero disparity by definition, the depth reference."""
    hw, hh = 0.52, 0.26
    pts = [cam.project((dx, dy, Z_PLANE), eye)
           for dx, dy in ((-hw, hh), (hw, hh), (hw, -hh), (-hw, -hh))]
    d.line(pts + [pts[0]], fill=(255, 255, 255), width=4)


def render_eye(t: float, eye: int, cam: Camera) -> Image.Image:
    img = Image.new("RGB", (EYE_W, EYE_H), (0, 0, 0))  # black = transparent on the OLED
    d = ImageDraw.Draw(img)
    draw_floor(d, cam, eye, 1.2, 9.0)
    draw_plane_frame(d, cam, eye)

    # Painter's algorithm: farthest first, so nearer boxes occlude farther ones.
    for x, y, (near, far), half, colour, phase in sorted(
            BOXES, key=lambda b: -box_depth(t, b[2][0], b[2][1], b[5])):
        draw_box(d, cam, x, y, box_depth(t, near, far, phase), half, colour, eye)
    return img


def render_frame(t: float, cam: Camera) -> np.ndarray:
    frame = np.zeros((EYE_H, EYE_W * 2, 3), dtype=np.uint8)
    frame[:, :EYE_W] = np.asarray(render_eye(t, -1, cam))
    frame[:, EYE_W:] = np.asarray(render_eye(t, +1, cam))
    return frame


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="docs/stereo-demo.mp4")
    ap.add_argument("--frames", type=int, default=120)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--still", action="store_true", help="render one PNG instead of a video")
    ap.add_argument("--t", type=float, default=0.0, help="animation phase for --still")
    ap.add_argument("--yaw", type=float, default=0.0)
    ap.add_argument("--pitch", type=float, default=0.0)
    ap.add_argument("--roll", type=float, default=0.0)
    ap.add_argument("--cam", default="0,0,0", help="camera position x,y,z in metres")
    a = ap.parse_args()

    cam = Camera(pos=tuple(float(v) for v in a.cam.split(",")), yaw=a.yaw, pitch=a.pitch, roll=a.roll)

    if a.still:
        out = pathlib.Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(render_frame(a.t, cam)).save(out)
        print(f"wrote {out} ({out.stat().st_size} bytes)  camera yaw={a.yaw} pitch={a.pitch} roll={a.roll}")
        return 0

    depths = [box_depth(i / a.frames, b[2][0], b[2][1], b[5]) for i in range(a.frames) for b in BOXES]
    disp = [disparity_px(z) for z in depths]
    print(f"SBS {EYE_W*2}x{EYE_H} @ {a.fps} fps, {a.frames} frames ({a.frames / a.fps:.1f} s loop), "
          f"eye FOV {FOV_H_DEG} deg, IPD {IPD*1000:.0f} mm, {len(BOXES)} boxes")
    print(f"  disparity range {min(disp):+.1f}..{max(disp):+.1f} px (negative = nearer) "
          f"({min(disp)/focal_px()*180/math.pi:+.2f}..{max(disp)/focal_px()*180/math.pi:+.2f} deg), "
          f"plane at {Z_PLANE} m; depth range {min(depths):.2f}..{max(depths):.2f} m")

    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{EYE_W*2}x{EYE_H}", "-r", str(a.fps), "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", str(a.crf),
           "-pix_fmt", "yuv420p", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    for i in range(a.frames):
        proc.stdin.write(render_frame(i / a.frames, cam).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        print("ffmpeg failed", file=sys.stderr)
        return 1
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    print(f"play it with:  mpv --fullscreen --loop --no-audio {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
