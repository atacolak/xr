#!/usr/bin/env bash
# Build tools/viture-pose-dump against the vendor SDK (no Monado needed).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK="${VITURE_SDK_DIR:-$HOME/workspace/uxspace/Android/SDK/linux-x86_64}"
OUT="${OUT:-$ROOT/tools/viture-pose-dump}"

[ -f "$SDK/include/viture_glasses_provider.h" ] || { echo "no VITURE SDK at $SDK"; exit 1; }

cc -std=c11 -O2 -Wall -Wextra -o "$OUT" \
  "$ROOT/tools/viture-pose-dump.c" \
  "$ROOT/src/viture/viture_probe.c" \
  "$ROOT/src/viture/viture_modes.c" \
  -I"$ROOT/src/viture" \
  -I"$SDK/include" \
  -L"$SDK/x86_64" \
  -lglasses -lm \
  -Wl,-rpath,"$SDK/x86_64"

echo "built $OUT"
