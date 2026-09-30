package sh.colak.xrconsole.recorder;

import android.util.Log;

final class NativeCarina {
    static final String TAG = "XRRecorder";

    interface Listener {
        void onStereoFrame(byte[] left0, byte[] right0, byte[] left1, byte[] right1,
                           double timestamp, int width, int height, int planeBytes);
        void onNativeError(String message);
    }

    private static boolean loaded;
    private static String loadError;

    static synchronized boolean load() {
        if (loaded) return true;
        NativeRgbCamera.loadOptional("cloud_protocol");
        NativeRgbCamera.loadOptional("carina_vio");
        if (!NativeRgbCamera.load()) {
            loadError = NativeRgbCamera.loadError();
            return false;
        }
        try {
            System.loadLibrary("carina_bridge");
            loaded = true;
            Log.i(TAG, "carina_bridge loaded");
            return true;
        } catch (UnsatisfiedLinkError e) {
            loadError = e.getMessage();
            Log.e(TAG, "carina native load failed", e);
            return false;
        }
    }

    static String loadError() { return loadError; }

    static native boolean nativeIsValidProduct(int pid);
    static native boolean nativeCreate(int pid, int fd, Listener listener);
    static native int nativeDeviceType();
    static native int nativeStart();
    static native void nativeDestroy();
    /** cam, pose, imu, vsync counts since nativeCreate. */
    static native int[] nativeStats();
}
