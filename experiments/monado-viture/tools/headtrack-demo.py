#!/usr/bin/env python3
"""Live 3DoF demo: the stereo scene rendered from the glasses' own orientation.

This is the perceptual check for M3. Numbers can tell you that yaw, pitch and roll each
respond to *something*; only your eyes can tell you whether turning your head turns the
scene the way a fixed world should (and whether any axis is inverted or swapped).

Pipeline (each stage exists because the obvious alternative failed measurably):

  viture-pose-dump --3dof --json   pose lines at ~120 Hz (IMU; 3DoF has no position)
  this script                      renders the SBS scene with camera yaw/pitch/roll from
                                   the pose, paced to --fps
  ffmpeg                           scales the small render up to the panel resolution and
                                   converts to the byte order X wants natively (bgra)
  tools/xpresent                   blits each frame into a fullscreen override-redirect
                                   X window via MIT-SHM, no demuxer, no cache, no vsync
                                   queue (measured 70-91 fps at 3840x1200)

Why not a video player: ffplay consumed a live 60 fps stream and put 1-2 frames/second on
the glass; mpv reached ~3.6 with its demuxer cache disabled. Players are built for files,
and latency you can see is nausea.

Usage:
    tools/headtrack-demo.py                       # 60 fps, 960x600 per eye render
    tools/headtrack-demo.py --seconds 30 --fps 45
    tools/headtrack-demo.py --invert-pitch        # if an axis feels wrong
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SDK = pathlib.Path(os.environ.get("VITURE_SDK_DIR", pathlib.Path.home() / "workspace/uxspace/Android/SDK/linux-x86_64"))


def load_renderer():
    """Import make-stereo-demo.py (hyphen in the name, so by path)."""
    spec = importlib.util.spec_from_file_location("stereo_demo", ROOT / "tools" / "make-stereo-demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _is_placeholder(quat, pos, tol=1e-9) -> bool:
    """The SDK's placeholder: exactly identity rotation and exactly zero position.

    Exactness matters. A real pose landing on exactly (1,0,0,0)/(0,0,0) in every component is
    a measure-zero event, whereas the placeholders are exactly that -- measured: 120
    consecutive in the first second of every session, and a burst of 83 whenever the glasses
    are replugged. At startup they are indistinguishable from a real origin, which is why the
    warm-up window exists; mid-session they can only be placeholders.
    """
    return (abs(quat[0] - 1.0) < tol and all(abs(v) < tol for v in quat[1:])
            and all(abs(v) < tol for v in pos))


def sample_ok(status, pose, pos, last_pose, last_pos, ok=1, consecutive_bad=0,
              quat=None, last_quat=None) -> bool:
    """Is this pose sample believable enough to show?

    Two rules, and neither uses `status`. That flag cannot be used to filter samples: in 3DoF
    the SDK emits placeholders tagged status=1, but in 6DoF *every* sample -- good ones
    included -- is status=1 (measured 958/958). An earlier version keyed on it and threw away
    the whole 6DoF stream.

    1. An exact-identity placeholder, mid-session, is not a pose. Beware that "mid-session" is
       load-bearing: after --reset the first real samples are also exactly identity, which is
       what the warm-up window covers.
    2. A sample farther than 180 deg / 2 m from the last accepted one is not believed on its
       own -- but it *is* adopted after 5 consecutive samples, because a stalled stream or a
       fast turn simply moves the head before the next sample arrives. The limit used to be
       60 deg with a 20-sample, status-gated adoption path, and since 6DoF never reports
       status=0 that path could never fire: the reference froze, and turning past ~60 deg from
       it was rejected forever. That was the reported "it doesn't turn beyond a certain
       degree ... like behind me".
    """
    if not ok:
        return False
    if last_pose is None:
        return True
    if quat is not None and last_quat is not None:
        if _is_placeholder(quat, pos) and not _is_placeholder(last_quat, last_pos):
            return False
    off = (max(abs(a - b) for a, b in zip(pose, last_pose)) > 180.0
           or max(abs(a - b) for a, b in zip(pos, last_pos)) > 2.0)
    if not off:
        return True
    return consecutive_bad >= 5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=int, default=90,
                    help="target frames/s. The Luma Ultra refreshes at 90 Hz, and the default "
                         "640x400 per eye measured 119 fps of render headroom at 3x upscale, "
                         "so 90 is attainable when the panel is actually driving the swap.")
    ap.add_argument("--res", default="640x400", help="per-eye render size (scaled up for the panels)")
    ap.add_argument("--screen", default="3840x1200", help="panel size the presenter blits to")
    ap.add_argument("--seconds", type=float, default=600.0)
    ap.add_argument("--world", choices=("drift", "room"), default="room",
                    help="room = static landmarks + a distance ruler + an origin plate, for "
                         "judging translation; drift = the radial object ring (rotation). "
                         "The room world is the default because the drift world cannot show "
                         "translation: its floor grid is symmetric and its objects move on "
                         "their own, which is indistinguishable from the viewer moving.")
    ap.add_argument("--pos-gain", type=float, default=1.0,
                    help="scale the 6DoF translation. Useful because the VIO's metric scale is "
                         "estimated, so 'I moved 30 cm' can render as a metre. Compare against "
                         "the floor graduations in --world room; a gain far from 1.0 is a scale "
                         "error worth recording, not a preference.")
    ap.add_argument("--6dof", dest="sixdof", action="store_true",
                    help="use the device's 6DoF pose (Quaternion + translation) instead of "
                         "3DoF orientation only. 6DoF is the SDK default; --3dof overrode it.")
    ap.add_argument("--no-presenter", action="store_true", help="render and measure only")
    ap.add_argument("--presenter", choices=("auto", "gl", "shm"), default="auto",
                    help="gl = GPU presenter (tools/xpresent-gl: small frames over the pipe, GPU "
                         "scales, the only way to 90 fps here). shm = CPU presenter "
                         "(tools/xpresent: full-size frames, ~60 fps ceiling). auto picks gl when built.")
    ap.add_argument("--smooth", type=float, default=0.015,
                    help="exponential smoothing time constant in seconds (0 disables). Light by "
                         "design: smoothing is lag, and lag is what makes an HMD view feel wrong.")
    ap.add_argument("--deadband", type=float, default=0.03,
                    help="ignore pose changes smaller than this many degrees (kills micro-jitter "
                         "with no lag at all, unlike smoothing)")
    ap.add_argument("--no-flip-xy", action="store_true",
                    help="do not apply the pose-frame handedness fix (the SDK GL pose has z "
                         "backward while this renderer looks down +z; without the fix, yaw and "
                         "pitch drive the scene backwards)")
    ap.add_argument("--invert-yaw", action="store_true")
    ap.add_argument("--invert-pitch", action="store_true")
    ap.add_argument("--invert-roll", action="store_true")
    ap.add_argument("--fov", type=float, default=44.9,
                    help="per-eye horizontal FOV in degrees; the Luma Ultra is 52 deg "
                         "diagonal, which is ~44.9 deg horizontal on an 8:5 panel. This "
                         "must match the optics or head motion feels too fast/slow, "
                         "because the panel stretches the render across the real FOV.")
    ap.add_argument("--src", choices=("poll", "cb", "synth"), default="poll",
                    help="pose source. 'poll' = get_gl_pose_carina: correct OpenGL frame and "
                         "gravity-anchored pitch/roll (the SDK documents this), ~30 pose updates/s. "
                         "'cb' = the device callback: much higher rate, but its quaternion is in the "
                         "IMU's North-West-Up frame and does NOT agree with the gravity-anchored "
                         "attitude, so the axes come out wrong.")
    ap.add_argument("--predict", type=float, default=0.0,
                    help="seconds of pose prediction, to compensate pipeline latency "
                         "(the SDK predicts internally). 0 disables.")
    ap.add_argument("--no-recenter", action="store_true",
                    help="use absolute pose instead of pose relative to the first samples")
    a = ap.parse_args()

    eye_w, eye_h = (int(v) for v in a.res.lower().split("x"))
    screen_w, screen_h = (int(v) for v in a.screen.lower().split("x"))
    frame_w, frame_h = eye_w * 2, eye_h

    demo = load_renderer()
    demo.EYE_W, demo.EYE_H = eye_w, eye_h   # keep the 8:5 aspect so the FOV math holds
    demo.FOV_H_DEG = a.fov

    tool = ROOT / "tools" / "viture-pose-dump"
    xpresent = ROOT / "tools" / "xpresent"
    if not tool.exists():
        print(f"no {tool} (build: tools/build-pose-tool.sh / build-pose-dump.sh)", file=sys.stderr)
        return 1

    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = f"{SDK}/x86_64{os.pathsep}{env.get('LD_LIBRARY_PATH', '')}"
    env["DISPLAY"] = env.get("DISPLAY", ":1")

    pose_args = [str(tool), "--seconds", str(a.seconds), "--json", "--auto-exposure"]
    if not a.sixdof:
        pose_args.append("--3dof")
    else:
        # Put the VIO origin at the head. Without it the origin sits wherever the VIO
        # happened to initialise, and the callback source then reports an absolute height
        # (measured y ~ 0.87 m), which floats the whole scene under the viewer.
        pose_args.append("--reset")
    if not a.no_flip_xy:
        pose_args.append("--flip-xy")
    if a.src == "cb":
        pose_args.append("--src-cb")
    else:
        pose_args += ["--predict", str(a.predict)]
    pose = [None]   # holder: the watchdog below replaces the process, see start_pose()

    def start_pose() -> None:
        """(Re)start the pose source.

        The device's VIO appears to need real motion to initialise: a session started while
        the glasses sit still reports a constant identity pose forever, at full sample rate,
        with nothing to suggest a problem. Restarting the source is what re-initialises it, so
        the frozen-pose watchdog calls this until motion appears -- which means the operator no
        longer has to start the demo at exactly the right moment wearing the glasses.
        """
        if pose[0] is not None:
            try:
                pose[0].kill()
            except Exception:
                pass
        pose[0] = subprocess.Popen(pose_args, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=env, text=True)
        threading.Thread(target=reader_for, args=(pose[0],), daemon=True).start()

    encoder = player = None
    if not a.no_presenter:
        xpresent_gl = ROOT / "tools" / "xpresent-gl"
        use_gl = a.presenter == "gl" or (a.presenter == "auto" and xpresent_gl.exists())
        vf = [] if use_gl else ["-vf", f"scale={screen_w}:{screen_h}:flags=fast_bilinear"]
        encoder = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{frame_w}x{frame_h}", "-r", str(a.fps), "-i", "-", *vf,
             "-pix_fmt", "bgra", "-f", "rawvideo", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
        assert encoder.stdin is not None and encoder.stdout is not None
        if use_gl:
            player = subprocess.Popen([str(xpresent_gl), str(frame_w), str(frame_h),
                                       str(screen_w), str(screen_h)],
                                      stdin=encoder.stdout, env=env)
        elif xpresent.exists():
            player = subprocess.Popen([str(xpresent), str(screen_w), str(screen_h)],
                                      stdin=encoder.stdout, env=env)
        else:  # fallback player; slower, and it will say so
            player = subprocess.Popen(
                ["mpv", "--no-audio", "--fullscreen", "--no-osc", "--really-quiet",
                 "--cache=no", "--demuxer-readahead-secs=0", "--untimed", "-"],
                stdin=encoder.stdout, env=env)

    print(f"pose: {tool.name} --3dof   render {frame_w}x{frame_h} SBS -> {screen_w}x{screen_h}   "
          f"presenter: {'xpresent' if xpresent.exists() and not a.no_presenter else 'none/fallback'}", flush=True)
    print("turn / nod / tilt your head -- the scene should stay put in the world", flush=True)

    # Recentring. An HMD view is always driven by orientation *relative* to a reference:
    # the device reports an absolute gravity-referenced pose, and whatever the glasses
    # happen to be tilted at when the demo starts (on a desk: tens of degrees of pitch)
    # would otherwise aim the camera there and push the scene out of frame. The vendor
    # demo keeps a stored reference for the same reason; the SDK exposes reset_pose_carina.
    # Re-centring can be requested at runtime (the IMU's yaw drifts; that is inherent to
    # 3DoF and the SDK's own answer is to re-anchor: reset_pose_carina). SIGUSR1 does it:
    #   kill -USR1 $(pgrep -f headtrack-demo)
    recenter_request = [True]

    def on_usr1(_sig, _frm):
        recenter_request[0] = True

    signal.signal(signal.SIGUSR1, on_usr1)

    ref = None
    ref_acc: list[tuple[float, float, float]] = []
    warmup = [0]

    def ang_diff(a1: float, a2: float) -> float:
        d = a1 - a2
        while d > 180.0:
            d -= 360.0
        while d < -180.0:
            d += 360.0
        return d

    # Latest-value pose reader. The pose stream is faster than the render loop, so a plain
    # "for line in stdout" consumes every sample in order: the pipe accumulates a backlog
    # and the view falls steadily behind the head. That reads as drift, choppiness and
    # nausea, and no amount of FOV or axis fixing helps. Keep only the newest sample.
    latest = {"pose": (0.0, 0.0, 0.0), "pos": (0.0, 0.0, 0.0), "quat": None, "t": 0.0,
              "status": 1, "n": -1, "dropped": 0}
    lock = threading.Lock()
    stream_t0 = [None]

    def reader_for(proc):
        last = [None]      # last pose we believed: (yaw, pitch, roll)
        last_pos = [None]  # and its position, so a 6DoF teleport is caught too
        last_quat = [None]  # its quaternion: identity is how a placeholder is recognised
        streak = [0]       # consecutive rejects, used to tell a jump from a real move
        # see sample_ok() for why samples get dropped
        for line in (proc.stdout or []):
            if not line.startswith("{"):
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if stream_t0[0] is None:
                stream_t0[0] = time.monotonic() - d.get("t", 0.0)
            status = d.get("status", 1)
            p = (d.get("yaw", 0.0), d.get("pitch", 0.0), d.get("roll", 0.0))
            pos_now = (d.get("px", 0.0), d.get("py", 0.0), d.get("pz", 0.0))
            quat_now = (d["qw"], d["qx"], d["qy"], d["qz"]) if "qw" in d else None
            ok = d.get("ok", 1)
            # Two kinds of sample are thrown away and the last good pose is held instead:
            #   * the vendor marks it invalid (status != 0). The SDK emits zeroed poses while
            #     it settles, and this loop used to apply every line verbatim -- so a single
            #     bad sample snapped the view to the scene origin for one frame and then
            #     back. That is the split-second jump that was reported ("turns my head to
            #     the origin and jerks it back").
            #   * it would teleport the head. No real head turns 60 deg or moves a metre
            #     between samples, so a jump that size is corrupt data, not motion. This also
            #     keeps 6DoF honest once translation is live.
            if not sample_ok(status, p, pos_now, last[0], last_pos[0], ok, streak[0],
                             quat_now, last_quat[0]):
                streak[0] += 1
                with lock:
                    latest["dropped"] += 1
                    latest["status"] = status
                continue
            streak[0] = 0
            last[0], last_pos[0] = p, pos_now
            last_quat[0] = quat_now
            with lock:
                latest["pose"] = p
                latest["pos"] = pos_now
                latest["quat"] = quat_now
                latest["t"] = d.get("t", 0.0)
                latest["status"] = status
                latest["n"] += 1

    def synthetic():
        """A known pose signal: sweeps yaw, pitch and roll at different rates, plus a small
        translation, so the whole render/present chain can be exercised and measured with
        no device attached (the glasses get unplugged between sessions)."""
        t0 = time.monotonic()
        while True:
            el = time.monotonic() - t0
            with lock:
                latest["pose"] = (35.0 * math.sin(2 * math.pi * 0.12 * el),
                                  12.0 * math.sin(2 * math.pi * 0.07 * el + 1.0),
                                  10.0 * math.sin(2 * math.pi * 0.05 * el + 2.0))
                latest["pos"] = (0.06 * math.sin(2 * math.pi * 0.09 * el),
                                 0.0,
                                 0.10 * math.sin(2 * math.pi * 0.11 * el + 0.7))
                latest["quat"] = demo.quat_from_euler(*latest["pose"])
                latest["t"] = el
                latest["status"] = 0
                latest["n"] += 1
            time.sleep(1.0 / 120.0)

    if a.src == "synth":
        stream_t0[0] = time.monotonic()
        threading.Thread(target=synthetic, daemon=True).start()
    else:
        start_pose()

    render_errors = [0]
    respawns = [0]
    frozen_key = [None]
    frozen_since = [None]
    frozen_warned = [0.0]
    smoothed = [0.0, 0.0, 0.0, None]
    smoothed_q = [None, None, None, None]
    ref_q = [None]
    ref_pos = [None]
    prev_t = [time.monotonic()]
    interval = 1.0 / float(a.fps)
    next_deadline = time.monotonic()
    n = 0
    t_report = time.monotonic()
    last = (0.0, 0.0, 0.0)
    demo.set_world(a.world)
    try:
        while True:
            with lock:
                yaw0, pitch0, roll0 = latest["pose"]
                px0, py0, pz0 = latest["pos"]
                quat0 = latest["quat"]
                pose_t, pose_status = latest["t"], latest["status"]
            d = {"status": pose_status}
            yaw = yaw0 * (-1.0 if a.invert_yaw else 1.0)
            pitch = pitch0 * (-1.0 if a.invert_pitch else 1.0)
            roll = roll0 * (-1.0 if a.invert_roll else 1.0)
            if not a.no_recenter:
                if recenter_request[0]:
                    recenter_request[0] = False
                    # Re-reference to where the head is *now*. Dropping back into the warm-up
                    # branch would force the pose to identity for the ~20 samples it takes to
                    # collect a reference, i.e. show the unrotated scene for about half a
                    # second -- a visible lurch for a function whose whole point is to be
                    # invisible. latest[] only ever holds samples that passed sample_ok(), so
                    # these values are a real pose even if a placeholder arrived just now.
                    ref = (yaw, pitch, roll)
                    ref_q[0] = quat0
                    ref_pos[0] = (px0, py0, pz0)
                    ref_acc.clear()
                    print(f"re-referenced on yaw {ref[0]:+.1f} pitch {ref[1]:+.1f} roll {ref[2]:+.1f}",
                          flush=True)
                if ref is None:
                    # Reference the *settled* pose. The device emits placeholders (zeros)
                    # briefly after start regardless of source, so drop a warm-up window
                    # first; otherwise the reference is zero and every later pose reads as a
                    # large offset that pushes the scene out of frame.
                    warmup[0] += 1
                    if warmup[0] > 30 and d.get("status", 1) == 0:
                        ref_acc.append((yaw, pitch, roll))
                    if len(ref_acc) >= 20:
                        ref = tuple(sum(v[i] for v in ref_acc) / len(ref_acc) for i in range(3))
                        ref_q[0] = quat0
                        ref_pos[0] = (px0, py0, pz0)
                        print(f"recentred on yaw {ref[0]:+.1f} pitch {ref[1]:+.1f} roll {ref[2]:+.1f} "
                              f"({len(ref_acc)} stable samples)", flush=True)
                    yaw, pitch, roll = 0.0, 0.0, 0.0
                else:
                    yaw = ang_diff(yaw, ref[0])
                    pitch = ang_diff(pitch, ref[1])
                    roll = ang_diff(roll, ref[2])
            # Prefer the quaternion when the source provides one. Euler angles are rebuilt
            # from yaw/pitch/roll here, and that construction is singular when the head
            # pitches near +-90 deg: yaw and roll then act on the same axis, the reported
            # yaw flips 180 deg and the view stops turning -- reported as the head getting
            # stuck looking up, unable to pitch or roll further. The rotation is also taken
            # relative to the reference *in the world frame*, which is what makes a turn of
            # the head map to the same turn of the view instead of a per-axis approximation
            # of it.
            q_rel = None
            if quat0 is not None and ref_q[0] is not None:
                q_rel = demo.quat_mul(demo.quat_conj(ref_q[0]), quat0)
            last = (yaw, pitch, roll)

            # Smoothing is lag and a deadband is not, so apply the deadband first: it alone
            # removes the sensor's micro-jitter. 3DoF reports no translation, so the position
            # stays at the origin -- but it is plumbed through, so a 6DoF pose drops straight in.
            now_s = time.monotonic()
            dt = max(1e-3, min(0.25, now_s - prev_t[0]))
            prev_t[0] = now_s
            alpha = 1.0 if a.smooth <= 0.0 else (1.0 - math.exp(-dt / a.smooth))
            if ref_pos[0] is not None and a.sixdof:
                px0 = (px0 - ref_pos[0][0]) * a.pos_gain
                py0 = (py0 - ref_pos[0][1]) * a.pos_gain
                pz0 = (pz0 - ref_pos[0][2]) * a.pos_gain
            cam = None
            if q_rel is not None:
                if q_rel[0] < 0.0:                      # q and -q are the same rotation
                    q_rel = tuple(-v for v in q_rel)
                if smoothed_q[0] is None:
                    smoothed_q[:] = list(q_rel)
                else:
                    sm = smoothed_q
                    dot = abs(sum(a1 * b1 for a1, b1 in zip(sm, q_rel)))
                    # deadband as an angle: |dot| = cos(theta/2), so hold if theta is under it
                    if dot < math.cos(math.radians(a.deadband) / 2.0):
                        blended = [s + alpha * (g - s) for s, g in zip(sm, q_rel)]
                        norm = math.sqrt(sum(v * v for v in blended)) or 1.0
                        sm[:] = [v / norm for v in blended]
                    q_rel = tuple(sm)
                cam = demo.Camera.from_quat(q_rel, pos=(px0, py0, pz0))
            else:
                sm = smoothed
                if sm[3] is None:
                    sm[0], sm[1], sm[2] = yaw, pitch, roll
                    sm[3] = 1.0
                else:
                    for i, target in enumerate((yaw, pitch, roll)):
                        d_ang = target - sm[i]
                        if abs(d_ang) < a.deadband:
                            d_ang = 0.0
                        sm[i] += alpha * d_ang
                    yaw, pitch, roll = sm[0], sm[1], sm[2]
                cam = demo.Camera(pos=(px0, py0, pz0), yaw=yaw, pitch=pitch, roll=roll)
            # slow self-drift, so a stuttering display is distinguishable from a still scene
            now_mono = time.monotonic()
            # A device whose VIO never initialised reports a constant identity pose while
            # happily delivering samples at full rate, with nothing dropped: the view is
            # simply frozen and every counter reads healthy. That is indistinguishable from
            # "the app is broken" unless it says so, so it says so.
            pose_key = (round(px0, 4), round(py0, 4), round(pz0, 4),
                        round(last[0], 2), round(last[1], 2), round(last[2], 2))
            if frozen_key[0] != pose_key:
                frozen_key[0] = pose_key
                frozen_since[0] = now_mono
            elif frozen_since[0] is not None and now_mono - frozen_since[0] > 6.0:
                frozen_since[0] = now_mono
                if respawns[0] < 60:
                    respawns[0] += 1
                    print(f"  pose unchanged while samples keep arriving: the VIO is not tracking "
                          f"(it needs motion to initialise, so a session begun with the glasses "
                          f"still never starts). Re-initialising the pose source "
                          f"(attempt {respawns[0]}).", flush=True)
                    with lock:
                        latest["quat"] = None
                    # the new stream has its own time base; without this the reported pose age
                    # counts from the old one and reads as tens of seconds after a respawn
                    stream_t0[0] = None
                    ref = None
                    ref_q[0] = None
                    ref_pos[0] = None
                    ref_acc.clear()
                    warmup[0] = 0
                    smoothed[3] = None
                    smoothed_q[:] = [None, None, None, None]
                    start_pose()
            phase = (now_mono * 0.2) % 1.0
            try:
                frame = demo.render_frame(phase, cam, now_mono).tobytes()
            except Exception as exc:
                # One bad frame must not kill a demo that is on someone's face. Report it,
                # keep the previous frame, and carry on: a stuck image is far easier to
                # diagnose later than a dead process is to notice now.
                render_errors[0] += 1
                if render_errors[0] <= 3 or render_errors[0] % 100 == 0:
                    print(f"  render error #{render_errors[0]}: {type(exc).__name__}: {exc}", flush=True)
                time.sleep(0.01)
                continue
            if encoder is not None:
                encoder.stdin.write(frame)
            n += 1

            # Pace: the pose stream runs at 120 Hz and the pipeline can outrun the panel, so
            # without this frames queue and every extra queued frame is latency you can see.
            next_deadline += interval
            slack = next_deadline - time.monotonic()
            if slack > 0:
                time.sleep(slack)
            else:
                next_deadline = time.monotonic()   # we are behind: resync instead of chasing

            now = time.monotonic()
            if now - t_report > 2.0:
                age_ms = 1000.0 * (time.monotonic() - (stream_t0[0] + pose_t)) if stream_t0[0] else float("nan")
                print(f"  {n / (now - t_report):5.1f} fps   pose age {age_ms:6.1f} ms   dropped {latest['dropped']:6d}   "
                      f"pos {px0:+.3f} {py0:+.3f} {pz0:+.3f} m   errs {render_errors[0]:4d}   yaw {last[0]:+7.1f}  "
                      f"pitch {last[1]:+7.1f}  roll {last[2]:+7.1f}", flush=True)
                n, t_report = 0, now
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        if pose[0] is not None:
            pose[0].terminate()
        if encoder is not None:
            try:
                encoder.stdin.close()
            except Exception:
                pass
            encoder.terminate()
        if player is not None:
            player.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
