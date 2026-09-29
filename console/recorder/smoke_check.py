#!/usr/bin/env python3
import glob, json, subprocess, sys, pathlib
out = pathlib.Path(sys.argv[1])
fails = []
def need(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)
sess = out / "session.json"
need(sess.is_file() and sess.stat().st_size > 20, "session.json exists")
if sess.is_file():
    try:
        data = json.loads(sess.read_text())
        need("monotonic_origin_ns" in data, "monotonic origin")
        need("video" in data, "video metadata")
        audio = data.get("audio") or {}
        need(bool(audio), "audio metadata")
        need(audio.get("selection_mode") in ("auto", "explicit"), "audio selection mode")
        need("requested_device" in audio, "requested microphone metadata")
        actual = audio.get("actual_routed_device")
        need(isinstance(actual, dict) and bool(actual), "actual routed microphone metadata")
        need(audio.get("route_matches_request") is True, "requested route matches actual route")
        need(int(audio.get("pcm_samples") or 0) > 0, "captured PCM samples")
        need(float(audio.get("pcm_peak") or 0) > 0, "audio peak is nonzero")
        need(float(audio.get("pcm_rms") or 0) > 1, "audio RMS is not digital silence")
        inputs = data.get("audio_inputs_at_start")
        need(isinstance(inputs, list), "input-device enumeration metadata")
        keys = ("session_id", "video", "audio", "audio_inputs_at_start", "stats", "rgb_usb")
        print(json.dumps({k: data.get(k) for k in keys}, indent=2)[:8000])
    except Exception as e:
        need(False, f"session.json parse {e}")
segments = sorted(out.glob("segment-*.mp4"))
need(len(segments) >= 2, f"segment rollover produced {len(segments)} segments")
for segment in segments:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height:format=duration",
         "-print_format", "json", str(segment)],
        capture_output=True, text=True)
    need(probe.returncode == 0, f"{segment.name} independently probeable")
    if probe.returncode == 0:
        segment_info = json.loads(probe.stdout)
        segment_streams = segment_info.get("streams") or []
        need(any(s.get("codec_type") == "video" for s in segment_streams),
             f"{segment.name} video track")
        need(any(s.get("codec_type") == "audio" for s in segment_streams),
             f"{segment.name} audio track")
ev = out / "events.jsonl"
need(ev.is_file() and ev.stat().st_size > 10, "events.jsonl exists")
mp4 = out / "sample.mp4"
need(mp4.is_file() and mp4.stat().st_size > 100_000,
     f"mp4 nontrivial ({mp4.stat().st_size if mp4.is_file() else 0} bytes)")
if mp4.is_file():
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format",
         "-print_format", "json", str(mp4)],
        capture_output=True, text=True)
    (out / "ffprobe.json").write_text(p.stdout or p.stderr)
    need(p.returncode == 0, "ffprobe")
    try:
        info = json.loads(p.stdout)
        streams = info.get("streams") or []
        v = next((s for s in streams if s.get("codec_type") == "video"), None)
        a = next((s for s in streams if s.get("codec_type") == "audio"), None)
        need(v is not None, "video track")
        need(a is not None, "audio track")
        if v:
            w = int(v.get("width") or 0)
            h = int(v.get("height") or 0)
            need(abs(w - 1920) < 16 and abs(h - 1080) < 16, f"resolution {w}x{h}")
            codec = v.get("codec_name", "")
            need(codec in ("hevc", "h264"), f"video codec {codec}")
            print("video", codec, w, h, "fps", v.get("avg_frame_rate"),
                  "bit_rate", v.get("bit_rate") or (info.get("format") or {}).get("bit_rate"))
        if a:
            print("audio", a.get("codec_name"), a.get("sample_rate"), a.get("channels"))
            need(a.get("codec_name") in ("aac",), f"audio codec {a.get('codec_name')}")
        first_dur = float((info.get("format") or {}).get("duration") or 0)
        total_dur = 0.0
        for segment in segments:
            duration_probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(segment)],
                capture_output=True, text=True)
            if duration_probe.returncode == 0:
                total_dur += float(duration_probe.stdout.strip() or 0)
        need(total_dur >= 25, f"total segment duration {total_dur:.2f}s")
        print("first_segment_duration", first_dur, "total_segment_duration", total_dur)
    except Exception as e:
        need(False, f"ffprobe parse {e}")
logp = out / "xrr.txt"
log = logp.read_text(errors="replace") if logp.exists() else ""
need("FATAL EXCEPTION" not in log and "Fatal signal" not in log, "no fatal in XRRecorder log")
print("run_dir", out)
sys.exit(1 if fails else 0)
