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
import os
import pathlib
import signal
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SDK = pathlib.Path(os.environ.get("VITURE_SDK_DIR", pathlib.Path.home() / "workspace/uxspace/Android/SDK/linux-x86_64"))


def load_renderer():
    """Import make-stereo-demo.py (hyphen in the name, so by path)."""
    spec = importlib.util.spec_from_file_location("stereo_demo", ROOT / "tools" / "make-stereo-demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--res", default="960x600", help="per-eye render size (scaled up for the panels)")
    ap.add_argument("--screen", default="3840x1200", help="panel size the presenter blits to")
    ap.add_argument("--seconds", type=float, default=600.0)
    ap.add_argument("--no-presenter", action="store_true", help="render and measure only")
    ap.add_argument("--invert-yaw", action="store_true")
    ap.add_argument("--invert-pitch", action="store_true")
    ap.add_argument("--invert-roll", action="store_true")
    ap.add_argument("--fov", type=float, default=44.9,
                    help="per-eye horizontal FOV in degrees; the Luma Ultra is 52 deg "
                         "diagonal, which is ~44.9 deg horizontal on an 8:5 panel. This "
                         "must match the optics or head motion feels too fast/slow, "
                         "because the panel stretches the render across the real FOV.")
    ap.add_argument("--src", choices=("cb", "poll"), default="cb",
                    help="pose source: 'cb' uses the device callback (~800 Hz, gravity-stable, "
                         "100%% stable in testing); 'poll' uses get_gl_pose_carina, which drifts "
                         "(measured 30 deg of pitch drift while stationary).")
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
    if a.src == "cb":
        pose_args.append("--src-cb")
    else:
        pose_args += ["--predict", str(a.predict)]
    pose = subprocess.Popen(pose_args,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, text=True)
    assert pose.stdout is not None

    encoder = player = None
    if not a.no_presenter:
        encoder = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{frame_w}x{frame_h}", "-r", str(a.fps), "-i", "-",
             "-vf", f"scale={screen_w}:{screen_h}:flags=fast_bilinear",
             "-pix_fmt", "bgra", "-f", "rawvideo", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
        assert encoder.stdin is not None and encoder.stdout is not None
        if xpresent.exists():
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

    interval = 1.0 / float(a.fps)
    next_deadline = time.monotonic()
    n = 0
    t_report = time.monotonic()
    last = (0.0, 0.0, 0.0)
    try:
        for line in pose.stdout:
            if not line.startswith("{"):
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            yaw = d.get("yaw", 0.0) * (-1.0 if a.invert_yaw else 1.0)
            pitch = d.get("pitch", 0.0) * (-1.0 if a.invert_pitch else 1.0)
            roll = d.get("roll", 0.0) * (-1.0 if a.invert_roll else 1.0)
            if not a.no_recenter:
                if recenter_request[0]:
                    recenter_request[0] = False
                    ref = None
                    ref_acc.clear()
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

            cam = demo.Camera(pos=(0.0, 0.0, 0.0), yaw=yaw, pitch=pitch, roll=roll)
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
                print(f"  {n / (now - t_report):5.1f} fps   yaw {last[0]:+7.1f}  pitch {last[1]:+7.1f}  "
                      f"roll {last[2]:+7.1f}", flush=True)
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
