package sh.colak.xrconsole.recorder;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbDeviceConnection;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import android.widget.ImageView;

final class GrayPreview implements NativeCarina.Listener, UsbHost.Listener {
    static final String TAG = "XRRecorder";
    private static final long MIN_FRAME_MS = 80;
    private static final Object LOCK = new Object();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    private static volatile boolean wantFrames;
    private static volatile ImageView sink;
    private static volatile Bitmap shown;
    private static volatile long lastPreviewMs;
    private static int[] pixels;
    private static GrayPreview idle;

    private final Context ctx;
    private UsbHost usb;
    private UsbDevice glassesDev;
    private UsbDeviceConnection glassesConn;
    private volatile boolean running;
    private volatile boolean waitingPerm;

    private final Runnable statsTick = new Runnable() {
        @Override public void run() {
            if (!running) return;
            int[] s = NativeCarina.nativeStats();
            if (s != null && s.length >= 4) {
                RecState.I.grayInfo = "cam=" + s[0] + " pose=" + s[1]
                        + " imu=" + s[2] + " vsync=" + s[3]
                        + " " + RecState.I.width + "x" + RecState.I.height;
                RecState.I.ping();
            }
            MAIN.postDelayed(this, 1000);
        }
    };

    static void attach(Context ctx, ImageView view) {
        sink = view;
        wantFrames = true;
        sync(ctx);
    }

    static void detach() {
        wantFrames = false;
        sink = null;
        GrayPreview session;
        synchronized (LOCK) { session = idle; }
        // USB permission dialog pauses the activity. Keep the application-context
        // receiver so the grant is not dropped; close if we were already streaming.
        if (session != null && session.waitingPerm) return;
        stopIdle();
    }

    static void sync(Context ctx) {
        if (!wantFrames || !RecState.I.previewSource.isGray() || !RecState.I.glassesPresent) {
            GrayPreview session;
            synchronized (LOCK) { session = idle; }
            if (session != null && session.waitingPerm && RecState.I.previewSource.isGray()) {
                return;
            }
            stopIdle();
            return;
        }
        startIdle(ctx);
    }

    static void release() {
        stopIdle();
    }

    private static void startIdle(Context ctx) {
        GrayPreview session;
        synchronized (LOCK) {
            if (idle != null) return;
            idle = new GrayPreview(ctx.getApplicationContext());
            session = idle;
        }
        session.open();
    }

    private static void stopIdle() {
        GrayPreview session;
        synchronized (LOCK) {
            session = idle;
            idle = null;
        }
        if (session != null) session.close();
    }

    private GrayPreview(Context ctx) {
        this.ctx = ctx;
    }

    private void open() {
        try {
            if (!NativeCarina.load()) {
                Log.w(TAG, "gray preview native load failed: " + NativeCarina.loadError());
                RecState.I.grayInfo = "Carina load failed";
                RecState.I.ping();
                return;
            }
            usb = new UsbHost(ctx, this);
            usb.register();
            glassesDev = usb.findGlasses();
            if (glassesDev == null) {
                Log.i(TAG, "gray preview: no glasses control USB");
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
            Log.w(TAG, "gray preview open", e);
            close();
        }
    }

    @Override public void onUsbOpened(UsbDevice device, UsbDeviceConnection connection) {
        waitingPerm = false;
        if (!running || glassesDev == null || device.getDeviceId() != glassesDev.getDeviceId()) return;
        glassesConn = connection;
        if (!NativeCarina.nativeCreate(device.getProductId(), connection.getFileDescriptor(), this)) {
            Log.w(TAG, "gray preview nativeCreate failed");
            RecState.I.grayInfo = "Carina create failed";
            RecState.I.ping();
            close();
            return;
        }
        int type = NativeCarina.nativeDeviceType();
        int rc = NativeCarina.nativeStart();
        if (rc != 0) {
            Log.w(TAG, "gray preview nativeStart rc=" + rc + " type=" + type);
            RecState.I.grayInfo = "Carina start rc=" + rc + " type=" + type;
            RecState.I.ping();
            close();
        } else {
            RecState.I.grayInfo = "Carina streaming type=" + type;
            RecState.I.ping();
            Log.i(TAG, "gray preview streaming " + UsbHost.describe(device) + " type=" + type);
            MAIN.post(statsTick);
        }
    }

    @Override public void onUsbDenied(UsbDevice device) {
        waitingPerm = false;
        Log.w(TAG, "gray preview USB denied for " + UsbHost.describe(device));
        RecState.I.grayInfo = "glasses USB permission needed";
        RecState.I.ping();
        close();
    }

    @Override public void onStereoFrame(byte[] left0, byte[] right0, byte[] left1, byte[] right1,
                                        double timestamp, int width, int height, int planeBytes) {
        if (!running) return;
        RecState.I.width = width;
        RecState.I.height = height;
        PreviewSource src = RecState.I.previewSource;
        byte[] plane = src == PreviewSource.GRAY_RIGHT
                ? firstNonEmpty(right0, right1, left0, left1)
                : firstNonEmpty(left0, left1, right0, right1);
        if (plane == null) return;
        offerGray(plane, width, height);
    }

    @Override public void onNativeError(String message) {
        Log.w(TAG, "gray preview native: " + message);
        RecState.I.grayInfo = message != null ? message : "Carina error";
        RecState.I.ping();
    }

    private static byte[] firstNonEmpty(byte[] a, byte[] b, byte[] c, byte[] d) {
        if (a != null && a.length > 0) return a;
        if (b != null && b.length > 0) return b;
        if (c != null && c.length > 0) return c;
        if (d != null && d.length > 0) return d;
        return null;
    }

    static void offerGray(byte[] gray, int width, int height) {
        if (!wantFrames || gray == null || gray.length == 0 || width <= 0 || height <= 0) return;
        ImageView v = sink;
        if (v == null) return;
        long now = SystemClock.elapsedRealtime();
        if (now - lastPreviewMs < MIN_FRAME_MS) return;
        lastPreviewMs = now;
        int n = width * height;
        if (gray.length < n) n = gray.length;
        int[] px = pixels;
        if (px == null || px.length < n) {
            px = new int[n];
            pixels = px;
        }
        for (int i = 0; i < n; i++) {
            int g = gray[i] & 0xff;
            px[i] = 0xFF000000 | (g << 16) | (g << 8) | g;
        }
        Bitmap bmp;
        try {
            bmp = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
            bmp.setPixels(px, 0, width, 0, 0, width, Math.min(height, n / width));
        } catch (Exception e) {
            return;
        }
        MAIN.post(() -> {
            ImageView view = sink;
            if (view == null || !wantFrames) {
                bmp.recycle();
                return;
            }
            Bitmap old = shown;
            shown = bmp;
            view.setImageBitmap(bmp);
            view.setBackgroundColor(Color.BLACK);
            if (old != null && old != bmp) old.recycle();
        });
    }

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
}
