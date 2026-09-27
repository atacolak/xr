// SPDX-License-Identifier: BSL-1.0
/*!
 * @file
 * @brief  VITURE Carina -> Monado pose conversion.
 *
 * Kept in its own translation unit, depending only on Monado's public headers,
 * so the mapping can be unit-tested on a workstation with no glasses attached
 * (tests/test_coordinates.c).
 *
 * @ingroup drv_viture
 */

#pragma once

#include "xrt/xrt_defines.h"

#include "viture_pose_layout.h"

#ifdef __cplusplus
extern "C" {
#endif

/*!
 * Convert a raw vendor Carina pose into a Monado space relation.
 *
 * Position and orientation are copied verbatim for VITURE_AXES_IDENTITY; the
 * quaternion is normalised defensively, because a denormal quaternion reaching
 * the compositor produces a garbage view matrix.
 *
 * @param pose       Vendor pose, VITURE_POSE_COUNT floats.
 * @param sixdof     Whether to mark position as valid/tracked.
 * @param stable     Vendor pose status: false means the VIO reported an
 *                   unstable sample (typically just after start). The pose is
 *                   still reported, but without the TRACKED bits, so an
 *                   application can observe the difference instead of being
 *                   told a lie.
 * @param axes       Axis remap to apply.
 * @param position_scale Multiplier applied to the translation. The vendor
 *                   documentation does not state the unit of the translation
 *                   component, so this stays an explicit measured constant
 *                   rather than a silent assumption. 1.0 means pass through;
 *                   see docs/measurements.md.
 * @param out_relation Filled in.
 * @ingroup drv_viture
 */
void
viture_carina_to_space_relation(const float pose[VITURE_POSE_COUNT],
                                bool sixdof,
                                bool stable,
                                enum viture_axes axes,
                                float position_scale,
                                struct xrt_space_relation *out_relation);

#ifdef __cplusplus
}
#endif
