package sh.colak.xrconsole.recorder;

import android.content.Context;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbDeviceConnection;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;

import java.io.File;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Owns the glasses-control USB session and Carina JNI.
 * Preview and sensor capture subscribe; they do not open USB themselves.
 */
final class CarinaSession implements NativeCarina.Listener, UsbHost.Listener {
    static final String TAG = "XRRecorder";
    private static final Object LOCK = new Object();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static CarinaSession idle;
    private static final CopyOnWriteArrayList<Sink> sinks = new CopyOnWriteArrayList<>();

    interface Sink {
        void onCamera(byte[] l0, byte[] r0, byte[] l1, byte[] r1,
                      double sdkTs, long hostNs, int w, int h, long[] extras);
        default void onPose(float[] pose, double sdkTs, long hostNs) {}
        default void onImu(float[] imu, double sdkTs, long hostNs) {}
        default void onVsync(double sdkTs, long hostNs) {}
        default void onCarinaError(String message) {}
    }

    private final Context ctx;
    private UsbHost usb;
    private UsbDevice glassesDev;
    private UsbDeviceConnection glassesConn;
    private volatile boolean running;
    private volatile boolean waitingPerm;
    private File cacheDir;

    static void removeSink(Sink s) { sinks.remove(s); }
    static void addSink(Sink s) {
        if (s != null && !sinks.contains(s)) sinks.add(s);
    }
    static boolean waitingPermission() {
        synchronized (LOCK) { return idle != null && idle.waitingPerm; }
    }

    static void ensure(Context ctx) {
        CarinaSession session;
        synchronized (LOCK) {
            if (idle != null) return;
            idle = new CarinaSession(ctx.getApplicationContext());
            session = idle;
        }
        session.open();
    }

    static void releaseIfIdle() {
        if (SensorCapture.active()) return;
        boolean wantGray = RecState.I.previewSource.isGray();
        if (wantGray) return;
        stop();
    }

    static void stop() {
        CarinaSession session;
        synchronized (LOCK) {
            session = idle;
            idle = null;
        }
        if (session != null) session.close();
    }

    private CarinaSession(Context ctx) { this.ctx = ctx; }

    private void open() {
        try {
            if (!NativeCarina.load()) {
                RecState.I.grayInfo = "Carina load failed";
                RecState.I.ping();
                return;
            }
            cacheDir = new File(ctx.getCacheDir(), "carina");
            if (!cacheDir.isDirectory() && !cacheDir.mkdirs()) {
                Log.w(TAG, "carina cache mkdir failed " + cacheDir);
            }
            usb = new UsbHost(ctx, this);
            usb.register();
            glassesDev = usb.findGlasses();
            if (glassesDev == null) {
                RecState.I.grayInfo = "glasses USB missing";
                RecState.I.ping();
                return;
            }
            running = true;
            if (!usb.hasPermission(glassesDev)) {
                waitingPerm = true;
                RecState.I.grayInfo = "glasses USB permission needed";
                RecState.I.ping();
            }
            usb.open(glassesDev);
        } catch (Exception e) {
            Log.w(TAG, "carina session open", e);
            close();
        }
    }

    @Override public void onUsbOpened(UsbDevice device, UsbDeviceConnection connection) {
        waitingPerm = false;
        if (!running || glassesDev == null || device.getDeviceId() != glassesDev.getDeviceId()) return;
        glassesConn = connection;
        String cache = cacheDir != null ? cacheDir.getAbsolutePath() : null;
        if (!NativeCarina.nativeCreate(device.getProductId(), connection.getFileDescriptor(), cache, this)) {
            RecState.I.grayInfo = "Carina create failed";
            RecState.I.ping();
            close();
            return;
        }
        int type = NativeCarina.nativeDeviceType();
        int rc = NativeCarina.nativeStart();
        if (rc != 0) {
            RecState.I.grayInfo = "Carina start rc=" + rc + " type=" + type;
            RecState.I.ping();
            close();
            return;
        }
        byte[] sn = NativeCarina.nativeSnHash();
        RecState.I.carinaSnHash = sn == null ? "" : hex(sn);
        RecState.I.grayInfo = "Carina type=" + type + " sn=" + shortSn();
        RecState.I.ping();
        Log.i(TAG, "carina session streaming " + UsbHost.describe(device)
                + " type=" + type + " cache=" + cache + " sn=" + RecState.I.carinaSnHash);
        MAIN.post(statsTick);
    }

    @Override public void onUsbDenied(UsbDevice device) {
        waitingPerm = false;
        RecState.I.grayInfo = "glasses USB permission needed";
        RecState.I.ping();
        close();
    }

    @Override public void onCameraFrame(byte[] l0, byte[] r0, byte[] l1, byte[] r1,
                                        double sdkTs, long hostNs, int w, int h, long[] extras) {
        if (!running) return;
        RecState.I.width = w;
        RecState.I.height = h;
        RecState.I.planePresent = planes(l0, r0, l1, r1);
        if (extras != null && extras.length >= 8) {
            RecState.I.planePtr = extras;
        }
        CarinaClock.onCamera(sdkTs, hostNs, w, h, l0, r0, l1, r1, extras);
        for (Sink s : sinks) {
            try { s.onCamera(l0, r0, l1, r1, sdkTs, hostNs, w, h, extras); }
            catch (Throwable t) { Log.w(TAG, "sink camera", t); }
        }
    }

    @Override public void onPose(float[] pose, double sdkTs, long hostNs) {
        CarinaClock.onPose(sdkTs, hostNs, pose);
        for (Sink s : sinks) {
            try { s.onPose(pose, sdkTs, hostNs); } catch (Throwable ignored) {}
        }
    }

    @Override public void onImu(float[] imu, double sdkTs, long hostNs) {
        CarinaClock.onImu(sdkTs, hostNs, imu);
        for (Sink s : sinks) {
            try { s.onImu(imu, sdkTs, hostNs); } catch (Throwable ignored) {}
        }
    }

    @Override public void onVsync(double sdkTs, long hostNs) {
        CarinaClock.onVsync(sdkTs, hostNs);
        for (Sink s : sinks) {
            try { s.onVsync(sdkTs, hostNs); } catch (Throwable ignored) {}
        }
    }

    @Override public void onNativeError(String message) {
        RecState.I.grayInfo = message != null ? message : "Carina error";
        RecState.I.ping();
        for (Sink s : sinks) {
            try { s.onCarinaError(RecState.I.grayInfo); } catch (Throwable ignored) {}
        }
    }

    @Override public void onSdkLog(int level, String tag, String message) {
        CarinaClock.onSdkLog(level, tag, message);
    }

    private final Runnable statsTick = new Runnable() {
        @Override public void run() {
            if (!running) return;
            RecState.I.grayInfo = CarinaClock.overlay();
            RecState.I.ping();
            MAIN.postDelayed(this, 1000);
        }
    };

    private void close() {
        running = false;
        waitingPerm = false;
        MAIN.removeCallbacks(statsTick);
        try { NativeCarina.nativeDestroy(); } catch (Throwable ignored) {}
        try { if (glassesConn != null) glassesConn.close(); } catch (Exception ignored) {}
        glassesConn = null;
        try { if (usb != null) usb.release(); } catch (Exception ignored) {}
        usb = null;
        synchronized (LOCK) {
            if (idle == this) idle = null;
        }
    }

    private static String planes(byte[] l0, byte[] r0, byte[] l1, byte[] r1) {
        return "L0=" + (l0 != null ? l0.length : 0)
                + " R0=" + (r0 != null ? r0.length : 0)
                + " L1=" + (l1 != null ? l1.length : 0)
                + " R1=" + (r1 != null ? r1.length : 0);
    }

    private static String hex(byte[] b) {
        StringBuilder sb = new StringBuilder(b.length * 2);
        for (byte v : b) sb.append(String.format("%02x", v));
        return sb.toString();
    }

    private static String shortSn() {
        String s = RecState.I.carinaSnHash;
        if (s == null || s.length() < 8) return "none";
        return s.substring(0, 8);
    }
}
