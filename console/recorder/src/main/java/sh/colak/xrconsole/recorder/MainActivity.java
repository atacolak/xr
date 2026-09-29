package sh.colak.xrconsole.recorder;

import android.Manifest;
import android.app.Activity;
import android.app.Dialog;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.hardware.usb.UsbManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.FrameLayout;
import android.widget.ImageButton;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.Spinner;
import android.widget.TextView;

public final class MainActivity extends Activity implements RecState.Listener {
    static final String ACTION_SMOKE = "sh.colak.xrconsole.recorder.SMOKE";
    static final String ACTION_STOP = "sh.colak.xrconsole.recorder.STOP";
    private TextView rec, timer, err, btn, cam;
    private ImageButton glassesBtn, gearBtn;
    private ImageView preview;
    private int actionW, actionH;
    private Dialog settings;
    private AudioDeviceMonitor audioMonitor;
    private GlassesMonitor glassesMonitor;
    private final Handler h = new Handler(Looper.getMainLooper());
    private long smokeSegMs = RecordEngine.DEFAULT_SEGMENT_MS;
    private long smokeDurMs;
    private boolean smoke;

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.BLACK);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);

        preview = RgbPreview.createView(this);
        preview.setLayoutParams(new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        root.addView(preview);

        View scrim = new View(this);
        scrim.setBackgroundResource(R.drawable.overlay_bottom);
        FrameLayout.LayoutParams scrimLp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(120));
        scrimLp.gravity = Gravity.BOTTOM;
        scrim.setLayoutParams(scrimLp);
        scrim.setClickable(false);
        scrim.setFocusable(false);
        root.addView(scrim);

        LinearLayout chrome = new LinearLayout(this);
        chrome.setOrientation(LinearLayout.HORIZONTAL);
        chrome.setGravity(Gravity.CENTER_VERTICAL);
        int pad = dp(12);
        chrome.setPadding(pad, 0, pad, pad);
        FrameLayout.LayoutParams chromeLp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        chromeLp.gravity = Gravity.BOTTOM;
        chrome.setLayoutParams(chromeLp);

        glassesBtn = iconButton(R.drawable.ic_glasses);
        glassesBtn.setContentDescription("Glasses");
        glassesBtn.setClickable(false);
        glassesBtn.setFocusable(false);

        LinearLayout center = new LinearLayout(this);
        center.setOrientation(LinearLayout.VERTICAL);
        center.setGravity(Gravity.CENTER_HORIZONTAL);
        LinearLayout.LayoutParams centerLp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        center.setLayoutParams(centerLp);

        rec = tv(14, 0xFFE11D48);
        rec.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        rec.setShadowLayer(6f, 0, 1, 0xCC000000);
        rec.setVisibility(View.GONE);

        timer = new TextView(this);
        timer.setTextColor(Color.WHITE);
        timer.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        timer.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        timer.setGravity(Gravity.CENTER);
        timer.setShadowLayer(6f, 0, 1, 0xCC000000);
        timer.setText("00:00:00");

        btn = actionButton();
        cam = tv(13, Color.WHITE);
        cam.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        cam.setShadowLayer(6f, 0, 1, 0xCC000000);
        cam.setPadding(dp(12), dp(6), dp(12), dp(6));
        cam.setOnClickListener(v -> cyclePreview());
        err = tv(13, 0xFFFF6666);
        err.setShadowLayer(6f, 0, 1, 0xCC000000);
        err.setVisibility(View.GONE);

        center.addView(rec);
        center.addView(timer);
        center.addView(btn);
        center.addView(cam);
        center.addView(err);

        gearBtn = iconButton(R.drawable.ic_gear);
        gearBtn.setContentDescription("Settings");
        gearBtn.setOnClickListener(v -> showSettings());

        chrome.addView(glassesBtn);
        chrome.addView(center);
        chrome.addView(gearBtn);
        root.addView(chrome);
        setContentView(root);

        RecState.I.add(this);
        audioMonitor = new AudioDeviceMonitor();
        glassesMonitor = new GlassesMonitor();
        refreshPresence();
        audioMonitor.start();
        glassesMonitor.start();
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
        refreshPresence();
        if (!RecState.I.cameraPresent) {
            RecState.I.fail("connect glasses RGB camera to record");
            render();
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

    private void showSettings() {
        if (settings != null && settings.isShowing()) {
            settings.dismiss();
            return;
        }
        java.util.List<MicrophoneDevices.Choice> choices = MicrophoneDevices.enumerate(this);
        MicrophoneDevices.Choice selected = MicrophoneDevices.selected(this, choices);
        RecState.I.micSelection = selected.label;

        Dialog d = new Dialog(this);
        d.setCanceledOnTouchOutside(true);
        if (d.getWindow() != null) {
            d.getWindow().setBackgroundDrawable(new ColorDrawable(0xFF161616));
        }

        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(20);
        body.setPadding(pad, pad, pad, pad);
        body.setMinimumWidth(dp(280));

        TextView title = tv(14, 0xFFAAAAAA);
        title.setText("DEVICES");
        title.setGravity(Gravity.START);
        body.addView(title);

        TextView micLabel = tv(13, 0xFF888888);
        micLabel.setText("Microphone");
        micLabel.setGravity(Gravity.START);
        micLabel.setPadding(0, dp(12), 0, dp(4));
        body.addView(micLabel);

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
        Spinner spinner = new Spinner(this);
        spinner.setMinimumHeight(dp(48));
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_item, labels) {
            @Override public View getView(int position, View convertView, ViewGroup parent) {
                TextView t = (TextView) super.getView(position, convertView, parent);
                t.setTextColor(Color.WHITE);
                t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
                t.setPadding(dp(4), dp(8), dp(4), dp(8));
                return t;
            }
            @Override public View getDropDownView(int position, View convertView, ViewGroup parent) {
                TextView t = (TextView) super.getDropDownView(position, convertView, parent);
                t.setTextColor(Color.WHITE);
                t.setBackgroundColor(0xFF222222);
                t.setPadding(dp(16), dp(12), dp(16), dp(12));
                return t;
            }
        };
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spinner.setAdapter(adapter);
        spinner.setSelection(selectedIndex, false);
        boolean idle = RecState.I.phase == RecState.Phase.IDLE || RecState.I.phase == RecState.Phase.ERROR;
        spinner.setEnabled(idle);
        spinner.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(android.widget.AdapterView<?> parent,
                                                  android.view.View view, int position, long id) {
                if (position < choices.size()) {
                    MicrophoneDevices.Choice choice = choices.get(position);
                    MicrophoneDevices.persist(MainActivity.this, choice);
                    RecState.I.micSelection = choice.label;
                }
            }
            @Override public void onNothingSelected(android.widget.AdapterView<?> parent) {}
        });
        body.addView(spinner);

        RecState st = RecState.I;
        TextView glasses = tv(14, st.cameraPresent ? 0xFF86EFAC : 0xFFF87171);
        glasses.setGravity(Gravity.START);
        glasses.setText(st.cameraPresent ? "Glasses RGB ready" : "Glasses RGB missing");
        glasses.setPadding(0, dp(16), 0, 0);
        body.addView(glasses);

        d.setContentView(body);
        settings = d;
        d.show();
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
                RecState.I.micSelection = MicrophoneDevices.selected(
                        MainActivity.this, MicrophoneDevices.enumerate(MainActivity.this)).label;
            }
        }

        @Override public void onAudioDevicesRemoved(android.media.AudioDeviceInfo[] removed) {
            if (RecState.I.phase == RecState.Phase.IDLE || RecState.I.phase == RecState.Phase.ERROR) {
                RecState.I.micSelection = MicrophoneDevices.selected(
                        MainActivity.this, MicrophoneDevices.enumerate(MainActivity.this)).label;
            }
        }
    }

    private final Runnable tick = new Runnable() {
        @Override public void run() {
            render();
            h.postDelayed(this, 250);
        }
    };

    @Override public void onRecState() {
        h.post(() -> {
            RgbPreview.sync(this);
            GrayPreview.sync(this);
            render();
        });
    }

    @Override protected void onResume() {
        super.onResume();
        refreshPresence();
        RgbPreview.attach(this, preview);
        GrayPreview.attach(this, preview);
        render();
    }

    @Override protected void onPause() {
        if (settings != null && settings.isShowing()) settings.dismiss();
        GrayPreview.detach();
        RgbPreview.detach();
        super.onPause();
    }

    private void cyclePreview() {
        RecState.I.previewSource = RecState.I.previewSource.next();
        RecState.I.grayInfo = "";
        RgbPreview.sync(this);
        GrayPreview.sync(this);
        render();
    }

    private void refreshPresence() {
        RecordEngine.applyPresence(new UsbHost(this, unusedUsb).presence());
    }

    private final UsbHost.Listener unusedUsb = new UsbHost.Listener() {
        @Override public void onUsbOpened(android.hardware.usb.UsbDevice device,
                                          android.hardware.usb.UsbDeviceConnection connection) {}
        @Override public void onUsbDenied(android.hardware.usb.UsbDevice device) {}
    };

    private final class GlassesMonitor extends BroadcastReceiver {
        private boolean registered;
        void start() {
            if (registered) return;
            IntentFilter f = new IntentFilter();
            f.addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED);
            f.addAction(UsbManager.ACTION_USB_DEVICE_DETACHED);
            if (Build.VERSION.SDK_INT >= 33) {
                registerReceiver(this, f, Context.RECEIVER_NOT_EXPORTED);
            } else {
                registerReceiver(this, f);
            }
            registered = true;
        }
        void stop() {
            if (!registered) return;
            try { unregisterReceiver(this); } catch (Exception ignored) {}
            registered = false;
        }
        @Override public void onReceive(Context context, Intent intent) {
            refreshPresence();
            RgbPreview.sync(MainActivity.this);
            GrayPreview.sync(MainActivity.this);
            render();
        }
    }

    private void render() {
        RecState st = RecState.I;
        boolean recOn = st.phase == RecState.Phase.RECORDING;
        boolean ready = st.cameraPresent;
        timer.setText(RecordService.formatDur(st.elapsedMs()));
        if (recOn) {
            rec.setVisibility(View.VISIBLE);
            rec.setText("● REC");
            rec.setTextColor(0xFFE11D48);
        } else if (st.phase == RecState.Phase.ERROR) {
            rec.setVisibility(View.VISIBLE);
            rec.setText("ERROR");
            rec.setTextColor(0xFFE11D48);
        } else if (st.phase == RecState.Phase.STARTING || st.phase == RecState.Phase.STOPPING) {
            rec.setVisibility(View.VISIBLE);
            rec.setText(st.phase.name());
            rec.setTextColor(Color.WHITE);
        } else {
            rec.setVisibility(View.GONE);
        }
        glassesBtn.setImageTintList(ColorStateList.valueOf(ready ? 0xFF86EFAC : 0xFF555555));
        glassesBtn.setAlpha(ready ? 1f : 0.5f);
        glassesBtn.setContentDescription(ready ? "Glasses connected" : "Glasses disconnected");
        cam.setText(st.previewSource.label);
        String gray = st.grayInfo == null ? "" : st.grayInfo;
        if (st.previewSource.isGray() && !gray.isEmpty()) {
            err.setText(gray);
        } else if (st.phase == RecState.Phase.IDLE && !ready) {
            err.setText("connect glasses to record");
        } else {
            err.setText(st.error != null ? st.error : "");
        }
        err.setVisibility(err.getText().length() == 0 ? View.GONE : View.VISIBLE);
        if (recOn || st.phase == RecState.Phase.STARTING || st.phase == RecState.Phase.STOPPING) {
            btn.setText("STOP");
            btn.setEnabled(st.phase != RecState.Phase.STOPPING);
            btn.setAlpha(1f);
        } else {
            btn.setText("RECORD");
            btn.setEnabled(ready && st.phase != RecState.Phase.STOPPING);
            btn.setAlpha(ready ? 1f : 0.35f);
        }
    }
    private TextView actionButton() {
        measureActionBox();
        TextView t = new TextView(this);
        t.setText("RECORD");
        t.setTextColor(Color.WHITE);
        t.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        t.setGravity(Gravity.CENTER);
        t.setShadowLayer(6f, 0, 1, 0xCC000000);
        t.setBackgroundColor(Color.TRANSPARENT);
        t.setPadding(0, dp(4), 0, dp(4));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(actionW, actionH);
        lp.gravity = Gravity.CENTER_HORIZONTAL;
        t.setLayoutParams(lp);
        t.setOnClickListener(v -> onToggle());
        return t;
    }

    private void measureActionBox() {
        Paint p = new Paint();
        p.setTypeface(Typeface.MONOSPACE);
        p.setTextSize(TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_SP, 22, getResources().getDisplayMetrics()));
        p.setFakeBoldText(true);
        Rect bounds = new Rect();
        int w = 0;
        int h = 0;
        for (String s : new String[] {"RECORD", "STOP", "STOPPING…"}) {
            p.getTextBounds(s, 0, s.length(), bounds);
            w = Math.max(w, bounds.width());
            h = Math.max(h, bounds.height());
        }
        actionW = w + dp(16);
        actionH = h + dp(16);
    }

    private ImageButton iconButton(int drawable) {
        ImageButton b = new ImageButton(this);
        b.setImageResource(drawable);
        b.setBackgroundColor(Color.TRANSPARENT);
        b.setPadding(dp(8), dp(8), dp(8), dp(8));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(40), dp(40));
        b.setLayoutParams(lp);
        b.setScaleType(ImageView.ScaleType.CENTER_INSIDE);
        b.setImageTintList(ColorStateList.valueOf(0xFFDDDDDD));
        return b;
    }

    private TextView tv(int sp, int color) {
        TextView t = new TextView(this);
        t.setTextColor(color);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setGravity(Gravity.CENTER);
        return t;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    @Override protected void onDestroy() {
        RecState.I.remove(this);
        if (settings != null && settings.isShowing()) settings.dismiss();
        GrayPreview.detach();
        RgbPreview.detach();
        if (audioMonitor != null) audioMonitor.stop();
        if (glassesMonitor != null) glassesMonitor.stop();
        h.removeCallbacks(tick);
        super.onDestroy();
    }
}
