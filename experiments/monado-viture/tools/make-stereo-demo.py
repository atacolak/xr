#!/usr/bin/env python3
"""Render a side-by-side stereo scene meant to read as a *space you are standing in*.

Design, and why each piece is there:

  two cameras, 64 mm apart   real stereo: depth is the disparity a pair of eyes produces,
                             not a per-eye offset applied by hand
  real solids                every box draws all six faces, culled by the face's own
                             normal with per-face lambert shading. (Two earlier bugs here:
                             culling tested the centre->corner vector, so it drew the *far*
                             faces and the operator could see the insides; and a
                             centre-based side-face guess made faces pop as a box crossed
                             the eye axis.)
  you are inside it          objects ring the camera - ahead, either side, behind - and the
                             ground is a shaded plane with radial bands, so turning your
                             head sweeps a populated space rather than a row of targets
  depth-only motion          each object oscillates along its own radius: it approaches and
                             recedes without orbiting, which is the clearest depth cue and
                             the thing that translates straight to 6DoF
  black background           see-through OLED: black is transparent, so the real room shows
                             through and stereo depth is judged against it

Geometry is real throughout: perspective projection at the panel's true per-eye FOV, an
IPD-separated camera pair, and the scene laid out in metres around the origin. The camera
takes a position as well as an orientation, so a 6DoF pose drops straight in when the VIV
side is solved -- 3DoF just leaves the position at the origin.

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
FOV_H_DEG = 44.9     # per eye: the Luma Ultra is 52 deg diagonal, ~44.9 horizontal on 8:5
FOG = 0.075          # how fast things dim with distance
EYE_HEIGHT = 0.0     # the camera is the eye line; the floor sits below it
FLOOR_Y = -1.35      # metres below the eye: roughly standing height, so it reads as ground


def focal_px() -> float:
    return (EYE_W / 2) / math.tan(math.radians(FOV_H_DEG) / 2.0)


class Camera:
    """Position plus yaw/pitch/roll in degrees. Defaults look straight down +Z.

    Y-up, and R = Ry(yaw) * Rx(pitch) * Rz(roll) -- the same convention the pose is
    decomposed with (see viture-pose-dump --self-test-axes); mismatching the order skews
    combined motions.
    """

    def __init__(self, pos=(0.0, 0.0, 0.0), yaw=0.0, pitch=0.0, roll=0.0):
        self.pos = np.array(pos, dtype=float)
        cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
        cr, sr = math.cos(math.radians(roll)), math.sin(math.radians(roll))
        ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
        rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]])
        self.rot = ry @ rx @ rz
        self.eye_offset = np.array([IPD / 2.0, 0.0, 0.0])

    def to_camera(self, p, eye: int):
        """World point -> camera-space, for one eye (-1 left, +1 right)."""
        eye_world = self.rot @ (self.eye_offset * eye)  # rot maps camera space -> world
        return self.rot.T @ (np.asarray(p, dtype=float) - self.pos - eye_world)

    def project(self, p, eye: int) -> tuple[float, float]:
        c = self.to_camera(p, eye)
        z = c[2]
        if z <= 1e-3:
            z = 1e-3
        f = focal_px()
        return (EYE_W / 2 + f * c[0] / z, EYE_H / 2 - f * c[1] / z)


# Objects ring the camera: (bearing deg, radius near/far, height, half, colour, phase).
# Bearing 0 = straight ahead, 90 = right, 180 = behind, 270 = left. Motion is *radial*:
# each object approaches and recedes along its own bearing.
OBJECTS = [
    # (bearing deg, radius near/far, height, half size, colour, phase)
    # Bigger and fewer: presence near you without turning the view into clutter.
    (0.0, (1.40, 3.20), -0.70, 0.30, (255, 96, 96), 0.00),
    (26.0, (1.70, 3.80), 0.10, 0.24, (255, 210, 90), 0.14),
    (-28.0, (1.60, 3.60), -0.55, 0.26, (120, 200, 255), 0.29),
    (52.0, (2.20, 4.60), -0.95, 0.28, (255, 170, 90), 0.43),
    (-56.0, (2.10, 4.40), 0.30, 0.22, (150, 255, 220), 0.57),
    (92.0, (1.55, 3.40), -0.35, 0.27, (110, 255, 150), 0.71),
    (-96.0, (1.70, 3.60), -0.85, 0.29, (255, 130, 130), 0.86),
    (130.0, (2.00, 4.20), 0.20, 0.24, (190, 190, 255), 0.21),
    (-134.0, (1.90, 4.00), -0.60, 0.26, (255, 240, 160), 0.36),
    (170.0, (2.30, 4.80), -0.95, 0.28, (215, 150, 255), 0.50),
    (-174.0, (2.20, 4.60), 0.15, 0.23, (160, 255, 200), 0.64),
    (0.0, (4.60, 7.60), 0.95, 0.45, (255, 190, 130), 0.79),
    (-60.0, (4.80, 8.00), 0.85, 0.40, (140, 220, 255), 0.93),
    (120.0, (4.70, 7.90), 1.00, 0.42, (200, 255, 200), 0.07),
]


def object_state(t: float, bearing: float, near: float, far: float, height: float, phase: float):
    """Position of an object at animation phase t. Radial only: it changes distance."""
    r = (near + far) / 2.0 + (far - near) / 2.0 * math.cos(2.0 * math.pi * (t + phase))
    a = math.radians(bearing)
    return (r * math.sin(a), height, r * math.cos(a)), r


def disparity_px(z: float) -> float:
    """Horizontal disparity relative to a 2.5 m reference, in pixels (negative = nearer)."""
    return focal_px() * IPD * (1.0 / 2.5 - 1.0 / max(z, 1e-3))


def shaded(colour, factor: float, z: float) -> tuple[int, int, int]:
    dim = max(0.35, 1.0 - FOG * max(0.0, z - 2.0))
    return tuple(max(0, min(255, int(c * factor * dim))) for c in colour)


def draw_ground(d: ImageDraw.ImageDraw, cam: Camera, eye: int, r_near: float = 0.6, r_far: float = 14.0) -> None:
    """A solid shaded floor with a few radial bands.

    Thin receding grid lines moire badly at grazing angles, which the operator read as the
    floor "warping". Filled quads with distance shading give a stable ground plane, and the
    bands keep enough texture to read depth; a handful of radial lines add the perspective
    without the aliasing storm.
    """
    bands = 9
    for i in range(bands):
        r0 = r_near * (r_far / r_near) ** (i / bands)
        r1 = r_near * (r_far / r_near) ** ((i + 1) / bands)
        shade = int(64 * (r_near / r0))
        quad = [
            cam.project((-r0, FLOOR_Y, r0), eye), cam.project((r0, FLOOR_Y, r0), eye),
            cam.project((r1, FLOOR_Y, r1), eye), cam.project((-r1, FLOOR_Y, r1), eye),
        ]
        quad_back = [
            cam.project((-r0, FLOOR_Y, -r0), eye), cam.project((r0, FLOOR_Y, -r0), eye),
            cam.project((r0, FLOOR_Y, -r1), eye), cam.project((-r0, FLOOR_Y, -r1), eye),
        ]
        d.polygon(quad, fill=(shade, shade, shade + 6))
        d.polygon(quad_back, fill=(max(0, shade - 10), max(0, shade - 10), shade))
    for j in range(-4, 5):
        x = j * 1.6
        d.line([cam.project((x, FLOOR_Y, r_near), eye), cam.project((x, FLOOR_Y, r_far), eye)],
               fill=(28, 28, 34), width=2)
    for j in range(-4, 5):
        z = j * 1.8
        d.line([cam.project((-r_far, FLOOR_Y, z), eye), cam.project((r_far, FLOOR_Y, z), eye)],
               fill=(28, 28, 34), width=2)


def draw_wall_ring(d: ImageDraw.ImageDraw, cam: Camera, eye: int, radius: float = 10.5,
                   segments: int = 14) -> None:
    """A faint cylinder of vertical panels at the horizon.

    The operator's complaint was that it did not feel like being inside a space; props on a
    floor do not enclose you. A dim ring gives the space a boundary and a horizon, which is
    what makes rotation read as looking around a room rather than watching objects slide by.
    """
    top, bottom = 1.70, FLOOR_Y
    for i in range(segments):
        a0 = 2.0 * math.pi * i / segments
        a1 = 2.0 * math.pi * (i + 1) / segments
        p0 = (radius * math.sin(a0), 0.0, radius * math.cos(a0))
        p1 = (radius * math.sin(a1), 0.0, radius * math.cos(a1))
        # brighter where the wall faces the view, dimmer at the sides: no lighting model needed
        facing = max(0.0, math.cos((a0 + a1) / 2.0))
        shade = int(10 + 26 * facing)
        quad = [cam.project((p0[0], bottom, p0[2]), eye), cam.project((p1[0], bottom, p1[2]), eye),
                cam.project((p1[0], top, p1[2]), eye), cam.project((p0[0], top, p0[2]), eye)]
        d.polygon(quad, fill=(shade, shade, min(255, shade + 4)))


def draw_box(d: ImageDraw.ImageDraw, cam: Camera, centre, half: float, colour, eye: int) -> None:
    """All six faces, culled by the face's own normal, lit per face."""
    x, y, z = centre
    lo, hi = -half, half
    faces = (
        ((0.0, 0.0, -1.0), ((lo, lo, -half), (hi, lo, -half), (hi, hi, -half), (lo, hi, -half))),
        ((0.0, 0.0, 1.0), ((lo, lo, half), (hi, lo, half), (hi, hi, half), (lo, hi, half))),
        ((1.0, 0.0, 0.0), ((half, lo, -half), (half, lo, half), (half, hi, half), (half, hi, -half))),
        ((-1.0, 0.0, 0.0), ((-half, lo, -half), (-half, lo, half), (-half, hi, half), (-half, hi, -half))),
        ((0.0, 1.0, 0.0), ((lo, half, -half), (hi, half, -half), (hi, half, half), (lo, half, half))),
        ((0.0, -1.0, 0.0), ((lo, -half, -half), (hi, -half, -half), (hi, -half, half), (lo, -half, half))),
    )
    light = np.array([-0.45, 0.80, -0.40])
    light = light / np.linalg.norm(light)
    visible = []
    for normal, verts in faces:
        n_world = np.array(normal, dtype=float)
        n_cam = cam.rot.T @ n_world
        # The face is visible when its outward normal points back at the camera. The camera
        # sits at the origin of camera space, so that is dot(n_cam, face_centre_cam) < 0.
        face_centre = np.array(centre, dtype=float) + n_world * half
        if float(np.dot(n_cam, cam.to_camera(face_centre, eye))) >= 0.0:
            continue
        shade = 0.30 + 0.70 * max(0.0, float(np.dot(n_world, light)))
        visible.append((n_world[2], [cam.project((x + vx, y + vy, z + vz), eye) for vx, vy, vz in verts],
                        shaded(colour, shade, z)))
    for _, pts, c in sorted(visible, key=lambda it: it[0]):  # draw far faces first
        d.polygon(pts, fill=c)


def draw_reference_frame(d: ImageDraw.ImageDraw, cam: Camera, eye: int) -> None:
    """A thin outline at 2.5 m: zero-disparity anchor, and a scale reference."""
    hw, hh, z = 0.52, 0.26, 2.5
    pts = [cam.project((dx, dy, z), eye) for dx, dy in ((-hw, hh), (hw, hh), (hw, -hh), (-hw, -hh))]
    d.line(pts + [pts[0]], fill=(110, 110, 110), width=3)


def render_eye(t: float, eye: int, cam: Camera) -> Image.Image:
    img = Image.new("RGB", (EYE_W, EYE_H), (0, 0, 0))  # black = transparent on the OLED
    d = ImageDraw.Draw(img)
    draw_ground(d, cam, eye)
    draw_wall_ring(d, cam, eye)
    draw_reference_frame(d, cam, eye)
    drawables = []
    for bearing, (near, far), height, half, colour, phase in OBJECTS:
        centre, r = object_state(t, bearing, near, far, height, phase)
        drawables.append((r, centre, half, colour))
    for _, centre, half, colour in sorted(drawables, key=lambda it: -it[0]):  # far first
        draw_box(d, cam, centre, half, colour, eye)
    return img


def render_frame(t: float, cam: Camera) -> np.ndarray:
    frame = np.zeros((EYE_H, EYE_W * 2, 3), dtype=np.uint8)
    frame[:, :EYE_W] = np.asarray(render_eye(t, -1, cam))
    frame[:, EYE_W:] = np.asarray(render_eye(t, +1, cam))
    return frame


def main() -> int:
    global FOV_H_DEG

    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="docs/stereo-demo.mp4")
    ap.add_argument("--frames", type=int, default=180)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--still", action="store_true")
    ap.add_argument("--t", type=float, default=0.0)
    ap.add_argument("--yaw", type=float, default=0.0)
    ap.add_argument("--pitch", type=float, default=0.0)
    ap.add_argument("--roll", type=float, default=0.0)
    ap.add_argument("--cam", default="0,0,0", help="camera position x,y,z in metres")
    ap.add_argument("--fov", type=float, default=FOV_H_DEG)
    a = ap.parse_args()

    FOV_H_DEG = a.fov
    cam = Camera(pos=tuple(float(v) for v in a.cam.split(",")), yaw=a.yaw, pitch=a.pitch, roll=a.roll)

    if a.still:
        out = pathlib.Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(render_frame(a.t, cam)).save(out)
        print(f"wrote {out} ({out.stat().st_size} bytes) yaw={a.yaw} pitch={a.pitch} roll={a.roll} "
              f"pos={a.cam} fov={a.fov}")
        return 0

    radii = [object_state(i / a.frames, b, n, f, h, p)[1] for i in range(a.frames)
             for b, (n, f), h, _, _, p in OBJECTS]
    disp = [disparity_px(r) for r in radii]
    print(f"SBS {EYE_W*2}x{EYE_H} @ {a.fps} fps, {a.frames} frames ({a.frames/a.fps:.1f} s loop), "
          f"fov {FOV_H_DEG} deg, IPD {IPD*1000:.0f} mm, {len(OBJECTS)} objects")
    print(f"  radial range {min(radii):.2f}..{max(radii):.2f} m; disparity vs 2.5 m "
          f"{min(disp):+.0f}..{max(disp):+.0f} px ({min(disp)/focal_px()*180/math.pi:+.2f}.."
          f"{max(disp)/focal_px()*180/math.pi:+.2f} deg)")

    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{EYE_W*2}x{EYE_H}", "-r", str(a.fps), "-i", "-", "-c:v", "libx264",
         "-preset", "medium", "-crf", str(a.crf), "-pix_fmt", "yuv420p", str(out)],
        stdin=subprocess.PIPE)
    assert proc.stdin is not None
    for i in range(a.frames):
        proc.stdin.write(render_frame(i / a.frames, cam).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        print("ffmpeg failed", file=sys.stderr)
        return 1
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
