package sh.colak.xrconsole.recorder;

import java.util.concurrent.CopyOnWriteArrayList;

final class RecState {
    enum Phase { IDLE, STARTING, RECORDING, STOPPING, ERROR }

    static final RecState I = new RecState();

    interface Listener { void onRecState(); }

    private final CopyOnWriteArrayList<Listener> listeners = new CopyOnWriteArrayList<>();
    volatile Phase phase = Phase.IDLE;
    volatile String error = "";
    volatile String sessionDir = "";
    volatile String lastMp4 = "";
    volatile String micName = "Auto / System Default";
    volatile String micSelection = "Auto / System Default";
    volatile String micRoute = "not recording";
    volatile String videoCodec = "";
    volatile String rgbInfo = "RGB —";
    volatile long startedElapsedMs;
    volatile long frames;
    volatile long dropped;
    volatile long bytesWritten;
    volatile int width;
    volatile int height;
    volatile float fps;
    volatile long storageFreeBytes;
    volatile boolean glassesPresent;
    volatile boolean cameraPresent;
    volatile String glassesStatus = "GLASSES —";
    volatile String cameraModes = "";

    void add(Listener l) { listeners.add(l); }
    void remove(Listener l) { listeners.remove(l); }

    synchronized void setPhase(Phase p) {
        phase = p;
        if (p != Phase.ERROR) error = "";
        ping();
    }

    synchronized void fail(String msg) {
        error = msg != null ? msg : "error";
        phase = Phase.ERROR;
        ping();
    }

    void ping() {
        for (Listener l : listeners) {
            try { l.onRecState(); } catch (Throwable ignored) {}
        }
    }

    long elapsedMs() {
        if (phase != Phase.RECORDING && phase != Phase.STOPPING) return 0;
        if (startedElapsedMs == 0) return 0;
        return android.os.SystemClock.elapsedRealtime() - startedElapsedMs;
    }
}
