package sh.colak.xrconsole.recorder;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.TypedValue;
import android.view.Gravity;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class MainActivity extends Activity implements RecState.Listener {
    static final String ACTION_SMOKE = "sh.colak.xrconsole.recorder.SMOKE";
    private TextView rec, timer, rgb, mic, storage, err;
    private Button btn;
    private final Handler h = new Handler(Looper.getMainLooper());
    private long smokeSegMs = RecordEngine.DEFAULT_SEGMENT_MS;
    private long smokeDurMs;
    private boolean smoke;

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.BLACK);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.BLACK);
        int pad = dp(28);
        root.setPadding(pad, pad, pad, pad);
        root.setGravity(Gravity.CENTER_HORIZONTAL);

        rec = tv(42, 0xFFE11D48);
        rec.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        rec.setText("RECORD");
        root.addView(rec);

        timer = tv(36, Color.WHITE);
        timer.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        timer.setText("00:00:00");
        root.addView(timer);

        rgb = tv(18, 0xFFDDDDDD);
        mic = tv(18, 0xFFDDDDDD);
        storage = tv(18, 0xFFDDDDDD);
        err = tv(16, 0xFFFF6666);
        root.addView(rgb);
        root.addView(mic);
        root.addView(storage);
        root.addView(err);

        btn = new Button(this);
        btn.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, dp(64));
        lp.topMargin = dp(24);
        btn.setLayoutParams(lp);
        btn.setOnClickListener(v -> onToggle());
        root.addView(btn);

        setContentView(root);
        RecState.I.add(this);
        handleIntent(getIntent());
        render();
        h.post(tick);
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIntent(intent);
    }

    private void handleIntent(Intent intent) {
        if (intent == null) return;
        if (ACTION_SMOKE.equals(intent.getAction()) || intent.getBooleanExtra("auto_record", false)) {
            smoke = true;
            int segS = intent.getIntExtra("segment_s", 0);
            int durS = intent.getIntExtra("duration_s", 35);
            if (segS > 0) smokeSegMs = segS * 1000L;
            smokeDurMs = durS * 1000L;
            if (RecState.I.phase == RecState.Phase.IDLE || RecState.I.phase == RecState.Phase.ERROR) {
                tryStart(smokeSegMs, smokeDurMs);
            }
        }
    }

    private void onToggle() {
        RecState.Phase p = RecState.I.phase;
        if (p == RecState.Phase.RECORDING || p == RecState.Phase.STARTING) {
            RecordService.stop(this);
        } else {
            tryStart(RecordEngine.DEFAULT_SEGMENT_MS, 0);
        }
    }

    private void tryStart(long segMs, long durMs) {
        if (!hasPerms()) {
            requestPerms();
            return;
        }
        RecState.I.error = "";
        RecordService.start(this, segMs, durMs);
    }

    private boolean hasPerms() {
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) return false;
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) return false;
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            return false;
        }
        return true;
    }

    private void requestPerms() {
        java.util.ArrayList<String> p = new java.util.ArrayList<>();
        p.add(Manifest.permission.CAMERA);
        p.add(Manifest.permission.RECORD_AUDIO);
        if (Build.VERSION.SDK_INT >= 33) p.add(Manifest.permission.POST_NOTIFICATIONS);
        requestPermissions(p.toArray(new String[0]), 7);
    }

    @Override public void onRequestPermissionsResult(int code, String[] perms, int[] grant) {
        super.onRequestPermissionsResult(code, perms, grant);
        if (hasPerms()) {
            tryStart(smoke ? smokeSegMs : RecordEngine.DEFAULT_SEGMENT_MS, smoke ? smokeDurMs : 0);
        } else {
            RecState.I.fail("runtime permission denied");
            render();
        }
    }

    private final Runnable tick = new Runnable() {
        @Override public void run() {
            render();
            h.postDelayed(this, 250);
        }
    };

    @Override public void onRecState() { h.post(this::render); }

    private void render() {
        RecState st = RecState.I;
        boolean recOn = st.phase == RecState.Phase.RECORDING;
        rec.setText(recOn ? "● REC" : (st.phase == RecState.Phase.ERROR ? "ERROR" : st.phase.name()));
        rec.setTextColor(recOn || st.phase == RecState.Phase.ERROR ? 0xFFE11D48 : Color.WHITE);
        timer.setText(RecordService.formatDur(st.elapsedMs()));
        rgb.setText(st.rgbInfo);
        mic.setText("MIC " + st.micName);
        long mb = st.storageFreeBytes / (1024 * 1024);
        storage.setText(st.storageFreeBytes > 0 ? ("STORAGE " + mb + " MB free") : "STORAGE —");
        err.setText(st.error != null ? st.error : "");
        if (recOn || st.phase == RecState.Phase.STARTING || st.phase == RecState.Phase.STOPPING) {
            btn.setText("STOP");
        } else {
            btn.setText("RECORD");
        }
    }

    private TextView tv(int sp, int color) {
        TextView t = new TextView(this);
        t.setTextColor(color);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setGravity(Gravity.CENTER);
        t.setPadding(0, dp(6), 0, dp(6));
        return t;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    @Override protected void onDestroy() {
        RecState.I.remove(this);
        h.removeCallbacks(tick);
        super.onDestroy();
    }
}
