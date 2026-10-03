#!/usr/bin/env python3
"""x-edid -- dump and decode the EDID an X output presents.

Reads the `EDID` property of a RandR output (the only EDID source on this host:
nvidia-drm's /sys/class/drm/*/edid is empty because NVKMS owns the outputs) and
decodes enough of it to answer the questions this project keeps asking:

  * what timings does the sink actually declare (DTD list)?
  * what is its declared maximum pixel clock (range-limits descriptor)?
  * does it declare anything wide enough for side-by-side stereo (>= 3840)?
  * is this a real sink EDID or a synthesised adapter one?

Usage:
    tools/x-edid.py                      # default output HDMI-0 on :1
    tools/x-edid.py --output DP-0 --display :0
    tools/x-edid.py --json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def xrandr_props(display: str, output: str) -> str:
    return subprocess.run(["xrandr", "--prop", "--output", output], env={"DISPLAY": display, "PATH": "/usr/bin:/bin"},
                          capture_output=True, text=True).stdout


def grab_edid(display: str, output: str) -> bytes:
    txt = xrandr_props(display, output)
    lines, inside = [], False
    for line in txt.splitlines():
        if line.startswith(output):
            inside = True
            continue
        if inside and line and not line[0].isspace():
            break
        if inside and "\tEDID:" in line:
            continue
        if inside and line.strip() and all(c in "0123456789abcdefABCDEF" for c in line.strip()):
            lines.append(line.strip())
    return bytes.fromhex("".join(lines))


def decode(d: bytes) -> dict:
    if len(d) < 128 or d[:8] != bytes([0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0]):
        return {"error": "no/!valid EDID", "bytes": len(d)}
    mfg = (d[8] << 8) | d[9]
    out = {
        "bytes": len(d),
        "manufacturer": "".join(chr(((mfg >> s) & 31) + 64) for s in (10, 5, 0)),
        "product": f"0x{(d[11] << 8) | d[10]:04x}",
        "serial": f"0x{int.from_bytes(d[12:16], 'little'):08x}",
        "week": d[16], "year": d[17] + 1990,
        "edid_version": f"{d[18]}.{d[19]}",
        "digital_input": f"0x{d[20]:02x}",
        "size_cm": [d[21], d[22]],
        "gamma": round((d[23] + 100) / 100, 2),
        "extension_blocks": d[126],
        "timings": [], "descriptors": [],
    }
    for i, off in enumerate((54, 72, 90, 108)):
        b = d[off:off + 18]
        if b[0] == 0 and b[1] == 0:
            tag = b[3]
            if tag in (0xFC, 0xFE, 0xFF):
                out["descriptors"].append({"kind": {0xFC: "name", 0xFE: "string", 0xFF: "serial"}[tag],
                                           "value": b[5:18].decode("ascii", "replace").strip()})
            elif tag == 0xFD:
                out["descriptors"].append({"kind": "range_limits", "min_v": b[5], "max_v": b[6],
                                           "min_h_khz": b[7], "max_h_khz": b[8],
                                           "max_pixel_clock_mhz": b[9] * 10})
            continue
        clk = ((b[1] << 8) | b[0]) * 10  # kHz
        if clk == 0:
            continue
        ha = b[2] | ((b[4] >> 4) << 8); hb = b[3] | ((b[4] & 15) << 8)
        va = b[5] | ((b[7] >> 4) << 8); vb = b[6] | ((b[7] & 15) << 8)
        ht, vt = ha + hb, va + vb
        out["timings"].append({"active": f"{ha}x{va}", "pixel_clock_mhz": round(clk / 1000, 2),
                               "htotal": ht, "vtotal": vt, "refresh": round(clk / (ht * vt) * 1e6, 2),
                               "dtor": i})
    clocks = [t["pixel_clock_mhz"] for t in out["timings"]]
    out["max_dtd_clock_mhz"] = max(clocks) if clocks else None
    out["widest_active"] = max((t["active"] for t in out["timings"]), key=lambda s: int(s.split("x")[0])) if out["timings"] else None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--display", default=":1")
    ap.add_argument("--output", default="HDMI-0")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    raw = grab_edid(a.display, a.output)
    dec = decode(raw)
    if a.json:
        print(json.dumps({"output": a.output, **dec}, indent=2))
        return 0
    print(f"{a.output} @ {a.display}: {dec.get('bytes', 0)} EDID bytes")
    if "error" in dec:
        print(" ", dec["error"]); return 1
    print(f"  manufacturer {dec['manufacturer']}  product {dec['product']}  serial {dec['serial']}")
    print(f"  EDID {dec['edid_version']}  week {dec['week']}/{dec['year']}  "
          f"{dec['size_cm'][0]}x{dec['size_cm'][1]} cm  gamma {dec['gamma']}  "
          f"input {dec['digital_input']}  extensions {dec['extension_blocks']}")
    for t in dec["timings"]:
        print(f"  DTD{t['dtor']:<2} {t['active']:<12} {t['pixel_clock_mhz']:>8.2f} MHz  "
              f"{t['refresh']:>6.2f} Hz  (h {t['htotal']} v {t['vtotal']})")
    for d in dec["descriptors"]:
        if d["kind"] == "range_limits":
            print(f"  range: v {d['min_v']}-{d['max_v']} Hz, h {d['min_h_khz']}-{d['max_h_khz']} kHz, "
                  f"max pixel clock {d['max_pixel_clock_mhz']} MHz")
        else:
            print(f"  {d['kind']}: {d['value']}")
    wide = [t for t in dec["timings"] if int(t["active"].split("x")[0]) >= 3840]
    print(f"  VERDICT: widest active {dec['widest_active']}, max DTD clock {dec['max_dtd_clock_mhz']} MHz, "
          f"wide(>=3840) DTDs: {len(wide)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
