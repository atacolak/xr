package sh.colak.xrconsole.recorder;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.widget.ImageView;

final class GrayPreview implements CarinaSession.Sink {
    private static final long MIN_FRAME_MS = 80;
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static volatile boolean wantFrames;
    private static volatile ImageView sink;
    private static volatile Bitmap shown;
    private static volatile long lastPreviewMs;
    private static int[] pixels;
    private static final GrayPreview INSTANCE = new GrayPreview();

    static void attach(Context ctx, ImageView view) {
        sink = view;
        wantFrames = true;
        sync(ctx);
    }

    static void detach() {
        wantFrames = false;
        sink = null;
        if (CarinaSession.waitingPermission()) return;
        CarinaSession.removeSink(INSTANCE);
        CarinaSession.releaseIfIdle();
    }

    static void sync(Context ctx) {
        if (!wantFrames || !RecState.I.previewSource.isGray() || !RecState.I.glassesPresent) {
            if (CarinaSession.waitingPermission() && RecState.I.previewSource.isGray()) return;
            CarinaSession.removeSink(INSTANCE);
            CarinaSession.releaseIfIdle();
            return;
        }
        CarinaSession.addSink(INSTANCE);
        CarinaSession.ensure(ctx);
    }

    static void release() {
        CarinaSession.removeSink(INSTANCE);
        CarinaSession.releaseIfIdle();
    }

    @Override public void onCamera(byte[] l0, byte[] r0, byte[] l1, byte[] r1,
                                   double sdkTs, long hostNs, int w, int h, long[] extras) {
        PreviewSource src = RecState.I.previewSource;
        if (src.isStereo()) {
            byte[] left = firstNonEmpty(l0, l1);
            byte[] right = firstNonEmpty(r0, r1);
            if (left == null && right == null) return;
            offerStereo(left, right, w, h);
            return;
        }
        byte[] plane = src == PreviewSource.GRAY_RIGHT ? firstNonEmpty(r0, r1) : firstNonEmpty(l0, l1);
        if (plane == null) return;
        offerGray(plane, w, h);
    }

    private static byte[] firstNonEmpty(byte[] a, byte[] b) {
        if (a != null && a.length > 0) return a;
        if (b != null && b.length > 0) return b;
        return null;
    }

    static void offerGray(byte[] gray, int width, int height) {
        if (!wantFrames || gray == null || gray.length == 0 || width <= 0 || height <= 0) return;
        if (sink == null) return;
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
        postBitmap(px, width, Math.min(height, n / Math.max(width, 1)));
    }

    static void offerStereo(byte[] left, byte[] right, int width, int height) {
        if (!wantFrames || width <= 0 || height <= 0) return;
        if (sink == null) return;
        long now = SystemClock.elapsedRealtime();
        if (now - lastPreviewMs < MIN_FRAME_MS) return;
        lastPreviewMs = now;
        int dstW = width * 2;
        int n = dstW * height;
        int[] px = pixels;
        if (px == null || px.length < n) {
            px = new int[n];
            pixels = px;
        }
        for (int y = 0; y < height; y++) {
            int src = y * width;
            int dst = y * dstW;
            for (int x = 0; x < width; x++) {
                int li = src + x;
                int gl = (left != null && li < left.length) ? (left[li] & 0xff) : 0;
                int gr = (right != null && li < right.length) ? (right[li] & 0xff) : 0;
                px[dst + x] = 0xFF000000 | (gl << 16) | (gl << 8) | gl;
                px[dst + width + x] = 0xFF000000 | (gr << 16) | (gr << 8) | gr;
            }
        }
        postBitmap(px, dstW, height);
    }

    private static void postBitmap(int[] px, int width, int height) {
        if (width <= 0 || height <= 0) return;
        Bitmap bmp;
        try {
            bmp = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
            bmp.setPixels(px, 0, width, 0, 0, width, height);
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
            view.setScaleType(ImageView.ScaleType.FIT_CENTER);
            view.setImageBitmap(bmp);
            view.setBackgroundColor(Color.BLACK);
            if (old != null && old != bmp) old.recycle();
        });
    }
}
