// SPDX-License-Identifier: BSL-1.0
/*!
 * @file
 * @brief  VITURE panel timing / stereo mode table.
 * @ingroup drv_viture
 */

#include "viture_modes.h"

#include <string.h>
#include <strings.h>

#define VITURE_MODE_COUNT (sizeof(g_viture_modes) / sizeof(g_viture_modes[0]))

/*
 * Every mode the vendor SDK documents for Gen1/Carina devices. Kept as data so
 * the driver never has to special-case a timing anywhere else.
 *
 * 2D entries: one image across the panel.
 * 3D entries: side-by-side, left eye in the left half.
 */
static const struct viture_mode_info g_viture_modes[] = {
    {VITURE_DISPLAY_MODE_1920_1200_60HZ, 1920, 1200, 1, 60.0f, "1920x1200@60-2d"},
    {VITURE_DISPLAY_MODE_1920_1200_90HZ, 1920, 1200, 1, 90.0f, "1920x1200@90-2d"},
    {VITURE_DISPLAY_MODE_1920_1200_120HZ, 1920, 1200, 1, 120.0f, "1920x1200@120-2d"},
    {VITURE_DISPLAY_MODE_3840_1200_60HZ, 3840, 1200, 2, 60.0f, "3840x1200@60-sbs"},
    {VITURE_DISPLAY_MODE_3840_1200_90HZ, 3840, 1200, 2, 90.0f, "3840x1200@90-sbs"},
    {VITURE_DISPLAY_MODE_1920_1080_60HZ, 1920, 1080, 1, 60.0f, "1920x1080@60-2d"},
    {VITURE_DISPLAY_MODE_1920_1080_90HZ, 1920, 1080, 1, 90.0f, "1920x1080@90-2d"},
    {VITURE_DISPLAY_MODE_1920_1080_120HZ, 1920, 1080, 1, 120.0f, "1920x1080@120-2d"},
    {VITURE_DISPLAY_MODE_3840_1080_60HZ, 3840, 1080, 2, 60.0f, "3840x1080@60-sbs"},
    {VITURE_DISPLAY_MODE_3840_1080_90HZ, 3840, 1080, 2, 90.0f, "3840x1080@90-sbs"},
};

const struct viture_mode_info *
viture_mode_lookup(int vendor_mode)
{
	for (size_t i = 0; i < VITURE_MODE_COUNT; i++) {
		if (g_viture_modes[i].vendor_mode == vendor_mode) {
			return &g_viture_modes[i];
		}
	}

	return NULL;
}

const struct viture_mode_info *
viture_mode_by_name(const char *name)
{
	if (name == NULL || name[0] == '\0') {
		return NULL;
	}

	for (size_t i = 0; i < VITURE_MODE_COUNT; i++) {
		if (strcasecmp(g_viture_modes[i].name, name) == 0) {
			return &g_viture_modes[i];
		}
	}

	return NULL;
}

const struct viture_mode_info *
viture_mode_default(void)
{
	return viture_mode_lookup(VITURE_DISPLAY_MODE_3840_1200_90HZ);
}

void
viture_mode_per_eye(const struct viture_mode_info *mode, uint32_t *w, uint32_t *h)
{
	*w = mode->total_w / mode->view_count;
	*h = mode->total_h;
}

int
viture_mode_native_equiv(int vendor_mode)
{
	switch (vendor_mode) {
	case VITURE_DISPLAY_MODE_1920_1080_60HZ: return VITURE_NATIVE_DISPLAY_MODE_1920_1080_60HZ;
	case VITURE_DISPLAY_MODE_1920_1080_90HZ: return VITURE_NATIVE_DISPLAY_MODE_1920_1080_90HZ;
	case VITURE_DISPLAY_MODE_1920_1080_120HZ: return VITURE_NATIVE_DISPLAY_MODE_1920_1080_120HZ;
	case VITURE_DISPLAY_MODE_1920_1200_60HZ: return VITURE_NATIVE_DISPLAY_MODE_1920_1200_60HZ;
	case VITURE_DISPLAY_MODE_1920_1200_90HZ: return VITURE_NATIVE_DISPLAY_MODE_1920_1200_90HZ;
	case VITURE_DISPLAY_MODE_1920_1200_120HZ: return VITURE_NATIVE_DISPLAY_MODE_1920_1200_120HZ;
	case VITURE_DISPLAY_MODE_3840_1080_60HZ: return VITURE_NATIVE_DISPLAY_MODE_3D_SBS_3840_1080_60HZ;
	case VITURE_DISPLAY_MODE_3840_1080_90HZ: return VITURE_NATIVE_DISPLAY_MODE_3D_SBS_3840_1080_90HZ;
	case VITURE_DISPLAY_MODE_3840_1200_60HZ: return VITURE_NATIVE_DISPLAY_MODE_3D_SBS_3840_1200_60HZ;
	case VITURE_DISPLAY_MODE_3840_1200_90HZ: return VITURE_NATIVE_DISPLAY_MODE_3D_SBS_3840_1200_90HZ;
	default: return -1;
	}
}
