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
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.Spinner;
import android.widget.TextView;

public final class MainActivity extends Activity implements RecState.Listener {
    static final String ACTION_SMOKE = "sh.colak.xrconsole.recorder.SMOKE";
    static final String ACTION_STOP = "sh.colak.xrconsole.recorder.STOP";
    private TextView rec, timer, rgb, mic, storage, err;
    private Spinner micSelector;
    private Button btn;
    private AudioDeviceMonitor audioMonitor;
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
        TextView micLabel = tv(14, 0xFFAAAAAA);
        micLabel.setText("MIC");
        micSelector = new Spinner(this);
        micSelector.setMinimumHeight(dp(56));
        storage = tv(18, 0xFFDDDDDD);
        err = tv(16, 0xFFFF6666);
        root.addView(rgb);
        root.addView(micLabel);
        root.addView(micSelector);
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
        audioMonitor = new AudioDeviceMonitor();
        refreshMicrophones();
        audioMonitor.start();
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
        if (ACTION_STOP.equals(intent.getAction())) {
            RecordService.stop(this);
            return;
        }
        if (ACTION_SMOKE.equals(intent.getAction()) || intent.getBooleanExtra("auto_record", false)) {
            smoke = true;
            String micProduct = intent.getStringExtra("mic_product");
            int micType = intent.getIntExtra("mic_type", -1);
            if ((micProduct != null && !micProduct.isEmpty()) || micType >= 0) {
                try {
                    MicrophoneDevices.Choice choice =
                            MicrophoneDevices.selectForSmoke(this, micProduct, micType);
                    RecState.I.micSelection = choice.label;
                    refreshMicrophones();
                } catch (Exception e) {
                    RecState.I.fail(e.getMessage());
                    return;
                }
            }
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
        if (p == RecState.Phase.RECORDING || p == RecState.Phase.STARTING
                || p == RecState.Phase.STOPPING) {
            btn.setEnabled(false);
            btn.setText("STOPPING…");
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

    private void refreshMicrophones() {
        java.util.List<MicrophoneDevices.Choice> choices = MicrophoneDevices.enumerate(this);
        MicrophoneDevices.Choice selected = MicrophoneDevices.selected(this, choices);
        java.util.ArrayList<String> labels = new java.util.ArrayList<>();
        int selectedIndex = -1;
        for (int i = 0; i < choices.size(); i++) {
            labels.add(choices.get(i).label);
            if (choices.get(i).key.equals(selected.key)) selectedIndex = i;
        }
        if (selectedIndex < 0) {
            choices.add(selected);
            labels.add(selected.label);
            selectedIndex = choices.size() - 1;
        }
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_dropdown_item, labels);
        micSelector.setAdapter(adapter);
        micSelector.setSelection(selectedIndex, false);
        micSelector.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(android.widget.AdapterView<?> parent,
                                                  android.view.View view, int position, long id) {
                if (position < choices.size()) {
                    MicrophoneDevices.Choice choice = choices.get(position);
                    MicrophoneDevices.persist(MainActivity.this, choice);
                    RecState.I.micSelection = choice.label;
                    render();
                }
            }
            @Override public void onNothingSelected(android.widget.AdapterView<?> parent) {}
        });
        RecState.I.micSelection = selected.label;
    }

    private final class AudioDeviceMonitor extends android.media.AudioDeviceCallback {
        private final android.media.AudioManager manager =
                (android.media.AudioManager) getSystemService(AUDIO_SERVICE);

        void start() {
            if (manager != null) manager.registerAudioDeviceCallback(this, h);
        }

        void stop() {
            if (manager != null) manager.unregisterAudioDeviceCallback(this);
        }

        @Override public void onAudioDevicesAdded(android.media.AudioDeviceInfo[] added) {
            if (RecState.I.phase == RecState.Phase.IDLE || RecState.I.phase == RecState.Phase.ERROR) {
                refreshMicrophones();
            }
        }

        @Override public void onAudioDevicesRemoved(android.media.AudioDeviceInfo[] removed) {
            if (RecState.I.phase == RecState.Phase.IDLE || RecState.I.phase == RecState.Phase.ERROR) {
                refreshMicrophones();
            }
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
        mic.setText("MIC selected: " + st.micSelection + "\nactual: " + st.micRoute);
        micSelector.setEnabled(st.phase == RecState.Phase.IDLE || st.phase == RecState.Phase.ERROR);
        long mb = st.storageFreeBytes / (1024 * 1024);
        storage.setText(st.storageFreeBytes > 0 ? ("STORAGE " + mb + " MB free") : "STORAGE —");
        err.setText(st.error != null ? st.error : "");
        if (recOn || st.phase == RecState.Phase.STARTING || st.phase == RecState.Phase.STOPPING) {
            btn.setText("STOP");
        } else {
            btn.setText("RECORD");
        }
        btn.setEnabled(st.phase != RecState.Phase.STOPPING);
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
        if (audioMonitor != null) audioMonitor.stop();
        h.removeCallbacks(tick);
        super.onDestroy();
    }
}
