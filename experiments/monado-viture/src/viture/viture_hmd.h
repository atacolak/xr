// SPDX-License-Identifier: BSL-1.0
/*!
 * @file
 * @brief  VITURE glasses HMD device.
 * @ingroup drv_viture
 */

#pragma once

#include <stdbool.h>

#include "xrt/xrt_device.h"

#include "util/u_logging.h"

#include "viture_pose.h"

/*!
 * Panel timing description (viture_modes.h). Only ever held by pointer here, so
 * consumers of this header do not need the vendor include path.
 */
struct viture_mode_info;

#ifdef __cplusplus
extern "C" {
#endif

/*!
 * Driver configuration.
 *
 * Everything that is not known from a datasheet lives here, with a documented
 * default, so the unknowns are greppable instead of buried in the code.
 *
 * @ingroup drv_viture
 */
struct viture_config
{
	//! Panel timing to command/expect.
	const struct viture_mode_info *mode;

	//! Command the panel timing over USB at start.
	bool set_display_mode;

	//! 6DoF (translation + orientation) versus 3DoF (orientation only).
	bool sixdof;

	//! Reset the VIO origin at start so the head starts near the frame origin.
	bool reset_origin;

	//! Software IPD / lens separation, metres. UNVERIFIED default, see docs.
	float ipd_meters;

	//! Per-eye horizontal FOV, degrees. UNVERIFIED default, see docs.
	float fov_h_deg;

	//! Nominal virtual image distance, metres (physical size derivation only).
	float image_distance_m;

	/*!
	 * Multiplier applied to the vendor translation component before it is
	 * published as metres. The SDK does not document the unit of that
	 * component; see docs/measurements.md for the calibration procedure.
	 */
	float position_scale;

	//! Where the vendor SDK may cache calibration data.
	const char *cache_dir;

	//! Axis remap applied to the vendor pose.
	enum viture_axes axes;

	//! Skip the vendor SDK entirely and report an identity pose (bring-up).
	bool no_sdk;
};

/*!
 * Documented defaults (also see docs/coordinates.md for the unknowns).
 * @ingroup drv_viture
 */
void
viture_config_defaults(struct viture_config *cfg);

/*!
 * Read `VITURE_*` environment overrides on top of the defaults.
 * @ingroup drv_viture
 */
void
viture_config_from_env(struct viture_config *cfg);

/*!
 * Create the HMD for an attached product.
 *
 * @param product_id Vendor product id (see viture_enumerate_product_ids).
 * @param cfg        Configuration; NULL means defaults plus environment.
 * @return The device, or NULL on failure (already logged).
 * @ingroup drv_viture
 */
struct xrt_device *
viture_hmd_create(int product_id, const struct viture_config *cfg);

/*!
 * @dir drivers/viture
 * @ingroup drv_viture
 */

#ifdef __cplusplus
}
#endif
