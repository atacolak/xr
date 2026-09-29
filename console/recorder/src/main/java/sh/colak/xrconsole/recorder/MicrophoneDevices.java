package sh.colak.xrconsole.recorder;

import android.content.Context;
import android.content.SharedPreferences;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.Objects;

final class MicrophoneDevices {
    static final String AUTO_KEY = "auto";
    private static final String PREFS = "recorder";
    private static final String PREF_MIC = "microphone_selector";

    static final class Choice {
        final String key;
        final String label;
        final AudioDeviceInfo device;
        final JSONObject identity;

        Choice(String key, String label, AudioDeviceInfo device, JSONObject identity) {
            this.key = key;
            this.label = label;
            this.device = device;
            this.identity = identity;
        }

        boolean isAuto() { return AUTO_KEY.equals(key); }
    }

    private MicrophoneDevices() {}

    static List<Choice> enumerate(Context ctx) {
        AudioManager am = (AudioManager) ctx.getSystemService(Context.AUDIO_SERVICE);
        List<Choice> out = new ArrayList<>();
        out.add(new Choice(AUTO_KEY, "Auto / System Default", null, null));
        if (am == null) return out;
        AudioDeviceInfo[] devices = am.getDevices(AudioManager.GET_DEVICES_INPUTS);
        Arrays.sort(devices, Comparator
                .comparing((AudioDeviceInfo d) -> AudioCapture.typeName(d.getType()))
                .thenComparing(d -> product(d).toLowerCase())
                .thenComparing(AudioDeviceInfo::getAddress));
        for (AudioDeviceInfo d : devices) {
            if (!d.isSource()) continue;
            JSONObject id = describe(d);
            String product = product(d);
            String type = displayType(d.getType());
            String label = product.isEmpty() ? type : product + " (" + type + ")";
            out.add(new Choice(key(id), label, d, id));
        }
        return out;
    }

    static Choice selected(Context ctx, List<Choice> choices) {
        String key = prefs(ctx).getString(PREF_MIC, AUTO_KEY);
        for (Choice c : choices) if (Objects.equals(c.key, key)) return c;
        if (AUTO_KEY.equals(key)) return choices.get(0);
        JSONObject saved = savedIdentity(ctx);
        return new Choice(key, unavailableLabel(saved), null, saved);
    }

    static Choice resolveForRecording(Context ctx) {
        Choice desired = selected(ctx, enumerate(ctx));
        if (desired.isAuto()) return desired;
        if (desired.device == null) {
            throw new IllegalStateException("selected microphone unavailable: " + desired.label);
        }
        return desired;
    }

    static void persist(Context ctx, Choice choice) {
        SharedPreferences.Editor e = prefs(ctx).edit().putString(PREF_MIC, choice.key);
        if (choice.identity == null) e.remove(PREF_MIC + "_identity");
        else e.putString(PREF_MIC + "_identity", choice.identity.toString());
        e.apply();
    }

    static JSONObject describe(AudioDeviceInfo d) {
        JSONObject o = new JSONObject();
        try {
            o.put("id", d.getId());
            o.put("type", d.getType());
            o.put("type_name", AudioCapture.typeName(d.getType()));
            o.put("product", product(d));
            o.put("address", d.getAddress());
            o.put("is_source", d.isSource());
            o.put("is_sink", d.isSink());
            o.put("channel_counts", array(d.getChannelCounts()));
            o.put("channel_index_masks", array(d.getChannelIndexMasks()));
            o.put("channel_masks", array(d.getChannelMasks()));
            o.put("sample_rates", array(d.getSampleRates()));
            o.put("encodings", array(d.getEncodings()));
        } catch (Exception ignored) {}
        return o;
    }

    static JSONArray enumerateJson(Context ctx) {
        JSONArray a = new JSONArray();
        for (Choice c : enumerate(ctx)) {
            if (!c.isAuto() && c.identity != null) a.put(c.identity);
        }
        return a;
    }

    static boolean sameDevice(JSONObject expected, AudioDeviceInfo actual) {
        if (expected == null || actual == null) return false;
        JSONObject got = describe(actual);
        return expected.optInt("type", -1) == got.optInt("type", -2)
                && expected.optString("product").equals(got.optString("product"))
                && stableAddress(expected.optString("address")).equals(stableAddress(got.optString("address")));
    }

    private static SharedPreferences prefs(Context ctx) {
        return ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private static JSONObject savedIdentity(Context ctx) {
        String raw = prefs(ctx).getString(PREF_MIC + "_identity", null);
        if (raw == null) return null;
        try { return new JSONObject(raw); } catch (Exception ignored) { return null; }
    }

    private static String key(JSONObject o) {
        return o.optInt("type", -1) + "|" + o.optString("product") + "|" + stableAddress(o.optString("address"));
    }

    private static String stableAddress(String address) {
        return address == null ? "" : address.trim();
    }

    private static String product(AudioDeviceInfo d) {
        CharSequence p = d.getProductName();
        return p == null ? "" : p.toString().trim();
    }

    private static String unavailableLabel(JSONObject o) {
        if (o == null) return "Selected microphone (unavailable)";
        String product = o.optString("product");
        String type = displayType(o.optInt("type"));
        return (product.isEmpty() ? type : product + " (" + type + ")") + " — unavailable";
    }

    private static String displayType(int type) {
        switch (type) {
            case AudioDeviceInfo.TYPE_BUILTIN_MIC: return "Built-in mic";
            case AudioDeviceInfo.TYPE_USB_DEVICE: return "USB";
            case AudioDeviceInfo.TYPE_USB_HEADSET: return "USB headset";
            case AudioDeviceInfo.TYPE_WIRED_HEADSET: return "Wired headset";
            case AudioDeviceInfo.TYPE_BLUETOOTH_SCO: return "Bluetooth SCO";
            case AudioDeviceInfo.TYPE_BLE_HEADSET: return "Bluetooth LE";
            default: return AudioCapture.typeName(type);
        }
    }

    private static JSONArray array(int[] values) {
        JSONArray a = new JSONArray();
        for (int v : values) a.put(v);
        return a;
    }
}
