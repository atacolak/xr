#!/usr/bin/env python3
"""Live 3DoF demo: the stereo scene rendered from the glasses' own orientation.

This is the perceptual check for M3. Numbers can tell you that yaw, pitch and roll each
respond to *something*; only your eyes can tell you whether turning your head turns the
scene the way a fixed world should (and whether any axis is inverted or swapped).

How it works
------------
  viture-pose-dump --3dof --json   ->  a JSON pose line per sample (the device's IMU pose)
  this script                      ->  renders the SBS scene with camera yaw/pitch/roll
                                       taken from the pose and streams raw frames
  mpv (rawvideo from stdin)        ->  fullscreen on the 3840x1200 side-by-side output

The camera IS the head, so head yaw = camera yaw: the world stays put and slides across
the view, which is what a fixed room looks like when you turn. 3DoF has no position, so
the camera stays at the origin by design -- that is the difference you will feel at 6DoF.

Usage:
    tools/headtrack-demo.py                     # 60 fps, half-res render
    tools/headtrack-demo.py --fps 30 --res 960x600
    tools/headtrack-demo.py --no-mpv            # render to stdout only (plumbing check)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import pathlib
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
    ap.add_argument("--res", default="960x600", help="per-eye render size (mpv upscales)")
    ap.add_argument("--seconds", type=float, default=600.0)
    ap.add_argument("--no-mpv", action="store_true")
    ap.add_argument("--invert-yaw", action="store_true", help="flip yaw sign if the world turns the wrong way")
    ap.add_argument("--invert-pitch", action="store_true")
    ap.add_argument("--invert-roll", action="store_true")
    a = ap.parse_args()

    eye_w, eye_h = (int(v) for v in a.res.lower().split("x"))
    demo = load_renderer()
    demo.EYE_W, demo.EYE_H = eye_w, eye_h          # keep the 8:5 aspect so the FOV math holds
    frame_w, frame_h = eye_w * 2, eye_h

    tool = ROOT / "tools" / "viture-pose-dump"
    if not tool.exists():
        print(f"no {tool} (build: tools/build-pose-dump.sh)", file=sys.stderr)
        return 1

    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = f"{SDK}/x86_64{os.pathsep}{env.get('LD_LIBRARY_PATH', '')}"
    pose = subprocess.Popen([str(tool), "--3dof", "--seconds", str(a.seconds), "--json"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, text=True)
    assert pose.stdout is not None

    player = None
    if not a.no_mpv:
        # ffplay, not mpv: mpv's rawvideo demuxer wants a fourcc from its own table and
        # rejects rgb24 outright ("invalid FourCC"), while ffplay takes -pixel_format.
        cmd = ["ffplay", "-fs", "-autoexit", "-loglevel", "error",
               "-f", "rawvideo", "-pixel_format", "rgb24",
               "-video_size", f"{frame_w}x{frame_h}", "-framerate", str(a.fps), "-"]
        player = subprocess.Popen(cmd, stdin=subprocess.PIPE, env={**env, "DISPLAY": env.get("DISPLAY", ":1")})
        assert player.stdin is not None

    print(f"pose source: {tool.name} --3dof   render {frame_w}x{frame_h} SBS   target {a.fps} fps")
    print("turn / nod / tilt your head -- the scene should stay put in the world", flush=True)

    n = 0
    last_pose = (0.0, 0.0, 0.0)
    t_report = time.time()
    try:
        for line in pose.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            yaw = d.get("yaw", 0.0) * (-1.0 if a.invert_yaw else 1.0)
            pitch = d.get("pitch", 0.0) * (-1.0 if a.invert_pitch else 1.0)
            roll = d.get("roll", 0.0) * (-1.0 if a.invert_roll else 1.0)
            last_pose = (yaw, pitch, roll)
            cam = demo.Camera(pos=(0.0, 0.0, 0.0), yaw=yaw, pitch=pitch, roll=roll)
            frame = demo.render_frame(0.35, cam).tobytes()
            if player is not None:
                player.stdin.write(frame)
            elif n < 3:
                sys.stdout.buffer.write(frame)
            n += 1
            now = time.time()
            if now - t_report > 2.0:
                print(f"  {n / (now - t_report):5.1f} fps   yaw {last_pose[0]:+7.1f}  "
                      f"pitch {last_pose[1]:+7.1f}  roll {last_pose[2]:+7.1f}", flush=True)
                n, t_report = 0, now
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        pose.terminate()
        if player is not None:
            try:
                player.stdin.close()
            except Exception:
                pass
            player.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
