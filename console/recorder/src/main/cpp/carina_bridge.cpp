#include <jni.h>
#include <android/log.h>

#include <cstdint>
#include <cstring>
#include <mutex>
#include <string>
#include <time.h>

#include "viture_device_carina.h"
#include "viture_glasses_provider.h"
#include "viture_protocol_public.h"
#include "viture_result.h"

#define LOG_TAG "XRRecorder/Carina"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGW(...) __android_log_print(ANDROID_LOG_WARN, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

static JavaVM* g_vm = nullptr;
static std::mutex g_lock;
static XRDeviceProviderHandle g_dev = nullptr;
static jobject g_listener = nullptr;
static jmethodID g_onCamera = nullptr;
static jmethodID g_onPose = nullptr;
static jmethodID g_onImu = nullptr;
static jmethodID g_onVsync = nullptr;
static jmethodID g_onError = nullptr;
static jmethodID g_onSdkLog = nullptr;
static std::string g_cache_dir;
static int g_logged_frames = 0;
static int g_logged_pose = 0;
static int g_logged_imu = 0;
static int g_logged_vsync = 0;
static int g_n_cam = 0;
static int g_n_pose = 0;
static int g_n_imu = 0;
static int g_n_vsync = 0;
static double g_last_cam = 0, g_last_pose = 0, g_last_imu = 0, g_last_vsync = 0;
static double g_dt_cam = 0, g_dt_pose = 0, g_dt_imu = 0, g_dt_vsync = 0;

static int64_t host_mono_ns() {
    timespec ts{};
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<int64_t>(ts.tv_sec) * 1000000000LL + ts.tv_nsec;
}

static uint64_t fnv1a(const char* p, int n) {
    uint64_t h = 1469598103934665603ull;
    if (!p || n <= 0) return 0;
    for (int i = 0; i < n; i++) {
        h ^= static_cast<uint8_t>(p[i]);
        h *= 1099511628211ull;
    }
    return h;
}

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

static void sdk_log_hook(int level, const char* tag, const char* message) {
    LOGI("sdk[%d] %s %s", level, tag ? tag : "", message ? message : "");
    jobject listener;
    jmethodID onLog;
    {
        std::lock_guard<std::mutex> lk(g_lock);
        listener = g_listener;
        onLog = g_onSdkLog;
    }
    if (!listener || !onLog) return;
    bool attached = false;
    JNIEnv* env = env_for_cb(&attached);
    if (!env) return;
    jstring jtag = env->NewStringUTF(tag ? tag : "");
    jstring jmsg = env->NewStringUTF(message ? message : "");
    env->CallVoidMethod(listener, onLog, static_cast<jint>(level), jtag, jmsg);
    if (env->ExceptionCheck()) {
        env->ExceptionDescribe();
        env->ExceptionClear();
    }
    env->DeleteLocalRef(jtag);
    env->DeleteLocalRef(jmsg);
    if (attached) g_vm->DetachCurrentThread();
}

static void carina_camera_cb(char* image_left0, char* image_right0,
                             char* image_left1, char* image_right1,
                             double timestamp, int width, int height) {
    if (width <= 0 || height <= 0) return;
    const int64_t hostNs = host_mono_ns();
    g_n_cam++;
    if (g_last_cam > 0) g_dt_cam = timestamp - g_last_cam;
    g_last_cam = timestamp;
    jobject listener;
    jmethodID onCamera;
    {
        std::lock_guard<std::mutex> lk(g_lock);
        listener = g_listener;
        onCamera = g_onCamera;
    }
    if (!listener || !onCamera) return;

    bool attached = false;
    JNIEnv* env = env_for_cb(&attached);
    if (!env) return;

    const int gray = width * height;
    const char* planes[4] = {image_left0, image_right0, image_left1, image_right1};
    if (g_logged_frames < 8) {
        LOGI("cam %d %dx%d sdk=%.6f dt=%.6f host=%lld L0=%p R0=%p L1=%p R1=%p sameL=%d sameR=%d",
             g_logged_frames, width, height, timestamp, g_dt_cam,
             static_cast<long long>(hostNs),
             static_cast<void*>(image_left0), static_cast<void*>(image_right0),
             static_cast<void*>(image_left1), static_cast<void*>(image_right1),
             image_left0 && image_left0 == image_left1,
             image_right0 && image_right0 == image_right1);
        g_logged_frames++;
    }

    jbyteArray arr[4];
    jlong extras[8];
    for (int i = 0; i < 4; i++) {
        extras[i] = reinterpret_cast<jlong>(planes[i]);
        extras[4 + i] = static_cast<jlong>(fnv1a(planes[i], planes[i] ? gray : 0));
        arr[i] = copy_plane(env, planes[i], planes[i] ? gray : 0);
    }
    jlongArray jex = env->NewLongArray(8);
    env->SetLongArrayRegion(jex, 0, 8, extras);
    env->CallVoidMethod(listener, onCamera,
                        arr[0], arr[1], arr[2], arr[3],
                        static_cast<jdouble>(timestamp),
                        static_cast<jlong>(hostNs),
                        static_cast<jint>(width),
                        static_cast<jint>(height),
                        jex);
    if (env->ExceptionCheck()) {
        env->ExceptionDescribe();
        env->ExceptionClear();
        fail_java(env, "onCameraFrame JNI exception");
    }
    for (int i = 0; i < 4; i++) if (arr[i]) env->DeleteLocalRef(arr[i]);
    env->DeleteLocalRef(jex);
    if (attached) g_vm->DetachCurrentThread();
}

static void pose_cb(float* pose, double ts) {
    const int64_t hostNs = host_mono_ns();
    g_n_pose++;
    if (g_last_pose > 0) g_dt_pose = ts - g_last_pose;
    g_last_pose = ts;
    if (g_logged_pose < 3) {
        LOGI("pose %d sdk=%.6f dt=%.6f p=[%.3f %.3f %.3f]",
             g_logged_pose, ts, g_dt_pose,
             pose ? pose[0] : 0.f, pose ? pose[1] : 0.f, pose ? pose[2] : 0.f);
        g_logged_pose++;
    }
    jobject listener;
    jmethodID onPose;
    {
        std::lock_guard<std::mutex> lk(g_lock);
        listener = g_listener;
        onPose = g_onPose;
    }
    if (!listener || !onPose) return;
    bool attached = false;
    JNIEnv* env = env_for_cb(&attached);
    if (!env) return;
    jfloatArray a = env->NewFloatArray(7);
    if (a && pose) env->SetFloatArrayRegion(a, 0, 7, pose);
    env->CallVoidMethod(listener, onPose, a, static_cast<jdouble>(ts), static_cast<jlong>(hostNs));
    if (env->ExceptionCheck()) { env->ExceptionDescribe(); env->ExceptionClear(); }
    if (a) env->DeleteLocalRef(a);
    if (attached) g_vm->DetachCurrentThread();
}

static void vsync_cb(double ts) {
    const int64_t hostNs = host_mono_ns();
    g_n_vsync++;
    if (g_last_vsync > 0) g_dt_vsync = ts - g_last_vsync;
    g_last_vsync = ts;
    if (g_logged_vsync < 3) {
        LOGI("vsync %d sdk=%.6f dt=%.6f", g_logged_vsync, ts, g_dt_vsync);
        g_logged_vsync++;
    }
    jobject listener;
    jmethodID onVsync;
    {
        std::lock_guard<std::mutex> lk(g_lock);
        listener = g_listener;
        onVsync = g_onVsync;
    }
    if (!listener || !onVsync) return;
    bool attached = false;
    JNIEnv* env = env_for_cb(&attached);
    if (!env) return;
    env->CallVoidMethod(listener, onVsync, static_cast<jdouble>(ts), static_cast<jlong>(hostNs));
    if (env->ExceptionCheck()) { env->ExceptionDescribe(); env->ExceptionClear(); }
    if (attached) g_vm->DetachCurrentThread();
}

static void imu_cb(float* imu, double ts) {
    const int64_t hostNs = host_mono_ns();
    g_n_imu++;
    if (g_last_imu > 0) g_dt_imu = ts - g_last_imu;
    g_last_imu = ts;
    if (g_logged_imu < 3) {
        LOGI("imu %d sdk=%.6f dt=%.6f ax=%.3f", g_logged_imu, ts, g_dt_imu, imu ? imu[0] : 0.f);
        g_logged_imu++;
    }
    jobject listener;
    jmethodID onImu;
    {
        std::lock_guard<std::mutex> lk(g_lock);
        listener = g_listener;
        onImu = g_onImu;
    }
    if (!listener || !onImu) return;
    bool attached = false;
    JNIEnv* env = env_for_cb(&attached);
    if (!env) return;
    jfloatArray a = env->NewFloatArray(6);
    if (a && imu) env->SetFloatArrayRegion(a, 0, 6, imu);
    env->CallVoidMethod(listener, onImu, a, static_cast<jdouble>(ts), static_cast<jlong>(hostNs));
    if (env->ExceptionCheck()) { env->ExceptionDescribe(); env->ExceptionClear(); }
    if (a) env->DeleteLocalRef(a);
    if (attached) g_vm->DetachCurrentThread();
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
        JNIEnv* env, jclass, jint pid, jint fd, jstring cacheDir, jobject listener) {
    std::lock_guard<std::mutex> lk(g_lock);
    if (g_dev) {
        xr_device_provider_destroy(g_dev);
        g_dev = nullptr;
    }
    if (g_listener) {
        env->DeleteGlobalRef(g_listener);
        g_listener = nullptr;
    }
    g_onCamera = g_onPose = g_onImu = g_onVsync = g_onError = g_onSdkLog = nullptr;
    g_logged_frames = g_logged_pose = g_logged_imu = g_logged_vsync = 0;
    g_n_cam = g_n_pose = g_n_imu = g_n_vsync = 0;
    g_last_cam = g_last_pose = g_last_imu = g_last_vsync = 0;
    g_dt_cam = g_dt_pose = g_dt_imu = g_dt_vsync = 0;
    g_cache_dir.clear();
    if (cacheDir) {
        const char* c = env->GetStringUTFChars(cacheDir, nullptr);
        if (c) {
            g_cache_dir = c;
            env->ReleaseStringUTFChars(cacheDir, c);
        }
    }
    if (listener == nullptr) {
        LOGE("nativeCreate: null listener");
        return JNI_FALSE;
    }
    jclass cls = env->GetObjectClass(listener);
    g_onCamera = env->GetMethodID(cls, "onCameraFrame", "([B[B[B[BDJII[J)V");
    g_onPose = env->GetMethodID(cls, "onPose", "([FDJ)V");
    g_onImu = env->GetMethodID(cls, "onImu", "([FDJ)V");
    g_onVsync = env->GetMethodID(cls, "onVsync", "(DJ)V");
    g_onError = env->GetMethodID(cls, "onNativeError", "(Ljava/lang/String;)V");
    g_onSdkLog = env->GetMethodID(cls, "onSdkLog", "(ILjava/lang/String;Ljava/lang/String;)V");
    if (!g_onCamera || !g_onPose || !g_onImu || !g_onVsync) {
        LOGE("nativeCreate: missing listener methods");
        env->ExceptionClear();
        return JNI_FALSE;
    }
    g_listener = env->NewGlobalRef(listener);
    xr_device_provider_set_log_level(3);
    xr_device_provider_set_log_hook(sdk_log_hook);
    g_dev = xr_device_provider_create(pid, fd);
    if (!g_dev) {
        LOGE("device create failed pid=0x%04x fd=%d", pid, fd);
        env->DeleteGlobalRef(g_listener);
        g_listener = nullptr;
        return JNI_FALSE;
    }
    LOGI("device create ok pid=0x%04x fd=%d cache=%s", pid, fd,
         g_cache_dir.empty() ? "(null)" : g_cache_dir.c_str());
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
    const char* cache = g_cache_dir.empty() ? nullptr : g_cache_dir.c_str();
    r = xr_device_provider_initialize(g_dev, nullptr, cache);
    if (r != VITURE_GLASSES_SUCCESS) {
        LOGE("initialize failed: %d cache=%s", r, cache ? cache : "(null)");
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

extern "C" JNIEXPORT jint JNICALL
Java_sh_colak_xrconsole_recorder_NativeCarina_nativeSetExposure(
        JNIEnv*, jclass, jboolean autoExp, jfloat ms, jint gain) {
    std::lock_guard<std::mutex> lk(g_lock);
    if (!g_dev) return VITURE_GLASSES_ERROR_INVALID_PARAM;
    if (autoExp) return xr_device_provider_set_auto_exposure_carina(g_dev);
    return xr_device_provider_set_manual_exposure_carina(g_dev, ms, gain);
}

extern "C" JNIEXPORT jbyteArray JNICALL
Java_sh_colak_xrconsole_recorder_NativeCarina_nativeSnHash(JNIEnv* env, jclass) {
    std::lock_guard<std::mutex> lk(g_lock);
    if (!g_dev) return nullptr;
    uint8_t hash[32] = {};
    int r = xr_device_provider_get_sn_hash(g_dev, hash);
    if (r != VITURE_GLASSES_SUCCESS) {
        LOGW("get_sn_hash rc=%d", r);
        return nullptr;
    }
    jbyteArray out = env->NewByteArray(32);
    if (out) env->SetByteArrayRegion(out, 0, 32, reinterpret_cast<const jbyte*>(hash));
    return out;
}

extern "C" JNIEXPORT void JNICALL
Java_sh_colak_xrconsole_recorder_NativeCarina_nativeDestroy(JNIEnv* env, jclass) {
    std::lock_guard<std::mutex> lk(g_lock);
    xr_device_provider_set_log_hook(nullptr);
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
    g_onCamera = g_onPose = g_onImu = g_onVsync = g_onError = g_onSdkLog = nullptr;
    LOGI("carina destroyed");
}

extern "C" JNIEXPORT jintArray JNICALL
Java_sh_colak_xrconsole_recorder_NativeCarina_nativeStats(JNIEnv* env, jclass) {
    jint vals[4] = {g_n_cam, g_n_pose, g_n_imu, g_n_vsync};
    jintArray out = env->NewIntArray(4);
    if (out) env->SetIntArrayRegion(out, 0, 4, vals);
    return out;
}

extern "C" JNIEXPORT jdoubleArray JNICALL
Java_sh_colak_xrconsole_recorder_NativeCarina_nativeClock(JNIEnv* env, jclass) {
    jdouble vals[8] = {
        g_last_cam, g_dt_cam, g_last_pose, g_dt_pose,
        g_last_imu, g_dt_imu, g_last_vsync, g_dt_vsync
    };
    jdoubleArray out = env->NewDoubleArray(8);
    if (out) env->SetDoubleArrayRegion(out, 0, 8, vals);
    return out;
}
