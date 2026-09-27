// SPDX-License-Identifier: BSL-1.0
/*!
 * @file
 * @brief  VITURE Carina -> Monado pose conversion.
 * @ingroup drv_viture
 */

#include "viture_pose.h"

#include <math.h>
#include <string.h>

enum viture_axes
viture_axes_from_string(const char *name)
{
	if (name == NULL) {
		return VITURE_AXES_IDENTITY;
	}
	if (strcmp(name, "flip-z") == 0 || strcmp(name, "z") == 0) {
		return VITURE_AXES_FLIP_Z;
	}
	if (strcmp(name, "flip-x") == 0 || strcmp(name, "x") == 0) {
		return VITURE_AXES_FLIP_X;
	}
	if (strcmp(name, "flip-y") == 0 || strcmp(name, "y") == 0) {
		return VITURE_AXES_FLIP_Y;
	}
	return VITURE_AXES_IDENTITY;
}

void
viture_carina_to_space_relation(const float pose[VITURE_POSE_COUNT],
                                bool sixdof,
                                bool stable,
                                enum viture_axes axes,
                                float position_scale,
                                struct xrt_space_relation *out_relation)
{
	struct xrt_space_relation relation = XRT_SPACE_RELATION_ZERO;

	float px = pose[VITURE_POSE_PX];
	float py = pose[VITURE_POSE_PY];
	float pz = pose[VITURE_POSE_PZ];

	float qx = pose[VITURE_POSE_QX];
	float qy = pose[VITURE_POSE_QY];
	float qz = pose[VITURE_POSE_QZ];
	float qw = pose[VITURE_POSE_QW];

	switch (axes) {
	case VITURE_AXES_FLIP_Z:
		pz = -pz;
		// Negating one axis of a right-handed frame flips handedness; the
		// quaternion is corrected the same way (z component negated).
		qz = -qz;
		break;
	case VITURE_AXES_FLIP_X:
		px = -px;
		qx = -qx;
		break;
	case VITURE_AXES_FLIP_Y:
		py = -py;
		qy = -qy;
		break;
	case VITURE_AXES_IDENTITY: break;
	}

	relation.pose.position.x = px * position_scale;
	relation.pose.position.y = py * position_scale;
	relation.pose.position.z = pz * position_scale;
	relation.pose.orientation.x = qx;
	relation.pose.orientation.y = qy;
	relation.pose.orientation.z = qz;
	relation.pose.orientation.w = qw;

	// Defensive: a non-normalised quaternion is a corrupt view matrix.
	const float len2 = qx * qx + qy * qy + qz * qz + qw * qw;
	if (len2 > 0.000001f) {
		const float inv = 1.0f / sqrtf(len2);
		relation.pose.orientation.x *= inv;
		relation.pose.orientation.y *= inv;
		relation.pose.orientation.z *= inv;
		relation.pose.orientation.w *= inv;
	} else {
		relation.pose.orientation.x = 0.0f;
		relation.pose.orientation.y = 0.0f;
		relation.pose.orientation.z = 0.0f;
		relation.pose.orientation.w = 1.0f;
	}

	/*
	 * Monado models "unknown" as a cleared VALID bit; there are no INVALID
	 * flag bits. Nothing we do not actually know is ever advertised.
	 */
	enum xrt_space_relation_flags flags = XRT_SPACE_RELATION_ORIENTATION_VALID_BIT;
	if (stable) {
		flags |= XRT_SPACE_RELATION_ORIENTATION_TRACKED_BIT;
	}
	if (sixdof) {
		flags |= XRT_SPACE_RELATION_POSITION_VALID_BIT;
		if (stable) {
			flags |= XRT_SPACE_RELATION_POSITION_TRACKED_BIT;
		}
	}
	relation.relation_flags = flags;

	*out_relation = relation;
}
