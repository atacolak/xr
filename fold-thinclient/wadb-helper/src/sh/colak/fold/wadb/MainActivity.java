package sh.colak.fold.wadb;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private TextView status;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, 20, getResources().getDisplayMetrics());
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("Fold Wireless Debugging");
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        root.addView(title);

        status = new TextView(this);
        status.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        status.setPadding(0, pad, 0, pad);
        root.addView(status, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        Button enable = new Button(this);
        enable.setText("Enable Wireless Debugging now");
        enable.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                Wadb.enable(MainActivity.this);
                startWatch();
                refresh();
            }
        });
        root.addView(enable);

        TextView help = new TextView(this);
        help.setPadding(0, pad, 0, 0);
        help.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        help.setText("One-time grant from a working Fold-local adb:\n\n"
                + "adb shell pm grant sh.colak.fold.wadb android.permission.WRITE_SECURE_SETTINGS\n\n"
                + "Then open this app once. On a previously allowed Wi-Fi, boot and reconnect re-enable Wireless Debugging. New networks still show Android's Allow dialog. This app does not scan ports or speak ADB.");
        root.addView(help);

        setContentView(root);
        startWatch();
        refresh();
    }

    @Override protected void onResume() { super.onResume(); refresh(); }

    private void startWatch() {
        Intent svc = new Intent(this, WadbService.class);
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(svc);
        else startService(svc);
    }

    private void refresh() {
        boolean perm = Wadb.canWrite(this);
        int val = Wadb.read(this);
        boolean wifi = Wadb.wifiUsable(this);
        status.setText("WRITE_SECURE_SETTINGS: " + (perm ? "granted" : "MISSING")
                + "\nadb_wifi_enabled: " + val
                + "\nWi-Fi usable: " + (wifi ? "yes" : "no"));
        status.setTextColor(perm ? Color.parseColor("#0B7A0B") : Color.parseColor("#B00020"));
    }
}
