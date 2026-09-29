package sh.colak.xrconsole.recorder;

import android.content.ContentValues;
import android.content.Context;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.os.StatFs;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.FileInputStream;
import java.io.OutputStream;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

final class SessionStore {
    static final String TAG = "XRRecorder";
    final File dir;
    final File publicDir;
    final File fallbackDir;
    final String sessionId;
    final JSONObject session = new JSONObject();
    final JSONArray segments = new JSONArray();
    private OutputStreamWriter events;
    private final Object lock = new Object();

    SessionStore(Context ctx, String sessionId, File publicDir, File fallbackDir) {
        this.sessionId = sessionId;
        this.publicDir = publicDir;
        this.fallbackDir = fallbackDir;
        File chosen = fallbackDir;
        if (!mkdirs(fallbackDir)) {
            throw new IllegalStateException("app-specific recording path unavailable: " + fallbackDir);
        }
        // Capture into app-specific storage so an interrupted segment remains
        // recoverable. Finalized segments are copied to MediaStore for Gallery.
        this.dir = chosen;
        try {
            events = new OutputStreamWriter(new FileOutputStream(new File(dir, "events.jsonl"), true),
                    StandardCharsets.UTF_8);
        } catch (Exception e) {
            Log.e(TAG, "events.jsonl", e);
        }
    }

    static String newId() {
        SimpleDateFormat f = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US);
        f.setTimeZone(TimeZone.getDefault());
        return f.format(new Date());
    }

    static File publicRoot() {
        File movies = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MOVIES);
        return new File(new File(movies, "XRConsole"), "Recorder");
    }

    static File fallbackRoot(Context ctx) {
        File ext = ctx.getExternalFilesDir(Environment.DIRECTORY_MOVIES);
        if (ext == null) ext = ctx.getFilesDir();
        return new File(new File(ext, "XRConsole"), "Recorder");
    }

    static boolean mkdirs(File d) {
        if (d.exists()) return d.isDirectory() && d.canWrite();
        boolean ok = d.mkdirs();
        try { d.setReadable(true, false); d.setWritable(true, false); d.setExecutable(true, false); } catch (Exception ignored) {}
        return ok && d.isDirectory();
    }

    static long freeBytes(File d) {
        try {
            StatFs s = new StatFs(d.getAbsolutePath());
            return s.getAvailableBytes();
        } catch (Exception e) {
            return -1;
        }
    }

    File segmentFile(int index, long startMs) {
        SimpleDateFormat f = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US);
        String name = f.format(new Date(startMs)) + String.format(Locale.US, "_%03d.mp4", index);
        return new File(dir, name);
    }

    Uri publishVideo(Context ctx, File source) throws Exception {
        ContentValues values = new ContentValues();
        values.put(MediaStore.Video.Media.DISPLAY_NAME, source.getName());
        values.put(MediaStore.Video.Media.MIME_TYPE, "video/mp4");
        values.put(MediaStore.Video.Media.RELATIVE_PATH,
                Environment.DIRECTORY_MOVIES + "/XRConsole/Recorder");
        values.put(MediaStore.Video.Media.IS_PENDING, 1);
        Uri uri = ctx.getContentResolver().insert(
                MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values);
        if (uri == null) throw new IllegalStateException("MediaStore insert failed");
        boolean complete = false;
        try (FileInputStream in = new FileInputStream(source);
             OutputStream out = ctx.getContentResolver().openOutputStream(uri, "w")) {
            if (out == null) throw new IllegalStateException("MediaStore output unavailable");
            byte[] buffer = new byte[256 * 1024];
            int count;
            while ((count = in.read(buffer)) >= 0) {
                if (count > 0) out.write(buffer, 0, count);
            }
            complete = true;
        } finally {
            if (!complete) ctx.getContentResolver().delete(uri, null, null);
        }
        values.clear();
        values.put(MediaStore.Video.Media.IS_PENDING, 0);
        ctx.getContentResolver().update(uri, values, null, null);
        return uri;
    }

    void put(String key, Object value) {
        synchronized (lock) {
            try { session.put(key, value); } catch (Exception ignored) {}
        }
    }

    void event(String type, JSONObject extra) {
        synchronized (lock) {
            try {
                JSONObject o = extra != null ? extra : new JSONObject();
                o.put("type", type);
                o.put("t_utc", utcNow());
                o.put("t_mono_ns", android.os.SystemClock.elapsedRealtimeNanos());
                if (events != null) {
                    events.write(o.toString());
                    events.write("\n");
                    events.flush();
                }
            } catch (Exception e) {
                Log.w(TAG, "event " + type, e);
            }
        }
    }

    void addSegment(JSONObject seg) {
        synchronized (lock) {
            segments.put(seg);
            try { session.put("segments", segments); } catch (Exception ignored) {}
            flushSession();
        }
    }

    void flushSession() {
        synchronized (lock) {
            try {
                session.put("segments", segments);
                File f = new File(dir, "session.json");
                FileOutputStream out = new FileOutputStream(f);
                out.write(session.toString(2).getBytes(StandardCharsets.UTF_8));
                out.close();
                try { f.setReadable(true, false); } catch (Exception ignored) {}
            } catch (Exception e) {
                Log.e(TAG, "session.json", e);
            }
        }
    }

    void close() {
        synchronized (lock) {
            flushSession();
            try { if (events != null) events.close(); } catch (Exception ignored) {}
            events = null;
        }
    }

    static String utcNow() {
        SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US);
        f.setTimeZone(TimeZone.getTimeZone("UTC"));
        return f.format(new Date());
    }

    static JSONObject deviceInfo() {
        JSONObject o = new JSONObject();
        try {
            o.put("manufacturer", Build.MANUFACTURER);
            o.put("model", Build.MODEL);
            o.put("device", Build.DEVICE);
            o.put("product", Build.PRODUCT);
            o.put("android_release", Build.VERSION.RELEASE);
            o.put("sdk_int", Build.VERSION.SDK_INT);
            o.put("one_ui", System.getProperty("ro.build.version.oneui", ""));
            try {
                Class<?> sp = Class.forName("android.os.SystemProperties");
                java.lang.reflect.Method get = sp.getMethod("get", String.class, String.class);
                o.put("one_ui", get.invoke(null, "ro.build.version.oneui", ""));
                o.put("fingerprint_brand", get.invoke(null, "ro.product.brand", ""));
            } catch (Exception ignored) {}
        } catch (Exception ignored) {}
        return o;
    }
}
