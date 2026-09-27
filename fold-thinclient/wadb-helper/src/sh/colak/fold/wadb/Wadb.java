package sh.colak.fold.wadb;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.provider.Settings;
import android.util.Log;

final class Wadb {
    static final String TAG = "FoldWadb";
    static final String SETTING = "adb_wifi_enabled";

    static boolean canWrite(Context ctx) {
        return ctx.checkSelfPermission(Manifest.permission.WRITE_SECURE_SETTINGS)
                == PackageManager.PERMISSION_GRANTED;
    }

    static int read(Context ctx) {
        try {
            return Settings.Global.getInt(ctx.getContentResolver(), SETTING, 0);
        } catch (Exception e) {
            return -1;
        }
    }

    static boolean enable(Context ctx) {
        if (!canWrite(ctx)) {
            Log.w(TAG, "WRITE_SECURE_SETTINGS not granted");
            return false;
        }
        try {
            return Settings.Global.putInt(ctx.getContentResolver(), SETTING, 1);
        } catch (SecurityException e) {
            Log.e(TAG, "enable failed", e);
            return false;
        }
    }

    static boolean wifiUsable(Context ctx) {
        ConnectivityManager cm = ctx.getSystemService(ConnectivityManager.class);
        if (cm == null) return false;
        Network net = cm.getActiveNetwork();
        if (net == null) return false;
        NetworkCapabilities caps = cm.getNetworkCapabilities(net);
        return caps != null
                && caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
                && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
    }
}
