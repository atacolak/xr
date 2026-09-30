#include <jni.h>
#include <android/log.h>

#include <cstdint>
#include <cstring>
#include <mutex>

#include "viture_device_carina.h"
#include "viture_glasses_provider.h"
#include "viture_result.h"

#define LOG_TAG "XRRecorder/Carina"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGW(...) __android_log_print(ANDROID_LOG_WARN, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

static JavaVM* g_vm = nullptr;
static std::mutex g_lock;
static XRDeviceProviderHandle g_dev = nullptr;
static jobject g_listener = nullptr;
static jmethodID g_onStereo = nullptr;
static jmethodID g_onError = nullptr;
static int g_logged_frames = 0;
static int g_logged_pose = 0;
static int g_logged_imu = 0;
static int g_logged_vsync = 0;
static int g_n_cam = 0;
static int g_n_pose = 0;
static int g_n_imu = 0;
static int g_n_vsync = 0;

static JNIEnv* env_for_cb(bool* attached) {
    *attached = false;
    if (!g_vm) return nullptr;
    JNIEnv* env = nullptr;
    int get = g_vm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6);
    if (get == JNI_EDETACHED) {
        if (g_vm->AttachCurrentThread(&env, nullptr) != JNI_OK) return nullptr;
        *attached = true;
    } else if (get != JNI_OK) {
        return nullptr;
    }
    return env;
}

static void fail_java(JNIEnv* env, const char* msg) {
    if (!env || !g_listener || !g_onError || !msg) return;
    jstring s = env->NewStringUTF(msg);
    env->CallVoidMethod(g_listener, g_onError, s);
    env->DeleteLocalRef(s);
    if (env->ExceptionCheck()) {
        env->ExceptionDescribe();
        env->ExceptionClear();
    }
}

static jbyteArray copy_plane(JNIEnv* env, const char* src, int nbytes) {
    if (!src || nbytes <= 0) return nullptr;
    jbyteArray arr = env->NewByteArray(nbytes);
    if (!arr) return nullptr;
    env->SetByteArrayRegion(arr, 0, nbytes, reinterpret_cast<const jbyte*>(src));
    return arr;
}

static void carina_camera_cb(char* image_left0, char* image_right0,
                             char* image_left1, char* image_right1,
                             double timestamp, int width, int height) {
    if (width <= 0 || height <= 0) return;
    g_n_cam++;
    jobject listener;
    jmethodID onStereo;
    {
        std::lock_guard<std::mutex> lk(g_lock);
        listener = g_listener;
        onStereo = g_onStereo;
    }
    if (!listener || !onStereo) return;

    bool attached = false;
    JNIEnv* env = env_for_cb(&attached);
    if (!env) return;

    const int gray = width * height;
    if (g_logged_frames < 5) {
        LOGI("stereo frame %d %dx%d ts=%.6f L0=%p R0=%p L1=%p R1=%p assume %d B gray cam=%d pose=%d imu=%d vsync=%d",
             g_logged_frames, width, height, timestamp,
             static_cast<void*>(image_left0), static_cast<void*>(image_right0),
             static_cast<void*>(image_left1), static_cast<void*>(image_right1), gray,
             g_n_cam, g_n_pose, g_n_imu, g_n_vsync);
        g_logged_frames++;
    }

    jbyteArray l0 = copy_plane(env, image_left0, image_left0 ? gray : 0);
    jbyteArray r0 = copy_plane(env, image_right0, image_right0 ? gray : 0);
    jbyteArray l1 = copy_plane(env, image_left1, image_left1 ? gray : 0);
    jbyteArray r1 = copy_plane(env, image_right1, image_right1 ? gray : 0);
    env->CallVoidMethod(listener, onStereo,
                        l0, r0, l1, r1,
                        static_cast<jdouble>(timestamp),
                        static_cast<jint>(width),
                        static_cast<jint>(height),
                        static_cast<jint>(gray));
    if (env->ExceptionCheck()) {
        env->ExceptionDescribe();
        env->ExceptionClear();
        fail_java(env, "onStereoFrame JNI exception");
    }
    if (l0) env->DeleteLocalRef(l0);
    if (r0) env->DeleteLocalRef(r0);
    if (l1) env->DeleteLocalRef(l1);
    if (r1) env->DeleteLocalRef(r1);
    if (attached) g_vm->DetachCurrentThread();
}

static void pose_cb(float* pose, double ts) {
    g_n_pose++;
    if (g_logged_pose < 3) {
        LOGI("pose %d ts=%.6f p=[%.3f %.3f %.3f] cam=%d imu=%d vsync=%d",
             g_logged_pose, ts,
             pose ? pose[0] : 0.f, pose ? pose[1] : 0.f, pose ? pose[2] : 0.f,
             g_n_cam, g_n_imu, g_n_vsync);
        g_logged_pose++;
    }
}

static void vsync_cb(double ts) {
    g_n_vsync++;
    if (g_logged_vsync < 3) {
        LOGI("vsync %d ts=%.6f cam=%d pose=%d imu=%d",
             g_logged_vsync, ts, g_n_cam, g_n_pose, g_n_imu);
        g_logged_vsync++;
    }
}

static void imu_cb(float* imu, double ts) {
    g_n_imu++;
    if (g_logged_imu < 3) {
        LOGI("imu %d ts=%.6f cam=%d pose=%d vsync=%d ax=%.3f",
             g_logged_imu, ts, g_n_cam, g_n_pose, g_n_vsync,
             imu ? imu[0] : 0.f);
        g_logged_imu++;
    }
}

extern "C" JNIEXPORT jint JNI_OnLoad(JavaVM* vm, void*) {
    g_vm = vm;
    return JNI_VERSION_1_6;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_sh_colak_xrconsole_recorder_NativeCarina_nativeIsValidProduct(JNIEnv*, jclass, jint pid) {
    return xr_device_provider_is_product_id_valid(pid) ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_sh_colak_xrconsole_recorder_NativeCarina_nativeCreate(
        JNIEnv* env, jclass, jint pid, jint fd, jobject listener) {
    std::lock_guard<std::mutex> lk(g_lock);
    if (g_dev) {
        xr_device_provider_destroy(g_dev);
        g_dev = nullptr;
    }
    if (g_listener) {
        env->DeleteGlobalRef(g_listener);
        g_listener = nullptr;
    }
    g_onStereo = nullptr;
    g_onError = nullptr;
    g_logged_frames = 0;
    g_logged_pose = 0;
    g_logged_imu = 0;
    g_logged_vsync = 0;
    g_n_cam = 0;
    g_n_pose = 0;
    g_n_imu = 0;
    g_n_vsync = 0;
    if (listener == nullptr) {
        LOGE("nativeCreate: null listener");
        return JNI_FALSE;
    }
    jclass cls = env->GetObjectClass(listener);
    g_onStereo = env->GetMethodID(cls, "onStereoFrame", "([B[B[B[BDIII)V");
    g_onError = env->GetMethodID(cls, "onNativeError", "(Ljava/lang/String;)V");
    if (!g_onStereo) {
        LOGE("nativeCreate: missing onStereoFrame");
        env->ExceptionClear();
        return JNI_FALSE;
    }
    g_listener = env->NewGlobalRef(listener);
    g_dev = xr_device_provider_create(pid, fd);
    if (!g_dev) {
        LOGE("device create failed pid=0x%04x fd=%d", pid, fd);
        env->DeleteGlobalRef(g_listener);
        g_listener = nullptr;
        return JNI_FALSE;
    }
    LOGI("device create ok pid=0x%04x fd=%d", pid, fd);
    return JNI_TRUE;
}

extern "C" JNIEXPORT jint JNICALL
Java_sh_colak_xrconsole_recorder_NativeCarina_nativeDeviceType(JNIEnv*, jclass) {
    std::lock_guard<std::mutex> lk(g_lock);
    if (!g_dev) return -1;
    return xr_device_provider_get_device_type(g_dev);
}

extern "C" JNIEXPORT jint JNICALL
Java_sh_colak_xrconsole_recorder_NativeCarina_nativeStart(JNIEnv*, jclass) {
    std::lock_guard<std::mutex> lk(g_lock);
    if (!g_dev) return VITURE_GLASSES_ERROR_INVALID_PARAM;
    int type = xr_device_provider_get_device_type(g_dev);
    LOGI("device type=%d (carina=%d)", type, XR_DEVICE_TYPE_VITURE_CARINA);
    if (type != XR_DEVICE_TYPE_VITURE_CARINA) {
        LOGE("not a Carina device; grayscale cameras require Luma Ultra");
        return VITURE_GLASSES_ERROR_NOT_SUPPORTED;
    }
    int r = xr_device_provider_set_dof_type_carina(g_dev, 1);
    if (r != VITURE_GLASSES_SUCCESS) {
        LOGW("set_dof_type_carina rc=%d (continuing)", r);
    }
    r = xr_device_provider_initialize(g_dev, nullptr, nullptr);
    if (r != VITURE_GLASSES_SUCCESS) {
        LOGE("initialize failed: %d", r);
        return r;
    }
    r = xr_device_provider_register_callbacks_carina(g_dev, pose_cb, vsync_cb, imu_cb, carina_camera_cb);
    if (r != VITURE_GLASSES_SUCCESS) {
        LOGE("register_callbacks_carina failed: %d", r);
        return r;
    }
    r = xr_device_provider_start(g_dev);
    if (r != VITURE_GLASSES_SUCCESS) {
        LOGE("device start failed: %d", r);
        return r;
    }
    r = xr_device_provider_set_auto_exposure_carina(g_dev);
    if (r != VITURE_GLASSES_SUCCESS) {
        LOGW("set_auto_exposure_carina rc=%d", r);
    }
    LOGI("carina started; waiting for stereo frames");
    return VITURE_GLASSES_SUCCESS;
}

extern "C" JNIEXPORT void JNICALL
Java_sh_colak_xrconsole_recorder_NativeCarina_nativeDestroy(JNIEnv* env, jclass) {
    std::lock_guard<std::mutex> lk(g_lock);
    if (g_dev) {
        xr_device_provider_stop(g_dev);
        xr_device_provider_shutdown(g_dev);
        xr_device_provider_destroy(g_dev);
        g_dev = nullptr;
    }
    if (g_listener) {
        env->DeleteGlobalRef(g_listener);
        g_listener = nullptr;
    }
    g_onStereo = nullptr;
    g_onError = nullptr;
    LOGI("carina destroyed");
}

extern "C" JNIEXPORT jintArray JNICALL
Java_sh_colak_xrconsole_recorder_NativeCarina_nativeStats(JNIEnv* env, jclass) {
    jint vals[4] = {g_n_cam, g_n_pose, g_n_imu, g_n_vsync};
    jintArray out = env->NewIntArray(4);
    if (out) env->SetIntArrayRegion(out, 0, 4, vals);
    return out;
}
