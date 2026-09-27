#!/usr/bin/env bash
# Apply / revert the Monado plumbing patch and copy the driver sources in.
#
#   patch-monado.sh apply     # copy sources + apply patch (idempotent)
#   patch-monado.sh revert    # unpatch + remove copied sources
#   patch-monado.sh status
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MONADO="${MONADO_DIR:-$HOME/workspace/monado}"
PATCH="$ROOT/patches/0001-monado-add-viture-driver.patch"

DRIVER_DIR="$MONADO/src/xrt/drivers/viture"
BUILDER="$MONADO/src/xrt/targets/common/target_builder_viture.c"

apply() {
  mkdir -p "$DRIVER_DIR"
  cp "$ROOT"/src/viture/*.h "$ROOT"/src/viture/*.c "$DRIVER_DIR/"
  cp "$ROOT"/src/monado/target_builder_viture.c "$BUILDER"

  cd "$MONADO"
  if git apply --reverse --check "$PATCH" >/dev/null 2>&1; then
    echo "patch already applied"
  elif git apply --3way "$PATCH" 2>/dev/null || git apply "$PATCH"; then
    echo "patch applied"
  else
    echo "FAILED to apply $PATCH" >&2
    echo "Monado HEAD: $(git rev-parse --short HEAD); patch was generated against:" >&2
    cat "$ROOT/patches/monado-base-commit.txt" >&2
    exit 1
  fi
}

revert() {
  cd "$MONADO"
  if git apply --reverse --check "$PATCH" >/dev/null 2>&1; then
    git apply --reverse "$PATCH" && echo "patch reverted"
  else
    echo "patch not applied"
  fi
  rm -rf "$DRIVER_DIR" "$BUILDER"
  echo "driver sources removed"
}

status() {
  cd "$MONADO"
  echo "monado:       $MONADO"
  echo "head:         $(git rev-parse --short HEAD)"
  echo "patch base:   $(head -1 "$ROOT/patches/monado-base-commit.txt")"
  if git apply --reverse --check "$PATCH" >/dev/null 2>&1; then
    echo "patch:        APPLIED"
  else
    echo "patch:        not applied"
  fi
  [ -d "$DRIVER_DIR" ] && echo "driver dir:   present" || echo "driver dir:   missing"
}

case "${1:-status}" in
  apply) apply ;;
  revert) revert ;;
  status) status ;;
  *) echo "usage: patch-monado.sh [apply|revert|status]" >&2; exit 1 ;;
esac
