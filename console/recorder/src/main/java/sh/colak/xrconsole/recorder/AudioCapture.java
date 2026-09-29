package sh.colak.xrconsole.recorder;

import android.content.Context;
import android.content.BroadcastReceiver;
import android.content.Intent;
import android.content.IntentFilter;
import android.media.AudioDeviceCallback;
import android.media.AudioDeviceInfo;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.AudioTimestamp;
import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaFormat;
import android.media.MediaRecorder;
import android.os.Build;
import android.util.Log;

import org.json.JSONObject;

import java.nio.ByteBuffer;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

final class AudioCapture {
    static final String TAG = "XRRecorder";
    static final int SAMPLE_RATE = 48000;
    static final int CHANNELS = 1;
    static final int BITRATE = 128_000;

    interface Sink {
        void onAudioFormat(MediaFormat format);
        void onAudioSample(ByteBuffer buf, MediaCodec.BufferInfo info);
        void onAudioError(String msg);
        void onMicChanged(JSONObject device);
    }

    private final Context ctx;
    private final Sink sink;
    private final long originMonoNs;
    private AudioRecord record;
    private MediaCodec codec;
    private Thread thread;
    private volatile boolean running;
    private AudioManager am;
    private final MicrophoneDevices.Choice requested;
    private JSONObject actual = new JSONObject();
    private volatile boolean explicitDisconnected;
    private long pcmSamples;
    private double pcmSumSquares;
    private int pcmPeak;
    private boolean legacySco;

    AudioCapture(Context ctx, Sink sink, long originMonoNs, MicrophoneDevices.Choice requested) {
        this.ctx = ctx.getApplicationContext();
        this.sink = sink;
        this.originMonoNs = originMonoNs;
        this.requested = requested;
    }

    synchronized void start() throws Exception {
        int min = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT);
        int buf = Math.max(min * 4, SAMPLE_RATE * 2); // ~1s 16-bit mono
        record = new AudioRecord.Builder()
                .setAudioSource(MediaRecorder.AudioSource.MIC)
                .setAudioFormat(new AudioFormat.Builder()
                        .setSampleRate(SAMPLE_RATE)
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                        .build())
                .setBufferSizeInBytes(buf)
                .build();
        if (record.getState() != AudioRecord.STATE_INITIALIZED) {
            throw new IllegalStateException("AudioRecord init failed");
        }
        if (!requested.isAuto()) {
            if (requested.device == null || !record.setPreferredDevice(requested.device)) {
                throw new IllegalStateException("microphone routing request rejected: " + requested.label);
            }
        }
        am = (AudioManager) ctx.getSystemService(Context.AUDIO_SERVICE);
        if (!requested.isAuto() && requested.device != null
                && requested.device.getType() == AudioDeviceInfo.TYPE_BLUETOOTH_SCO) {
            boolean communicationSet = Build.VERSION.SDK_INT >= 31
                    && am.setCommunicationDevice(requested.device);
            if (!communicationSet) {
                startLegacySco();
            }
        }
        codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_AAC);
        MediaFormat fmt = MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_AAC, SAMPLE_RATE, CHANNELS);
        fmt.setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC);
        fmt.setInteger(MediaFormat.KEY_BIT_RATE, BITRATE);
        fmt.setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 4096);
        codec.configure(fmt, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
        codec.start();
        running = true;
        record.startRecording();
        if (record.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) {
            throw new IllegalStateException("AudioRecord did not enter recording state");
        }
        describeRouted("start");
        if (!requested.isAuto() && !MicrophoneDevices.sameDevice(requested.identity, record.getRoutedDevice())) {
            throw new IllegalStateException("requested microphone did not become actual route");
        }
        if (am != null) {
            am.registerAudioDeviceCallback(cb, null);
        }
        thread = new Thread(this::loop, "xr-aac");
        thread.start();
    }

    private final AudioDeviceCallback cb = new AudioDeviceCallback() {
        @Override public void onAudioDevicesAdded(AudioDeviceInfo[] added) {
            describeRouted("devices_added");
        }

        @Override public void onAudioDevicesRemoved(AudioDeviceInfo[] removed) {
            if (!requested.isAuto() && removed != null) {
                for (AudioDeviceInfo d : removed) {
                    if (MicrophoneDevices.sameDevice(requested.identity, d)) {
                        explicitDisconnected = true;
                        sink.onAudioError("selected microphone disconnected: " + requested.label);
                        return;
                    }
                }
            }
            describeRouted("devices_removed");
        }
    };

    private void describeRouted(String reason) {
        try {
            AudioDeviceInfo d = record != null ? record.getRoutedDevice() : null;
            JSONObject o = d != null ? MicrophoneDevices.describe(d) : new JSONObject().put("product", "none");
            actual = o;
            String product = o.optString("product");
            RecState.I.micName = product.isEmpty() ? o.optString("type_name", "none") : product;
            sink.onMicChanged(audioState(reason));
        } catch (Exception e) {
            Log.w(TAG, "mic describe", e);
        }
    }

    private JSONObject audioState(String reason) {
        JSONObject o = new JSONObject();
        try {
            o.put("selection_mode", requested.isAuto() ? "auto" : "explicit");
            o.put("requested_device", requested.identity != null ? requested.identity : JSONObject.NULL);
            o.put("actual_routed_device", actual);
            o.put("route_matches_request", requested.isAuto()
                    || MicrophoneDevices.sameIdentity(requested.identity, actual));
        } catch (Exception ignored) {}
        return o;
    }

    static String typeName(int t) {
        switch (t) {
            case AudioDeviceInfo.TYPE_BUILTIN_MIC: return "builtin";
            case AudioDeviceInfo.TYPE_WIRED_HEADSET: return "wired_headset";
            case AudioDeviceInfo.TYPE_USB_DEVICE: return "usb";
            case AudioDeviceInfo.TYPE_USB_HEADSET: return "usb_headset";
            case AudioDeviceInfo.TYPE_BLUETOOTH_SCO: return "bt_sco";
            case AudioDeviceInfo.TYPE_BLE_HEADSET: return "ble_headset";
            case AudioDeviceInfo.TYPE_FM_TUNER: return "fm";
            default: return "type_" + t;
        }
    }

    JSONObject finalState() {
        JSONObject o = audioState(explicitDisconnected ? "disconnected" : "stop");
        try {
            o.put("pcm_samples", pcmSamples);
            o.put("pcm_peak", pcmPeak);
            o.put("pcm_rms", pcmSamples > 0 ? Math.sqrt(pcmSumSquares / pcmSamples) : 0);
        } catch (Exception ignored) {}
        return o;
    }

    private void loop() {
        byte[] pcm = new byte[2048];
        MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
        long frames = 0;
        try {
            while (running) {
                int n = record.read(pcm, 0, pcm.length);
                if (n < 0) {
                    sink.onAudioError("AudioRecord read " + n);
                    break;
                }
                if (n == 0) continue;
                measurePcm(pcm, n);
                long ptsUs;
                AudioTimestamp ts = new AudioTimestamp();
                if (record.getTimestamp(ts, AudioTimestamp.TIMEBASE_BOOTTIME) == AudioRecord.SUCCESS) {
                    ptsUs = (ts.nanoTime - originMonoNs) / 1000L;
                } else {
                    ptsUs = (frames * 1_000_000L) / SAMPLE_RATE;
                }
                frames += n / 2;
                int inIx = codec.dequeueInputBuffer(10_000);
                if (inIx >= 0) {
                    ByteBuffer in = codec.getInputBuffer(inIx);
                    if (in != null) {
                        in.clear();
                        int put = Math.min(n, in.remaining());
                        in.put(pcm, 0, put);
                        codec.queueInputBuffer(inIx, 0, put, Math.max(0, ptsUs), 0);
                    }
                }
                drain(info, false);
            }
        } catch (Exception e) {
            Log.e(TAG, "audio loop", e);
            sink.onAudioError("audio " + e.getMessage());
        } finally {
            try { drain(info, true); } catch (Exception ignored) {}
        }
    }

    private void measurePcm(byte[] pcm, int n) {
        for (int i = 0; i + 1 < n; i += 2) {
            int sample = (short) ((pcm[i] & 0xff) | (pcm[i + 1] << 8));
            int abs = Math.abs(sample);
            if (abs > pcmPeak) pcmPeak = abs;
            pcmSumSquares += (double) sample * sample;
            pcmSamples++;
        }
    }

    @SuppressWarnings("deprecation")
    private void startLegacySco() throws Exception {
        CountDownLatch connected = new CountDownLatch(1);
        BroadcastReceiver receiver = new BroadcastReceiver() {
            @Override public void onReceive(Context context, Intent intent) {
                if (intent != null
                        && intent.getIntExtra(AudioManager.EXTRA_SCO_AUDIO_STATE, -1)
                        == AudioManager.SCO_AUDIO_STATE_CONNECTED) {
                    connected.countDown();
                }
            }
        };
        ctx.registerReceiver(receiver,
                new IntentFilter(AudioManager.ACTION_SCO_AUDIO_STATE_UPDATED),
                Context.RECEIVER_NOT_EXPORTED);
        try {
            am.setMode(AudioManager.MODE_IN_COMMUNICATION);
            am.startBluetoothSco();
            if (!connected.await(5, TimeUnit.SECONDS)) {
                am.stopBluetoothSco();
                am.setMode(AudioManager.MODE_NORMAL);
                throw new IllegalStateException("Bluetooth SCO did not connect: " + requested.label);
            }
            legacySco = true;
        } finally {
            try { ctx.unregisterReceiver(receiver); } catch (Exception ignored) {}
        }
    }

    private void drain(MediaCodec.BufferInfo info, boolean eos) {
        if (eos) {
            int inIx = codec.dequeueInputBuffer(50_000);
            if (inIx >= 0) codec.queueInputBuffer(inIx, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM);
        }
        while (true) {
            int out = codec.dequeueOutputBuffer(info, eos ? 50_000 : 0);
            if (out == MediaCodec.INFO_TRY_AGAIN_LATER) break;
            if (out == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                sink.onAudioFormat(codec.getOutputFormat());
                continue;
            }
            if (out < 0) continue;
            ByteBuffer buf = codec.getOutputBuffer(out);
            if (buf != null && info.size > 0 && (info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
                buf.position(info.offset);
                buf.limit(info.offset + info.size);
                sink.onAudioSample(buf, info);
            }
            codec.releaseOutputBuffer(out, false);
            if ((info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) break;
        }
    }

    synchronized void stop() {
        running = false;
        Thread t = thread;
        thread = null;
        if (t != null) {
            try { t.join(1500); } catch (InterruptedException ignored) {}
        }
        if (!requested.isAuto() && requested.device != null
                && requested.device.getType() == AudioDeviceInfo.TYPE_BLUETOOTH_SCO) {
            try {
                if (legacySco && am != null) {
                    am.stopBluetoothSco();
                    am.setMode(AudioManager.MODE_NORMAL);
                } else if (Build.VERSION.SDK_INT >= 31 && am != null) {
                    am.clearCommunicationDevice();
                }
            } catch (Exception ignored) {}
        }
        try { if (am != null) am.unregisterAudioDeviceCallback(cb); } catch (Exception ignored) {}
        try { if (record != null) record.stop(); } catch (Exception ignored) {}
        try { if (record != null) record.release(); } catch (Exception ignored) {}
        record = null;
        try { if (codec != null) codec.stop(); } catch (Exception ignored) {}
        try { if (codec != null) codec.release(); } catch (Exception ignored) {}
        codec = null;
    }
}
