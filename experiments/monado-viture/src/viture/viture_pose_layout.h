// SPDX-License-Identifier: BSL-1.0
/*!
 * @file
 * @brief  Layout of the raw vendor pose buffer, and the axis-remap selector.
 *
 * Deliberately free of any Monado dependency: this is a fact about the vendor
 * API, and diagnostics that do not link Monado (tools/viture-pose-dump) need it.
 * The conversion into Monado types lives in viture_pose.h.
 *
 * @ingroup drv_viture
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*!
 * Index layout of the vendor pose buffer.
 *
 * `xr_device_provider_get_gl_pose_carina()` documents:
 *
 *     [px, py, pz, qw, qx, qy, qz]
 *
 * in the OpenGL coordinate system (x -> right, y -> up, z -> backward), which is
 * the same axis convention OpenXR uses (right-handed, +Y up, -Z forward).
 */
#define VITURE_POSE_PX 0
#define VITURE_POSE_PY 1
#define VITURE_POSE_PZ 2
#define VITURE_POSE_QW 3
#define VITURE_POSE_QX 4
#define VITURE_POSE_QY 5
#define VITURE_POSE_QZ 6
#define VITURE_POSE_COUNT 7

/*!
 * Optional axis remap applied on top of the vendor pose.
 *
 * The vendor frame and the OpenXR frame already agree, so VITURE_AXES_IDENTITY
 * is the expected configuration. The alternatives exist so that a measurement
 * pass can characterise a unit without a rebuild; they are not guesses.
 */
enum viture_axes
{
	VITURE_AXES_IDENTITY = 0,
	//! Negate the forward axis (z).
	VITURE_AXES_FLIP_Z,
	//! Negate the right axis (x).
	VITURE_AXES_FLIP_X,
	//! Negate up (y).
	VITURE_AXES_FLIP_Y,
};

/*!
 * Parse an axes name from `VITURE_POSE_AXES`. NULL/unknown input yields
 * VITURE_AXES_IDENTITY.
 */
enum viture_axes
viture_axes_from_string(const char *name);

#ifdef __cplusplus
}
#endif
