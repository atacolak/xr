# Next frontier

Do not treat this list as an instruction to start the work in this file.
It is the ordered exploration after UxSpace bring-up was preserved.

## NEXT FRONTIER

1. Stardust XR
   - Telescope
   - Flatland
   - Protostar / Hexagon
   - Gravity
   - scene graph / spatial object model
   - input
   - Linux/OpenXR path

2. Simula
   - spatial desktop/window-manager prior art
   - interaction/community/design ideas

3. DisplayXR
   - runtime / shell separation
   - workspace-controller architecture
   - external control ideas

4. Luma / Linux display + tracking path     <-- ACTIVE, see experiments/monado-viture/
   - determine the cleanest path for Luma Ultra rendering/tracking into the Linux XR stack
   - evaluate existing Luma/Linux/OpenXR work before implementing our own
   - outcome of that evaluation: no Monado driver for VITURE exists anywhere, so we
     wrote one (xrt_device + builder, small patch, see that experiment's docs/architecture.md)
   - XRLinuxDriver / Breezy drive the same glasses on Linux but with no OpenXR at all
     (shader-injection + shm); they are prior art for the device layer, not a runtime

5. Spatial agent architecture
   - semantic scene query
   - semantic scene mutation
   - probe/observer cameras
   - screenshots/render buffers
   - depth/object-id inspection
   - visual verification
   - agent navigation WITHOUT moving the user's own view

6. Eventually:
   - local hand tracking
   - voice-first control
   - agent-native spatial interaction
   - distance/perception-aware UI placement
   - persistent spatial environments

Notes live under `experiments/` and `docs/spatial-agent.md`.
The next *active* frontier is Stardust XR: `experiments/stardust.md`.
