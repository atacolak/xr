package sh.colak.xrconsole.recorder;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import android.os.SystemClock;
import android.util.Log;

public final class RecordService extends Service implements RecState.Listener {
    static final String TAG = "XRRecorder";
    static final String ACTION_START = "sh.colak.xrconsole.recorder.START";
    static final String ACTION_STOP = "sh.colak.xrconsole.recorder.STOP";
    static final String EXTRA_SEGMENT_MS = "segment_ms";
    static final String EXTRA_DURATION_MS = "duration_ms";
    static final String CH = "xr-recorder";
    static final int NID = 42;

    private RecordEngine engine;
    private PowerManager.WakeLock wake;
    private final android.os.Handler h = new android.os.Handler(android.os.Looper.getMainLooper());

    static void start(Context ctx, long segmentMs, long durationMs) {
        Intent i = new Intent(ctx, RecordService.class);
        i.setAction(ACTION_START);
        i.putExtra(EXTRA_SEGMENT_MS, segmentMs);
        i.putExtra(EXTRA_DURATION_MS, durationMs);
        ctx.startForegroundService(i);
    }

    static void stop(Context ctx) {
        Intent i = new Intent(ctx, RecordService.class);
        i.setAction(ACTION_STOP);
        ctx.startService(i);
    }

    @Override public void onCreate() {
        super.onCreate();
        NotificationChannel ch = new NotificationChannel(CH,
                getString(R.string.channel_name), NotificationManager.IMPORTANCE_LOW);
        ch.setSound(null, null);
        getSystemService(NotificationManager.class).createNotificationChannel(ch);
        RecState.I.add(this);
        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        if (pm != null) {
            wake = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "xrrecorder:rec");
            wake.setReferenceCounted(false);
        }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent != null ? intent.getAction() : ACTION_START;
        if (ACTION_STOP.equals(action)) {
            if (engine != null) engine.requestStop("service");
            else stopSelf();
            return START_NOT_STICKY;
        }
        long seg = intent != null ? intent.getLongExtra(EXTRA_SEGMENT_MS, RecordEngine.DEFAULT_SEGMENT_MS) : RecordEngine.DEFAULT_SEGMENT_MS;
        long dur = intent != null ? intent.getLongExtra(EXTRA_DURATION_MS, 0) : 0;
        startFg();
        if (wake != null && !wake.isHeld()) wake.acquire();
        if (engine == null) {
            engine = new RecordEngine(this);
            new Thread(() -> {
                try {
                    engine.start(seg, dur);
                } catch (Exception e) {
                    Log.e(TAG, "start", e);
                    RecState.I.fail(e.getMessage());
                    stopSelf();
                }
            }, "xr-start").start();
        }
        h.post(tick);
        return START_NOT_STICKY;
    }

    private void startFg() {
        Notification n = buildNotif();
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NID, n,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA
                            | ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
        } else if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NID, n,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA
                            | ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
        } else {
            startForeground(NID, n);
        }
    }

    private Notification buildNotif() {
        RecState st = RecState.I;
        String title = st.phase == RecState.Phase.RECORDING ? "● REC" : st.phase.name();
        String dur = formatDur(st.elapsedMs());
        String text = dur + "  " + st.rgbInfo + "  MIC " + st.micName;
        if (st.phase == RecState.Phase.ERROR) text = st.error;
        Intent stop = new Intent(this, RecordService.class).setAction(ACTION_STOP);
        PendingIntent piStop = PendingIntent.getService(this, 1, stop, PendingIntent.FLAG_IMMUTABLE);
        PendingIntent piAct = PendingIntent.getActivity(this, 0,
                new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder b = new Notification.Builder(this, CH)
                .setSmallIcon(R.drawable.ic_tile)
                .setContentTitle(title)
                .setContentText(text)
                .setOngoing(st.phase == RecState.Phase.RECORDING || st.phase == RecState.Phase.STARTING)
                .setOnlyAlertOnce(true)
                .setContentIntent(piAct)
                .addAction(new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(this, R.drawable.ic_tile), "STOP", piStop).build());
        if (st.phase == RecState.Phase.RECORDING) {
            b.setUsesChronometer(true).setWhen(System.currentTimeMillis() - st.elapsedMs());
        }
        return b.build();
    }

    static String formatDur(long ms) {
        long s = Math.max(0, ms / 1000);
        long h = s / 3600;
        long m = (s % 3600) / 60;
        long sec = s % 60;
        return String.format(java.util.Locale.US, "%02d:%02d:%02d", h, m, sec);
    }

    private final Runnable tick = new Runnable() {
        @Override public void run() {
            if (RecState.I.phase == RecState.Phase.IDLE && engine != null
                    && RecState.I.error.isEmpty()) {
                stopSelf();
                return;
            }
            try {
                getSystemService(NotificationManager.class).notify(NID, buildNotif());
            } catch (Exception ignored) {}
            if (RecState.I.phase == RecState.Phase.RECORDING
                    || RecState.I.phase == RecState.Phase.STARTING
                    || RecState.I.phase == RecState.Phase.STOPPING) {
                h.postDelayed(this, 1000);
            }
        }
    };

    @Override public void onRecState() {
        h.post(() -> {
            try { getSystemService(NotificationManager.class).notify(NID, buildNotif()); } catch (Exception ignored) {}
            if (RecState.I.phase == RecState.Phase.IDLE || RecState.I.phase == RecState.Phase.ERROR) {
                if (RecState.I.phase == RecState.Phase.IDLE) stopSelf();
            }
        });
    }

    @Override public void onDestroy() {
        RecState.I.remove(this);
        h.removeCallbacks(tick);
        if (engine != null) {
            engine.requestStop("destroy");
            engine = null;
        }
        if (wake != null && wake.isHeld()) wake.release();
        stopForeground(STOP_FOREGROUND_REMOVE);
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
