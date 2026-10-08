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


def sample_ok(status, pose, pos, last_pose, last_pos) -> bool:
    """Is this pose sample believable enough to show?

    Two kinds are not, and the last good pose is held instead:

      * the vendor marks it invalid (status != 0). The SDK emits zeroed poses while it
        settles, and this loop used to apply every line verbatim -- so a single bad sample
        snapped the view to the scene origin for one frame and then back. That is the
        split-second jump reported from inside the headset.
      * it would teleport the head. No real head turns 60 deg or moves a metre between
        samples, so a jump that size is corrupt data rather than motion. This is also what
        will keep a 6DoF pose honest once translation is live.
    """
    if status != 0:
        return False
    if pose == (0.0, 0.0, 0.0):
        # The SDK's placeholder is exactly zero in all three channels. A real pose landing
        # on exactly 0.000 in all three axes is a measure-zero event, so treating it as
        # invalid costs one frame of held pose at worst; treating it as valid snaps the view
        # to the reference direction. (Measured: status==0 with an all-zero pose was never
        # observed -- the 120 placeholders in a startup capture were all status==1 -- so
        # this is belt and braces for a second source, not the primary gate.)
        return False
    if last_pose is None:
        return True
    return (max(abs(a - b) for a, b in zip(pose, last_pose)) <= 60.0
            and max(abs(a - b) for a, b in zip(pos, last_pos)) <= 1.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=int, default=90,
                    help="target frames/s. The Luma Ultra refreshes at 90 Hz, and the default "
                         "640x400 per eye measured 119 fps of render headroom at 3x upscale, "
                         "so 90 is attainable when the panel is actually driving the swap.")
    ap.add_argument("--res", default="640x400", help="per-eye render size (scaled up for the panels)")
    ap.add_argument("--screen", default="3840x1200", help="panel size the presenter blits to")
    ap.add_argument("--seconds", type=float, default=600.0)
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

    pose_args = [str(tool), "--3dof", "--seconds", str(a.seconds), "--json", "--auto-exposure"]
    if not a.no_flip_xy:
        pose_args.append("--flip-xy")
    if a.src == "cb":
        pose_args.append("--src-cb")
    else:
        pose_args += ["--predict", str(a.predict)]
    pose = subprocess.Popen(pose_args,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, text=True)
    assert pose.stdout is not None

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
    latest = {"pose": (0.0, 0.0, 0.0), "pos": (0.0, 0.0, 0.0), "t": 0.0, "status": 1, "n": -1,
              "dropped": 0}
    lock = threading.Lock()
    stream_t0 = [None]

    def reader():
        last = [None]      # last pose we believed: (yaw, pitch, roll)
        last_pos = [None]  # and its position, so a 6DoF teleport is caught too
        # see sample_ok() for why samples get dropped
        for line in pose.stdout:
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
            q = (d.get("px", 0.0), d.get("py", 0.0), d.get("pz", 0.0))
            # Two kinds of sample are thrown away and the last good pose is held instead:
            #   * the vendor marks it invalid (status != 0). The SDK emits zeroed poses while
            #     it settles, and this loop used to apply every line verbatim -- so a single
            #     bad sample snapped the view to the scene origin for one frame and then
            #     back. That is the split-second jump that was reported ("turns my head to
            #     the origin and jerks it back").
            #   * it would teleport the head. No real head turns 60 deg or moves a metre
            #     between samples, so a jump that size is corrupt data, not motion. This also
            #     keeps 6DoF honest once translation is live.
            if not sample_ok(status, p, q, last[0], last_pos[0]):
                with lock:
                    latest["dropped"] += 1
                    latest["status"] = status
                continue
            last[0], last_pos[0] = p, q
            with lock:
                latest["pose"] = p
                latest["pos"] = q
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
                latest["t"] = el
                latest["status"] = 0
                latest["n"] += 1
            time.sleep(1.0 / 120.0)

    if a.src == "synth":
        stream_t0[0] = time.monotonic()
        threading.Thread(target=synthetic, daemon=True).start()
    else:
        threading.Thread(target=reader, daemon=True).start()

    smoothed = [0.0, 0.0, 0.0, None]
    prev_t = [time.monotonic()]
    interval = 1.0 / float(a.fps)
    next_deadline = time.monotonic()
    n = 0
    t_report = time.monotonic()
    last = (0.0, 0.0, 0.0)
    try:
        while True:
            with lock:
                yaw0, pitch0, roll0 = latest["pose"]
                px0, py0, pz0 = latest["pos"]
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
                        print(f"recentred on yaw {ref[0]:+.1f} pitch {ref[1]:+.1f} roll {ref[2]:+.1f} "
                              f"({len(ref_acc)} stable samples)", flush=True)
                    yaw, pitch, roll = 0.0, 0.0, 0.0
                else:
                    yaw = ang_diff(yaw, ref[0])
                    pitch = ang_diff(pitch, ref[1])
                    roll = ang_diff(roll, ref[2])
            last = (yaw, pitch, roll)

            # Smoothing is lag and a deadband is not, so apply the deadband first: it alone
            # removes the sensor's micro-jitter. 3DoF reports no translation, so the position
            # stays at the origin -- but it is plumbed through, so a 6DoF pose drops straight in.
            now_s = time.monotonic()
            dt = max(1e-3, min(0.25, now_s - prev_t[0]))
            prev_t[0] = now_s
            sm = smoothed
            if sm[3] is None:
                sm[0], sm[1], sm[2] = yaw, pitch, roll
                sm[3] = 1.0
            else:
                alpha = 1.0 if a.smooth <= 0.0 else (1.0 - math.exp(-dt / a.smooth))
                for i, target in enumerate((yaw, pitch, roll)):
                    d_ang = target - sm[i]
                    if abs(d_ang) < a.deadband:
                        d_ang = 0.0
                    sm[i] += alpha * d_ang
                yaw, pitch, roll = sm[0], sm[1], sm[2]

            cam = demo.Camera(pos=(px0, py0, pz0), yaw=yaw, pitch=pitch, roll=roll)
            # slow self-drift, so a stuttering display is distinguishable from a still scene
            phase = (time.monotonic() * 0.2) % 1.0
            frame = demo.render_frame(phase, cam).tobytes()
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
                print(f"  {n / (now - t_report):5.1f} fps   pose age {age_ms:6.1f} ms   dropped {latest['dropped']:6d}   yaw {last[0]:+7.1f}  "
                      f"pitch {last[1]:+7.1f}  roll {last[2]:+7.1f}", flush=True)
                n, t_report = 0, now
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        pose.terminate()
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
