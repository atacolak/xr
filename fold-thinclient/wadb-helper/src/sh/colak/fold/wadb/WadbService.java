package sh.colak.fold.wadb;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.os.IBinder;
import android.util.Log;

public final class WadbService extends Service {
    private static final String CHANNEL = "wadb";
    private ConnectivityManager.NetworkCallback callback;

    @Override
    public void onCreate() {
        super.onCreate();
        ensureChannel();
        startForeground(1, notification("Watching Wi-Fi for Wireless Debugging"));
        Wadb.enable(this);
        ConnectivityManager cm = getSystemService(ConnectivityManager.class);
        if (cm == null) return;
        callback = new ConnectivityManager.NetworkCallback() {
            @Override public void onAvailable(Network network) { tryEnable("available"); }
            @Override public void onCapabilitiesChanged(Network network, NetworkCapabilities caps) {
                if (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) tryEnable("wifi-caps");
            }
            @Override public void onLost(Network network) { Log.i(Wadb.TAG, "network lost"); }
        };
        NetworkRequest req = new NetworkRequest.Builder()
                .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
                .build();
        cm.registerNetworkCallback(req, callback);
        if (Wadb.wifiUsable(this)) tryEnable("already-wifi");
    }

    private void tryEnable(String why) {
        boolean ok = Wadb.enable(this);
        Log.i(Wadb.TAG, "enable via " + why + " ok=" + ok + " value=" + Wadb.read(this));
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm != null) {
            nm.notify(1, notification(ok
                    ? ("Wireless Debugging requested (" + why + ")")
                    : "Need WRITE_SECURE_SETTINGS grant"));
        }
    }

    private void ensureChannel() {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm == null) return;
        NotificationChannel ch = new NotificationChannel(
                CHANNEL, getString(R.string.channel_name), NotificationManager.IMPORTANCE_MIN);
        ch.setShowBadge(false);
        nm.createNotificationChannel(ch);
    }

    private Notification notification(String text) {
        PendingIntent pi = PendingIntent.getActivity(
                this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL)
                .setContentTitle(getString(R.string.app_name))
                .setContentText(text)
                .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
                .setContentIntent(pi)
                .setOngoing(true)
                .build();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        Wadb.enable(this);
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        ConnectivityManager cm = getSystemService(ConnectivityManager.class);
        if (cm != null && callback != null) {
            try { cm.unregisterNetworkCallback(callback); } catch (Exception ignored) {}
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
