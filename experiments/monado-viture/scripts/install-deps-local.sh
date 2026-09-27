#!/usr/bin/env bash
# Acquire Monado build dependencies WITHOUT root.
#
# sfub has no passwordless sudo, and installing system packages is a machine
# mutation we do not need: -dev packages are unpacked into a private sysroot
# and consumed via PKG_CONFIG_SYSROOT_DIR, so nothing outside this tree changes.
#
# Nothing here is committed as a binary; the sysroot is a build cache.
set -euo pipefail

SYSROOT="${SYSROOT:-$HOME/workspace/monado-deps}"
DEBS="$SYSROOT/debs"
mkdir -p "$SYSROOT" "$DEBS"

PKGS=(
  # core build
  libeigen3-dev
  # shader compilation (Monado compiles GLSL -> SPIR-V at build time)
  glslang-dev glslang-tools spirv-tools
  # device enumeration
  libudev-dev libusb-1.0-0-dev libhidapi-dev
  # X11 / XCB surface + input
  libxcb1-dev libxcb-randr0-dev libxcb-xinput-dev libxcb-xrm-dev
  libxcb-glx0-dev libxcb-present-dev libxcb-shm0-dev libxcb-sync-dev
  libxcb-xfixes0-dev libxcb-xkb-dev libxcb-icccm4-dev libxcb-keysyms1-dev
  libxcb-util0-dev libxcb-image0-dev libxcb-render-util0-dev
  libx11-dev libx11-xcb-dev libxext-dev libxxf86vm-dev
  # GL / EGL (Monado's GLES compositor paths)
  libgl1-mesa-dev libglvnd-dev libegl1-mesa-dev libgles2-mesa-dev
  # misc
  libsdl2-dev libcjson-dev libjsoncpp-dev
)

cd "$DEBS"
missing=()
for p in "${PKGS[@]}"; do
  if compgen -G "${p}_*.deb" > /dev/null; then
    continue
  fi
  if ! apt-get download "$p" >/dev/null 2>&1; then
    missing+=("$p")
  fi
done

for d in "$DEBS"/*.deb; do
  [ -e "$d" ] || continue
  dpkg -x "$d" "$SYSROOT"
done

if [ "${#missing[@]}" -gt 0 ]; then
  echo "unavailable from apt (non-fatal, noted): ${missing[*]}" >&2
fi


# Runtime packages whose objects the -dev symlinks point at. Without these the
# sysroot contains dangling libfoo.so -> libfoo.so.N links, which makes
# pkg-config report a library that cannot actually be linked.
RUNTIME_PKGS=(
  libhidapi-hidraw0 libhidapi-libusb0
)
for p in "${RUNTIME_PKGS[@]}"; do
  compgen -G "${p}_*.deb" >/dev/null 2>&1 && continue
  apt-get download "$p" >/dev/null 2>&1 || true
done
for d in "$DEBS"/libhidapi*.deb; do
  [ -e "$d" ] && dpkg -x "$d" "$SYSROOT"
done

# Debian .pc files hardcode prefix=/usr. Point them at the sysroot so that
# PKG_CONFIG_SYSROOT_DIR is not needed (it would also rewrite the paths of
# *system* packages, which we do not want).
for f in "$SYSROOT"/usr/lib/x86_64-linux-gnu/pkgconfig/*.pc "$SYSROOT"/usr/share/pkgconfig/*.pc; do
  [ -e "$f" ] || continue
  # Some .pc files (systemd's libudev.pc among them) hardcode absolute /usr
  # paths instead of deriving them from prefix, which defeats the rewrite.
  sed -i -e "s|^prefix=.*|prefix=$SYSROOT/usr|" \
         -e "s|-I/usr/|-I$SYSROOT/usr/|g" \
         -e "s|-L/usr/|-L$SYSROOT/usr/|g" \
         -e "s|^libdir=/usr|libdir=$SYSROOT/usr|" \
         -e "s|^includedir=/usr|includedir=$SYSROOT/usr|" \
         -e "s|^exec_prefix=/usr|exec_prefix=$SYSROOT/usr|" "$f"
done

# Multiarch headers (Debian ships e.g. SDL2/_real_SDL_config.h only under
# include/x86_64-linux-gnu) must be reachable by pkg-config consumers.
MULTIARCH_INCLUDE="$SYSROOT/usr/include/x86_64-linux-gnu"
if [ -d "$MULTIARCH_INCLUDE" ]; then
  for f in "$SYSROOT"/usr/lib/x86_64-linux-gnu/pkgconfig/*.pc "$SYSROOT"/usr/share/pkgconfig/*.pc; do
    [ -e "$f" ] || continue
    grep -q 'x86_64-linux-gnu' "$f" && continue
    sed -i "s|^\(Cflags:.*\)$|\1 -I$MULTIARCH_INCLUDE|" "$f"
  done
fi

# Repair any remaining dangling libfoo.so symlink against the host runtime
# object, so a -dev package never advertises a library that cannot link.
for f in "$SYSROOT"/usr/lib/x86_64-linux-gnu/*.so; do
  [ -L "$f" ] || continue
  [ -e "$f" ] && continue
  tgt="$(basename "$(readlink "$f")")"
  for cand in "/usr/lib/x86_64-linux-gnu/$tgt" "/lib/x86_64-linux-gnu/$tgt"; do
    if [ -e "$cand" ]; then
      ln -sf "$cand" "$f"
      break
    fi
  done
done


# SDL2's CMake config exports only include/SDL2, but Debian splits SDL_config.h
# across the multiarch dir as well, so consumers cannot compile without this.
SDL2_CFG="$SYSROOT/usr/lib/x86_64-linux-gnu/cmake/SDL2/sdl2-config.cmake"
if [ -f "$SDL2_CFG" ] && ! grep -q 'monado-viture sysroot fix' "$SDL2_CFG"; then
  python3 - "$SDL2_CFG" <<'PYEOF'
import sys
from pathlib import Path
p = Path(sys.argv[1]); t = p.read_text()
fix = """
foreach(_sdl2_tgt SDL2::SDL2 SDL2::SDL2-static SDL2::SDL2test)
  if(TARGET ${_sdl2_tgt})
    set_property(TARGET ${_sdl2_tgt} APPEND PROPERTY INTERFACE_INCLUDE_DIRECTORIES
      "${SDL2_INCLUDE_DIR};${SDL2_PREFIX}/include;${SDL2_PREFIX}/include/x86_64-linux-gnu")
  endif()
endforeach()

"""
p.write_text(t.replace('check_required_components(SDL2)', fix + 'check_required_components(SDL2)', 1))
PYEOF
fi

cat > "$SYSROOT/env.sh" <<'EOF'
# Source this to build against the private dependency sysroot.
export MONADO_SYSROOT="${MONADO_SYSROOT:-$HOME/workspace/monado-deps}"
export PKG_CONFIG_SYSROOT_DIR="$MONADO_SYSROOT"
export PKG_CONFIG_PATH="$MONADO_SYSROOT/usr/lib/x86_64-linux-gnu/pkgconfig:$MONADO_SYSROOT/usr/share/pkgconfig"
export CMAKE_PREFIX_PATH="$MONADO_SYSROOT"
export PATH="$MONADO_SYSROOT/usr/bin:$PATH"
# Build-time tools that live in the sysroot must find the host libc; keep the
# sysroot OUT of LD_LIBRARY_PATH while building.
EOF

echo "sysroot=$SYSROOT"
ls "$SYSROOT/usr/bin" 2>/dev/null | grep -iE 'glslang|spirv' || true
echo "pkgconfig dirs: $(ls -d "$SYSROOT"/usr/*/pkgconfig 2>/dev/null | tr '\n' ' ')"
