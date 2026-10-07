#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cc -O2 -Wall -o "$ROOT/tools/xpresent-gl" "$ROOT/tools/xpresent-gl.c" -lGL -lX11
echo "built $ROOT/tools/xpresent-gl"
