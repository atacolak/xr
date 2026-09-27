// SPDX-License-Identifier: BSL-1.0
/*!
 * @file
 * @brief  VITURE panel timing / stereo mode table.
 *
 * The glasses expose a fixed set of panel timings. In the 3D entries the panel
 * accepts a single side-by-side frame of twice the width; that is how stereo
 * is delivered to the user. These are *all* the modes this driver knows about
 * and no attempt is made to invent intermediate timings.
 *
 * Vendor ids come from viture_protocol_public.h so there is exactly one source
 * of truth for the constants.
 *
 * @ingroup drv_viture
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "viture_protocol_public.h"

/*!
 * One panel timing the device accepts.
 *
 * @ingroup drv_viture
 */
struct viture_mode_info
{
	//! Vendor display mode id (passed to xr_device_provider_set_display_mode).
	int vendor_mode;

	//! Total horizontal pixels across the panel(s).
	uint32_t total_w;

	//! Vertical pixels.
	uint32_t total_h;

	//! 2 for side-by-side stereo, 1 for a plain 2D panel.
	uint32_t view_count;

	//! Nominal refresh rate in Hz.
	float fps;

	//! Human-readable name, for logs and docs.
	const char *name;
};

/*!
 * Look up a mode by vendor id, or NULL if unknown.
 * @ingroup drv_viture
 */
const struct viture_mode_info *
viture_mode_lookup(int vendor_mode);

/*!
 * Look up a mode by its name (case-insensitive), for environment overrides.
 * @ingroup drv_viture
 */
const struct viture_mode_info *
viture_mode_by_name(const char *name);

/*!
 * The default mode for XR use: side-by-side stereo at the highest refresh the
 * Carina generation accepts.
 * @ingroup drv_viture
 */
const struct viture_mode_info *
viture_mode_default(void);

/*!
 * Per-eye pixel extents for a mode.
 * @ingroup drv_viture
 */
void
viture_mode_per_eye(const struct viture_mode_info *mode, uint32_t *w, uint32_t *h);
