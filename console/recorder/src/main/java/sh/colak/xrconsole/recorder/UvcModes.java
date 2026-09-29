package sh.colak.xrconsole.recorder;

import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbDeviceConnection;
import android.hardware.usb.UsbEndpoint;
import android.hardware.usb.UsbInterface;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

final class UvcModes {
    static final String TAG = "XRRecorder";
    static final String SDK_FIXED = "1920x1080@30 MJPEG (SDK fixed)";

    static final class Mode {
        final String format;
        final int width;
        final int height;
        final float fps;
        Mode(String format, int width, int height, float fps) {
            this.format = format;
            this.width = width;
            this.height = height;
            this.fps = fps;
        }
        JSONObject json() {
            JSONObject o = new JSONObject();
            try {
                o.put("format", format);
                o.put("width", width);
                o.put("height", height);
                o.put("fps", fps);
            } catch (Exception ignored) {}
            return o;
        }
        String label() {
            String fpsText = fps == (int) fps
                    ? String.valueOf((int) fps)
                    : String.format(Locale.US, "%.2f", fps);
            return width + "x" + height + "@" + fpsText + " " + format;
        }
    }

    static final class Result {
        final List<Mode> hardware = new ArrayList<>();
        final JSONArray interfaces = new JSONArray();
        String error = "";
        JSONObject json() {
            JSONObject o = new JSONObject();
            try {
                o.put("sdk_stream", SDK_FIXED);
                JSONArray modes = new JSONArray();
                for (Mode m : hardware) modes.put(m.json());
                o.put("uvc_frames", modes);
                o.put("usb_interfaces", interfaces);
                if (!error.isEmpty()) o.put("probe_error", error);
            } catch (Exception ignored) {}
            return o;
        }
        String summary() {
            Mode bestMjpeg = null;
            Mode bestAny = null;
            for (Mode m : hardware) {
                if (bestAny == null || better(m, bestAny)) bestAny = m;
                if ("MJPEG".equals(m.format) && (bestMjpeg == null || better(m, bestMjpeg))) bestMjpeg = m;
            }
            if (bestAny == null) return SDK_FIXED + " · UVC frames not advertised";
            boolean higher = bestAny.width * bestAny.height > 1920 * 1080
                    || (bestAny.width * bestAny.height == 1920 * 1080 && bestAny.fps > 30.5f);
            String extra = higher
                    ? ("UVC higher: " + bestAny.label())
                    : ("UVC max " + (bestMjpeg != null ? bestMjpeg.label() : bestAny.label()) + ", no 4K/60");
            return SDK_FIXED + " · " + extra;
        }

        private static boolean better(Mode a, Mode b) {
            long pa = (long) a.width * a.height;
            long pb = (long) b.width * b.height;
            if (pa != pb) return pa > pb;
            return a.fps > b.fps;
        }
    }

    static Result probe(UsbDevice device, UsbDeviceConnection conn) {
        Result r = new Result();
        if (device != null) dumpInterfaces(device, r);
        if (conn == null) {
            r.error = "no USB connection";
            return r;
        }
        try {
            byte[] cfg = readConfig(conn);
            if (cfg == null || cfg.length < 9) {
                r.error = "GET_DESCRIPTOR configuration failed";
                return r;
            }
            parseConfig(cfg, r);
        } catch (Exception e) {
            r.error = e.getMessage() != null ? e.getMessage() : "uvc probe failed";
            Log.w(TAG, "uvc probe", e);
        }
        Log.i(TAG, "camera modes: " + r.summary() + " uvc_frames=" + r.hardware.size());
        return r;
    }

    private static void dumpInterfaces(UsbDevice device, Result r) {
        for (int i = 0; i < device.getInterfaceCount(); i++) {
            UsbInterface in = device.getInterface(i);
            JSONObject o = new JSONObject();
            try {
                o.put("id", in.getId());
                o.put("class", in.getInterfaceClass());
                o.put("subclass", in.getInterfaceSubclass());
                o.put("protocol", in.getInterfaceProtocol());
                JSONArray eps = new JSONArray();
                for (int e = 0; e < in.getEndpointCount(); e++) {
                    UsbEndpoint ep = in.getEndpoint(e);
                    JSONObject p = new JSONObject();
                    p.put("addr", ep.getAddress());
                    p.put("type", ep.getType());
                    p.put("max_packet", ep.getMaxPacketSize());
                    p.put("dir_in", ep.getDirection() == android.hardware.usb.UsbConstants.USB_DIR_IN);
                    eps.put(p);
                }
                o.put("endpoints", eps);
            } catch (Exception ignored) {}
            r.interfaces.put(o);
        }
    }

    private static byte[] readConfig(UsbDeviceConnection conn) {
        byte[] head = new byte[9];
        int n = conn.controlTransfer(0x80, 6, 0x0200, 0, head, head.length, 1000);
        if (n < 9) return n > 0 ? java.util.Arrays.copyOf(head, n) : null;
        int total = (head[2] & 0xff) | ((head[3] & 0xff) << 8);
        if (total < 9) total = 9;
        if (total > 8192) total = 8192;
        byte[] cfg = new byte[total];
        n = conn.controlTransfer(0x80, 6, 0x0200, 0, cfg, cfg.length, 1000);
        if (n <= 0) return null;
        return n == cfg.length ? cfg : java.util.Arrays.copyOf(cfg, n);
    }

    private static void parseConfig(byte[] cfg, Result r) {
        String format = null;
        int off = 0;
        while (off + 2 <= cfg.length) {
            int len = cfg[off] & 0xff;
            if (len < 2 || off + len > cfg.length) break;
            int type = cfg[off + 1] & 0xff;
            if (type == 0x24 && len >= 3) {
                int subtype = cfg[off + 2] & 0xff;
                if (subtype == 0x04) format = "YUY2";
                else if (subtype == 0x06) format = "MJPEG";
                else if (subtype == 0x10) format = "FRAME";
                else if ((subtype == 0x05 || subtype == 0x07 || subtype == 0x11) && len >= 26) {
                    int w = u16(cfg, off + 5);
                    int h = u16(cfg, off + 7);
                    int interval = u32(cfg, off + 21);
                    if (w > 0 && h > 0) {
                        r.hardware.add(new Mode(format != null ? format : "UVC", w, h, fps(interval)));
                    }
                    int count = cfg[off + 25] & 0xff;
                    int p = off + 26;
                    for (int i = 0; i < count && p + 4 <= off + len; i++, p += 4) {
                        int extra = u32(cfg, p);
                        if (extra > 0 && extra != interval && w > 0 && h > 0) {
                            r.hardware.add(new Mode(format != null ? format : "UVC", w, h, fps(extra)));
                        }
                    }
                }
            }
            off += len;
        }
    }

    private static int u16(byte[] b, int i) {
        return (b[i] & 0xff) | ((b[i + 1] & 0xff) << 8);
    }

    private static int u32(byte[] b, int i) {
        return (b[i] & 0xff)
                | ((b[i + 1] & 0xff) << 8)
                | ((b[i + 2] & 0xff) << 16)
                | ((b[i + 3] & 0xff) << 24);
    }

    private static float fps(int interval100ns) {
        if (interval100ns <= 0) return 0;
        return 10_000_000f / interval100ns;
    }
}
