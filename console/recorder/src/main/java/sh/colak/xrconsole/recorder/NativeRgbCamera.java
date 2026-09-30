package sh.colak.xrconsole.recorder;

import android.util.Log;

final class NativeRgbCamera {
    static final String TAG = "XRRecorder";
    static final int FORMAT_MJPEG = 0;
    static final int LUMA_ULTRA_PID = 0x1104;
    static final int CAMERA_VID_SONIX = 0x0C45;
    static final int CAMERA_PID_LUMA = 0x636B;

    interface Listener {
        void onRgbFrame(byte[] jpeg, int width, int height, long sdkTsNs, int sequence, int format);
        void onNativeError(String message);
    }

    private static boolean loaded;
    private static String loadError;
    private static String version = "";

    static synchronized boolean load() {
        if (loaded) return true;
        // libglasses dladdr-locates sibling libcarina_vio.so at load time.
        // UxSpace preloads cloud_protocol then carina_vio first; if we skip
        // that, RGB-first preview makes stereo cameras a silent no-op.
        loadOptional("cloud_protocol");
        loadOptional("carina_vio");
        try {
            System.loadLibrary("camera_bridge");
            version = nativeVersion();
            loaded = true;
            Log.i(TAG, "libglasses camera_bridge loaded sdk=" + version);
            return true;
        } catch (UnsatisfiedLinkError e) {
            loadError = e.getMessage();
            Log.e(TAG, "native load failed", e);
            return false;
        }
    }

    static void loadOptional(String name) {
        try {
            System.loadLibrary(name);
            Log.i(TAG, "loaded " + name);
        } catch (UnsatisfiedLinkError e) {
            Log.w(TAG, "optional native " + name + " missing: " + e.getMessage());
        }
    }

    static String sdkVersion() { return version; }
    static String loadError() { return loadError; }

    static native String nativeVersion();
    static native int nativeCameraVid(int glassesPid);
    static native int nativeCameraPid(int glassesPid);
    static native boolean nativeIsValidCamera(int vid, int pid);
    static native boolean nativeCreate(int vid, int pid, int fd, Listener listener);
    static native int nativeStart();
    static native int nativeStop();
    static native boolean nativeIsStreaming();
    static native void nativeDestroy();
}
