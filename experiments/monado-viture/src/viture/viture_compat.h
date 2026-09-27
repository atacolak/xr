// SPDX-License-Identifier: BSL-1.0
/*!
 * @file
 * @brief  C-safe access to vendor SDK version information.
 *
 * The vendor's `viture_version.h` contains `extern "C"` and
 * `namespace viture::version { ... }` with no `#ifdef __cplusplus` guard, so it
 * cannot be included from a C translation unit at all. Rather than copy their
 * version macros (which would silently drift), this header exposes only the
 * exported C-linkage query and lets the library report its own version.
 *
 * @ingroup drv_viture
 */

#pragma once

#include "viture_macros_public.h"

#ifdef __cplusplus
extern "C" {
#endif

/*!
 * Version string of the linked libglasses, e.g. "2.4.0".
 *
 * Owned by the library; do not free.
 */
VITURE_API const char *
GetVersionString(void);

#ifdef __cplusplus
}
#endif
