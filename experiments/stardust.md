# Stardust XR

**Next frontier after current Monado/VITURE work.**

We are interested in Stardust because it is much closer to an actual
spatial display server than UxSpace. It is primarily a Linux/OpenXR
architecture and experience to learn from. This file is exploration notes.

## Pieces that matter

- Stardust XR Server
- Telescope (bundled working setup)
- Flatland (ordinary Wayland apps become spatial surfaces)
- Protostar / Hexagon launcher
- Gravity (explicit spatial placement)

Important existing idea: a shared 3D environment where conventional 2D
Wayland applications and native spatial objects coexist. Flatland is
particularly interesting for that. Telescope is useful because it
bundles a working setup.

Understand the architecture before modifying it.

## Initial sequence (future task)

1. Install/run Telescope in flatscreen mode on an appropriate Linux host
2. Understand scene/object lifecycle
3. Launch ordinary apps through Flatland
4. Move/resize/grab panels
5. Understand Protostar/launcher model
6. Inspect Gravity and explicit spatial placement
7. Inspect input abstraction
8. Inspect how the scene graph represents spatial transforms
9. Identify how much of the scene can already be introspected programmatically
10. Evaluate the path from the Luma Ultra / our tracking into OpenXR/Linux

## Long-term question

Which Stardust abstractions should our phone-native XR environment adopt?

Begin with exploration, not a rewrite.
