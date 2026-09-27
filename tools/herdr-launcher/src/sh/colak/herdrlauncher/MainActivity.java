package sh.colak.herdrlauncher;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ComponentName;
import android.content.Intent;
import android.os.Bundle;
import android.widget.TextView;

/**
 * DeX-visible launcher entry. Play Store Termux (googleplay.2026.06.21)
 * has no RunCommandService. The supported external execute path is
 * TermuxFileReceiverActivity ACTION_SEND of a Patterns.WEB_URL string,
 * which runs ~/bin/termux-url-opener with that URL.
 */
public final class MainActivity extends Activity {
    static final String SENTINEL = "https://herdr.colak.sh/launch";
    static final String TERMUX = "com.termux";
    static final String RECEIVER = "com.termux.app.TermuxFileReceiverActivity";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Intent send = new Intent(Intent.ACTION_SEND);
        send.setComponent(new ComponentName(TERMUX, RECEIVER));
        send.setType("text/plain");
        send.putExtra(Intent.EXTRA_TEXT, SENTINEL);
        send.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            startActivity(send);
            finish();
        } catch (ActivityNotFoundException e) {
            TextView tv = new TextView(this);
            tv.setText("Termux FileReceiver is not available.\n"
                    + "Install Play Store Termux, then retry HERDR.\n\n"
                    + e);
            int pad = (int) (20 * getResources().getDisplayMetrics().density);
            tv.setPadding(pad, pad, pad, pad);
            setContentView(tv);
        }
    }
}
