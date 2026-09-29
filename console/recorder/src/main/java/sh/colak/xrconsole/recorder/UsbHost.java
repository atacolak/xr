package sh.colak.xrconsole.recorder;

import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbDeviceConnection;
import android.hardware.usb.UsbManager;
import android.os.Build;
import android.util.Log;

import java.util.ArrayList;
import java.util.List;

final class UsbHost {
    static final String TAG = "XRRecorder";
    static final String ACTION_PERM = "sh.colak.xrconsole.recorder.USB_PERMISSION";
    static final int VITURE_VID = 0x35CA;
    static final int CAMERA_VID = 0x0C45;
    static final int[] GLASSES_PIDS = {0x1104, 0x1102, 0x1101};

    interface Listener {
        void onUsbOpened(UsbDevice device, UsbDeviceConnection connection);
        void onUsbDenied(UsbDevice device);
    }

    private final Context context;
    private final UsbManager usb;
    private final Listener listener;
    private boolean registered;

    UsbHost(Context context, Listener listener) {
        this.context = context.getApplicationContext();
        this.listener = listener;
        this.usb = (UsbManager) this.context.getSystemService(Context.USB_SERVICE);
    }

    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override public void onReceive(Context ctx, Intent intent) {
            if (intent == null || !ACTION_PERM.equals(intent.getAction())) return;
            UsbDevice device = extraDevice(intent);
            if (device == null) return;
            boolean granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false);
            UsbDeviceConnection conn = granted ? usb.openDevice(device) : null;
            if (conn != null) listener.onUsbOpened(device, conn);
            else listener.onUsbDenied(device);
        }
    };

    void register() {
        if (registered) return;
        IntentFilter f = new IntentFilter(ACTION_PERM);
        if (Build.VERSION.SDK_INT >= 33) {
            context.registerReceiver(receiver, f, Context.RECEIVER_NOT_EXPORTED);
        } else {
            context.registerReceiver(receiver, f);
        }
        registered = true;
    }

    void release() {
        if (!registered) return;
        try { context.unregisterReceiver(receiver); } catch (Exception ignored) {}
        registered = false;
    }

    List<UsbDevice> all() {
        return new ArrayList<>(usb.getDeviceList().values());
    }

    UsbDevice findGlasses() {
        UsbDevice preferred = null;
        for (UsbDevice d : usb.getDeviceList().values()) {
            if (!isGlassesControl(d)) continue;
            if (d.getProductId() == NativeRgbCamera.LUMA_ULTRA_PID) return d;
            if (preferred == null) preferred = d;
        }
        return preferred;
    }

    UsbDevice findCamera() {
        for (UsbDevice d : usb.getDeviceList().values()) {
            if (isRgbCamera(d)) return d;
        }
        return null;
    }

    UsbDevice findCamera(int vid, int pid) {
        for (UsbDevice d : usb.getDeviceList().values()) {
            if (d.getVendorId() == vid && d.getProductId() == pid) return d;
        }
        return findCamera();
    }

    Presence presence() {
        UsbDevice glasses = findGlasses();
        UsbDevice camera = findCamera();
        return new Presence(glasses, camera);
    }

    static final class Presence {
        final UsbDevice glasses;
        final UsbDevice camera;
        Presence(UsbDevice glasses, UsbDevice camera) {
            this.glasses = glasses;
            this.camera = camera;
        }
        boolean ready() { return camera != null; }
        boolean glassesOnly() { return glasses != null && camera == null; }
    }

    static boolean isRgbCamera(UsbDevice d) {
        if (d == null) return false;
        if (NativeRgbCamera.load() && NativeRgbCamera.nativeIsValidCamera(d.getVendorId(), d.getProductId())) {
            return true;
        }
        return d.getVendorId() == CAMERA_VID && d.getProductId() == NativeRgbCamera.CAMERA_PID_LUMA;
    }

    static boolean isGlassesControl(UsbDevice d) {
        if (d == null || isRgbCamera(d)) return false;
        if (d.getVendorId() == VITURE_VID) return true;
        String name = ((d.getManufacturerName() == null ? "" : d.getManufacturerName())
                + " " + (d.getProductName() == null ? "" : d.getProductName())).toLowerCase();
        return name.contains("viture") || name.contains("xr glasses") || name.contains("smart glasses");
    }

    boolean hasPermission(UsbDevice d) {
        return usb.hasPermission(d);
    }

    void open(UsbDevice device) {
        register();
        if (usb.hasPermission(device)) {
            UsbDeviceConnection conn = usb.openDevice(device);
            if (conn != null) listener.onUsbOpened(device, conn);
            else listener.onUsbDenied(device);
            return;
        }
        int flags = PendingIntent.FLAG_MUTABLE;
        PendingIntent pi = PendingIntent.getBroadcast(
                context, 0, new Intent(ACTION_PERM).setPackage(context.getPackageName()), flags);
        usb.requestPermission(device, pi);
    }

    static String describe(UsbDevice d) {
        if (d == null) return "none";
        return String.format("vid=0x%04X pid=0x%04X name=%s",
                d.getVendorId(), d.getProductId(), d.getDeviceName());
    }

    static UsbDevice extraDevicePublic(Intent intent) { return extraDevice(intent); }

    @SuppressWarnings("deprecation")
    private static UsbDevice extraDevice(Intent intent) {
        if (Build.VERSION.SDK_INT >= 33) {
            return intent.getParcelableExtra(UsbManager.EXTRA_DEVICE, UsbDevice.class);
        }
        return intent.getParcelableExtra(UsbManager.EXTRA_DEVICE);
    }
}
