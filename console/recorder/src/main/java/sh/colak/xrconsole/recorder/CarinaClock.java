package sh.colak.xrconsole.recorder;

import android.util.Log;

import java.util.ArrayDeque;
import java.util.Locale;

/** Rolling characterization of Carina callbacks. Not a View. */
final class CarinaClock {
    static final String TAG = "XRRecorder/Clock";
    private static final Object LOCK = new Object();
    private static final ArrayDeque<String> sdkLogs = new ArrayDeque<>();

    static long camN, poseN, imuN, vsyncN;
    static double camSdk, poseSdk, imuSdk, vsyncSdk;
    static double camDt, poseDt, imuDt, vsyncDt;
    static long camHost, poseHost, imuHost, vsyncHost;
    static long camHostDt, poseHostDt, imuHostDt, vsyncHostDt;
    static int w, h;
    static long l0ptr, r0ptr, l1ptr, r1ptr;
    static long l0hash, r0hash, l1hash, r1hash;
    static int l0n, r0n, l1n, r1n;
    static int l0eqL1, r0eqR1, l0eqR0, hashL0eqL1, hashR0eqR1;
    static int droppedRepeat;
    static long lastCamHashPair;
    static String lastSdkLog = "";

    static void reset() {
        synchronized (LOCK) {
            camN = poseN = imuN = vsyncN = 0;
            camSdk = poseSdk = imuSdk = vsyncSdk = 0;
            camDt = poseDt = imuDt = vsyncDt = 0;
            camHost = poseHost = imuHost = vsyncHost = 0;
            camHostDt = poseHostDt = imuHostDt = vsyncHostDt = 0;
            l0n = r0n = l1n = r1n = 0;
            l0eqL1 = r0eqR1 = l0eqR0 = hashL0eqL1 = hashR0eqR1 = 0;
            droppedRepeat = 0;
            lastCamHashPair = 0;
            sdkLogs.clear();
        }
    }

    static void onCamera(double sdk, long host, int width, int height,
                         byte[] l0, byte[] r0, byte[] l1, byte[] r1, long[] extras) {
        synchronized (LOCK) {
            if (camN > 0) {
                camDt = sdk - camSdk;
                camHostDt = host - camHost;
            }
            camN++;
            camSdk = sdk;
            camHost = host;
            w = width;
            h = height;
            l0n = l0 == null ? 0 : l0.length;
            r0n = r0 == null ? 0 : r0.length;
            l1n = l1 == null ? 0 : l1.length;
            r1n = r1 == null ? 0 : r1.length;
            if (extras != null && extras.length >= 8) {
                l0ptr = extras[0]; r0ptr = extras[1]; l1ptr = extras[2]; r1ptr = extras[3];
                l0hash = extras[4]; r0hash = extras[5]; l1hash = extras[6]; r1hash = extras[7];
                if (l0ptr != 0 && l0ptr == l1ptr) l0eqL1++;
                if (r0ptr != 0 && r0ptr == r1ptr) r0eqR1++;
                if (l0ptr != 0 && l0ptr == r0ptr) l0eqR0++;
                if (l1n > 0 && l0hash == l1hash) hashL0eqL1++;
                if (r1n > 0 && r0hash == r1hash) hashR0eqR1++;
                long pair = l0hash ^ (r0hash * 31);
                if (camN > 1 && pair == lastCamHashPair) droppedRepeat++;
                lastCamHashPair = pair;
            }
        }
    }

    static void onPose(double sdk, long host, float[] pose) {
        synchronized (LOCK) {
            if (poseN > 0) { poseDt = sdk - poseSdk; poseHostDt = host - poseHost; }
            poseN++; poseSdk = sdk; poseHost = host;
        }
    }

    static void onImu(double sdk, long host, float[] imu) {
        synchronized (LOCK) {
            if (imuN > 0) { imuDt = sdk - imuSdk; imuHostDt = host - imuHost; }
            imuN++; imuSdk = sdk; imuHost = host;
        }
    }

    static void onVsync(double sdk, long host) {
        synchronized (LOCK) {
            if (vsyncN > 0) { vsyncDt = sdk - vsyncSdk; vsyncHostDt = host - vsyncHost; }
            vsyncN++; vsyncSdk = sdk; vsyncHost = host;
        }
    }

    static void onSdkLog(int level, String tag, String message) {
        String line = level + " " + (tag == null ? "" : tag) + " " + (message == null ? "" : message);
        synchronized (LOCK) {
            lastSdkLog = line;
            sdkLogs.addLast(line);
            while (sdkLogs.size() > 64) sdkLogs.removeFirst();
        }
        if (message != null && message.toLowerCase(Locale.US).contains("calib")) {
            Log.i(TAG, "sdk calib: " + line);
        }
    }

    static String overlay() {
        synchronized (LOCK) {
            int[] st = NativeCarina.nativeStats();
            int cam = st != null && st.length > 0 ? st[0] : (int) camN;
            int pose = st != null && st.length > 1 ? st[1] : (int) poseN;
            int imu = st != null && st.length > 2 ? st[2] : (int) imuN;
            int vs = st != null && st.length > 3 ? st[3] : (int) vsyncN;
            return String.format(Locale.US,
                    "cam=%d pose=%d imu=%d vsync=%d %dx%d\n"
                            + "L0=%d R0=%d L1=%d R1=%d ptrL0=L1:%d R0=R1:%d\n"
                            + "sdk dt cam=%.4f pose=%.4f imu=%.5f vs=%.4f\n"
                            + "host dt ms cam=%.2f pose=%.2f imu=%.3f vs=%.2f",
                    cam, pose, imu, vs, w, h,
                    l0n, r0n, l1n, r1n, l0eqL1, r0eqR1,
                    camDt, poseDt, imuDt, vsyncDt,
                    camHostDt / 1e6, poseHostDt / 1e6, imuHostDt / 1e6, vsyncHostDt / 1e6);
        }
    }

    static String snapshotJson() {
        synchronized (LOCK) {
            return "{"
                    + "\"cam_n\":" + camN
                    + ",\"pose_n\":" + poseN
                    + ",\"imu_n\":" + imuN
                    + ",\"vsync_n\":" + vsyncN
                    + ",\"width\":" + w
                    + ",\"height\":" + h
                    + ",\"l0_bytes\":" + l0n
                    + ",\"r0_bytes\":" + r0n
                    + ",\"l1_bytes\":" + l1n
                    + ",\"r1_bytes\":" + r1n
                    + ",\"ptr_l0_eq_l1\":" + l0eqL1
                    + ",\"ptr_r0_eq_r1\":" + r0eqR1
                    + ",\"ptr_l0_eq_r0\":" + l0eqR0
                    + ",\"hash_l0_eq_l1\":" + hashL0eqL1
                    + ",\"hash_r0_eq_r1\":" + hashR0eqR1
                    + ",\"repeat_hash_pair\":" + droppedRepeat
                    + ",\"sdk_dt_cam\":" + camDt
                    + ",\"sdk_dt_pose\":" + poseDt
                    + ",\"sdk_dt_imu\":" + imuDt
                    + ",\"sdk_dt_vsync\":" + vsyncDt
                    + ",\"host_dt_ns_cam\":" + camHostDt
                    + ",\"host_dt_ns_pose\":" + poseHostDt
                    + ",\"host_dt_ns_imu\":" + imuHostDt
                    + ",\"host_dt_ns_vsync\":" + vsyncHostDt
                    + ",\"sdk_ts_cam\":" + camSdk
                    + ",\"sdk_ts_pose\":" + poseSdk
                    + ",\"sdk_ts_imu\":" + imuSdk
                    + ",\"sdk_ts_vsync\":" + vsyncSdk
                    + ",\"l0_ptr\":" + l0ptr
                    + ",\"r0_ptr\":" + r0ptr
                    + ",\"l1_ptr\":" + l1ptr
                    + ",\"r1_ptr\":" + r1ptr
                    + ",\"sn_hash\":\"" + (RecState.I.carinaSnHash == null ? "" : RecState.I.carinaSnHash) + "\""
                    + "}";
        }
    }

    static String[] sdkLogCopy() {
        synchronized (LOCK) { return sdkLogs.toArray(new String[0]); }
    }
}
