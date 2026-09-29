package sh.colak.xrconsole.recorder;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbDeviceConnection;
import android.hardware.usb.UsbManager;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import android.media.MediaMuxer;
import android.os.Build;
import android.os.SystemClock;
import android.util.Log;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;

final class RecordEngine implements NativeRgbCamera.Listener, UsbHost.Listener, AudioCapture.Sink {
    static final String TAG = "XRRecorder";
    static final int TARGET_BITRATE = 12_000_000;
    static final int TARGET_FPS = 30;
    static final long DEFAULT_SEGMENT_MS = 12 * 60_000L;
    static final long LOW_STORAGE = 500L * 1024 * 1024;
    static final long FRAME_STALL_MS = 2500;

    static final class Frame {
        byte[] jpeg;
        int w, h, seq, format;
        long sdkTsNs, arrivalNs;
    }

    private final Context ctx;
    private final RecState st = RecState.I;
    private final ArrayBlockingQueue<Frame> q = new ArrayBlockingQueue<>(3);
    private UsbHost usb;
    private UsbDeviceConnection camConn;
    private UsbDevice camDev;
    private UsbDevice glassesDev;
    private SessionStore store;
    private AudioCapture audio;
    private MediaCodec video;
    private MediaMuxer muxer;
    private MediaFormat videoFmt;
    private MediaFormat audioFmt;
    private final Object muxLock = new Object();
    private int vTrack = -1, aTrack = -1;
    private boolean muxStarted;
    private boolean wantKeyframe;
    private boolean running;
    private Thread encodeThread;
    private Thread watchThread;
    private long originNs;
    private long originElapsedMs;
    private long segmentStartMs;
    private long segmentStartMonoNs;
    private long segmentBytes;
    private int segmentIndex;
    private long segmentMs = DEFAULT_SEGMENT_MS;
    private long autoStopAtElapsed;
    private File currentMp4;
    private long lastFrameElapsed;
    private long framesIn, framesEnc, dropped;
    private int[] argb;
    private byte[] nv12;
    private int encW, encH;
    private String codecMime = MediaFormat.MIMETYPE_VIDEO_HEVC;
    private volatile boolean stopRequested;
    private volatile String fatal;

    RecordEngine(Context ctx) {
        this.ctx = ctx.getApplicationContext();
    }

    synchronized void start(long segmentMs, long durationMs) throws Exception {
        if (running) return;
        this.segmentMs = segmentMs > 0 ? segmentMs : DEFAULT_SEGMENT_MS;
        this.autoStopAtElapsed = durationMs > 0
                ? SystemClock.elapsedRealtime() + durationMs : 0;
        stopRequested = false;
        fatal = null;
        st.setPhase(RecState.Phase.STARTING);
        if (!NativeRgbCamera.load()) {
            throw new IllegalStateException("native SDK load failed: " + NativeRgbCamera.loadError());
        }
        originNs = SystemClock.elapsedRealtimeNanos();
        originElapsedMs = SystemClock.elapsedRealtime();
        String id = SessionStore.newId();
        File pub = new File(SessionStore.publicRoot(), id);
        File fb = new File(SessionStore.fallbackRoot(ctx), id);
        store = new SessionStore(ctx, id, pub, fb);
        st.sessionDir = store.dir.getAbsolutePath();
        store.put("schema", 1);
        store.put("session_id", id);
        store.put("utc_start", SessionStore.utcNow());
        store.put("monotonic_origin_ns", originNs);
        store.put("device", SessionStore.deviceInfo());
        JSONObject glasses = new JSONObject();
        glasses.put("sdk_version", NativeRgbCamera.sdkVersion());
        glasses.put("model", "VITURE Luma Ultra");
        store.put("glasses", glasses);
        writePointer();
        usb = new UsbHost(ctx, this);
        usb.register();
        ctx.registerReceiver(detachRx, new IntentFilter(UsbManager.ACTION_USB_DEVICE_DETACHED));
        glassesDev = usb.findGlasses();
        st.glassesPresent = glassesDev != null;
        int gPid = glassesDev != null ? glassesDev.getProductId() : NativeRgbCamera.LUMA_ULTRA_PID;
        int camVid = NativeRgbCamera.nativeCameraVid(gPid);
        int camPid = NativeRgbCamera.nativeCameraPid(gPid);
        if (camVid == 0) camVid = NativeRgbCamera.CAMERA_VID_SONIX;
        if (camPid == 0) camPid = NativeRgbCamera.CAMERA_PID_LUMA;
        camDev = usb.findCamera(camVid, camPid);
        if (camDev == null) {
            throw new IllegalStateException("Luma RGB camera USB not found vid=0x"
                    + Integer.toHexString(camVid) + " pid=0x" + Integer.toHexString(camPid));
        }
        st.cameraPresent = true;
        boolean valid = NativeRgbCamera.nativeIsValidCamera(camDev.getVendorId(), camDev.getProductId());
        JSONObject rgbUsb = new JSONObject();
        rgbUsb.put("vid", String.format("0x%04X", camDev.getVendorId()));
        rgbUsb.put("pid", String.format("0x%04X", camDev.getProductId()));
        rgbUsb.put("device_name", camDev.getDeviceName());
        rgbUsb.put("sdk_valid_camera", valid);
        rgbUsb.put("source", "viture_luma_ultra_front_rgb");
        store.put("rgb_usb", rgbUsb);
        if (glassesDev != null) {
            JSONObject gUsb = new JSONObject();
            gUsb.put("vid", String.format("0x%04X", glassesDev.getVendorId()));
            gUsb.put("pid", String.format("0x%04X", glassesDev.getProductId()));
            glasses.put("control_usb", gUsb);
            store.put("glasses", glasses);
        }
        store.event("session_start", new JSONObject().put("camera", UsbHost.describe(camDev)));
        store.flushSession();
        running = true;
        encodeThread = new Thread(this::encodeLoop, "xr-hevc");
        encodeThread.start();
        watchThread = new Thread(this::watchLoop, "xr-watch");
        watchThread.start();
        usb.open(camDev);
    }

    @Override public void onUsbOpened(UsbDevice device, UsbDeviceConnection connection) {
        if (camDev == null || device.getDeviceId() != camDev.getDeviceId()) return;
        try {
            camConn = connection;
            int fd = connection.getFileDescriptor();
            if (!NativeRgbCamera.nativeIsValidCamera(device.getVendorId(), device.getProductId())) {
                fail("SDK rejected camera USB " + UsbHost.describe(device));
                return;
            }
            if (!NativeRgbCamera.nativeCreate(device.getVendorId(), device.getProductId(), fd, this)) {
                fail("xr_camera_provider_create failed");
                return;
            }
            int rc = NativeRgbCamera.nativeStart();
            if (rc != 0) {
                fail("xr_camera_provider_start rc=" + rc);
                return;
            }
            store.event("camera_open", new JSONObject()
                    .put("usb", UsbHost.describe(device))
                    .put("fd", fd)
                    .put("sdk_version", NativeRgbCamera.sdkVersion()));
            MicrophoneDevices.Choice requestedMic = MicrophoneDevices.resolveForRecording(ctx);
            st.micSelection = requestedMic.label;
            store.put("audio_inputs_at_start", MicrophoneDevices.enumerateJson(ctx));
            audio = new AudioCapture(ctx, this, originNs, requestedMic);
            audio.start();
            lastFrameElapsed = SystemClock.elapsedRealtime();
            Log.i(TAG, "RGB camera streaming " + UsbHost.describe(device));
        } catch (Exception e) {
            fail("camera open: " + e.getMessage());
        }
    }

    @Override public void onUsbDenied(UsbDevice device) {
        fail("USB permission denied for " + UsbHost.describe(device)
                + " — grant the system USB dialog");
    }

    @Override public void onRgbFrame(byte[] jpeg, int width, int height, long sdkTsNs, int sequence, int format) {
        if (!running || jpeg == null) return;
        Frame f = new Frame();
        f.jpeg = jpeg;
        f.w = width;
        f.h = height;
        f.sdkTsNs = sdkTsNs;
        f.seq = sequence;
        f.format = format;
        f.arrivalNs = SystemClock.elapsedRealtimeNanos();
        lastFrameElapsed = SystemClock.elapsedRealtime();
        framesIn++;
        if (!q.offer(f)) {
            dropped++;
            st.dropped = dropped;
        }
    }

    @Override public void onNativeError(String message) {
        fail("native: " + message);
    }

    private void encodeLoop() {
        MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
        BitmapFactory.Options opts = new BitmapFactory.Options();
        opts.inPreferredConfig = Bitmap.Config.ARGB_8888;
        try {
            while (running && fatal == null) {
                Frame f = q.poll(100, TimeUnit.MILLISECONDS);
                if (f == null) continue;
                if (video == null) {
                    openVideo(f);
                }
                Bitmap bmp = BitmapFactory.decodeByteArray(f.jpeg, 0, f.jpeg.length, opts);
                if (bmp == null) {
                    dropped++;
                    st.dropped = dropped;
                    continue;
                }
                int w = bmp.getWidth();
                int h = bmp.getHeight();
                if (w != encW || h != encH) {
                    bmp.recycle();
                    dropped++;
                    continue;
                }
                if (argb == null || argb.length != w * h) argb = new int[w * h];
                if (nv12 == null || nv12.length != Yuv.nv12Size(w, h)) nv12 = new byte[Yuv.nv12Size(w, h)];
                bmp.getPixels(argb, 0, w, 0, 0, w, h);
                bmp.recycle();
                Yuv.argbToNv12(argb, w, h, nv12);
                long ptsUs = Math.max(0, (f.arrivalNs - originNs) / 1000L);
                int inIx = video.dequeueInputBuffer(20_000);
                if (inIx < 0) {
                    dropped++;
                    st.dropped = dropped;
                } else {
                    ByteBuffer in = video.getInputBuffer(inIx);
                    if (in != null) {
                        in.clear();
                        in.put(nv12);
                        video.queueInputBuffer(inIx, 0, nv12.length, ptsUs, 0);
                    }
                }
                drainVideo(info, false);
                maybeRollover();
            }
            drainVideo(info, true);
        } catch (Exception e) {
            Log.e(TAG, "encode", e);
            fail("encoder: " + e.getMessage());
        }
    }

    private void openVideo(Frame first) throws Exception {
        encW = first.w > 0 ? first.w : 1920;
        encH = first.h > 0 ? first.h : 1080;
        if ((encW & 1) == 1) encW--;
        if ((encH & 1) == 1) encH--;
        Exception last = null;
        String[] mimes = {MediaFormat.MIMETYPE_VIDEO_HEVC, MediaFormat.MIMETYPE_VIDEO_AVC};
        for (String mime : mimes) {
            try {
                video = MediaCodec.createEncoderByType(mime);
                MediaFormat fmt = MediaFormat.createVideoFormat(mime, encW, encH);
                fmt.setInteger(MediaFormat.KEY_COLOR_FORMAT,
                        MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420SemiPlanar);
                fmt.setInteger(MediaFormat.KEY_BIT_RATE, TARGET_BITRATE);
                fmt.setInteger(MediaFormat.KEY_FRAME_RATE, TARGET_FPS);
                fmt.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1);
                fmt.setInteger(MediaFormat.KEY_OPERATING_RATE, TARGET_FPS);
                video.configure(fmt, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
                video.start();
                codecMime = mime;
                last = null;
                break;
            } catch (Exception e) {
                last = e;
                Log.w(TAG, "encoder " + mime + " failed", e);
                try { if (video != null) video.release(); } catch (Exception ignored) {}
                video = null;
            }
        }
        if (video == null) throw last != null ? last : new IllegalStateException("no video encoder");
        st.width = encW;
        st.height = encH;
        st.videoCodec = codecMime.contains("hevc") ? "hevc" : "avc";
        st.rgbInfo = "RGB " + encW + "x" + encH + "@" + TARGET_FPS;
        JSONObject v = new JSONObject();
        v.put("source", "viture_luma_ultra_front_rgb");
        v.put("input_format", first.format == NativeRgbCamera.FORMAT_MJPEG ? "mjpeg" : String.valueOf(first.format));
        v.put("width", encW);
        v.put("height", encH);
        v.put("fps_target", TARGET_FPS);
        v.put("codec", st.videoCodec);
        v.put("bitrate_target", TARGET_BITRATE);
        v.put("first_sdk_ts_ns", first.sdkTsNs);
        v.put("first_seq", first.seq);
        store.put("video", v);
        store.event("video_open", v);
        store.flushSession();
        Log.i(TAG, "video encoder " + codecMime + " " + encW + "x" + encH);
    }

    private void drainVideo(MediaCodec.BufferInfo info, boolean eos) {
        if (video == null) return;
        if (eos) {
            try {
                int inIx = video.dequeueInputBuffer(50_000);
                if (inIx >= 0) video.queueInputBuffer(inIx, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM);
            } catch (Exception ignored) {}
        }
        while (true) {
            int out = video.dequeueOutputBuffer(info, eos ? 40_000 : 0);
            if (out == MediaCodec.INFO_TRY_AGAIN_LATER) break;
            if (out == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                synchronized (muxLock) {
                    videoFmt = video.getOutputFormat();
                    tryStartMuxer();
                }
                continue;
            }
            if (out < 0) continue;
            ByteBuffer buf = video.getOutputBuffer(out);
            boolean config = (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) != 0;
            boolean key = (info.flags & MediaCodec.BUFFER_FLAG_KEY_FRAME) != 0;
            if (buf != null && info.size > 0 && !config) {
                buf.position(info.offset);
                buf.limit(info.offset + info.size);
                synchronized (muxLock) {
                    if (muxStarted) {
                        if (wantKeyframe && !key) {
                            // drop until next IDR so the new segment is independently playable
                        } else {
                            if (wantKeyframe && key) wantKeyframe = false;
                            muxer.writeSampleData(vTrack, buf, info);
                            segmentBytes += info.size;
                            st.bytesWritten += info.size;
                            framesEnc++;
                            st.frames = framesEnc;
                        }
                    }
                }
            }
            video.releaseOutputBuffer(out, false);
            if ((info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) break;
        }
    }

    private void tryStartMuxer() {
        if (muxStarted || videoFmt == null || audioFmt == null) return;
        openMuxerLocked();
        st.startedElapsedMs = originElapsedMs;
        st.setPhase(RecState.Phase.RECORDING);
        store.event("recording", new JSONObject());
    }

    private void openMuxerLocked() {
        try {
            long now = System.currentTimeMillis();
            currentMp4 = store.segmentFile(segmentIndex, now);
            muxer = new MediaMuxer(currentMp4.getAbsolutePath(), MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4);
            vTrack = muxer.addTrack(videoFmt);
            aTrack = muxer.addTrack(audioFmt);
            muxer.start();
            muxStarted = true;
            wantKeyframe = segmentIndex > 0;
            segmentStartMs = now;
            segmentStartMonoNs = SystemClock.elapsedRealtimeNanos();
            segmentBytes = 0;
            st.lastMp4 = currentMp4.getAbsolutePath();
            store.event("segment_start", new JSONObject()
                    .put("index", segmentIndex)
                    .put("path", currentMp4.getAbsolutePath()));
            Log.i(TAG, "segment " + segmentIndex + " " + currentMp4);
        } catch (Exception e) {
            fail("muxer: " + e.getMessage());
        }
    }

    private void closeMuxerLocked(String reason) {
        if (!muxStarted || muxer == null) return;
        File f = currentMp4;
        long bytes = segmentBytes;
        try { muxer.stop(); } catch (Exception e) { Log.w(TAG, "muxer stop", e); }
        try { muxer.release(); } catch (Exception ignored) {}
        muxer = null;
        muxStarted = false;
        vTrack = aTrack = -1;
        try {
            JSONObject seg = new JSONObject();
            seg.put("index", segmentIndex);
            seg.put("path", f != null ? f.getAbsolutePath() : "");
            seg.put("bytes", bytes);
            seg.put("utc_start", new java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'",
                    java.util.Locale.US) {{ setTimeZone(java.util.TimeZone.getTimeZone("UTC")); }}.format(new java.util.Date(segmentStartMs)));
            seg.put("monotonic_start_ns", segmentStartMonoNs);
            seg.put("monotonic_end_ns", SystemClock.elapsedRealtimeNanos());
            seg.put("close_reason", reason);
            if (f != null && f.exists()) {
                seg.put("bytes_on_disk", f.length());
                android.net.Uri galleryUri = store.publishVideo(ctx, f);
                seg.put("gallery_uri", galleryUri.toString());
                store.event("segment_published", new JSONObject()
                        .put("index", segmentIndex)
                        .put("uri", galleryUri.toString()));
            }
            store.addSegment(seg);
        } catch (Exception e) {
            Log.e(TAG, "segment publish", e);
            fail("Gallery publish: " + e.getMessage());
        }
        segmentIndex++;
    }

    private void maybeRollover() {
        if (!muxStarted) return;
        long elapsedSeg = SystemClock.elapsedRealtimeNanos() - segmentStartMonoNs;
        if (elapsedSeg < segmentMs * 1_000_000L) return;
        synchronized (muxLock) {
            if (!muxStarted) return;
            closeMuxerLocked("rollover");
            requestSync();
            openMuxerLocked();
        }
    }

    private void requestSync() {
        if (video == null) return;
        try {
            android.os.Bundle b = new android.os.Bundle();
            b.putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME, 0);
            video.setParameters(b);
            wantKeyframe = true;
        } catch (Exception ignored) {}
    }

    @Override public void onAudioFormat(MediaFormat format) {
        synchronized (muxLock) {
            audioFmt = format;
            tryStartMuxer();
        }
    }

    @Override public void onAudioSample(ByteBuffer buf, MediaCodec.BufferInfo info) {
        synchronized (muxLock) {
            if (!muxStarted || wantKeyframe && vTrack >= 0) {
                // still write audio after first video keyframe of the segment
            }
            if (muxStarted && aTrack >= 0) {
                try {
                    muxer.writeSampleData(aTrack, buf, info);
                    segmentBytes += info.size;
                    st.bytesWritten += info.size;
                } catch (Exception e) {
                    fail("audio mux " + e.getMessage());
                }
            }
        }
    }

    @Override public void onAudioError(String msg) {
        fail("microphone: " + msg);
    }

    @Override public void onMicChanged(JSONObject audioState) {
        try {
            JSONObject actual = audioState.optJSONObject("actual_routed_device");
            String product = actual != null ? actual.optString("product") : "";
            st.micRoute = product.isEmpty() && actual != null
                    ? actual.optString("type_name", "none") : product;
            JSONObject meta = new JSONObject()
                    .put("codec", "aac")
                    .put("sample_rate", AudioCapture.SAMPLE_RATE)
                    .put("channels", AudioCapture.CHANNELS)
                    .put("bitrate", AudioCapture.BITRATE)
                    .put("selection_mode", audioState.optString("selection_mode"))
                    .put("requested_device", audioState.opt("requested_device"))
                    .put("actual_routed_device", audioState.opt("actual_routed_device"))
                    .put("route_matches_request", audioState.optBoolean("route_matches_request"));
            store.put("audio", meta);
            store.event("mic_route", audioState);
            store.flushSession();
            RecState.I.ping();
        } catch (Exception ignored) {}
    }

    private void watchLoop() {
        while (running && fatal == null) {
            try { Thread.sleep(1000); } catch (InterruptedException e) { break; }
            long now = SystemClock.elapsedRealtime();
            if (st.phase == RecState.Phase.RECORDING && lastFrameElapsed > 0
                    && now - lastFrameElapsed > FRAME_STALL_MS) {
                fail("RGB stream stalled (" + (now - lastFrameElapsed) + "ms without frames)");
                break;
            }
            long free = SessionStore.freeBytes(store.dir);
            st.storageFreeBytes = free;
            if (free >= 0 && free < LOW_STORAGE) {
                fail("storage low: " + (free / (1024 * 1024)) + " MB free");
                break;
            }
            if (framesIn > 1) {
                float sec = Math.max(0.001f, (now - originElapsedMs) / 1000f);
                st.fps = framesIn / sec;
            }
            if (autoStopAtElapsed > 0 && now >= autoStopAtElapsed) {
                Log.i(TAG, "auto-stop");
                requestStop("auto");
                break;
            }
            RecState.I.ping();
        }
    }

    private final BroadcastReceiver detachRx = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            UsbDevice d = UsbHost.extraDevicePublic(intent);
            if (d == null) return;
            if (camDev != null && d.getDeviceId() == camDev.getDeviceId()) {
                store.event("usb_detach", new JSONObject());
                fail("glasses RGB camera disconnected");
            }
        }
    };

    synchronized void requestStop(String reason) {
        if (stopRequested) return;
        stopRequested = true;
        if (st.phase == RecState.Phase.RECORDING) st.setPhase(RecState.Phase.STOPPING);
        try { store.event("stop_requested", new JSONObject().put("reason", reason)); } catch (Exception ignored) {}
        running = false;
        q.clear();
        new Thread(this::stopNow, "xr-stop").start();
    }

    private void stopNow() {
        running = false;
        try { NativeRgbCamera.nativeStop(); } catch (Throwable ignored) {}
        try { NativeRgbCamera.nativeDestroy(); } catch (Throwable ignored) {}
        try { if (encodeThread != null) encodeThread.join(3000); } catch (Exception ignored) {}
        try { if (audio != null) audio.stop(); } catch (Throwable ignored) {}
        synchronized (muxLock) { closeMuxerLocked("stop"); }
        try { if (video != null) video.stop(); } catch (Exception ignored) {}
        try { if (video != null) video.release(); } catch (Exception ignored) {}
        video = null;
        try { if (camConn != null) camConn.close(); } catch (Exception ignored) {}
        camConn = null;
        try { ctx.unregisterReceiver(detachRx); } catch (Exception ignored) {}
        try { if (usb != null) usb.release(); } catch (Exception ignored) {}
        try {
            JSONObject stats = new JSONObject();
            stats.put("frames_in", framesIn);
            stats.put("frames_encoded", framesEnc);
            stats.put("dropped", dropped);
            stats.put("bytes", st.bytesWritten);
            long durMs = Math.max(1, SystemClock.elapsedRealtime() - originElapsedMs);
            stats.put("duration_ms", durMs);
            double mbMin = (st.bytesWritten / (1024.0 * 1024.0)) / (durMs / 60000.0);
            stats.put("mb_per_min", mbMin);
            stats.put("gb_per_hour", mbMin * 60.0 / 1024.0);
            stats.put("measured_fps", st.fps);
            store.put("stats", stats);
            store.event("session_end", stats);
        } catch (Exception ignored) {}
        try {
            if (audio != null) {
                JSONObject finalAudio = audio.finalState();
                JSONObject current = store.session.optJSONObject("audio");
                if (current == null) current = new JSONObject();
                current.put("selection_mode", finalAudio.optString("selection_mode"));
                current.put("requested_device", finalAudio.opt("requested_device"));
                current.put("actual_routed_device", finalAudio.opt("actual_routed_device"));
                current.put("route_matches_request", finalAudio.optBoolean("route_matches_request"));
                current.put("pcm_samples", finalAudio.optLong("pcm_samples"));
                current.put("pcm_peak", finalAudio.optInt("pcm_peak"));
                current.put("pcm_rms", finalAudio.optDouble("pcm_rms"));
                store.put("audio", current);
            }
        } catch (Exception ignored) {}
        if (store != null) store.close();
        if (fatal != null) st.fail(fatal);
        else st.setPhase(RecState.Phase.IDLE);
        st.ping();
        Log.i(TAG, "stopped dir=" + st.sessionDir + " last=" + st.lastMp4);
    }

    private void fail(String msg) {
        Log.e(TAG, msg);
        if (fatal != null) return;
        fatal = msg;
        try { store.event("error", new JSONObject().put("message", msg)); } catch (Exception ignored) {}
        st.fail(msg);
        running = false;
        if (!stopRequested) requestStop("error");
    }

    private void writePointer() {
        try {
            File p = new File(store.dir.getParentFile(), "current.txt");
            FileOutputStream o = new FileOutputStream(p);
            o.write((store.dir.getAbsolutePath() + "\n").getBytes(StandardCharsets.UTF_8));
            o.close();
            p.setReadable(true, false);
        } catch (Exception ignored) {}
        try {
            File p = new File(ctx.getFilesDir(), "current-session.txt");
            FileOutputStream o = new FileOutputStream(p);
            String s = store.dir.getAbsolutePath() + "\n" + store.sessionId + "\n";
            o.write(s.getBytes(StandardCharsets.UTF_8));
            o.close();
        } catch (Exception ignored) {}
    }
}
