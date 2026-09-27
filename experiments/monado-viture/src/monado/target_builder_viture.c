// SPDX-License-Identifier: BSL-1.0
/*!
 * @file
 * @brief  Builder glue that hands a VITURE HMD to Monado.
 *
 * Mirrors target_builder_xreal_air.c: the prober owns USB enumeration, this
 * builder decides whether it can provide a head, and the driver owns the device.
 *
 * One deliberate difference: there is no entry in target_entry_list for VID
 * 0x35CA. The vendor SDK opens the device itself, so letting Monado's prober
 * also claim HID interfaces would fight over the same endpoints.
 *
 * @ingroup drv_viture
 */

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "xrt/xrt_config_drivers.h"
#include "xrt/xrt_prober.h"
#include "xrt/xrt_system.h"

#include "util/u_builder_search.h"
#include "util/u_debug.h"
#include "util/u_logging.h"
#include "util/u_misc.h"
#include "util/u_trace_marker.h"

#include "target_builder_helpers.h"

#include "viture/viture_hmd.h"
#include "viture/viture_interface.h"

#define VITURE_MAX_CANDIDATES 8

DEBUG_GET_ONCE_LOG_OPTION(viture_log, "VITURE_LOG", U_LOGGING_INFO)

#define VITURE_WARN(...) U_LOG_IFL_W(debug_get_log_option_viture_log(), __VA_ARGS__)
#define VITURE_INFO(...) U_LOG_IFL_I(debug_get_log_option_viture_log(), __VA_ARGS__)

static const char *driver_list[] = {
    "viture",
};

/*!
 * Find the first attached, supported VITURE product.
 *
 * Uses sysfs rather than the prober device list: the vendor SDK validates
 * product ids, and this keeps detection working even when the prober has not
 * opened anything (which is the normal case for this driver).
 *
 * @param out_product_id Filled in with the product id.
 * @return true if a supported device is attached.
 */
static bool
viture_find_supported_device(uint16_t *out_product_id)
{
	uint16_t pids[VITURE_MAX_CANDIDATES] = {0};
	const int count = viture_enumerate_product_ids(pids, VITURE_MAX_CANDIDATES);

	for (int i = 0; i < count; i++) {
		if (viture_is_supported_product(pids[i])) {
			*out_product_id = pids[i];
			return true;
		}

		char name[64] = {0};
		if (viture_market_name(pids[i], name, sizeof(name))) {
			VITURE_INFO("attached VITURE product 0x%04X (%s) is not supported by this driver", pids[i],
			            name);
		} else {
			VITURE_INFO("attached VITURE product 0x%04X is not supported by this driver", pids[i]);
		}
	}

	return false;
}

static xrt_result_t
viture_estimate_system(struct xrt_builder *xb,
                       cJSON *config,
                       struct xrt_prober *xp,
                       struct xrt_builder_estimate *estimate)
{
	U_ZERO(estimate);

	uint16_t product_id = 0;
	if (viture_find_supported_device(&product_id)) {
		estimate->certain.head = true;
	}

	return XRT_SUCCESS;
}

static xrt_result_t
viture_open_system_impl(struct xrt_builder *xb,
                        cJSON *config,
                        struct xrt_prober *xp,
                        struct xrt_tracking_origin *origin,
                        struct xrt_system_devices *xsysd,
                        struct xrt_frame_context *xfctx,
                        struct t_builder_options *tbo)
{
	DRV_TRACE_MARKER();

	uint16_t product_id = 0;
	if (!viture_find_supported_device(&product_id)) {
		VITURE_WARN("no supported VITURE device attached");
		return XRT_ERROR_DEVICE_CREATION_FAILED;
	}

	struct viture_config vcfg;
	viture_config_from_env(&vcfg);

	struct xrt_device *dev = viture_hmd_create((int)product_id, &vcfg);
	if (dev == NULL) {
		// viture_hmd_create already logged the reason.
		return XRT_ERROR_DEVICE_CREATION_FAILED;
	}

	xsysd->static_xdevs[xsysd->static_xdev_count++] = dev;
	tbo->head = dev;

	return XRT_SUCCESS;
}

static void
viture_destroy(struct xrt_builder *xb)
{
	free(xb);
}

struct xrt_builder *
viture_builder_create(void)
{
	struct t_builder *ub = U_TYPED_CALLOC(struct t_builder);

	ub->base.estimate_system = viture_estimate_system;
	ub->base.open_system = t_builder_open_system_static_roles;
	ub->base.destroy = viture_destroy;
	ub->base.identifier = "viture";
	ub->base.name = "VITURE glasses";
	ub->base.driver_identifiers = driver_list;
	ub->base.driver_identifier_count = ARRAY_SIZE(driver_list);

	ub->open_system_static_roles = viture_open_system_impl;

	return &ub->base;
}
