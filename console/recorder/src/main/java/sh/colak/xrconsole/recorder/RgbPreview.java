package sh.colak.xrconsole.recorder;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbDeviceConnection;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import android.widget.ImageView;

final class RgbPreview implements NativeRgbCamera.Listener, UsbHost.Listener {
    static final String TAG = "XRRecorder";
    private static final long MIN_FRAME_MS = 80;
    private static final Object LOCK = new Object();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    private static volatile boolean wantFrames;
    private static volatile ImageView sink;
    private static volatile Bitmap shown;
    private static volatile long lastPreviewMs;
    private static RgbPreview idle;

    private final Context ctx;
    private UsbHost usb;
    private UsbDevice camDev;
    private UsbDeviceConnection camConn;
    private volatile boolean running;

    static ImageView createView(Context ctx) {
        ImageView v = new ImageView(ctx) {
            @Override protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
                int maxW = MeasureSpec.getSize(widthMeasureSpec);
                int maxH = MeasureSpec.getSize(heightMeasureSpec);
                if (MeasureSpec.getMode(widthMeasureSpec) == MeasureSpec.UNSPECIFIED) {
                    maxW = Integer.MAX_VALUE / 4;
                }
                if (MeasureSpec.getMode(heightMeasureSpec) == MeasureSpec.UNSPECIFIED) {
                    maxH = Integer.MAX_VALUE / 4;
                }
                if (maxW < 16) maxW = 16;
                if (maxH < 9) maxH = 9;
                int w;
                int h;
                if ((long) maxW * 9 <= (long) maxH * 16) {
                    w = maxW;
                    h = w * 9 / 16;
                } else {
                    h = maxH;
                    w = h * 16 / 9;
                }
                if (w < 1) w = 1;
                if (h < 1) h = 1;
                setMeasuredDimension(w, h);
            }
        };
        v.setBackgroundColor(0xFF111111);
        v.setScaleType(ImageView.ScaleType.CENTER_CROP);
        v.setAdjustViewBounds(false);
        v.setContentDescription("RGB camera");
        return v;
    }

    static void attach(Context ctx, ImageView view) {
        sink = view;
        wantFrames = true;
        sync(ctx);
    }

    static void detach() {
        wantFrames = false;
        sink = null;
        stopIdle();
        MAIN.post(() -> {
            Bitmap old = shown;
            shown = null;
            if (old != null) old.recycle();
        });
    }

    static void sync(Context ctx) {
        RecState.Phase p = RecState.I.phase;
        boolean recordOwns = p == RecState.Phase.STARTING
                || p == RecState.Phase.RECORDING
                || p == RecState.Phase.STOPPING;
        if (!wantFrames || recordOwns || !RecState.I.cameraPresent) {
            stopIdle();
            return;
        }
        startIdle(ctx);
    }

    static void releaseCamera() {
        stopIdle();
    }

    static void offerJpeg(byte[] jpeg, int width, int height) {
        if (!wantFrames || jpeg == null || jpeg.length == 0) return;
        ImageView v = sink;
        if (v == null) return;
        long now = SystemClock.elapsedRealtime();
        if (now - lastPreviewMs < MIN_FRAME_MS) return;
        lastPreviewMs = now;
        BitmapFactory.Options opts = new BitmapFactory.Options();
        opts.inPreferredConfig = Bitmap.Config.RGB_565;
        int sample = 1;
        int target = 480;
        while (width / (sample * 2) >= target && height / (sample * 2) >= target) sample *= 2;
        opts.inSampleSize = sample;
        Bitmap bmp;
        try {
            bmp = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, opts);
        } catch (Exception e) {
            return;
        }
        if (bmp == null) return;
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

    private static void startIdle(Context ctx) {
        RgbPreview session;
        synchronized (LOCK) {
            if (idle != null) return;
            idle = new RgbPreview(ctx.getApplicationContext());
            session = idle;
        }
        session.open();
    }

    private static void stopIdle() {
        RgbPreview session;
        synchronized (LOCK) {
            session = idle;
            idle = null;
        }
        if (session != null) session.close();
    }

    private RgbPreview(Context ctx) {
        this.ctx = ctx;
    }

    private void open() {
        try {
            if (!NativeRgbCamera.load()) {
                Log.w(TAG, "preview native load failed: " + NativeRgbCamera.loadError());
                return;
            }
            usb = new UsbHost(ctx, this);
            usb.register();
            camDev = usb.findCamera();
            if (camDev == null) {
                Log.i(TAG, "preview: no RGB camera");
                return;
            }
            running = true;
            usb.open(camDev);
        } catch (Exception e) {
            Log.w(TAG, "preview open", e);
            close();
        }
    }

    @Override public void onUsbOpened(UsbDevice device, UsbDeviceConnection connection) {
        if (!running || camDev == null || device.getDeviceId() != camDev.getDeviceId()) return;
        camConn = connection;
        UvcModes.Result modes = UvcModes.probe(device, connection);
        RecState.I.cameraModes = modes.summary();
        RecState.I.rgbInfo = "RGB " + modes.summary();
        RecState.I.ping();
        if (!NativeRgbCamera.nativeIsValidCamera(device.getVendorId(), device.getProductId())) {
            Log.w(TAG, "preview: SDK rejected " + UsbHost.describe(device));
            close();
            return;
        }
        if (!NativeRgbCamera.nativeCreate(device.getVendorId(), device.getProductId(),
                connection.getFileDescriptor(), this)) {
            Log.w(TAG, "preview nativeCreate failed");
            close();
            return;
        }
        int rc = NativeRgbCamera.nativeStart();
        if (rc != 0) {
            Log.w(TAG, "preview nativeStart rc=" + rc);
            close();
        } else {
            Log.i(TAG, "preview streaming " + UsbHost.describe(device));
        }
    }

    @Override public void onUsbDenied(UsbDevice device) {
        Log.w(TAG, "preview USB denied for " + UsbHost.describe(device));
        RecState.I.rgbInfo = "RGB USB permission needed";
        RecState.I.ping();
        close();
    }

    @Override public void onRgbFrame(byte[] jpeg, int width, int height, long sdkTsNs, int sequence, int format) {
        if (!running) return;
        RecState.I.width = width;
        RecState.I.height = height;
        offerJpeg(jpeg, width, height);
    }

    @Override public void onNativeError(String message) {
        Log.w(TAG, "preview native: " + message);
        close();
    }

    private void close() {
        running = false;
        try { NativeRgbCamera.nativeStop(); } catch (Throwable ignored) {}
        try { NativeRgbCamera.nativeDestroy(); } catch (Throwable ignored) {}
        try { if (camConn != null) camConn.close(); } catch (Exception ignored) {}
        camConn = null;
        try { if (usb != null) usb.release(); } catch (Exception ignored) {}
        usb = null;
        synchronized (LOCK) {
            if (idle == this) idle = null;
        }
    }
}
