package sh.colak.xrconsole.recorder;

import android.util.Log;

final class NativeCarina {
    static final String TAG = "XRRecorder";

    interface Listener {
        void onCameraFrame(byte[] left0, byte[] right0, byte[] left1, byte[] right1,
                           double sdkTs, long hostNs, int width, int height, long[] extras);
        void onPose(float[] pose, double sdkTs, long hostNs);
        void onImu(float[] imu, double sdkTs, long hostNs);
        void onVsync(double sdkTs, long hostNs);
        void onNativeError(String message);
        void onSdkLog(int level, String tag, String message);
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
    static native boolean nativeCreate(int pid, int fd, String cacheDir, Listener listener);
    static native int nativeDeviceType();
    static native int nativeStart();
    static native int nativeSetExposure(boolean autoExp, float ms, int gain);
    static native byte[] nativeSnHash();
    static native void nativeDestroy();
    static native int[] nativeStats();
    /** last,dt for cam/pose/imu/vsync sdk timestamps. */
    static native double[] nativeClock();
}
