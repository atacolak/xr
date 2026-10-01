package sh.colak.xrconsole.recorder;

import android.content.Context;
import android.os.SystemClock;
import android.util.Log;

import org.json.JSONObject;

import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/** Lossless Carina sensor session. Distinct from RGB MP4 recording. */
final class SensorCapture implements CarinaSession.Sink {
    static final String TAG = "XRRecorder/Sensor";
    private static final Object LOCK = new Object();
    private static SensorCapture active;

    private final File dir;
    private final long t0Elapsed;
    private final long maxMs;
    private OutputStreamWriter camIndex;
    private BufferedOutputStream gray;
    private OutputStreamWriter poseOut;
    private BufferedOutputStream imuOut;
    private OutputStreamWriter vsyncOut;
    private long camSeq, poseSeq, imuSeq, vsyncSeq;
    private long grayBytes;
    private volatile boolean running;

    static boolean active() {
        synchronized (LOCK) { return active != null; }
    }

    static File start(Context ctx, long durationMs) throws Exception {
        synchronized (LOCK) {
            if (active != null) throw new IllegalStateException("sensor session already running");
            File root = new File(ctx.getExternalFilesDir(null), "Movies/XRConsole/Sensor");
            if (!root.isDirectory() && !root.mkdirs()) {
                throw new IllegalStateException("sensor dir " + root);
            }
            String name = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(new Date());
            File dir = new File(root, name);
            if (!dir.mkdirs()) throw new IllegalStateException("mkdir " + dir);
            SensorCapture cap = new SensorCapture(dir, durationMs);
            cap.open();
            active = cap;
            CarinaSession.addSink(cap);
            RecState.I.sensorSession = true;
            RecState.I.sessionDir = dir.getAbsolutePath();
            RecState.I.startedElapsedMs = SystemClock.elapsedRealtime();
            RecState.I.setPhase(RecState.Phase.RECORDING);
            Log.i(TAG, "sensor session " + dir);
            return dir;
        }
    }

    static void stop() {
        SensorCapture cap;
        synchronized (LOCK) {
            cap = active;
            active = null;
        }
        if (cap == null) return;
        CarinaSession.removeSink(cap);
        cap.close();
        RecState.I.sensorSession = false;
        RecState.I.setPhase(RecState.Phase.IDLE);
        RecState.I.startedElapsedMs = 0;
        RecState.I.ping();
    }

    private SensorCapture(File dir, long durationMs) {
        this.dir = dir;
        this.maxMs = durationMs > 0 ? durationMs : 30_000;
        this.t0Elapsed = SystemClock.elapsedRealtime();
    }

    private void open() throws Exception {
        camIndex = new OutputStreamWriter(new FileOutputStream(new File(dir, "camera.index.jsonl")), StandardCharsets.UTF_8);
        gray = new BufferedOutputStream(new FileOutputStream(new File(dir, "camera.gray8")), 1 << 20);
        poseOut = new OutputStreamWriter(new FileOutputStream(new File(dir, "pose.jsonl")), StandardCharsets.UTF_8);
        imuOut = new BufferedOutputStream(new FileOutputStream(new File(dir, "imu.bin")), 1 << 16);
        vsyncOut = new OutputStreamWriter(new FileOutputStream(new File(dir, "vsync.jsonl")), StandardCharsets.UTF_8);
        running = true;
        writeMeta(false);
    }

    private void writeMeta(boolean closed) {
        try {
            JSONObject o = new JSONObject();
            o.put("format", "xr-carina-sensor-v1");
            o.put("closed", closed);
            o.put("created", isoNow());
            o.put("sn_hash", RecState.I.carinaSnHash == null ? "" : RecState.I.carinaSnHash);
            o.put("width", RecState.I.width);
            o.put("height", RecState.I.height);
            o.put("preview_source", RecState.I.previewSource.label);
            o.put("clocks", new JSONObject(CarinaClock.snapshotJson()));
            o.put("cam_seq", camSeq);
            o.put("pose_seq", poseSeq);
            o.put("imu_seq", imuSeq);
            o.put("vsync_seq", vsyncSeq);
            o.put("gray_bytes", grayBytes);
            o.put("imu_record", "host_ns i64le, sdk_ts f64le, ax ay az gx gy gz f32le");
            o.put("camera_gray8", "concatenated 8-bit planes in camera.index.jsonl order");
            FileOutputStream fos = new FileOutputStream(new File(dir, "metadata.json"));
            fos.write(o.toString(2).getBytes(StandardCharsets.UTF_8));
            fos.close();
        } catch (Exception e) {
            Log.w(TAG, "metadata", e);
        }
    }

    @Override public void onCamera(byte[] l0, byte[] r0, byte[] l1, byte[] r1,
                                   double sdkTs, long hostNs, int w, int h, long[] extras) {
        if (!running) return;
        try {
            long off = grayBytes;
            int n0 = writePlane(l0);
            int n1 = writePlane(r0);
            int n2 = writePlane(l1);
            int n3 = writePlane(r1);
            JSONObject o = new JSONObject();
            o.put("seq", camSeq++);
            o.put("sdk_ts", sdkTs);
            o.put("host_ns", hostNs);
            o.put("w", w);
            o.put("h", h);
            o.put("off", off);
            o.put("l0", n0);
            o.put("r0", n1);
            o.put("l1", n2);
            o.put("r1", n3);
            if (extras != null && extras.length >= 8) {
                o.put("l0_ptr", extras[0]);
                o.put("r0_ptr", extras[1]);
                o.put("l1_ptr", extras[2]);
                o.put("r1_ptr", extras[3]);
                o.put("l0_hash", extras[4]);
                o.put("r0_hash", extras[5]);
                o.put("l1_hash", extras[6]);
                o.put("r1_hash", extras[7]);
            }
            camIndex.write(o.toString());
            camIndex.write("\n");
            RecState.I.frames = camSeq;
            RecState.I.bytesWritten = grayBytes;
            if (SystemClock.elapsedRealtime() - t0Elapsed >= maxMs) {
                MAIN_STOP();
            }
        } catch (Exception e) {
            Log.w(TAG, "camera write", e);
            MAIN_STOP();
        }
    }

    private int writePlane(byte[] p) throws Exception {
        if (p == null || p.length == 0) return 0;
        gray.write(p);
        grayBytes += p.length;
        return p.length;
    }

    @Override public void onPose(float[] pose, double sdkTs, long hostNs) {
        if (!running || pose == null) return;
        try {
            JSONObject o = new JSONObject();
            o.put("seq", poseSeq++);
            o.put("sdk_ts", sdkTs);
            o.put("host_ns", hostNs);
            o.put("p", pose[0]); o.put("y", pose.length > 1 ? pose[1] : 0);
            o.put("z", pose.length > 2 ? pose[2] : 0);
            o.put("qw", pose.length > 3 ? pose[3] : 0);
            o.put("qx", pose.length > 4 ? pose[4] : 0);
            o.put("qy", pose.length > 5 ? pose[5] : 0);
            o.put("qz", pose.length > 6 ? pose[6] : 0);
            poseOut.write(o.toString());
            poseOut.write("\n");
        } catch (Exception e) { Log.w(TAG, "pose write", e); }
    }

    @Override public void onImu(float[] imu, double sdkTs, long hostNs) {
        if (!running || imu == null || imu.length < 6) return;
        try {
            ByteBuffer b = ByteBuffer.allocate(40).order(ByteOrder.LITTLE_ENDIAN);
            b.putLong(hostNs);
            b.putDouble(sdkTs);
            for (int i = 0; i < 6; i++) b.putFloat(imu[i]);
            imuOut.write(b.array());
            imuSeq++;
        } catch (Exception e) { Log.w(TAG, "imu write", e); }
    }

    @Override public void onVsync(double sdkTs, long hostNs) {
        if (!running) return;
        try {
            JSONObject o = new JSONObject();
            o.put("seq", vsyncSeq++);
            o.put("sdk_ts", sdkTs);
            o.put("host_ns", hostNs);
            vsyncOut.write(o.toString());
            vsyncOut.write("\n");
        } catch (Exception e) { Log.w(TAG, "vsync write", e); }
    }

    private void close() {
        running = false;
        try { if (camIndex != null) camIndex.flush(); } catch (Exception ignored) {}
        try { if (gray != null) gray.flush(); } catch (Exception ignored) {}
        try { if (poseOut != null) poseOut.flush(); } catch (Exception ignored) {}
        try { if (imuOut != null) imuOut.flush(); } catch (Exception ignored) {}
        try { if (vsyncOut != null) vsyncOut.flush(); } catch (Exception ignored) {}
        writeMeta(true);
        try { if (camIndex != null) camIndex.close(); } catch (Exception ignored) {}
        try { if (gray != null) gray.close(); } catch (Exception ignored) {}
        try { if (poseOut != null) poseOut.close(); } catch (Exception ignored) {}
        try { if (imuOut != null) imuOut.close(); } catch (Exception ignored) {}
        try { if (vsyncOut != null) vsyncOut.close(); } catch (Exception ignored) {}
        Log.i(TAG, "sensor closed " + dir + " cam=" + camSeq + " grayB=" + grayBytes);
    }

    private static void MAIN_STOP() {
        android.os.Handler h = new android.os.Handler(android.os.Looper.getMainLooper());
        h.post(SensorCapture::stop);
    }

    private static String isoNow() {
        SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US);
        f.setTimeZone(TimeZone.getTimeZone("UTC"));
        return f.format(new Date());
    }
}
