// SPDX-License-Identifier: BSL-1.0
/*!
 * @file
 * @brief  VITURE device discovery.
 *
 * Two independent jobs, deliberately separated:
 *
 *  1. sysfs scan for VID 0x35CA - needs nothing but the kernel, and is safe to
 *     run before any vendor handle exists. Used by the Monado builder to decide
 *     whether it can provide a head.
 *  2. market-name query via the vendor SDK - the SDK owns the product id list,
 *     so this driver never hardcodes product ids.
 *
 * @ingroup drv_viture
 */

#include "viture_interface.h"

#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "viture_glasses_provider.h"
#include "viture_protocol_public.h"

#define VITURE_SYSFS_USB "/sys/bus/usb/devices"

static bool
read_hex_file(const char *path, unsigned int *out)
{
	FILE *f = fopen(path, "r");
	if (f == NULL) {
		return false;
	}

	unsigned int value = 0;
	const int matched = fscanf(f, "%x", &value);
	fclose(f);

	if (matched != 1) {
		return false;
	}

	*out = value;
	return true;
}

int
viture_enumerate_product_ids(uint16_t *out_pids, int max)
{
	DIR *dir = opendir(VITURE_SYSFS_USB);
	if (dir == NULL) {
		return 0;
	}

	int count = 0;
	struct dirent *ent = NULL;
	while (count < max && (ent = readdir(dir)) != NULL) {
		// Skip "." / ".." and interface nodes (they contain a colon).
		if (ent->d_name[0] == '.' || strchr(ent->d_name, ':') != NULL) {
			continue;
		}

		char vpath[512];
		char ppath[512];
		snprintf(vpath, sizeof(vpath), VITURE_SYSFS_USB "/%s/idVendor", ent->d_name);
		snprintf(ppath, sizeof(ppath), VITURE_SYSFS_USB "/%s/idProduct", ent->d_name);

		unsigned int vid = 0;
		unsigned int pid = 0;
		if (!read_hex_file(vpath, &vid) || vid != VITURE_VID) {
			continue;
		}
		if (!read_hex_file(ppath, &pid)) {
			continue;
		}

		// The SDK decides what a valid product id is.
		if (!xr_device_provider_is_product_id_valid((int)pid)) {
			continue;
		}

		const uint16_t product_id = (uint16_t)pid;
		bool duplicate = false;
		for (int i = 0; i < count; i++) {
			if (out_pids[i] == product_id) {
				duplicate = true;
				break;
			}
		}
		if (!duplicate) {
			out_pids[count++] = product_id;
		}
	}

	closedir(dir);
	return count;
}

bool
viture_market_name(int product_id, char *out, size_t out_len)
{
	if (out == NULL || out_len == 0) {
		return false;
	}
	out[0] = '\0';

	char buf[64] = {0};
	int len = (int)sizeof(buf) - 1;
	const int ret = xr_device_provider_get_market_name(product_id, buf, &len);
	if (ret != VITURE_GLASSES_SUCCESS) {
		return false;
	}
	if (len <= 0 || (size_t)len >= out_len) {
		return false;
	}

	buf[len] = '\0';
	snprintf(out, out_len, "%s", buf);
	return true;
}

bool
viture_is_supported_product(int product_id)
{
	if (getenv("VITURE_ALLOW_ANY_PRODUCT") != NULL) {
		return xr_device_provider_is_product_id_valid(product_id);
	}

	// Carina is the generation with an IMU/VIO pose source ("Luma Ultra").
	// Gen1/Gen2 devices have no usable host-side pose path in this driver yet,
	// so they are rejected loudly rather than given a fake identity pose.
	char name[64];
	if (!viture_market_name(product_id, name, sizeof(name))) {
		return false;
	}

	return strcmp(name, VITURE_MARKET_NAME_LUMA_ULTRA) == 0;
}
