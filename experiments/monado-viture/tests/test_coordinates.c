// SPDX-License-Identifier: BSL-1.0
/*!
 * @file
 * @brief  Offline tests for the Carina -> Monado pose mapping.
 *
 * These must pass with no glasses, no vendor library and no Monado build: they
 * only exercise the pure conversion, which is where an axis or quaternion-order
 * mistake would silently ruin every downstream milestone.
 *
 * Build and run with scripts/test-coordinates.
 */

#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "viture_pose.h"

static int g_failures;
static int g_checks;

#define CHECK(cond, ...)                                                                                               \
	do {                                                                                                           \
		g_checks++;                                                                                            \
		if (!(cond)) {                                                                                         \
			g_failures++;                                                                                  \
			printf("FAIL %s:%d: ", __func__, __LINE__);                                                     \
			printf(__VA_ARGS__);                                                                           \
			printf("\n");                                                                                  \
		}                                                                                                      \
	} while (0)

#define EPS 0.0005f

static bool
near(float a, float b)
{
	return fabsf(a - b) < EPS;
}

static void
test_identity_passthrough(void)
{
	const float pose[VITURE_POSE_COUNT] = {0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f};
	struct xrt_space_relation rel;

	viture_carina_to_space_relation(pose, true, true, VITURE_AXES_IDENTITY, 1.0f, &rel);

	CHECK(near(rel.pose.orientation.w, 1.0f), "identity w=%f", rel.pose.orientation.w);
	CHECK(near(rel.pose.orientation.x, 0.0f), "identity x=%f", rel.pose.orientation.x);
	CHECK(near(rel.pose.orientation.y, 0.0f), "identity y=%f", rel.pose.orientation.y);
	CHECK(near(rel.pose.orientation.z, 0.0f), "identity z=%f", rel.pose.orientation.z);
	CHECK((rel.relation_flags & XRT_SPACE_RELATION_ORIENTATION_VALID_BIT) != 0, "orientation valid bit");
	CHECK((rel.relation_flags & XRT_SPACE_RELATION_ORIENTATION_TRACKED_BIT) != 0, "orientation tracked bit");
	CHECK((rel.relation_flags & XRT_SPACE_RELATION_POSITION_VALID_BIT) != 0, "position valid bit in 6dof");
}

/*! Quaternion component order must be (w, x, y, z) in the vendor buffer. */
static void
test_component_order(void)
{
	// 90 degrees about +Y (right-handed): q = (w=cos45, y=sin45)
	const float pose[VITURE_POSE_COUNT] = {0.0f, 0.0f, 0.0f, 0.70710678f, 0.0f, 0.70710678f, 0.0f};
	struct xrt_space_relation rel;

	viture_carina_to_space_relation(pose, false, true, VITURE_AXES_IDENTITY, 1.0f, &rel);

	CHECK(near(rel.pose.orientation.w, 0.70710678f), "w=%f", rel.pose.orientation.w);
	CHECK(near(rel.pose.orientation.y, 0.70710678f), "y=%f", rel.pose.orientation.y);
	CHECK(near(rel.pose.orientation.x, 0.0f), "x=%f", rel.pose.orientation.x);
	CHECK(near(rel.pose.orientation.z, 0.0f), "z=%f", rel.pose.orientation.z);
}

/*! Position must arrive unscaled and unmapped by default. */
static void
test_position_passthrough(void)
{
	const float pose[VITURE_POSE_COUNT] = {0.1f, 0.2f, 0.3f, 1.0f, 0.0f, 0.0f, 0.0f};
	struct xrt_space_relation rel;

	viture_carina_to_space_relation(pose, true, true, VITURE_AXES_IDENTITY, 1.0f, &rel);
	CHECK(near(rel.pose.position.x, 0.1f), "px=%f", rel.pose.position.x);
	CHECK(near(rel.pose.position.y, 0.2f), "py=%f", rel.pose.position.y);
	CHECK(near(rel.pose.position.z, 0.3f), "pz=%f", rel.pose.position.z);

	// The scale knob must actually apply, so a unit calibration is testable.
	viture_carina_to_space_relation(pose, true, true, VITURE_AXES_IDENTITY, 2.0f, &rel);
	CHECK(near(rel.pose.position.x, 0.2f), "scaled px=%f", rel.pose.position.x);
}

/*! 3DoF must not claim a position, and unstable samples must not claim tracking. */
static void
test_flags(void)
{
	const float pose[VITURE_POSE_COUNT] = {0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f};
	struct xrt_space_relation rel;

	viture_carina_to_space_relation(pose, false, true, VITURE_AXES_IDENTITY, 1.0f, &rel);
	CHECK((rel.relation_flags & XRT_SPACE_RELATION_POSITION_VALID_BIT) == 0, "3dof claims no position");
	CHECK((rel.relation_flags & XRT_SPACE_RELATION_ORIENTATION_VALID_BIT) != 0, "3dof orientation still valid");

	viture_carina_to_space_relation(pose, true, false, VITURE_AXES_IDENTITY, 1.0f, &rel);
	CHECK((rel.relation_flags & XRT_SPACE_RELATION_ORIENTATION_VALID_BIT) != 0, "unstable still valid");
	CHECK((rel.relation_flags & XRT_SPACE_RELATION_ORIENTATION_TRACKED_BIT) == 0, "unstable not tracked");
	CHECK((rel.relation_flags & XRT_SPACE_RELATION_POSITION_TRACKED_BIT) == 0, "unstable position not tracked");
}

/*! A denormal or zero quaternion must not reach the compositor. */
static void
test_denormal_quaternion(void)
{
	struct xrt_space_relation rel;
	const float scaled[VITURE_POSE_COUNT] = {0.0f, 0.0f, 0.0f, 10.0f, 0.0f, 0.0f, 0.0f};
	viture_carina_to_space_relation(scaled, false, true, VITURE_AXES_IDENTITY, 1.0f, &rel);
	CHECK(near(rel.pose.orientation.w, 1.0f), "denormal normalised to w=%f", rel.pose.orientation.w);

	const float zero[VITURE_POSE_COUNT] = {0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
	viture_carina_to_space_relation(zero, false, true, VITURE_AXES_IDENTITY, 1.0f, &rel);
	CHECK(near(rel.pose.orientation.w, 1.0f), "zero quaternion becomes identity, w=%f", rel.pose.orientation.w);
	CHECK(near(rel.pose.orientation.x, 0.0f) && near(rel.pose.orientation.y, 0.0f) &&
	          near(rel.pose.orientation.z, 0.0f),
	      "zero quaternion has no residual axis");
}

static void
test_axes_override(void)
{
	const float pose[VITURE_POSE_COUNT] = {0.1f, 0.2f, 0.3f, 0.70710678f, 0.0f, 0.70710678f, 0.0f};
	struct xrt_space_relation rel;

	viture_carina_to_space_relation(pose, true, true, VITURE_AXES_FLIP_Z, 1.0f, &rel);
	CHECK(near(rel.pose.position.z, -0.3f), "flip-z position %f", rel.pose.position.z);
	CHECK(near(rel.pose.orientation.y, 0.70710678f), "flip-z leaves yaw intact");

	CHECK(viture_axes_from_string(NULL) == VITURE_AXES_IDENTITY, "null axes name");
	CHECK(viture_axes_from_string("flip-z") == VITURE_AXES_FLIP_Z, "flip-z parsed");
	CHECK(viture_axes_from_string("nonsense") == VITURE_AXES_IDENTITY, "unknown axes falls back");
}

int
main(void)
{
	test_identity_passthrough();
	test_component_order();
	test_position_passthrough();
	test_flags();
	test_denormal_quaternion();
	test_axes_override();

	printf("%d checks, %d failures\n", g_checks, g_failures);
	return g_failures == 0 ? 0 : 1;
}
