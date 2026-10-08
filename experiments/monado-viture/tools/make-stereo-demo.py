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

    @classmethod
    def from_quat(cls, quat, pos=(0.0, 0.0, 0.0)):
        """Build a camera from a quaternion (w, x, y, z), skipping Euler angles.

        The demo used to decompose the pose into yaw/pitch/roll and rebuild a rotation from
        them. That is fine until the head pitches near +-90 deg, where yaw and roll act on
        the same axis: the decomposition is degenerate, the reported yaw flips 180 deg, and
        the view can no longer turn -- reported from inside the headset as the head "getting
        stuck" when looking up, unable to pitch or roll further. A quaternion has no such
        singularity, so the rotation is taken from it directly.
        """
        w, x, y, z = quat
        n = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
        w, x, y, z = w / n, x / n, y / n, z / n
        c = cls(pos=pos)
        c.rot = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ])
        return c

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

    def project_cam(self, c) -> tuple[float, float]:
        """Project an already-computed camera-space point."""
        f = focal_px()
        return (EYE_W / 2 + f * c[0] / c[2], EYE_H / 2 - f * c[1] / c[2])

    def project(self, p, eye: int) -> tuple[float, float]:
        c = self.to_camera(p, eye)
        z = c[2]
        if z <= 1e-3:
            z = 1e-3
        f = focal_px()
        return (EYE_W / 2 + f * c[0] / z, EYE_H / 2 - f * c[1] / z)


def quat_mul(a, b):
    """Hamilton product, a then b applied (a * b)."""
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw)


def quat_conj(q):
    return (q[0], -q[1], -q[2], -q[3])


def quat_from_euler(yaw, pitch, roll):
    """Quaternion for Camera's Ry(yaw).Rx(pitch).Rz(roll) convention."""
    cy, sy = math.cos(math.radians(yaw) / 2), math.sin(math.radians(yaw) / 2)
    cp, sp = math.cos(math.radians(pitch) / 2), math.sin(math.radians(pitch) / 2)
    cr, sr = math.cos(math.radians(roll) / 2), math.sin(math.radians(roll) / 2)
    qy = (cy, 0.0, sy, 0.0)
    qx = (cp, sp, 0.0, 0.0)
    qz = (cr, 0.0, 0.0, sr)
    return quat_mul(quat_mul(qy, qx), qz)


NEAR = 0.12  # metres; see project_poly


def project_polys(cam: Camera, polys, eye: int):
    """Project a batch of polygons, clipping each to the near plane.

    `polys` is a sequence of equal-length vertex lists. Returns a list of 2D polygons (or
    None where a polygon is entirely behind the camera).

    Batched on purpose. The per-vertex numpy calls were the *entire* render cost -- floor
    5.1 ms and wall 2.5 ms per eye, which is 15 ms per frame for both eyes and leaves no
    room for 90 Hz. One (M,N,3) transform plus a vectorised single-plane clip brings that
    to well under 1 ms.

    Clipping rather than dropping is what makes the geometry genuinely 3D: a floor disc
    always has part of its circle behind the viewer, so dropping any polygon with a vertex
    behind the camera deleted the whole floor. Without any guard it is worse still --
    Camera.project() clamps z, so a vertex behind the camera lands millions of pixels away
    and Pillow paints that face across the frame, which was the flat grey wash.
    """
    P = np.asarray(polys, dtype=float)                       # (M,N,3)
    if P.size == 0:
        return []
    C = (P - cam.pos) @ cam.rot - cam.eye_offset * eye       # world -> camera space
    m, n = C.shape[0], C.shape[1]
    inside = C[:, :, 2] > NEAR
    nxt = np.roll(np.arange(n), -1)
    a, b = C, C[:, nxt]
    denom = b[:, :, 2] - a[:, :, 2]
    t_ = np.where(np.abs(denom) > 1e-12, (NEAR - a[:, :, 2]) / np.where(denom == 0.0, 1.0, denom), 0.0)
    X = a + (b - a) * t_[:, :, None]
    cross = inside != inside[:, nxt]

    f = focal_px()
    out = []
    for i in range(m):
        if not inside[i].any():
            out.append(None)
            continue
        if inside[i].all():
            poly = C[i]
        else:
            pts = [v for j in range(n) for v in
                   ((C[i, j],) if inside[i, j] else ()) + ((X[i, j],) if cross[i, j] else ())]
            if len(pts) < 3:
                out.append(None)
                continue
            poly = np.array(pts)
        # Plain Python tuples, not a numpy array. Pillow's polygon() on this version draws
        # a numpy-coordinate polygon as an *outline only* -- no fill, no error -- which is
        # how every filled surface in the scene turned into thin lines and then nothing.
        out.append([(float(EYE_W * 0.5 + f * v[0] / v[2]),
                     float(EYE_H * 0.5 - f * v[1] / v[2])) for v in poly])
    return out


def project_poly(cam: Camera, pts, eye: int):
    """Single-polygon convenience wrapper around project_polys()."""
    return project_polys(cam, [pts], eye)[0]


def project_segment(cam: Camera, a, b, eye: int):
    """Project a segment, clipped to the near plane. None if it is wholly behind."""
    ca, cb = cam.to_camera(a, eye), cam.to_camera(b, eye)
    if ca[2] <= NEAR and cb[2] <= NEAR:
        return None
    if ca[2] <= NEAR:
        ca = ca + (cb - ca) * ((NEAR - ca[2]) / (cb[2] - ca[2]))
    if cb[2] <= NEAR:
        cb = cb + (ca - cb) * ((NEAR - cb[2]) / (ca[2] - cb[2]))
    return [cam.project_cam(ca), cam.project_cam(cb)]


# Objects ring the camera: (bearing deg, radius near/far, height, half, colour, phase).
# Bearing 0 = straight ahead, 90 = right, 180 = behind, 270 = left. Motion is *radial*:
# each object approaches and recedes along its own bearing.
OBJECTS = [
    # (bearing deg, radius near/far, height, half size, colour, phase)
    # Bigger and fewer: presence near you without turning the view into clutter.
    # Colours are saturated, not pastel: a pastel at the dim end of the face shading is
    # grey, and grey objects against a grey wall are objects you cannot see.
    # Heights cluster around eye level. The per-eye window is only 29 deg tall, so an
    # object 0.9 m below the eye at 2.3 m sits 22 deg down and is simply not in frame at a
    # level gaze -- which is the other half of "objects only appear from certain angles".
    (0.0, (1.40, 3.20), -0.30, 0.30, (255, 70, 70), 0.00),
    (26.0, (1.70, 3.80), 0.10, 0.24, (255, 190, 40), 0.14),
    (-28.0, (1.60, 3.60), -0.25, 0.26, (60, 170, 255), 0.29),
    (52.0, (2.20, 4.60), -0.35, 0.28, (255, 130, 40), 0.43),
    (-56.0, (2.10, 4.40), 0.30, 0.22, (60, 240, 180), 0.57),
    (92.0, (1.55, 3.40), -0.20, 0.27, (40, 230, 110), 0.71),
    (-96.0, (1.70, 3.60), -0.30, 0.29, (255, 80, 80), 0.86),
    (130.0, (2.00, 4.20), 0.20, 0.24, (120, 110, 255), 0.21),
    (-134.0, (1.90, 4.00), -0.25, 0.26, (255, 225, 90), 0.36),
    (170.0, (2.30, 4.80), -0.35, 0.28, (200, 110, 255), 0.50),
    (-174.0, (2.20, 4.60), 0.15, 0.23, (110, 245, 110), 0.64),
    (0.0, (4.60, 7.60), 0.95, 0.45, (255, 165, 70), 0.79),
    (-60.0, (4.80, 8.00), 0.85, 0.40, (90, 200, 255), 0.93),
    (120.0, (4.70, 7.90), 1.00, 0.42, (170, 255, 110), 0.07),
]


# The world the renderer draws. "drift" is the original: objects ring the viewer and move
# radially, which shows rotation well. "room" is a landmark world for judging translation.
WORLD = "drift"
SPIN_OBJECTS = True


def set_world(name: str) -> None:
    """Select the world. See ROOM_OBJECTS for why judging 6DoF needed a different one."""
    global WORLD, SPIN_OBJECTS
    WORLD = name
    SPIN_OBJECTS = name != "room"


def _column(bearing: float, radius: float, colour, size: float = 0.34):
    """Three stacked cubes standing on the floor: a landmark you can count."""
    out = []
    for k in range(3):
        out.append((bearing, (radius, radius), FLOOR_Y + size + 2.0 * size * k, size, colour, 0.0))
    return out


# A world built to answer "is translation working?". The drifting-object world cannot:
# its floor grid is rotationally symmetric and landmark-free, so sliding under it looks
# identical, and its objects move on their own -- which is indistinguishable from the
# viewer moving. Here:
#   * four cardinally-placed columns, one colour each, so left/right and forward/back have
#     a reference you can name;
#   * a graduated ruler of colour-coded blocks along +z at 1..5 m, so walking a metre forward
#     changes which block is at your feet -- a distance readout you can check by eye;
#   * a plate on the floor at the origin, so "where I started" is marked.
# Everything is static (radius near == far, no spin): motion in the view then means the
# viewer moved, which is the whole point.
def room_objects():
    objs = []
    for bearing, colour in ((0.0, (255, 70, 70)), (90.0, (40, 230, 110)),
                            (180.0, (60, 170, 255)), (270.0, (255, 190, 40))):
        objs += _column(bearing, 6.0, colour)
    # Distance gates receding along +z at 2,4,6,8 m, offset to either side of the axis so
    # they do not occlude each other or the north column. Each gate's posts get taller with
    # distance, so "how far away is that gate" is readable at a glance -- which makes a metre
    # of forward motion a visible change rather than a guess.
    for d in (2.0, 4.0, 6.0, 8.0):
        colour = (255, 255, 255) if int(d) % 4 else (170, 170, 190)
        off = math.degrees(math.atan2(0.75, d))
        for sign in (-1.0, 1.0):
            for k in range(int(d / 2)):
                objs.append((sign * off, (d, d), FLOOR_Y + 0.18 + 0.36 * k, 0.18, colour, 0.0))
    # origin plate: stand on it and you are at the reference point
    objs.append((0.0, (0.0, 0.0), FLOOR_Y + 0.02, 0.85, (70, 95, 70), 0.0))
    return objs


ROOM_OBJECTS = None


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
    """A wireframe floor: concentric rings and radial spokes, nothing filled.

    An earlier version shaded the floor as filled discs so the ground read as a surface.
    From inside the headset that came back as "I don't like the grey what's under me, like a
    circular thing -- it should just be grid". It is a grid now: rings whose boundaries are
    arcs, and spokes, both drawn as polylines so nothing is filled and the world stays black
    behind them. That is also cheaper, since the fill was the expensive part.
    """
    rings, segments, spokes = 6, 32, 24
    radii = [r_near * (r_far / r_near) ** (i / rings) for i in range(rings + 1)]
    ang = [2 * math.pi * i / segments for i in range(segments)]

    # rings
    for r in radii:
        pts = project_poly(cam, [(r * math.sin(a), FLOOR_Y, r * math.cos(a)) for a in ang], eye)
        if pts:
            d.line([(float(x), float(y)) for x, y in pts] + [(float(pts[0][0]), float(pts[0][1]))],
                   fill=(46, 46, 56), width=1)
    # spokes
    for k in range(spokes):
        a = 2 * math.pi * k / spokes
        seg = project_segment(cam, (r_near * math.sin(a), FLOOR_Y, r_near * math.cos(a)),
                              (r_far * math.sin(a), FLOOR_Y, r_far * math.cos(a)), eye)
        if seg is not None:
            d.line([(float(x), float(y)) for x, y in seg], fill=(34, 34, 42), width=1)


def draw_wall_ring(d: ImageDraw.ImageDraw, cam: Camera, eye: int, radius: float = 10.5,
                   segments: int = 48) -> None:
    """A faint cylinder of vertical panels at the horizon.

    The operator's complaint was that it did not feel like being inside a space; props on a
    floor do not enclose you. A dim ring gives the space a boundary and a horizon, which is
    what makes rotation read as looking around a room rather than watching objects slide by.
    """
    top, bottom = 1.70, FLOOR_Y
    quads, shades = [], []
    for i in range(segments):
        a0 = 2.0 * math.pi * i / segments
        a1 = 2.0 * math.pi * (i + 1) / segments
        p0 = (radius * math.sin(a0), 0.0, radius * math.cos(a0))
        p1 = (radius * math.sin(a1), 0.0, radius * math.cos(a1))
        # Smooth and low contrast. At 14 segments (25.7 deg panels) each panel was a visibly
        # different flat grey -- neighbours differed by up to 11/255 -- and because the
        # brightness pattern is world-locked it slid sideways across the view as the head
        # turned. That is what read as glitching. At 144 segments the largest step between
        # neighbours differ by <=2/255 at 48 segments: a gradient, not a patchwork.
        facing = max(0.0, math.cos((a0 + a1) / 2.0))
        shade = int(18 + 10 * facing)
        quads.append([(p0[0], bottom, p0[2]), (p1[0], bottom, p1[2]),
                      (p1[0], top, p1[2]), (p0[0], top, p0[2])])
        shades.append((shade, shade, min(255, shade + 4)))
    for quad, fill in zip(project_polys(cam, quads, eye), shades):
        if quad is not None:
            d.polygon(quad, fill=fill)


# The six faces of a unit cube, as offsets from its centre, with their outward normals.
# Module level so draw_box does not rebuild them 14 times per eye per frame.
_FACE_OFFSETS = np.array([
    [[(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1)]],
    [[(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]],
    [[(1, -1, -1), (1, -1, 1), (1, 1, 1), (1, 1, -1)]],
    [[(-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)]],
    [[(-1, 1, -1), (1, 1, -1), (1, 1, 1), (-1, 1, 1)]],
    [[(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)]],
], dtype=float).reshape(6, 4, 3)
_FACE_NORMALS = np.array([[0, 0, -1], [0, 0, 1], [1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0]],
                         dtype=float)
_LIGHT = np.array([-0.45, 0.80, -0.40])
_LIGHT = _LIGHT / np.linalg.norm(_LIGHT)


def draw_box(d: ImageDraw.ImageDraw, cam: Camera, centre, half: float, colour, eye: int,
             spin: float = 0.0) -> None:
    """All six faces, culled by the face's own normal, lit per face, turned about its own
    vertical axis.

    The turn is what makes these read as solids. A cube viewed exactly face-on is a square,
    and a square is indistinguishable from a flat card -- which is what "they don't look
    like actual 3D objects" meant. Turning a few degrees a second guarantees two faces of
    differing shade are always visible, and the shading changing as it turns is itself a
    depth cue a static box cannot give.

    Rotating, culling, shading and projecting all happen in single numpy passes: doing this
    per vertex and per face in Python was 3 ms per eye, a third of the whole frame budget.
    """
    cs, sn = math.cos(spin), math.sin(spin)
    rot_m = np.array([[cs, 0.0, sn], [0.0, 1.0, 0.0], [-sn, 0.0, cs]])
    centre_v = np.asarray(centre, dtype=float)

    world = _FACE_OFFSETS * half @ rot_m.T + centre_v          # (6,4,3)
    n_world = _FACE_NORMALS @ rot_m.T                          # (6,3)

    face_centres = centre_v + n_world * half                   # (6,3)
    c_cam = (face_centres - cam.pos) @ cam.rot - cam.eye_offset * eye
    n_cam = n_world @ cam.rot
    shaded_faces = (n_cam * c_cam).sum(axis=1) < 0.0           # facing the camera

    shades = 0.50 + 0.50 * np.maximum(0.0, n_world @ _LIGHT)
    xs, ys, zs = centre_v
    if shaded_faces.any():
        idx = [i for i in range(6) if shaded_faces[i]]
    else:
        # The viewer is inside the box: every outward normal faces away, so nothing is
        # visible from outside. Draw the interior rather than nothing -- with 6DoF the
        # operator can genuinely walk into an object, and vanishing was both wrong and (on
        # an empty vertex array) a crash in the batched projection.
        idx = list(range(6))
    pending = [(float(n_world[i, 2]), shaded(colour, float(shades[i]), zs)) for i in idx]
    faces = [world[i] for i in idx]
    for (depth_key, fill), pts in zip(pending, project_polys(cam, faces, eye)):
        if pts is not None:
            d.polygon(pts, fill=fill)


def draw_reference_frame(d: ImageDraw.ImageDraw, cam: Camera, eye: int) -> None:
    """A thin outline at 2.5 m: zero-disparity anchor, and a scale reference."""
    hw, hh, z = 0.52, 0.26, 2.5
    pts = project_poly(cam, [(dx, dy, z) for dx, dy in ((-hw, hh), (hw, hh), (hw, -hh), (-hw, -hh))], eye)
    if pts is not None:
        xy = [(float(x), float(y)) for x, y in pts]
        d.line(xy + [xy[0]], fill=(110, 110, 110), width=3)


def render_eye(t: float, eye: int, cam: Camera, spin_t: float | None = None) -> Image.Image:
    img = Image.new("RGB", (EYE_W, EYE_H), (0, 0, 0))  # black = transparent on the OLED
    d = ImageDraw.Draw(img)
    draw_ground(d, cam, eye)
    draw_wall_ring(d, cam, eye)
    draw_reference_frame(d, cam, eye)
    drawables = []
    if WORLD == "room":
        global ROOM_OBJECTS
        if ROOM_OBJECTS is None:
            ROOM_OBJECTS = room_objects()
        for bearing, (near, far), height, half, colour, phase in ROOM_OBJECTS:
            centre, r = object_state(t, bearing, near, far, height, phase)
            drawables.append((r, centre, half, colour, phase, 0.0))
    for bearing, (near, far), height, half, colour, phase in ([] if WORLD == "room" else OBJECTS):
        centre, r = object_state(t, bearing, near, far, height, phase)
        drawables.append((r, centre, half, colour, phase))
    for item in sorted(drawables, key=lambda it: -it[0]):  # far first
        _, centre, half, colour, phase = item[:5]
        spin_override = item[5] if len(item) > 5 else None
        # Different rate per object so they never sync up, and a different starting angle so
        # none of them is face-on at t=0.
        # spin_t is *unwrapped* seconds. The animation phase wraps every 5 s, and
        # multiplying a wrapping value by ~20 rad/s made every object snap round by
        # hundreds of degrees at the same instant, every five seconds.
        t_unwrapped = spin_t if spin_t is not None else t
        if spin_override is not None and not SPIN_OBJECTS:
            spin = spin_override
        else:
            spin = math.radians(25.0 + 7.0 * phase + (8.0 + 13.0 * phase) * t_unwrapped)
        draw_box(d, cam, centre, half, colour, eye, spin=spin)
    return img


def render_frame(t: float, cam: Camera, spin_t: float | None = None) -> np.ndarray:
    frame = np.zeros((EYE_H, EYE_W * 2, 3), dtype=np.uint8)
    frame[:, :EYE_W] = np.asarray(render_eye(t, -1, cam, spin_t))
    frame[:, EYE_W:] = np.asarray(render_eye(t, +1, cam, spin_t))
    return frame


def main() -> int:
    global FOV_H_DEG

    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="docs/stereo-demo.mp4")
    ap.add_argument("--world", choices=("drift", "room"), default="drift",
                    help="drift = objects ring you and move radially (shows rotation). "
                         "room = static landmarks, a distance ruler and an origin plate "
                         "(shows translation; the drift world physically cannot).")
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
    set_world(a.world)
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
