// SPDX-License-Identifier: BSL-1.0
/*!
 * @file
 * @brief  Characterise the VITURE Carina pose stream, with no Monado involved.
 *
 * This exists to answer the questions a datasheet does not:
 *
 *   - what rate does the pose actually arrive at, and how jittery is it,
 *   - which way does yaw/pitch/roll go, and is any axis inverted,
 *   - how noisy is the pose while the head is still,
 *   - does the reported position change when the head translates, and by how
 *     much per centimetre (the vendor docs do not state a unit),
 *   - what does the vendor's instability flag actually do.
 *
 * It talks to the vendor SDK directly so it works even when the OpenXR stack is
 * broken, which is exactly when you need it.
 *
 * Build: tools/build-pose-dump.sh   Run: tools/viture-pose-dump --help
 */

#define _GNU_SOURCE

#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "viture_device_carina.h"
#include "viture_camera_provider.h"
#include "viture_glasses_provider.h"
#include "viture_protocol_public.h"
#include "viture_result.h"
#include "viture_compat.h"

#include "viture_interface.h"
#include "viture_pose_layout.h"
#include "viture_modes.h"

#define MAX_DEVICES 8

struct options
{
	double seconds;
	double rate_hz;
	double predict_s;
	bool json;
	bool quiet;
	bool reset;
	bool sixdof;
	int set_mode;
	bool have_set_mode;
	bool get_mode;
	bool native_probe;
	bool pose_cb;
	bool auto_exposure;
	bool camera_provider;
	bool src_cb;
	bool flip_xy;
	const char *cache;
};

static double
now_s(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static const char *
status_name(int status)
{
	return status == 0 ? "stable" : "unstable";
}

static void
usage(const char *argv0)
{
	fprintf(stderr,
	        "usage: %s [options]\n"
	        "\n"
	        "  --seconds N      run for N seconds (default 10)\n"
	        "  --rate HZ        poll rate, 0 = free-running (default 120)\n"
	        "  --predict S      prediction horizon in seconds (default 0)\n"
	        "  --set-mode M     set display mode first, by name or vendor id\n"
	        "                   e.g. 3840x1200@90-sbs or 0x45\n"
	        "  --get-mode       print the device's display-mode state and exit\n"
	        "  --self-test-axes verify the Y-up yaw/pitch/roll extraction and exit\n"
	        "  --pose-cb        register the pose callback too (tests the push path)\n"
	        "  --auto-exposure  call set_auto_exposure_carina after start (as the app does)\n"
	        "  --flip-xy        flip the pose frame handedness: negate quaternion x,y, which\n"
	        "                   inverts yaw and pitch but preserves roll. Needed because the\n"
	        "                   SDK's GL pose has z backward (right-handed) while the demo\n"
	        "                   renderer looks down +z; without it a head turn drives the\n"
	        "                   scene the wrong way.\n"
	        "  --src-cb         take poses from the device callback instead of polling\n"
	        "                   (the callback is ~800 Hz and gravity-stable; polling drifts)\n"
	        "  --cache DIR      cache directory for initialize() (as the app does)\n"
	        "  --native-probe   also query native (Gen2) mode state; BLOCKS on Carina\n"
	        "  --reset          reset the VIO origin before sampling\n"
	        "  --3dof           select 3DoF instead of 6DoF\n"
	        "  --json           emit one JSON object per sample\n"
	        "  --quiet          summary only\n"
	        "  --list-modes     print the known display modes and exit\n"
	        "  --help\n",
	        argv0);
}

/*!
 * Polar decomposition of a quaternion into degrees of yaw/pitch/roll.
 *
 * Convention: the SDK hands back OpenGL-convention poses (x right, y UP, z backward),
 * so the rotation decomposes as R = Ry(yaw) * Rx(pitch) * Rz(roll). The obvious
 * aerospace ZYX formula is WRONG here and was a real bug: it permuted the axes, which
 * felt as 'tilting my head down does roll' through the glasses. Derivation from that
 * product:
 *     R02 = sy*cp    R22 = cy*cp    R12 = -sp
 *     R10 = cp*sr    R11 = cp*cr
 * giving the three inverse trig calls below (cp != 0).
 *
 * --self-test-axes rebuilds quaternions from known angles and checks recovery.
 */
static void
quat_to_euler_deg(const float q[7], double *yaw, double *pitch, double *roll)
{
	const double w = q[3], x = q[4], y = q[5], z = q[6];
	const double r02 = 2.0 * (x * z + w * y);
	const double r22 = 1.0 - 2.0 * (x * x + y * y);
	const double r12 = 2.0 * (y * z - w * x);
	const double r10 = 2.0 * (x * y + w * z);
	const double r11 = 1.0 - 2.0 * (x * x + z * z);

	double sp = -r12;
	if (sp > 1.0) {
		sp = 1.0;
	} else if (sp < -1.0) {
		sp = -1.0;
	}
	*pitch = asin(sp) * 180.0 / M_PI;
	*yaw = atan2(r02, r22) * 180.0 / M_PI;
	*roll = atan2(r10, r11) * 180.0 / M_PI;
}

/*! Build the quaternion for R = Ry(yaw) * Rx(pitch) * Rz(roll), for the self-test. */
static void
euler_deg_to_quat(double yaw, double pitch, double roll, float q[7])
{
	const double hy = yaw * M_PI / 360.0, hp = pitch * M_PI / 360.0, hr = roll * M_PI / 360.0;
	const double cy = cos(hy), sy = sin(hy), cp = cos(hp), sp = sin(hp), cr = cos(hr), sr = sin(hr);
	q[0] = q[1] = q[2] = 0.0f;
	q[3] = (float)(cy * cp * cr + sy * sp * sr);
	q[4] = (float)(cy * sp * cr + sy * cp * sr);
	q[5] = (float)(sy * cp * cr - cy * sp * sr);
	q[6] = (float)(cy * cp * sr - sy * sp * cr);
}

static int
self_test_axes(void)
{
	const double cases[][3] = {
	    {0, 0, 0}, {30, 0, 0}, {-30, 0, 0}, {0, 20, 0}, {0, -20, 0}, {0, 0, 25}, {0, 0, -25},
	    {35, 15, -10}, {-70, 25, 40}, {179, 5, 5}, {-5, -40, 60},
	};
	int bad = 0;
	printf("axis self-test (Y-up: R = Ry(yaw) * Rx(pitch) * Rz(roll))\n");
	for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
		float q[7];
		double y, p, r;
		euler_deg_to_quat(cases[i][0], cases[i][1], cases[i][2], q);
		quat_to_euler_deg(q, &y, &p, &r);
		const double dy = fabs(y - cases[i][0]), dp = fabs(p - cases[i][1]), dr = fabs(r - cases[i][2]);
		/* float32 quaternion input, so allow well below anything perceptible */
		const int ok = dy < 1e-3 && dp < 1e-3 && dr < 1e-3;
		if (!ok) {
			bad++;
		}
		printf("  in (yaw %+7.1f pitch %+7.1f roll %+7.1f) -> out (%+7.1f %+7.1f %+7.1f)  %s\n",
		       cases[i][0], cases[i][1], cases[i][2], y, p, r, ok ? "ok" : "MISMATCH");
	}
	printf("%zu cases, %d failures\n", sizeof(cases) / sizeof(cases[0]), bad);
	return bad == 0 ? 0 : 1;
}

/* ---- the standalone camera provider's stream ----
 * Separate USB interface and separate API from xr_device_provider: the device provider's
 * camera callback belongs to the VIO, while this stream is opened explicitly. Without it the
 * video stream is never brought up at all ("init open_vst_str: off"), no frames reach the VIO,
 * and every pose comes back identity+unstable forever. */
static unsigned long long g_stream_frames;
static int g_stream_w, g_stream_h;

static void
stream_frame_cb(const XRCameraFrame *f, void *user)
{
	(void)user;
	if (g_stream_frames == 0) {
		g_stream_w = (int)f->width;
		g_stream_h = (int)f->height;
	}
	__atomic_add_fetch(&g_stream_frames, 1, __ATOMIC_RELAXED);
}

/* ---- stereo camera frames: the Carina VIO's input ---- */
static unsigned long long g_cam_frames;
static int g_cam_w;
static int g_cam_h;

static void
camera_frame_cb(char *left0, char *right0, char *left1, char *right1, double timestamp, int width, int height)
{
	(void)left0;
	(void)right0;
	(void)left1;
	(void)right1;
	(void)timestamp;
	__atomic_add_fetch(&g_cam_frames, 1, __ATOMIC_RELAXED);
	__atomic_store_n(&g_cam_w, width, __ATOMIC_RELAXED);
	__atomic_store_n(&g_cam_h, height, __ATOMIC_RELAXED);
}

/* ---- vsync / imu callbacks: the Android app registers all four, and the SDK may only
 * start a pipeline whose callback is non-null, so register them and count invocations. ---- */
static unsigned long long g_vsync_count;
static unsigned long long g_imu_count;

static void
vsync_cb(double timestamp)
{
	(void)timestamp;
	__atomic_add_fetch(&g_vsync_count, 1, __ATOMIC_RELAXED);
}

static void
imu_cb(float *imu, double timestamp)
{
	(void)imu;
	(void)timestamp;
	__atomic_add_fetch(&g_imu_count, 1, __ATOMIC_RELAXED);
}

/* ---- optional pose callback: does the device push poses at all? ---- */
static float g_cb_pose[7];
static double g_cb_ts;
static unsigned long long g_cb_count;

static void
pose_cb(float *pose, double timestamp)
{
	for (int i = 0; i < 7; i++) {
		g_cb_pose[i] = pose[i];
	}
	g_cb_ts = timestamp;
	__atomic_add_fetch(&g_cb_count, 1, __ATOMIC_RELAXED);
}

int
main(int argc, char **argv)
{
	struct options o = {
	    .seconds = 10.0,
	    .rate_hz = 120.0,
	    .predict_s = 0.0,
	    .sixdof = true,
	};

	for (int i = 1; i < argc; i++) {
		const char *a = argv[i];
		if (strcmp(a, "--seconds") == 0 && i + 1 < argc) {
			o.seconds = atof(argv[++i]);
		} else if (strcmp(a, "--rate") == 0 && i + 1 < argc) {
			o.rate_hz = atof(argv[++i]);
		} else if (strcmp(a, "--predict") == 0 && i + 1 < argc) {
			o.predict_s = atof(argv[++i]);
		} else if (strcmp(a, "--set-mode") == 0 && i + 1 < argc) {
			const char *v = argv[++i];
			const struct viture_mode_info *m = viture_mode_by_name(v);
			if (m == NULL) {
				m = viture_mode_lookup((int)strtol(v, NULL, 0));
			}
			if (m == NULL) {
				fprintf(stderr, "unknown display mode: %s\n", v);
				return 2;
			}
			o.set_mode = m->vendor_mode;
			o.have_set_mode = true;
		} else if (strcmp(a, "--native-probe") == 0) {
			o.native_probe = true;
		} else if (strcmp(a, "--flip-xy") == 0) {
			o.flip_xy = true;
		} else if (strcmp(a, "--src-cb") == 0) {
			o.src_cb = true;
			o.pose_cb = true;
		} else if (strcmp(a, "--auto-exposure") == 0) {
			o.auto_exposure = true;
		} else if (strcmp(a, "--camera-provider") == 0) {
			/* Open the stereo camera stream directly. Diagnostic only: the VIO opens the
			 * camera through the device provider, and holding it here starves the VIO. */
			o.camera_provider = true;
		} else if (strcmp(a, "--cache") == 0 && i + 1 < argc) {
			o.cache = argv[++i];
		} else if (strcmp(a, "--pose-cb") == 0) {
			o.pose_cb = true;
		} else if (strcmp(a, "--self-test-axes") == 0) {
			return self_test_axes();
		} else if (strcmp(a, "--get-mode") == 0) {
			o.get_mode = true;
		} else if (strcmp(a, "--reset") == 0) {
			o.reset = true;
		} else if (strcmp(a, "--3dof") == 0) {
			o.sixdof = false;
		} else if (strcmp(a, "--json") == 0) {
			o.json = true;
		} else if (strcmp(a, "--quiet") == 0) {
			o.quiet = true;
		} else if (strcmp(a, "--list-modes") == 0) {
			for (int m = 0; m < 0x50; m++) {
				const struct viture_mode_info *info = viture_mode_lookup(m);
				if (info != NULL) {
					printf("0x%02X  %-16s %ux%u  %u view(s)  %.0f Hz\n", info->vendor_mode,
					       info->name, info->total_w, info->total_h, info->view_count, info->fps);
				}
			}
			return 0;
		} else {
			usage(argv[0]);
			return 2;
		}
	}

	printf("libglasses %s\n", GetVersionString());

	uint16_t pids[MAX_DEVICES] = {0};
	const int count = viture_enumerate_product_ids(pids, MAX_DEVICES);
	printf("attached VITURE products: %d\n", count);
	for (int i = 0; i < count; i++) {
		char name[64] = {0};
		viture_market_name(pids[i], name, sizeof(name));
		printf("  [%d] pid=0x%04X name=\"%s\" supported=%s\n", i, pids[i], name,
		       viture_is_supported_product(pids[i]) ? "yes" : "no");
	}
	if (count == 0) {
		fprintf(stderr, "no VITURE device found on USB (vid 0x%04X).\n", VITURE_VID);
		fprintf(stderr, "Check: cable, and that the udev rule is installed so this user can open it.\n");
		return 1;
	}

	int product_id = -1;
	for (int i = 0; i < count; i++) {
		if (viture_is_supported_product(pids[i])) {
			product_id = pids[i];
			break;
		}
	}
	if (product_id < 0) {
		fprintf(stderr, "no supported (Carina) VITURE product attached\n");
		return 1;
	}

	XRDeviceProviderHandle h = xr_device_provider_create(product_id);

	/* Bring up the stereo camera stream before the device provider starts: the VIO needs
	 * images, and this is the API that opens them. */
	XRCameraProviderHandle cam = NULL;
	{
		const int cv = o.camera_provider ? xr_camera_provider_get_camera_vid(product_id) : 0;
		const int cp = xr_camera_provider_get_camera_pid(product_id);
		printf("camera provider: vid=0x%04X pid=0x%04X\n", cv, cp);
		if (o.camera_provider && cv != 0 && cp != 0) {
			cam = xr_camera_provider_create(cv, cp);
			printf("camera_provider_create -> %s\n", cam ? "ok" : "NULL");
			if (cam != NULL) {
				const int sr = xr_camera_provider_start(cam, stream_frame_cb, NULL);
				printf("camera_provider_start -> %d (is_streaming=%d)\n", sr,
				       xr_camera_provider_is_streaming(cam));
			}
		}
	}
	if (h == NULL) {
		fprintf(stderr, "xr_device_provider_create failed for pid 0x%04X\n", product_id);
		return 1;
	}

	int ret = xr_device_provider_set_dof_type_carina(h, o.sixdof ? 1 : 0);
	printf("set_dof_type_carina(%d) -> %d\n", o.sixdof ? 1 : 0, ret);

	/* The Android app passes a cache directory here (it also caches VIO data) and calls
	 * set_auto_exposure_carina after start; those are the only structural differences
	 * from the host tool that produced identity poses in 6DoF. */
	ret = xr_device_provider_initialize(h, NULL, o.cache);
	printf("initialize(cache=%s) -> %d\n", o.cache ? o.cache : "(null)", ret);
	if (ret != VITURE_GLASSES_SUCCESS) {
		xr_device_provider_destroy(h);
		return 1;
	}

	/*
	 * The stereo camera callback MUST be registered before start(): the Carina VIO
	 * engine captures the callback pointer at start time. Without it the VIO has no
	 * images to solve from, and get_gl_pose_carina then returns an identity pose
	 * flagged 'unstable' forever -- measured as 10798/10798 unstable samples with
	 * every component exactly zero, over 90 s, while the glasses were being moved.
	 * This is the sequence the vendor's own demo uses (glasses-demo carina_start()).
	 */
	ret = xr_device_provider_register_callbacks_carina(h, pose_cb, vsync_cb, imu_cb, camera_frame_cb);
	printf("register_callbacks_carina(pose, vsync, imu, camera) -> %d\n", ret);
	if (ret != VITURE_GLASSES_SUCCESS) {
		fprintf(stderr, "warning: no camera callback registered; the VIO will have no input\n");
	}

	/* Diagnostic: dump the first few callback payloads next to a polled pose, so the
	 * payload layout can be identified rather than guessed. */
	if (o.pose_cb) {
		fprintf(stderr, "waiting for pose callback payloads...\n");
	}

	ret = xr_device_provider_start(h);
	printf("start -> %d\n", ret);
	if (ret != VITURE_GLASSES_SUCCESS) {
		xr_device_provider_destroy(h);
		return 1;
	}
	if (o.auto_exposure) {
		const int ae = xr_device_provider_set_auto_exposure_carina(h);
		printf("set_auto_exposure_carina -> %d\n", ae);
	}

	printf("device_type=%d (2 == XR_DEVICE_TYPE_VITURE_CARINA)\n", xr_device_provider_get_device_type(h));

	if (o.native_probe) {
		/*
		 * Opt-in, because these block on devices that do not implement native
		 * mode: on the Carina Luma Ultra the query never returns. Only ask when
		 * the caller knows what they are probing.
		 */
		printf("native: state=%d display=%d\n", xr_device_provider_native_get_mode(h),
		       xr_device_provider_native_get_display_mode(h));
	}

	if (o.have_set_mode || o.get_mode) {
		const int before = xr_device_provider_get_display_mode(h);
		if (o.get_mode) {
			printf("display mode: standard=0x%02X (%s)\n", before,
			       viture_mode_lookup(before) ? viture_mode_lookup(before)->name : "unknown");
		}

		if (o.have_set_mode) {
			const struct viture_mode_info *m = viture_mode_lookup(o.set_mode);
			const int sr = xr_device_provider_set_display_mode(h, o.set_mode);
			if (sr == VITURE_GLASSES_SUCCESS) {
				printf("set(0x%02X, %s) -> ok\n", o.set_mode, m ? m->name : "?");
			} else {
				printf("set(0x%02X, %s) -> %d (refused)\n", o.set_mode, m ? m->name : "?", sr);
				printf("  A pinned device refuses every set (during bring-up every set returned\n"
				       "  -3 until the glasses were replugged). Read-back is also\n"
				       "  asynchronous: re-query, and check whether X re-presented the timing.\n");
			}
		}

		if (o.get_mode) {
			if (cam != NULL) {
		xr_camera_provider_stop(cam);
		xr_camera_provider_destroy(cam);
	}
	xr_device_provider_stop(h);
			xr_device_provider_shutdown(h);
			xr_device_provider_destroy(h);
			return 0;
		}
	}

	if (o.reset) {
		float pose[VITURE_POSE_COUNT] = {0};
		int status = -1;
		xr_device_provider_get_gl_pose_carina(h, pose, 0.0, &status);
		printf("reset_origin_carina -> %d\n", xr_device_provider_reset_origin_carina(h, pose));
	}

	/* ---- sampling loop ---- */
	unsigned long long n = 0, unstable = 0, failures = 0;
	double t0 = now_s();
	double first = 0.0, last = 0.0;
	double dt_min = 1e9, dt_max = 0.0, dt_sum = 0.0;
	double px_min = 1e9, px_max = -1e9, py_min = 1e9, py_max = -1e9, pz_min = 1e9, pz_max = -1e9;
	double max_ang_step = 0.0;
	double yaw_min = 1e9, yaw_max = -1e9, pitch_min = 1e9, pitch_max = -1e9, roll_min = 1e9, roll_max = -1e9;
	unsigned long long stable = 0;
	float prev[VITURE_POSE_COUNT] = {0};
	bool have_prev = false;
	const double interval = o.rate_hz > 0.0 ? 1.0 / o.rate_hz : 0.0;
	double next_t = now_s();

	while (now_s() - t0 < o.seconds) {
		float pose[VITURE_POSE_COUNT] = {0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f};
		int status = -1;
		const double t = now_s();
		int r;
		if (o.src_cb) {
			/* Callback payload is [qw,qx,qy,qz, px,py,pz]; this tool's internal layout is
			 * [px,py,pz, qw,qx,qy,qz] (the GL pose order), so reorder. No status field is
			 * provided by the callback, and it is gravity-referenced and stable, so treat a
			 * flowing callback as stable. */
			const float *raw = g_cb_pose;
			pose[0] = raw[4];
			pose[1] = raw[5];
			pose[2] = raw[6];
			pose[3] = raw[0];
			pose[4] = raw[1];
			pose[5] = raw[2];
			pose[6] = raw[3];
			status = 0;
			r = __atomic_load_n(&g_cb_count, __ATOMIC_RELAXED) > 0 ? VITURE_GLASSES_SUCCESS : -1;
		} else {
			r = xr_device_provider_get_gl_pose_carina(h, pose, o.predict_s, &status);
		}
		if (o.flip_xy) {
			/* Handedness fix: negate the quaternion's x and y. That conjugates the
			 * rotation by 180 deg about z, which inverts yaw and pitch and preserves
			 * roll -- exactly the correction the operator reported was needed, because
			 * the SDK's GL pose has z pointing backward (right-handed) while the demo
			 * renderer looks down +z. */
			pose[4] = -pose[4];
			pose[5] = -pose[5];
		}

		if (o.pose_cb && (n % 4) == 0) {
			printf("  #%llu polled p/an=(%.4f %.4f %.4f) q=(%.4f %.4f %.4f %.4f)\n", n, pose[0], pose[1],
			       pose[2], pose[3], pose[4], pose[5], pose[6]);
			printf("  #%llu cbp    raw=(%.4f %.4f %.4f %.4f %.4f %.4f %.4f)  cb_invocations=%llu\n", n,
			       g_cb_pose[0], g_cb_pose[1], g_cb_pose[2], g_cb_pose[3], g_cb_pose[4], g_cb_pose[5],
			       g_cb_pose[6], (unsigned long long)__atomic_load_n(&g_cb_count, __ATOMIC_RELAXED));
		}

		if (r != VITURE_GLASSES_SUCCESS) {
			failures++;
		} else {
			double yaw, pitch, roll;
			quat_to_euler_deg(pose, &yaw, &pitch, &roll);
			if (status != 0) {
				unstable++;
			} else {
				stable++;
			}

			if (yaw < yaw_min) yaw_min = yaw;
			if (yaw > yaw_max) yaw_max = yaw;
			if (pitch < pitch_min) pitch_min = pitch;
			if (pitch > pitch_max) pitch_max = pitch;
			if (roll < roll_min) roll_min = roll;
			if (roll > roll_max) roll_max = roll;

			if (n > 0) {
				const double dt = t - last;
				dt_sum += dt;
				if (dt < dt_min) {
					dt_min = dt;
				}
				if (dt > dt_max) {
					dt_max = dt;
				}
			}
			if (n == 0) {
				first = t;
			}
			last = t;

			if (pose[0] < px_min) px_min = pose[0];
			if (pose[0] > px_max) px_max = pose[0];
			if (pose[1] < py_min) py_min = pose[1];
			if (pose[1] > py_max) py_max = pose[1];
			if (pose[2] < pz_min) pz_min = pose[2];
			if (pose[2] > pz_max) pz_max = pose[2];

			if (have_prev) {
				double dot = fabs((double)prev[3] * pose[3] + (double)prev[4] * pose[4] +
				                  (double)prev[5] * pose[5] + (double)prev[6] * pose[6]);
				if (dot > 1.0) {
					dot = 1.0;
				}
				const double step = 2.0 * acos(dot) * 180.0 / M_PI;
				if (step > max_ang_step) {
					max_ang_step = step;
				}
			}
			memcpy(prev, pose, sizeof(prev));
			have_prev = true;
			n++;

			if (o.json) {
				printf("{\"t\":%.6f,\"px\":%.6f,\"py\":%.6f,\"pz\":%.6f,"
				       "\"qw\":%.6f,\"qx\":%.6f,\"qy\":%.6f,\"qz\":%.6f,"
				       "\"yaw\":%.3f,\"pitch\":%.3f,\"roll\":%.3f,\"status\":%d,\"ok\":1}\n",
				       t - t0, pose[0], pose[1], pose[2], pose[3], pose[4], pose[5], pose[6], yaw, pitch,
				       roll, status);
			} else if (!o.quiet) {
				printf("t=%7.3f  p=(%+7.4f %+7.4f %+7.4f)  q=(%+.4f %+.4f %+.4f %+.4f)  "
				       "ypr=(%+7.2f %+7.2f %+7.2f)  %s\n",
				       t - t0, pose[0], pose[1], pose[2], pose[3], pose[4], pose[5], pose[6], yaw, pitch,
				       roll, status_name(status));
			}
			fflush(stdout);
		}

		if (interval > 0.0) {
			next_t += interval;
			const double sleep_s = next_t - now_s();
			if (sleep_s > 0.0) {
				struct timespec ts = {.tv_sec = (time_t)sleep_s,
				                      .tv_nsec = (long)((sleep_s - (double)(time_t)sleep_s) * 1e9)};
				nanosleep(&ts, NULL);
			}
		}
	}

	const double elapsed = last - first;
	printf("\n---- summary ----\n");
	printf("samples=%llu  failures=%llu  unstable=%llu\n", n, failures, unstable);
	if (n > 1 && elapsed > 0.0) {
		printf("measured rate=%.2f Hz over %.3f s (requested %.1f Hz)\n", (double)(n - 1) / elapsed, elapsed,
		       o.rate_hz);
		printf("interval: min=%.3f ms mean=%.3f ms max=%.3f ms\n", dt_min * 1000.0,
		       (dt_sum / (double)(n - 1)) * 1000.0, dt_max * 1000.0);
	}
	printf("position spread (device units): x=%.5f y=%.5f z=%.5f\n", px_max - px_min, py_max - py_min,
	       pz_max - pz_min);
	printf("max orientation step between samples=%.3f deg\n", max_ang_step);
	{
		const unsigned long long frames = __atomic_load_n(&g_cam_frames, __ATOMIC_RELAXED);
		const int cw = __atomic_load_n(&g_cam_w, __ATOMIC_RELAXED);
		const int ch = __atomic_load_n(&g_cam_h, __ATOMIC_RELAXED);
		{
			const unsigned long long pcb = __atomic_load_n(&g_cb_count, __ATOMIC_RELAXED);
			printf("pose callback invocations: %llu", pcb);
			if (pcb > 0) {
				printf(" (last: p=(%.3f %.3f %.3f) q=(%.3f %.3f %.3f %.3f))", g_cb_pose[0],
				       g_cb_pose[1], g_cb_pose[2], g_cb_pose[3], g_cb_pose[4], g_cb_pose[5], g_cb_pose[6]);
			}
			printf("\n");
		}
		printf("vsync callbacks: %llu   imu callbacks: %llu\n",
		       (unsigned long long)__atomic_load_n(&g_vsync_count, __ATOMIC_RELAXED),
		       (unsigned long long)__atomic_load_n(&g_imu_count, __ATOMIC_RELAXED));
		printf("camera provider frames: %llu", (unsigned long long)g_stream_frames);
		if (g_stream_frames > 0) {
			printf(" (%dx%d)", g_stream_w, g_stream_h);
		}
		printf("\n");
		printf("stereo camera frames delivered: %llu", frames);
		if (frames > 0) {
			printf(" (%dx%d, %.1f fps)\n", cw, ch, (double)frames / (elapsed > 0.0 ? elapsed : 1.0));
		} else {
			printf("\n  NO camera frames: the VIO has no input at all, so every pose will\n"
			       "  be identity+unstable no matter how the glasses move. The stereo camera\n"
			       "  callback must be registered before start().\n");
		}
	}
	if (n > 0) {
		printf("pose status: stable=%llu unstable=%llu (%.1f%% stable)\n", stable, unstable,
		       100.0 * (double)stable / (double)n);
		printf("orientation range (deg): yaw=%.2f..%.2f  pitch=%.2f..%.2f  roll=%.2f..%.2f\n", yaw_min,
		       yaw_max, pitch_min, pitch_max, roll_min, roll_max);
		if (stable == 0) {
			printf("  NO stable sample in this run: the VIO has not converged, so any HMD\n"
			       "  orientation from this stream is meaningless. Point the glasses at a lit,\n"
			       "  textured scene and move them a little, then run again.\n");
		} else if (yaw_max - yaw_min < 1.0 && pitch_max - pitch_min < 1.0 && roll_max - roll_min < 1.0) {
			printf("  Poses are stable but nothing moved: turn/nod/tilt the glasses and rerun to\n"
			       "  check signs and axes.\n");
		}
	}
	printf("\nInterpretation notes:\n");
	printf("  * position spread while the head is still = noise floor of the VIO.\n");
	printf("  * the vendor headers do NOT state the unit of the position component;\n");
	printf("    translate the head by a measured 10 cm and read the spread to\n");
	printf("    calibrate VITURE_POSITION_SCALE (see docs/measurements.md).\n");
	printf("  * signature check: yaw must change when turning the head left/right,\n");
	printf("    pitch on nodding, roll on tilting. Any inverted axis is a mapping bug.\n");

	xr_device_provider_stop(h);
	xr_device_provider_shutdown(h);
	xr_device_provider_destroy(h);
	return 0;
}
