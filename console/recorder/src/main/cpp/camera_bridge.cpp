#include <jni.h>
#include <android/log.h>

#include <algorithm>
#include <cstdint>
#include <mutex>
#include <vector>

#include "viture_camera_provider.h"
#include "viture_result.h"
#include "viture_version.h"

#define LOG_TAG "XRRecorder/Native"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

static JavaVM* g_vm = nullptr;
static XRCameraProviderHandle g_cam = nullptr;
static jobject g_listener = nullptr;
static jmethodID g_onFrame = nullptr;
static jmethodID g_onNativeError = nullptr;

static void camera_frame_cb(const XRCameraFrame* frame, void* /*user*/) {
    if (!frame || !frame->data || frame->size == 0) return;
    if (!g_vm || !g_listener || !g_onFrame) return;
    JNIEnv* env = nullptr;
    bool attached = false;
    int get = g_vm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6);
    if (get == JNI_EDETACHED) {
        if (g_vm->AttachCurrentThread(&env, nullptr) != JNI_OK) return;
        attached = true;
    } else if (get != JNI_OK || env == nullptr) {
        return;
    }
    jbyteArray arr = env->NewByteArray(static_cast<jsize>(frame->size));
    if (arr == nullptr) {
        if (attached) g_vm->DetachCurrentThread();
        return;
    }
    env->SetByteArrayRegion(arr, 0, static_cast<jsize>(frame->size),
                            reinterpret_cast<const jbyte*>(frame->data));
    env->CallVoidMethod(
        g_listener, g_onFrame, arr,
        static_cast<jint>(frame->width),
        static_cast<jint>(frame->height),
        static_cast<jlong>(frame->timestamp),
        static_cast<jint>(frame->sequence),
        static_cast<jint>(frame->format));
    env->DeleteLocalRef(arr);
    if (env->ExceptionCheck()) {
        env->ExceptionDescribe();
        env->ExceptionClear();
        if (g_onNativeError) {
            jstring msg = env->NewStringUTF("onFrame JNI exception");
            env->CallVoidMethod(g_listener, g_onNativeError, msg);
            env->DeleteLocalRef(msg);
            env->ExceptionClear();
        }
    }
    if (attached) g_vm->DetachCurrentThread();
}

static uint8_t clamp_u8(int v) {
    if (v < 0) return 0;
    if (v > 255) return 255;
    return static_cast<uint8_t>(v);
}

extern "C" JNIEXPORT jint JNI_OnLoad(JavaVM* vm, void*) {
    g_vm = vm;
    return JNI_VERSION_1_6;
}

extern "C" JNIEXPORT jstring JNICALL
Java_sh_colak_xrconsole_recorder_NativeRgbCamera_nativeVersion(JNIEnv* env, jclass) {
    const char* v = GetVersionString();
    return env->NewStringUTF(v ? v : "");
}

extern "C" JNIEXPORT jint JNICALL
Java_sh_colak_xrconsole_recorder_NativeRgbCamera_nativeCameraVid(JNIEnv*, jclass, jint glassesPid) {
    return xr_camera_provider_get_camera_vid(glassesPid);
}

extern "C" JNIEXPORT jint JNICALL
Java_sh_colak_xrconsole_recorder_NativeRgbCamera_nativeCameraPid(JNIEnv*, jclass, jint glassesPid) {
    return xr_camera_provider_get_camera_pid(glassesPid);
}

extern "C" JNIEXPORT jboolean JNICALL
Java_sh_colak_xrconsole_recorder_NativeRgbCamera_nativeIsValidCamera(JNIEnv*, jclass, jint vid, jint pid) {
    return xr_camera_provider_is_valid_camera(vid, pid) ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_sh_colak_xrconsole_recorder_NativeRgbCamera_nativeCreate(
        JNIEnv* env, jclass, jint vid, jint pid, jint fd, jobject listener) {
    if (g_cam) {
        xr_camera_provider_destroy(g_cam);
        g_cam = nullptr;
    }
    if (g_listener) {
        env->DeleteGlobalRef(g_listener);
        g_listener = nullptr;
    }
    g_onFrame = nullptr;
    g_onNativeError = nullptr;
    if (listener == nullptr) {
        LOGE("nativeCreate: null listener");
        return JNI_FALSE;
    }
    jclass cls = env->GetObjectClass(listener);
    g_onFrame = env->GetMethodID(cls, "onRgbFrame", "([BIIJII)V");
    g_onNativeError = env->GetMethodID(cls, "onNativeError", "(Ljava/lang/String;)V");
    if (!g_onFrame) {
        LOGE("nativeCreate: missing onRgbFrame");
        env->ExceptionClear();
        return JNI_FALSE;
    }
    g_listener = env->NewGlobalRef(listener);
    g_cam = xr_camera_provider_create(vid, pid, fd);
    if (!g_cam) {
        LOGE("camera create failed vid=0x%04x pid=0x%04x fd=%d", vid, pid, fd);
        env->DeleteGlobalRef(g_listener);
        g_listener = nullptr;
        return JNI_FALSE;
    }
    LOGI("camera create ok vid=0x%04x pid=0x%04x fd=%d", vid, pid, fd);
    return JNI_TRUE;
}

extern "C" JNIEXPORT jint JNICALL
Java_sh_colak_xrconsole_recorder_NativeRgbCamera_nativeStart(JNIEnv*, jclass) {
    if (!g_cam) return VITURE_GLASSES_ERROR_INVALID_PARAM;
    int r = xr_camera_provider_start(g_cam, camera_frame_cb, nullptr);
    if (r != VITURE_GLASSES_SUCCESS) LOGE("camera start failed: %d", r);
    else LOGI("camera started");
    return r;
}

extern "C" JNIEXPORT jint JNICALL
Java_sh_colak_xrconsole_recorder_NativeRgbCamera_nativeStop(JNIEnv*, jclass) {
    if (!g_cam) return 0;
    return xr_camera_provider_stop(g_cam);
}

extern "C" JNIEXPORT jboolean JNICALL
Java_sh_colak_xrconsole_recorder_NativeRgbCamera_nativeIsStreaming(JNIEnv*, jclass) {
    if (!g_cam) return JNI_FALSE;
    return xr_camera_provider_is_streaming(g_cam) ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT void JNICALL
Java_sh_colak_xrconsole_recorder_NativeRgbCamera_nativeDestroy(JNIEnv* env, jclass) {
    if (g_cam) {
        xr_camera_provider_destroy(g_cam);
        g_cam = nullptr;
    }
    if (g_listener) {
        env->DeleteGlobalRef(g_listener);
        g_listener = nullptr;
    }
    g_onFrame = nullptr;
    g_onNativeError = nullptr;
}

extern "C" JNIEXPORT void JNICALL
Java_sh_colak_xrconsole_recorder_Yuv_argbToNv12(
        JNIEnv* env, jclass, jintArray argb, jint width, jint height, jbyteArray nv12) {
    if (argb == nullptr || nv12 == nullptr || width <= 0 || height <= 0) return;
    if ((width & 1) || (height & 1)) return;
    jsize nPix = env->GetArrayLength(argb);
    jsize nNv = env->GetArrayLength(nv12);
    int needPix = width * height;
    int needNv = width * height + width * height / 2;
    if (nPix < needPix || nNv < needNv) return;
    jint* px = env->GetIntArrayElements(argb, nullptr);
    jbyte* dst = env->GetByteArrayElements(nv12, nullptr);
    if (!px || !dst) {
        if (px) env->ReleaseIntArrayElements(argb, px, JNI_ABORT);
        if (dst) env->ReleaseByteArrayElements(nv12, dst, JNI_ABORT);
        return;
    }
    auto* y = reinterpret_cast<uint8_t*>(dst);
    uint8_t* uv = y + width * height;
    for (int j = 0; j < height; ++j) {
        const jint* row = px + j * width;
        uint8_t* yrow = y + j * width;
        for (int i = 0; i < width; ++i) {
            int p = row[i];
            int r = (p >> 16) & 255;
            int g = (p >> 8) & 255;
            int b = p & 255;
            int Y = ((66 * r + 129 * g + 25 * b + 128) >> 8) + 16;
            yrow[i] = clamp_u8(Y);
            if (((j | i) & 1) == 0) {
                int U = ((-38 * r - 74 * g + 112 * b + 128) >> 8) + 128;
                int V = ((112 * r - 94 * g - 18 * b + 128) >> 8) + 128;
                int off = (j / 2) * width + i;
                uv[off] = clamp_u8(U);
                uv[off + 1] = clamp_u8(V);
            }
        }
    }
    env->ReleaseIntArrayElements(argb, px, JNI_ABORT);
    env->ReleaseByteArrayElements(nv12, dst, 0);
}
