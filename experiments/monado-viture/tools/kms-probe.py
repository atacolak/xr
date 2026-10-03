#!/usr/bin/env python3
"""kms-probe -- set custom display timings on a DRM connector, no X, no libdrm.

Why this exists: the nvidia X driver refuses to attach any timing it did not
derive from the display's EDID (`xrandr --addmode` -> BadMatch), so wide or
side-by-side stereo timings cannot be pushed through X at all. Monado's display
compositor hits the same wall the other way round: it needs DRM master. This tool
is the minimal instrument for both -- it talks to /dev/dri/card* directly.

Usage
-----
    # enumerate (no DRM master needed; safe while X is running)
    tools/kms-probe.py --enumerate

    # set a timing (needs DRM master -> X must not be on the active VT)
    sudo tools/kms-probe.py --connector HDMI-A-1 --timing 3840x1200@60 --hold 12

    # sweep several timings, holding each so a human can watch the panels
    sudo tools/kms-probe.py --connector HDMI-A-1 --hold 12 \
        --timing 1920x1200@90 --timing 2560x1200@90 --timing 3840x1200@60 --timing 3840x1200@90

Getting master without stopping the session: switch away from the X VT first
(`sudo chvt 3`), run the probe, then `sudo chvt 2` to come back. X re-acquires
master when its VT is activated again.

The screen shows coloured bands whose colour encodes the timing index, so a human
looking through the glasses can report which timings actually locked. The tool
reports what the kernel accepted; only eyes can report what the sink locked.

Known limitation on this host (2026-10-04, RTX 4070, nvidia 595.84)
------------------------------------------------------------------
nvidia-drm (the only DRM card) reports every connector as disconnected with 0
modes even while the X server drives HDMI-0 at 1920x1200@90 with a valid EDID,
because NVKMS -- the X driver -- owns the real outputs. X also holds DRM master.

A DRM-level mode set on this machine therefore requires X to be stopped first; a
VT switch alone only drops X's master, the connectors still report disconnected.
The tool stays useful for that case, and its enumeration is the evidence above.
"""

from __future__ import annotations

import argparse
import ctypes
import fcntl
import json
import mmap
import os
import struct
import sys
import time

# ---------------------------------------------------------------- ioctls
DRM_IOCTL_SET_MASTER = 0x0000641E
DRM_IOCTL_DROP_MASTER = 0x0000641F
DRM_IOCTL_MODE_GETRESOURCE = 0xC04064A0
DRM_IOCTL_MODE_GETCRTC = 0xC06864A1
DRM_IOCTL_MODE_SETCRTC = 0xC06864A2
DRM_IOCTL_MODE_GETCONNECTOR = 0xC05064A7
DRM_IOCTL_MODE_GETENCODER = 0xC01464A6
DRM_IOCTL_MODE_ADDFB = 0xC01C64AE
DRM_IOCTL_MODE_CREATE_DUMB = 0xC02064B2
DRM_IOCTL_MODE_MAP_DUMB = 0xC01064B3
DRM_IOCTL_MODE_DESTROY_DUMB = 0xC00464B4

DRM_MODE_CONNECTED = 1
CONNECTOR_TYPE = {"HDMI-A": 11, "DisplayPort": 10, "VGA": 1, "DVI-I": 3, "Virtual": 15, "eDP": 14}

# drm_mode_modeinfo flags
DRM_MODE_FLAG_PHSYNC = 1 << 0
DRM_MODE_FLAG_NHSYNC = 1 << 1
DRM_MODE_FLAG_PVSYNC = 1 << 2
DRM_MODE_FLAG_NVSYNC = 1 << 3


class ModeInfo(ctypes.Structure):
    _fields_ = [
        ("clock", ctypes.c_uint32),          # kHz
        ("hdisplay", ctypes.c_uint16),
        ("hsync_start", ctypes.c_uint16),
        ("hsync_end", ctypes.c_uint16),
        ("htotal", ctypes.c_uint16),
        ("hskew", ctypes.c_uint16),
        ("vdisplay", ctypes.c_uint16),
        ("vsync_start", ctypes.c_uint16),
        ("vsync_end", ctypes.c_uint16),
        ("vtotal", ctypes.c_uint16),
        ("vscan", ctypes.c_uint16),
        ("vrefresh", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("name", ctypes.c_char * 32),
    ]


class CardRes(ctypes.Structure):
    _fields_ = [
        ("fb_id_ptr", ctypes.c_uint64),
        ("crtc_id_ptr", ctypes.c_uint64),
        ("connector_id_ptr", ctypes.c_uint64),
        ("encoder_id_ptr", ctypes.c_uint64),
        ("count_fbs", ctypes.c_uint32),
        ("count_crtcs", ctypes.c_uint32),
        ("count_connectors", ctypes.c_uint32),
        ("count_encoders", ctypes.c_uint32),
        ("min_width", ctypes.c_uint32),
        ("max_width", ctypes.c_uint32),
        ("min_height", ctypes.c_uint32),
        ("max_height", ctypes.c_uint32),
    ]


class GetConnector(ctypes.Structure):
    _fields_ = [
        ("encoders_ptr", ctypes.c_uint64),
        ("modes_ptr", ctypes.c_uint64),
        ("props_ptr", ctypes.c_uint64),
        ("prop_values_ptr", ctypes.c_uint64),
        ("count_modes", ctypes.c_uint32),
        ("count_props", ctypes.c_uint32),
        ("count_encoders", ctypes.c_uint32),
        ("encoder_id", ctypes.c_uint32),
        ("connector_id", ctypes.c_uint32),
        ("connector_type", ctypes.c_uint32),
        ("connector_type_id", ctypes.c_uint32),
        ("connection", ctypes.c_uint32),
        ("mm_width", ctypes.c_uint32),
        ("mm_height", ctypes.c_uint32),
        ("subpixel", ctypes.c_uint32),
        ("pad", ctypes.c_uint32),
    ]


class Encoder(ctypes.Structure):
    _fields_ = [
        ("encoder_id", ctypes.c_uint32),
        ("encoder_type", ctypes.c_uint32),
        ("crtc_id", ctypes.c_uint32),
        ("possible_crtcs", ctypes.c_uint32),
        ("possible_clones", ctypes.c_uint32),
    ]


class Crtc(ctypes.Structure):
    _fields_ = [
        ("set_connectors_ptr", ctypes.c_uint64),
        ("count_connectors", ctypes.c_uint32),
        ("crtc_id", ctypes.c_uint32),
        ("fb_id", ctypes.c_uint32),
        ("x", ctypes.c_uint32),
        ("y", ctypes.c_uint32),
        ("gamma_size", ctypes.c_uint32),
        ("mode_valid", ctypes.c_uint32),
        ("mode", ModeInfo),
        ("pad", ctypes.c_uint32),
    ]


class CreateDumb(ctypes.Structure):
    _fields_ = [
        ("height", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("bpp", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("handle", ctypes.c_uint32),
        ("pitch", ctypes.c_uint32),
        ("size", ctypes.c_uint64),
    ]


class MapDumb(ctypes.Structure):
    _fields_ = [("handle", ctypes.c_uint32), ("pad", ctypes.c_uint32), ("offset", ctypes.c_uint64)]


class FbCmd(ctypes.Structure):
    _fields_ = [
        ("fb_id", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("pitch", ctypes.c_uint32),
        ("bpp", ctypes.c_uint32),
        ("depth", ctypes.c_uint32),
        ("handle", ctypes.c_uint32),
    ]


def ioctl(fd, req, obj):
    return fcntl.ioctl(fd, req, obj, True)


# ---------------------------------------------------------------- timings
def cvtrb(w: int, h: int, hz: int) -> ModeInfo:
    """CVT reduced blanking. Radical but widely accepted by sinks."""
    htotal = w + 160
    vtotal = h + 26
    clock = int(round(htotal * vtotal * hz / 1000))  # kHz
    m = ModeInfo()
    m.clock = clock
    m.hdisplay, m.hsync_start, m.hsync_end, m.htotal = w, w + 48, w + 80, htotal
    m.hskew = 0
    m.vdisplay, m.vsync_start, m.vsync_end, m.vtotal = h, h + 3, h + 8, vtotal
    m.vscan = 0
    m.vrefresh = hz
    m.flags = DRM_MODE_FLAG_PHSYNC | DRM_MODE_FLAG_NVSYNC
    m.name = f"{w}x{h}@{hz}rb".encode()
    return m


def dtd_style(w: int, h: int, hz: int) -> ModeInfo:
    """Blankings scaled from the sink's own DTD0 proportions (2000/1250 at 1920x1200)."""
    htotal = w + (2000 - 1920) * w // 1920
    vtotal = h + (1250 - 1200)
    clock = int(round(htotal * vtotal * hz / 1000))
    m = ModeInfo()
    m.clock = clock
    m.hdisplay, m.hsync_start, m.hsync_end, m.htotal = w, w + int(32 * w / 1920) + 32, w + int(38 * w / 1920) + 38, htotal
    m.hskew = 0
    m.vdisplay, m.vsync_start, m.vsync_end, m.vtotal = h, h + 9, h + 14, vtotal
    m.vscan = 0
    m.vrefresh = hz
    m.flags = DRM_MODE_FLAG_PHSYNC | DRM_MODE_FLAG_PVSYNC
    m.name = f"{w}x{h}@{hz}dtd".encode()
    return m


def parse_timing(spec: str) -> ModeInfo:
    """WxH@Rz[+style] -> ModeInfo. style: rb (reduced blanking) | dtd (EDID-scaled)."""
    style = "rb"
    if "+" in spec:
        spec, style = spec.split("+", 1)
    if "@" not in spec or "x" not in spec:
        raise SystemExit(f"bad timing {spec!r}; want WxH@R e.g. 3840x1200@60")
    wh, hz = spec.split("@")
    w, h = (int(v) for v in wh.split("x"))
    hz = int(hz)
    return cvtrb(w, h, hz) if style == "rb" else dtd_style(w, h, hz)


# ---------------------------------------------------------------- drm helpers
class Card:
    def __init__(self, path: str):
        self.path = path
        self.fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
        self._master = False

    def set_master(self) -> bool:
        try:
            ioctl(self.fd, DRM_IOCTL_SET_MASTER, 0)
            self._master = True
            return True
        except OSError as e:
            return False

    def drop_master(self):
        if self._master:
            try:
                ioctl(self.fd, DRM_IOCTL_DROP_MASTER, 0)
            except OSError:
                pass
            self._master = False

    def resources(self):
        res = CardRes()
        ioctl(self.fd, DRM_IOCTL_MODE_GETRESOURCE, res)
        crtcs = (ctypes.c_uint32 * res.count_crtcs)()
        conns = (ctypes.c_uint32 * res.count_connectors)()
        encs = (ctypes.c_uint32 * res.count_encoders)()
        res.crtc_id_ptr = ctypes.addressof(crtcs)
        res.connector_id_ptr = ctypes.addressof(conns)
        res.encoder_id_ptr = ctypes.addressof(encs)
        ioctl(self.fd, DRM_IOCTL_MODE_GETRESOURCE, res)
        return list(crtcs), list(conns), list(encs)

    def connector(self, cid: int):
        c = GetConnector()
        c.connector_id = cid
        ioctl(self.fd, DRM_IOCTL_MODE_GETCONNECTOR, c)
        modes = (ModeInfo * c.count_modes)()
        encs = (ctypes.c_uint32 * c.count_encoders)()
        props = (ctypes.c_uint32 * c.count_props)()
        prop_vals = (ctypes.c_uint64 * c.count_props)()
        c.modes_ptr = ctypes.addressof(modes)
        c.encoders_ptr = ctypes.addressof(encs)
        c.props_ptr = ctypes.addressof(props)
        c.prop_values_ptr = ctypes.addressof(prop_vals)
        ioctl(self.fd, DRM_IOCTL_MODE_GETCONNECTOR, c)
        return c, list(modes), list(encs)

    def encoder(self, eid: int):
        e = Encoder()
        e.encoder_id = eid
        ioctl(self.fd, DRM_IOCTL_MODE_GETENCODER, e)
        return e

    def crtc(self, cid: int):
        cr = Crtc()
        cr.crtc_id = cid
        ioctl(self.fd, DRM_IOCTL_MODE_GETCRTC, cr)
        return cr

    def dumb(self, w: int, h: int, bpp: int = 32):
        d = CreateDumb(height=h, width=w, bpp=bpp)
        ioctl(self.fd, DRM_IOCTL_MODE_CREATE_DUMB, d)
        m = MapDumb(handle=d.handle)
        ioctl(self.fd, DRM_IOCTL_MODE_MAP_DUMB, m)
        buf = mmap.mmap(self.fd, d.size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=m.offset)
        fb = FbCmd(width=w, height=h, pitch=d.pitch, bpp=bpp, depth=24, handle=d.handle)
        ioctl(self.fd, DRM_IOCTL_MODE_ADDFB, fb)
        return d, buf, fb.fb_id

    def paint(self, buf, pitch: int, w: int, h: int, index: int):
        """Colour bands; the index is encoded so a human can name what they saw."""
        palette = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255)]
        r, g, b = palette[index % len(palette)]
        row_white = b"\xff" * (w * 4)
        row_body = bytes([b, g, r, 0xff]) * w
        for y in range(h):
            buf[y * pitch : (y + 1) * pitch] = row_white if (y // 40) % 2 == 0 else row_body
        # left edge marker: solid white column pair so orientation is unambiguous
        for y in range(h):
            off = y * pitch
            buf[off : off + 16] = b"\xff" * 16

    def set_crtc(self, crtc_id: int, fb_id: int, conn_id: int, mode: ModeInfo):
        cr = Crtc()
        cr.crtc_id = crtc_id
        cr.fb_id = fb_id
        conns = (ctypes.c_uint32 * 1)(conn_id)
        cr.set_connectors_ptr = ctypes.addressof(conns)
        cr.count_connectors = 1
        cr.mode = mode
        cr.mode_valid = 1
        ioctl(self.fd, DRM_IOCTL_MODE_SETCRTC, cr)


def find_connector(card: Card, name: str, conn_ids):
    want_type, _, want_idx = name.partition("-")
    for cid in conn_ids:
        c, modes, _ = card.connector(cid)
        tname = next((k for k, v in CONNECTOR_TYPE.items() if v == c.connector_type), str(c.connector_type))
        if tname == want_type and (not want_idx or str(c.connector_type_id) == want_idx):
            return cid, c, modes
    return None, None, None


def enumerate_all(card: Card):
    crtcs, conns, encs = card.resources()
    out = {"card": card.path, "crtcs": crtcs, "encoders": encs, "connectors": []}
    for cid in conns:
        c, modes, enc_ids = card.connector(cid)
        tname = next((k for k, v in CONNECTOR_TYPE.items() if v == c.connector_type), str(c.connector_type))
        out["connectors"].append({
            "id": cid,
            "name": f"{tname}-{c.connector_type_id}",
            "connected": c.connection == DRM_MODE_CONNECTED,
            "mm": [c.mm_width, c.mm_height],
            "encoder_id": c.encoder_id,
            "encoders": enc_ids,
            "modes": [
                {"name": m.name.decode(errors="replace"), "clock_mhz": round(m.clock / 1000, 2),
                 "vrefresh": m.vrefresh, "htotal": m.htotal, "vtotal": m.vtotal}
                for m in modes
            ],
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--card", default="/dev/dri/card0")
    ap.add_argument("--connector", default="HDMI-A-1")
    ap.add_argument("--timing", action="append", default=[], help="WxH@Rz[+rb|+dtd]; repeatable")
    ap.add_argument("--hold", type=float, default=10.0, help="seconds to hold each timing")
    ap.add_argument("--enumerate", action="store_true", help="just list connectors/modes (no master needed)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    card = Card(args.card)
    try:
        if args.enumerate:
            data = enumerate_all(card)
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                for c in data["connectors"]:
                    print(f"{c['name']:<14} id={c['id']:<3} {'CONNECTED' if c['connected'] else 'disconnected'} "
                          f"enc={c['encoder_id']} mm={c['mm']} modes={len(c['modes'])}")
                    for m in c["modes"]:
                        print(f"    {m['name']:<20} {m['clock_mhz']:>8.2f} MHz  {m['vrefresh']} Hz")
                print(f"crtcs={data['crtcs']} encoders={data['encoders']}")
            return 0

        if not args.timing:
            raise SystemExit("nothing to do: pass --timing, or --enumerate")

        if not card.set_master():
            print("SET_MASTER failed: another client (X) holds DRM master on this VT.\n"
                  "Switch away from the X VT first (sudo chvt 3), or stop the X server.", file=sys.stderr)
            return 2
        print("DRM master acquired", file=sys.stderr)

        crtcs, conn_ids, _ = card.resources()
        cid, c, _ = find_connector(card, args.connector, conn_ids)
        if cid is None:
            raise SystemExit(f"connector {args.connector} not found")
        if c.connection != DRM_MODE_CONNECTED:
            print(f"note: {args.connector} reports disconnected in KMS", file=sys.stderr)

        enc = card.encoder(c.encoder_id)
        possible = [crtcs[i] for i in range(len(crtcs)) if enc.possible_crtcs & (1 << i)]
        crtc_id = enc.crtc_id or (possible[0] if possible else crtcs[0])
        print(f"connector={args.connector} id={cid} encoder={enc.encoder_id} crtc={crtc_id} "
              f"possible_crtcs={possible}", file=sys.stderr)

        for idx, spec in enumerate(args.timing):
            mode = parse_timing(spec)
            print(f"--- [{idx}] {spec}: clock={mode.clock/1000:.2f} MHz htotal={mode.htotal} "
                  f"vtotal={mode.vtotal} flags=0x{mode.flags:x}", file=sys.stderr)
            try:
                d, buf, fb_id = card.dumb(mode.hdisplay, mode.vdisplay)
            except OSError as e:
                print(f"    dumb buffer {mode.hdisplay}x{mode.vdisplay} failed: {e}", file=sys.stderr)
                continue
            card.paint(buf, d.pitch, mode.hdisplay, mode.vdisplay, idx)
            t0 = time.time()
            try:
                card.set_crtc(crtc_id, fb_id, cid, mode)
                print(f"    SETCRTC accepted in {time.time()-t0:.3f}s", file=sys.stderr)
            except OSError as e:
                print(f"    SETCRTC refused: {e}", file=sys.stderr)
            time.sleep(args.hold)
        card.drop_master()
        print("master dropped", file=sys.stderr)
        return 0
    finally:
        os.close(card.fd)


if __name__ == "__main__":
    sys.exit(main())
