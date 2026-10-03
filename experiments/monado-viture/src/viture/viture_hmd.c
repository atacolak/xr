// SPDX-License-Identifier: BSL-1.0
/*!
 * @file
 * @brief  VITURE glasses HMD device.
 *
 * The device is unusual for a Monado driver in one respect: it does not talk to
 * the hardware protocol itself. The vendor SDK owns the USB transport and the
 * VIO, and hands back a fused pose with a prediction parameter. So this driver
 * is a policy layer:
 *
 *   - it decides *when* to ask for a pose and how far ahead to predict,
 *   - it declares the panel geometry to the compositor,
 *   - it maps the vendor pose into Monado's frames and flags.
 *
 * Deliberately absent: a packet parser, an IMU fusion filter, and any claim of
 * tracking we did not receive.
 *
 * @ingroup drv_viture
 */

#include "viture_hmd.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "os/os_time.h"
#include "os/os_threading.h"

#include "math/m_api.h"
#include "math/m_mathinclude.h"

#include "util/u_debug.h"
#include "util/u_device.h"
#include "util/u_distortion_mesh.h"
#include "util/u_logging.h"
#include "util/u_misc.h"
#include "util/u_time.h"
#include "util/u_var.h"

#include "viture_device_carina.h"
#include "viture_glasses_provider.h"
#include "viture_macros_public.h"
#include "viture_protocol_public.h"
#include "viture_result.h"
#include "viture_compat.h"

#include "viture_interface.h"
#include "viture_modes.h"

//! Never predict further ahead than this, whatever the compositor asks.
#define VITURE_MAX_PREDICT_S 0.050

//! Vendor pose status: 0 == stable, anything else == unstable.
#define VITURE_POSE_STATUS_STABLE 0

/*!
 * Degrees to radians.
 *
 * Monado exposes no shared macro for this (and MATH_DEG_TO_RAD does not exist),
 * so it is spelled out once here rather than inlined at each use.
 */
static inline float
viture_deg_to_rad(float deg)
{
	return deg * (float)(M_PI / 180.0);
}

/*!
 * The device.
 *
 * @implements xrt_device
 */
struct viture_hmd
{
	struct xrt_device base;

	//! Vendor SDK handle, NULL in VITURE_NO_SDK bring-up mode.
	XRDeviceProviderHandle provider;

	int product_id;
	char market_name[64];

	struct viture_config cfg;
	enum u_logging_level log_level;

	//! Serialises vendor calls against teardown.
	struct os_mutex mutex;

	//! Cached relation, used when a poll fails mid-stream.
	struct xrt_space_relation last_relation;
	bool has_relation;

	// Counters, surfaced through u_var for live debugging.
	uint64_t pose_samples;
	uint64_t pose_errors;
	uint64_t unstable_samples;
	int last_status;
	int reported_display_mode;
	timepoint_ns first_sample_ns;
	timepoint_ns last_sample_ns;
};

static inline struct viture_hmd *
viture_hmd(struct xrt_device *xdev)
{
	return (struct viture_hmd *)xdev;
}

DEBUG_GET_ONCE_LOG_OPTION(viture_log, "VITURE_LOG", U_LOGGING_INFO)
DEBUG_GET_ONCE_OPTION(viture_display_mode, "VITURE_DISPLAY_MODE", NULL)
DEBUG_GET_ONCE_BOOL_OPTION(viture_set_display_mode, "VITURE_SET_DISPLAY_MODE", true)
DEBUG_GET_ONCE_BOOL_OPTION(viture_sixdof, "VITURE_6DOF", true)
DEBUG_GET_ONCE_BOOL_OPTION(viture_reset_origin, "VITURE_RESET_ORIGIN", true)
DEBUG_GET_ONCE_BOOL_OPTION(viture_no_sdk, "VITURE_NO_SDK", false)
DEBUG_GET_ONCE_FLOAT_OPTION(viture_ipd_meters, "VITURE_IPD_METERS", 0.064f)
DEBUG_GET_ONCE_FLOAT_OPTION(viture_fov_h_deg, "VITURE_FOV_H_DEG", 42.0f)
DEBUG_GET_ONCE_FLOAT_OPTION(viture_image_distance_m, "VITURE_IMAGE_DISTANCE_M", 3.0f)
DEBUG_GET_ONCE_FLOAT_OPTION(viture_position_scale, "VITURE_POSITION_SCALE", 1.0f)
DEBUG_GET_ONCE_OPTION(viture_pose_axes, "VITURE_POSE_AXES", NULL)
DEBUG_GET_ONCE_OPTION(viture_cache_dir, "VITURE_CACHE_DIR", NULL)

#define VITURE_TRACE(hmd, ...) U_LOG_XDEV_IFL_T(&hmd->base, hmd->log_level, __VA_ARGS__)
#define VITURE_DEBUG(hmd, ...) U_LOG_XDEV_IFL_D(&hmd->base, hmd->log_level, __VA_ARGS__)
#define VITURE_INFO(hmd, ...) U_LOG_XDEV_IFL_I(&hmd->base, hmd->log_level, __VA_ARGS__)
#define VITURE_WARN(hmd, ...) U_LOG_XDEV_IFL_W(&hmd->base, hmd->log_level, __VA_ARGS__)
#define VITURE_ERROR(hmd, ...) U_LOG_XDEV_IFL_E(&hmd->base, hmd->log_level, __VA_ARGS__)


/*
 *
 * Config.
 *
 */

void
viture_config_defaults(struct viture_config *cfg)
{
	U_ZERO(cfg);

	cfg->mode = viture_mode_default();
	cfg->set_display_mode = true;
	cfg->sixdof = true;
	cfg->reset_origin = true;
	cfg->ipd_meters = 0.064f;
	cfg->fov_h_deg = 42.0f;
	cfg->image_distance_m = 3.0f;
	cfg->position_scale = 1.0f;
	cfg->cache_dir = NULL;
	cfg->axes = VITURE_AXES_IDENTITY;
	cfg->no_sdk = false;
}

static const char *
viture_default_cache_dir(void)
{
	static char buf[512];
	const char *from_env = debug_get_option_viture_cache_dir();
	if (from_env != NULL && from_env[0] != '\0') {
		return from_env;
	}

	const char *xdg = getenv("XDG_CACHE_HOME");
	const char *home = getenv("HOME");
	if (xdg != NULL && xdg[0] != '\0') {
		snprintf(buf, sizeof(buf), "%s/viture", xdg);
	} else if (home != NULL && home[0] != '\0') {
		snprintf(buf, sizeof(buf), "%s/.cache/viture", home);
	} else {
		return NULL;
	}

	return buf;
}

void
viture_config_from_env(struct viture_config *cfg)
{
	viture_config_defaults(cfg);

	const char *mode_name = debug_get_option_viture_display_mode();
	if (mode_name != NULL && mode_name[0] != '\0') {
		const struct viture_mode_info *mode = viture_mode_by_name(mode_name);
		if (mode == NULL) {
			// Also accept a raw vendor mode id, hex or decimal.
			const int raw = (int)strtol(mode_name, NULL, 0);
			mode = viture_mode_lookup(raw);
		}
		if (mode != NULL) {
			cfg->mode = mode;
		}
	}

	cfg->set_display_mode = debug_get_bool_option_viture_set_display_mode();
	cfg->sixdof = debug_get_bool_option_viture_sixdof();
	cfg->reset_origin = debug_get_bool_option_viture_reset_origin();
	cfg->no_sdk = debug_get_bool_option_viture_no_sdk();
	cfg->ipd_meters = debug_get_float_option_viture_ipd_meters();
	cfg->fov_h_deg = debug_get_float_option_viture_fov_h_deg();
	cfg->image_distance_m = debug_get_float_option_viture_image_distance_m();
	cfg->position_scale = debug_get_float_option_viture_position_scale();
	cfg->axes = viture_axes_from_string(debug_get_option_viture_pose_axes());
	cfg->cache_dir = viture_default_cache_dir();
}


/*
 *
 * Pose.
 *
 */

/*!
 * Ask the vendor SDK for a pose and convert it.
 *
 * Caller MUST hold hmd->mutex. os_mutex is NOT recursive (see os_mutex_init in
 * os_threading.h), and every caller here already holds the lock, so taking it
 * again in this function self-deadlocks the instant a provider exists. That is
 * exactly how session creation hung: xrCreateSession -> create_local_space ->
 * locate_space -> get_tracked_pose -> poll_pose -> lock, forever. With no SDK
 * (VITURE_NO_SDK=1) the early provider==NULL return hid the bug, because it
 * happens before the lock in the old code.
 *
 * @param hmd        Device.
 * @param predict_s  Seconds ahead to predict (0 = now).
 * @param out        Filled in on success.
 * @return true if a sample was obtained.
 */
static bool
viture_poll_pose_locked(struct viture_hmd *hmd, double predict_s, struct xrt_space_relation *out)
{
	if (hmd->provider == NULL) {
		return false;
	}

	if (predict_s < 0.0) {
		predict_s = 0.0;
	} else if (predict_s > VITURE_MAX_PREDICT_S) {
		predict_s = VITURE_MAX_PREDICT_S;
	}

	float pose[VITURE_POSE_COUNT] = {0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f};
	int status = 1;

	const int ret = xr_device_provider_get_gl_pose_carina(hmd->provider, pose, predict_s, &status);

	if (ret != VITURE_GLASSES_SUCCESS) {
		hmd->pose_errors++;
		if (hmd->pose_errors == 1 || (hmd->pose_errors % 500) == 0) {
			VITURE_WARN(hmd, "pose query failed: %d (%llu failures)", ret, (unsigned long long)hmd->pose_errors);
		}
		return false;
	}

	const bool stable = status == VITURE_POSE_STATUS_STABLE;
	hmd->last_status = status;
	hmd->pose_samples++;
	if (!stable) {
		hmd->unstable_samples++;
	}

	const timepoint_ns now = os_monotonic_get_ns();
	if (hmd->first_sample_ns == 0) {
		hmd->first_sample_ns = now;
	}
	hmd->last_sample_ns = now;

	viture_carina_to_space_relation(pose, hmd->cfg.sixdof, stable, hmd->cfg.axes, hmd->cfg.position_scale, out);
	return true;
}


/*
 *
 * xrt_device functions.
 *
 */

static xrt_result_t
viture_hmd_update_inputs(struct xrt_device *xdev)
{
	struct viture_hmd *hmd = viture_hmd(xdev);

	struct xrt_space_relation relation = XRT_SPACE_RELATION_ZERO;
	os_mutex_lock(&hmd->mutex);
	const bool ok = viture_poll_pose_locked(hmd, 0.0, &relation);
	if (ok) {
		hmd->last_relation = relation;
		hmd->has_relation = true;
	}
	os_mutex_unlock(&hmd->mutex);

	return XRT_SUCCESS;
}

static xrt_result_t
viture_hmd_get_tracked_pose(struct xrt_device *xdev,
                            enum xrt_input_name name,
                            int64_t at_timestamp_ns,
                            struct xrt_space_relation *out_relation)
{
	struct viture_hmd *hmd = viture_hmd(xdev);

	if (name != XRT_INPUT_GENERIC_HEAD_POSE) {
		U_LOG_XDEV_UNSUPPORTED_INPUT(&hmd->base, hmd->log_level, name);
		return XRT_ERROR_INPUT_UNSUPPORTED;
	}

	/*
	 * The vendor SDK predicts internally, so hand it the prediction interval
	 * rather than extrapolating a stale sample ourselves: that keeps the
	 * prediction model in one place (the vendor's VIO).
	 */
	double predict_s = 0.0;
	if (at_timestamp_ns > 0) {
		const int64_t now = (int64_t)os_monotonic_get_ns();
		predict_s = (double)(at_timestamp_ns - now) / 1000000000.0;
	}

	struct xrt_space_relation relation = XRT_SPACE_RELATION_ZERO;
	os_mutex_lock(&hmd->mutex);
	const bool ok = viture_poll_pose_locked(hmd, predict_s, &relation);
	if (ok) {
		hmd->last_relation = relation;
		hmd->has_relation = true;
		*out_relation = relation;
	} else if (hmd->has_relation) {
		// Keep the last good pose rather than snapping the view to identity.
		*out_relation = hmd->last_relation;
	} else if (hmd->cfg.no_sdk) {
		viture_carina_to_space_relation((const float[]){0, 0, 0, 1, 0, 0, 0}, hmd->cfg.sixdof, true,
		                                hmd->cfg.axes, 1.0f, out_relation);
	}
	os_mutex_unlock(&hmd->mutex);

	return XRT_SUCCESS;
}

static void
viture_hmd_destroy(struct xrt_device *xdev)
{
	struct viture_hmd *hmd = viture_hmd(xdev);

	u_var_remove_root(hmd);

	os_mutex_lock(&hmd->mutex);
	if (hmd->provider != NULL) {
		xr_device_provider_stop(hmd->provider);
		xr_device_provider_shutdown(hmd->provider);
		xr_device_provider_destroy(hmd->provider);
		hmd->provider = NULL;
	}
	os_mutex_unlock(&hmd->mutex);
	os_mutex_destroy(&hmd->mutex);

	u_device_free(&hmd->base);
}


/*
 *
 * Display setup.
 *
 */

/*!
 * Declare the panel geometry to the compositor.
 *
 * The physical sizes are derived from the configured FOV and image distance
 * purely so that Monado's asymmetric-FOV helper has consistent geometry to work
 * with; the angular FOV is the authoritative number, and it is an estimate (see
 * docs/coordinates.md).
 */
static bool
viture_hmd_setup_views(struct viture_hmd *hmd)
{
	const struct viture_mode_info *mode = hmd->cfg.mode;

	uint32_t eye_w = 0;
	uint32_t eye_h = 0;
	viture_mode_per_eye(mode, &eye_w, &eye_h);

	const float per_eye_w_m = 2.0f * hmd->cfg.image_distance_m * tanf(viture_deg_to_rad(hmd->cfg.fov_h_deg) / 2.0f);
	const float per_eye_h_m = per_eye_w_m * ((float)eye_h / (float)eye_w);

	struct u_device_simple_info info;
	U_ZERO(&info);
	info.display.w_pixels = mode->total_w;
	info.display.h_pixels = mode->total_h;
	info.display.w_meters = per_eye_w_m * (float)mode->view_count;
	info.display.h_meters = per_eye_h_m;
	info.lens_horizontal_separation_meters = hmd->cfg.ipd_meters;
	info.lens_vertical_position_meters = 0.0f;
	info.fov[0] = viture_deg_to_rad(hmd->cfg.fov_h_deg);
	info.fov[1] = viture_deg_to_rad(hmd->cfg.fov_h_deg);

	const bool ok = mode->view_count == 2 ? u_device_setup_split_side_by_side(&hmd->base, &info)
	                                      : u_device_setup_one_eye(&hmd->base, &info);
	if (!ok) {
		VITURE_ERROR(hmd, "failed to set up views");
		return false;
	}

	hmd->base.hmd->screens[0].nominal_frame_interval_ns = time_s_to_ns(1.0f / mode->fps);
	return true;
}


/*
 *
 * Vendor SDK bring-up.
 *
 */

static bool
viture_sdk_start(struct viture_hmd *hmd)
{
	hmd->provider = xr_device_provider_create(hmd->product_id);
	if (hmd->provider == NULL) {
		VITURE_ERROR(hmd, "xr_device_provider_create(product_id=0x%04X) failed", hmd->product_id);
		return false;
	}

	const int device_type = xr_device_provider_get_device_type(hmd->provider);
	if (device_type != XR_DEVICE_TYPE_VITURE_CARINA) {
		VITURE_ERROR(hmd, "device type %d is not Carina; this driver needs an IMU pose source", device_type);
		return false;
	}

	// Must happen after create and before initialize.
	const int dof_ret = xr_device_provider_set_dof_type_carina(hmd->provider, hmd->cfg.sixdof ? 1 : 0);
	if (dof_ret != VITURE_GLASSES_SUCCESS) {
		VITURE_ERROR(hmd, "failed to set DOF type: %d", dof_ret);
		return false;
	}

	const int init_ret = xr_device_provider_initialize(hmd->provider, NULL, hmd->cfg.cache_dir);
	if (init_ret != VITURE_GLASSES_SUCCESS) {
		VITURE_ERROR(hmd, "initialize failed: %d", init_ret);
		return false;
	}

	if (xr_device_provider_start(hmd->provider) != VITURE_GLASSES_SUCCESS) {
		VITURE_ERROR(hmd, "start failed");
		return false;
	}

	VITURE_INFO(hmd, "vendor SDK %s ready, %s, device_type=%d", GetVersionString(),
	            hmd->cfg.sixdof ? "6DoF" : "3DoF", device_type);
	return true;
}

static void
viture_sdk_configure_display(struct viture_hmd *hmd)
{
	if (!hmd->cfg.set_display_mode) {
		VITURE_INFO(hmd, "display mode left untouched (VITURE_SET_DISPLAY_MODE=0)");
		return;
	}

	const int want = hmd->cfg.mode->vendor_mode;
	const int ret = xr_device_provider_set_display_mode(hmd->provider, want);
	if (ret != VITURE_GLASSES_SUCCESS) {
		VITURE_WARN(hmd, "set_display_mode(0x%02X, %s) failed: %d — panel timing unchanged", want,
		            hmd->cfg.mode->name, ret);
		return;
	}

	const int got = xr_device_provider_get_display_mode(hmd->provider);
	hmd->reported_display_mode = got;
	if (got != want) {
		VITURE_WARN(hmd, "requested mode 0x%02X (%s) but device reports 0x%02X", want, hmd->cfg.mode->name, got);
	} else {
		VITURE_INFO(hmd, "display mode 0x%02X (%s) confirmed", got, hmd->cfg.mode->name);
	}
}

static void
viture_sdk_recenter(struct viture_hmd *hmd)
{
	if (!hmd->cfg.reset_origin) {
		return;
	}

	float pose[VITURE_POSE_COUNT] = {0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f};
	int status = 1;
	const int get_ret = xr_device_provider_get_gl_pose_carina(hmd->provider, pose, 0.0, &status);
	if (get_ret != VITURE_GLASSES_SUCCESS) {
		VITURE_WARN(hmd, "could not read pose to set the origin: %d", get_ret);
		return;
	}

	/*
	 * Position and yaw become the origin; pitch and roll stay gravity-anchored
	 * by the VIO. This gives OpenXR LOCAL-like semantics: the user starts at
	 * the frame origin, roughly facing -Z, with no tilt faked in.
	 */
	const int ret = xr_device_provider_reset_origin_carina(hmd->provider, pose);
	if (ret != VITURE_GLASSES_SUCCESS) {
		VITURE_WARN(hmd, "reset_origin failed: %d", ret);
		return;
	}

	VITURE_INFO(hmd, "origin set at head position (position+yaw zeroed, pitch/roll untouched)");
}


/*
 *
 * Exported functions.
 *
 */

struct xrt_device *
viture_hmd_create(int product_id, const struct viture_config *cfg)
{
	struct viture_config config;
	if (cfg != NULL) {
		config = *cfg;
	} else {
		viture_config_from_env(&config);
	}
	if (config.mode == NULL) {
		config.mode = viture_mode_default();
	}

	const enum u_device_alloc_flags flags =
	    (enum u_device_alloc_flags)(U_DEVICE_ALLOC_HMD | U_DEVICE_ALLOC_TRACKING_NONE);

	struct viture_hmd *hmd = U_DEVICE_ALLOCATE(struct viture_hmd, flags, 1, 0);
	if (hmd == NULL) {
		return NULL;
	}

	hmd->product_id = product_id;
	hmd->cfg = config;
	hmd->log_level = debug_get_log_option_viture_log();
	hmd->base.update_inputs = viture_hmd_update_inputs;
	hmd->base.get_tracked_pose = viture_hmd_get_tracked_pose;
	hmd->base.get_view_poses = u_device_get_view_poses;
	hmd->base.get_visibility_mask = u_device_get_visibility_mask;

	/*
	 * Distortion: none, because these are BirdBath optics with a pre-corrected
	 * virtual image. Use the setter rather than assigning compute_distortion
	 * directly: the setter also fills in meshuv, and the compositor otherwise
	 * has to fill in the defaults itself and logs a warning about the driver.
	 */
	u_distortion_mesh_set_none(&hmd->base);
	hmd->base.destroy = viture_hmd_destroy;
	hmd->base.name = XRT_DEVICE_GENERIC_HMD;
	hmd->base.device_type = XRT_DEVICE_TYPE_HMD;
	hmd->base.inputs[0].name = XRT_INPUT_GENERIC_HEAD_POSE;
	hmd->base.supported.orientation_tracking = true;
	hmd->base.supported.position_tracking = config.sixdof;

	os_mutex_init(&hmd->mutex);

	// Identity pose from the start so a failed first poll is still sane.
	viture_carina_to_space_relation((const float[]){0, 0, 0, 1, 0, 0, 0}, config.sixdof, true, config.axes,
	                                config.position_scale, &hmd->last_relation);

	char market[64] = {0};
	if (viture_market_name(product_id, market, sizeof(market))) {
		snprintf(hmd->market_name, sizeof(hmd->market_name), "%s", market);
	} else {
		snprintf(hmd->market_name, sizeof(hmd->market_name), "VITURE (pid 0x%04X)", product_id);
	}

	snprintf(hmd->base.str, XRT_DEVICE_NAME_LEN, "%s", hmd->market_name);
	snprintf(hmd->base.serial, XRT_DEVICE_NAME_LEN, "viture-%04x", product_id);

	if (config.no_sdk) {
		/*
		 * Bring-up mode: static HMD, no vendor library touched. This exists so
		 * that compositor and OpenXR enumeration can be validated before any
		 * tracking code is involved. It is NOT a tracking path.
		 */
		VITURE_WARN(hmd, "VITURE_NO_SDK=1: static HMD, no tracking, no vendor SDK");
	} else if (!viture_sdk_start(hmd)) {
		u_device_free(&hmd->base);
		return NULL;
	}

	if (!viture_hmd_setup_views(hmd)) {
		if (hmd->provider != NULL) {
			xr_device_provider_destroy(hmd->provider);
			hmd->provider = NULL;
		}
		u_device_free(&hmd->base);
		return NULL;
	}

	if (hmd->provider != NULL) {
		viture_sdk_configure_display(hmd);
		viture_sdk_recenter(hmd);
	}

	// Debug variables: live counters without a debugger.
	u_var_add_root(hmd, hmd->market_name, true);
	u_var_add_log_level(hmd, &hmd->log_level, "log_level");
	u_var_add_ro_u64(hmd, &hmd->pose_samples, "pose_samples");
	u_var_add_ro_u64(hmd, &hmd->pose_errors, "pose_errors");
	u_var_add_ro_u64(hmd, &hmd->unstable_samples, "unstable_samples");
	u_var_add_ro_i32(hmd, &hmd->last_status, "last_pose_status");
	u_var_add_ro_i32(hmd, &hmd->reported_display_mode, "reported_display_mode");
	u_var_add_gui_header(hmd, NULL, "config");
	u_var_add_ro_f32(hmd, &hmd->cfg.ipd_meters, "ipd_meters");
	u_var_add_ro_f32(hmd, &hmd->cfg.fov_h_deg, "fov_h_deg");

	if (hmd->log_level <= U_LOGGING_DEBUG) {
		u_device_dump_config(&hmd->base, __func__, hmd->market_name);
	}

	VITURE_INFO(hmd, "created: %s, panel %s (%ux%u total, %u view(s), %.0f Hz)", hmd->market_name,
	            config.mode->name, config.mode->total_w, config.mode->total_h, config.mode->view_count,
	            config.mode->fps);

	return &hmd->base;
}
