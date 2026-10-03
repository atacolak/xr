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
	        "  --native-probe   also query native (Gen2) mode state; BLOCKS on Carina\n"
	        "  --reset          reset the VIO origin before sampling\n"
	        "  --3dof           select 3DoF instead of 6DoF\n"
	        "  --json           emit one JSON object per sample\n"
	        "  --quiet          summary only\n"
	        "  --list-modes     print the known display modes and exit\n"
	        "  --help\n",
	        argv0);
}

/*! Polar decomposition of a quaternion into degrees of yaw/pitch/roll (ZYX). */
static void
quat_to_euler_deg(const float q[7], double *yaw, double *pitch, double *roll)
{
	const double w = q[3], x = q[4], y = q[5], z = q[6];
	const double sinr_cosp = 2.0 * (w * x + y * z);
	const double cosr_cosp = 1.0 - 2.0 * (x * x + y * y);
	*roll = atan2(sinr_cosp, cosr_cosp) * 180.0 / M_PI;

	double sinp = 2.0 * (w * y - z * x);
	if (sinp > 1.0) {
		sinp = 1.0;
	} else if (sinp < -1.0) {
		sinp = -1.0;
	}
	*pitch = asin(sinp) * 180.0 / M_PI;

	const double siny_cosp = 2.0 * (w * z + x * y);
	const double cosy_cosp = 1.0 - 2.0 * (y * y + z * z);
	*yaw = atan2(siny_cosp, cosy_cosp) * 180.0 / M_PI;
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
	if (h == NULL) {
		fprintf(stderr, "xr_device_provider_create failed for pid 0x%04X\n", product_id);
		return 1;
	}

	int ret = xr_device_provider_set_dof_type_carina(h, o.sixdof ? 1 : 0);
	printf("set_dof_type_carina(%d) -> %d\n", o.sixdof ? 1 : 0, ret);

	ret = xr_device_provider_initialize(h, NULL, NULL);
	printf("initialize -> %d\n", ret);
	if (ret != VITURE_GLASSES_SUCCESS) {
		xr_device_provider_destroy(h);
		return 1;
	}

	ret = xr_device_provider_start(h);
	printf("start -> %d\n", ret);
	if (ret != VITURE_GLASSES_SUCCESS) {
		xr_device_provider_destroy(h);
		return 1;
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
		const int r = xr_device_provider_get_gl_pose_carina(h, pose, o.predict_s, &status);

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
