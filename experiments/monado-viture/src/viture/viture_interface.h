// SPDX-License-Identifier: BSL-1.0
/*!
 * @file
 * @brief  VITURE glasses HMD driver interface.
 * @ingroup drv_viture
 */

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*!
 * USB vendor id of VITURE glasses (all generations).
 *
 * Product ids are deliberately NOT hardcoded: the vendor SDK owns that list
 * (xr_device_provider_is_product_id_valid) and it grows with each product
 * release. Ask the SDK instead of guessing here.
 *
 * @ingroup drv_viture
 */
#define VITURE_VID 0x35CA

/*!
 * Enumerate attached VITURE product ids by scanning sysfs.
 *
 * Independent of the vendor SDK so it can be used before any handle exists
 * (Monado builder estimation, diagnostics).
 *
 * @param out_pids   Caller-provided array.
 * @param max        Capacity of @p out_pids.
 * @return Number of product ids written.
 * @ingroup drv_viture
 */
int
viture_enumerate_product_ids(uint16_t *out_pids, int max);

/*!
 * Query the vendor SDK for a product's marketing name.
 *
 * @return true if the SDK answered and wrote a name.
 * @ingroup drv_viture
 */
bool
viture_market_name(int product_id, char *out, size_t out_len);

/*!
 * Whether this driver handles the given product id.
 *
 * Currently the Carina generation (VITURE Luma Ultra) only: that is the
 * generation with an IMU/VIO pose source. Override with
 * `VITURE_ALLOW_ANY_PRODUCT=1` to let the driver try other products.
 *
 * @ingroup drv_viture
 */
bool
viture_is_supported_product(int product_id);

/*!
 * Builder setup for VITURE glasses.
 *
 * @ingroup drv_viture
 */
struct xrt_builder *
viture_builder_create(void);

/*!
 * @dir drivers/viture
 *
 * @brief @ref drv_viture files.
 */

#ifdef __cplusplus
}
#endif
