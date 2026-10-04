#!/usr/bin/env python3
"""Carina stereo calibration CLI.

Layers: xr-carina-sensor-v1 -> L/R extract -> ChArUco -> fisheye KB4
-> stereo -> rectify check -> xr-carina-calib-v1 + Monado v2 JSON.

Translation is in board-square units, not metres.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV = HERE / "calib" / ".venv" / "bin" / "python"


def _boot():
    venv_root = HERE / "calib" / ".venv"
    if venv_root.is_dir() and Path(sys.prefix).resolve() != venv_root.resolve():
        os.execv(str(VENV), [str(VENV), *sys.argv])


_boot()
sys.path.insert(0, str(HERE))

from calib.artifact import save, to_dict, to_monado_v2  # noqa: E402
from calib.board import BoardSpec, save_png, show_fullscreen  # noqa: E402
from calib.compare import compare, dumps as compare_dumps  # noqa: E402
from calib.detect import detect_session, summarize  # noqa: E402
from calib.session import Session  # noqa: E402
from calib.solve import Rejected, remap_pair, solve  # noqa: E402
from calib.synth import selftest  # noqa: E402


def _spec(args) -> BoardSpec:
    sx, sy = 8, 5
    if getattr(args, "squares", None):
        a, b = args.squares.lower().split("x")
        sx, sy = int(a), int(b)
    return BoardSpec(
        squares_x=sx,
        squares_y=sy,
        square_length=float(getattr(args, "square", 1.0)),
        marker_length=float(getattr(args, "marker", 0.75)),
        dict_name=getattr(args, "dict", "4x4_50"),
    )


def cmd_target(args) -> int:
    spec = _spec(args)
    if args.png:
        save_png(spec, args.png)
        print("wrote", args.png)
        print("board", json.dumps(spec.to_json()))
        if args.no_show:
            return 0
    return show_fullscreen(spec)


def cmd_extract(args) -> int:
    from PIL import Image

    sess = Session(Path(args.session))
    out = Path(args.out or (Path(args.session) / "extract"))
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for fr in sess.iter_frames(every=args.every, limit=args.limit):
        if fr.l0 is not None:
            Image.fromarray(fr.l0).save(out / f"{fr.seq:04d}_l0.png")
        if fr.r0 is not None:
            Image.fromarray(fr.r0).save(out / f"{fr.seq:04d}_r0.png")
        n += 1
    print("extracted", n, "pairs ->", out)
    print(json.dumps(sess.summary(), indent=2))
    return 0


def cmd_detect(args) -> int:
    sess = Session(Path(args.session))
    ds = detect_session(sess, _spec(args), every=args.every, limit=args.limit)
    summary = summarize(ds)
    print(json.dumps(summary, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(summary, indent=2) + "\n")
    return 0 if ds.stereo or ds.views_l or ds.views_r else 2


def cmd_solve(args) -> int:
    sess = Session(Path(args.session))
    spec = _spec(args)
    ds = detect_session(sess, spec, every=args.every, limit=args.limit)
    print(json.dumps(summarize(ds), indent=2))
    try:
        cal = solve(ds, hold=args.holdout, seed=args.seed)
    except Rejected as e:
        print("REJECTED:", e)
        return 2
    payload = to_dict(
        cal,
        spec,
        sn_hash=sess.sn_hash,
        source_sessions=[str(Path(args.session).resolve())],
    )
    out = Path(args.out or (Path(args.session) / "calib.json"))
    save(out, payload)
    monado = Path(str(out).removesuffix(".json") + ".monado.json")
    save(monado, to_monado_v2(cal))
    print("wrote", out)
    print("wrote", monado)
    print("metrics", json.dumps(payload["metrics"], indent=2))
    print(payload["scale_note"])
    return 0


def cmd_validate(args) -> int:
    sess = Session(Path(args.session))
    spec = _spec(args)
    ds = detect_session(sess, spec, every=args.every, limit=args.limit)
    try:
        cal = solve(ds, hold=args.holdout, seed=args.seed)
    except Rejected as e:
        print("REJECTED:", e)
        return 2
    print("holdout L/R", cal.holdout_reproj_l, cal.holdout_reproj_r)
    print("epipolar_mean_px", cal.epipolar_mean_px)
    print("rms", cal.rms)
    if args.png and ds.stereo:
        # remap first stereo pair that we can load
        fr = None
        want = ds.stereo[0].seq
        for f in sess.iter_frames():
            if f.seq == want and f.l0 is not None and f.r0 is not None:
                fr = f
                break
        if fr is not None:
            import cv2
            from PIL import Image

            rl, rr, _Q = remap_pair(fr.l0, fr.r0, cal)
            vis = cv2.hconcat([rl, rr])
            # draw a few horizontal guides
            for y in range(40, vis.shape[0], 40):
                vis[y : y + 1, :] = 180
            Path(args.png).parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(vis).save(args.png)
            print("rectify preview", args.png)
    return 0


def cmd_monado(args) -> int:
    from calib.solve import MonoCalib, StereoCalib
    import numpy as np

    raw = json.loads(Path(args.calib).read_text())
    if raw.get("format") != "xr-carina-calib-v1":
        print("not xr-carina-calib-v1")
        return 2
    left = MonoCalib(K=np.array(raw["left"]["K"]), D=np.array(raw["left"]["D"]).reshape(4, 1), rms=0, n_views=0, holdout_rms=None)
    right = MonoCalib(K=np.array(raw["right"]["K"]), D=np.array(raw["right"]["D"]).reshape(4, 1), rms=0, n_views=0, holdout_rms=None)
    st = raw["stereo"]
    cal = StereoCalib(
        left=left,
        right=right,
        R=np.array(st["R"]),
        T=np.array(st["T"]).reshape(3, 1),
        E=np.array(st["E"]),
        F=np.array(st["F"]),
        rms=0,
        holdout_reproj_l=None,
        holdout_reproj_r=None,
        epipolar_mean_px=None,
        n_stereo=0,
        n_holdout=0,
        width=raw["image_size"]["width"],
        height=raw["image_size"]["height"],
    )
    out = Path(args.out or Path(args.calib).with_suffix(".monado.json"))
    save(out, to_monado_v2(cal))
    print("wrote", out)
    print("not a Mercury validation")
    return 0


def cmd_compare(args) -> int:
    a = Session(Path(args.session_a))
    b = Session(Path(args.session_b)) if args.session_b else None
    print(compare_dumps(compare(a, b)))
    return 0


def cmd_edid(_args) -> int:
    import os
    import re
    import subprocess

    print("EDID / xrandr physical size is NOT trusted metric scale (xr-wdw.5).")
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("no DISPLAY; not querying xrandr")
        print("do not silently trust EDID millimetres. close xr-wdw.5 only with a measured length.")
        return 0
    try:
        out = subprocess.check_output(["xrandr"], text=True, stderr=subprocess.DEVNULL, timeout=2)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print("xrandr unavailable:", e)
        return 1
    mm = re.findall(
        r"^(\S+) connected.* (\d+)x(\d+)\+\d+\+\d+.* (\d+)mm x (\d+)mm",
        out,
        re.M,
    )
    if not mm:
        mm2 = re.findall(r"^(\S+) connected.*?(\d+)mm x (\d+)mm", out, re.M | re.S)
        print("parsed", mm2)
        print("do not use these millimetres as square size without independent measurement")
        return 0
    for name, pxw, pxh, mmw, mmh in mm:
        pw, ph, mw, mh = int(pxw), int(pxh), int(mmw), int(mmh)
        sx = mw / pw if pw else None
        print(f"{name}: {pw}x{ph}px  reported {mw}x{mh}mm  ~{sx:.4f} mm/px" if sx else name)
    print("do not silently trust this. close xr-wdw.5 only with a measured length.")
    return 0


def cmd_selftest(_args) -> int:
    return selftest()


def main() -> int:
    p = argparse.ArgumentParser(prog="carina_calib.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("target", help="fullscreen ChArUco on this monitor")
    t.add_argument("--squares", default="8x5")
    t.add_argument("--dict", default="4x4_50")
    t.add_argument("--square", type=float, default=1.0)
    t.add_argument("--marker", type=float, default=0.75)
    t.add_argument("--png", help="also write a PNG (exact square pixels)")
    t.add_argument("--no-show", action="store_true")
    t.set_defaults(func=cmd_target)

    e = sub.add_parser("extract", help="dump L0/R0 pngs from a sensor session")
    e.add_argument("session")
    e.add_argument("--out")
    e.add_argument("--every", type=int, default=1)
    e.add_argument("--limit", type=int)
    e.set_defaults(func=cmd_extract)

    d = sub.add_parser("detect", help="ChArUco detect + diversity prompts")
    d.add_argument("session")
    d.add_argument("--every", type=int, default=2)
    d.add_argument("--limit", type=int)
    d.add_argument("--squares", default="8x5")
    d.add_argument("--dict", default="4x4_50")
    d.add_argument("--out")
    d.set_defaults(func=cmd_detect)

    s = sub.add_parser("solve", help="fisheye KB4 + stereo solve")
    s.add_argument("session")
    s.add_argument("--out")
    s.add_argument("--every", type=int, default=2)
    s.add_argument("--limit", type=int)
    s.add_argument("--squares", default="8x5")
    s.add_argument("--dict", default="4x4_50")
    s.add_argument("--holdout", type=float, default=0.2)
    s.add_argument("--seed", type=int, default=0)
    s.set_defaults(func=cmd_solve)

    v = sub.add_parser("validate", help="held-out / epipolar / optional rectify png")
    v.add_argument("session")
    v.add_argument("--png")
    v.add_argument("--every", type=int, default=2)
    v.add_argument("--limit", type=int)
    v.add_argument("--squares", default="8x5")
    v.add_argument("--dict", default="4x4_50")
    v.add_argument("--holdout", type=float, default=0.2)
    v.add_argument("--seed", type=int, default=0)
    v.set_defaults(func=cmd_validate)

    m = sub.add_parser("monado", help="emit Monado calibration_v2 JSON (not Mercury-validated)")
    m.add_argument("calib")
    m.add_argument("--out")
    m.set_defaults(func=cmd_monado)

    c = sub.add_parser("compare", help="offline Android vs Linux session compare")
    c.add_argument("session_a")
    c.add_argument("session_b", nargs="?")
    c.set_defaults(func=cmd_compare)

    ed = sub.add_parser("edid", help="print xrandr mm (untrusted; xr-wdw.5)")
    ed.set_defaults(func=cmd_edid)

    st = sub.add_parser("selftest", help="synthetic recovery without glasses")
    st.set_defaults(func=cmd_selftest)

    args = p.parse_args()
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
