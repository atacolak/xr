# Architecture note

Current hypothesis.

A useful conceptual model:

    hardware / OS substrate
            ↓
        XR runtime
            ↓
    shared spatial scene graph
            ↓
    surfaces + native spatial objects + agents
            ↓
    multimodal input / interaction
            ↓
    underlying applications / services

On the Fold, Android may remain the hardware/driver/application substrate.
The user-facing environment above it can still become its own spatial
computing surface.

Abstractions are still being learned. Implementation is not locked to one
runtime.

## What UxSpace taught about this split

UxSpace sits mostly in "an Android app + Presentation display + vendor
tracking SDK". That was enough to *feel* tracking, pinning, and
world-relative panels on Luma Ultra. It was not enough to be a spatial
display server:

- no shared scene graph other apps/agents can query
- window management is inside one app
- input is mostly Android's
- the privileged ADB helper is bring-up infrastructure, not an XR runtime

Those are architectural limits, not just missing features. The next
systems (Stardust, Simula, DisplayXR) are being studied because they
already treat "spatial desktop / compositor / scene" as the product.

## Transport

Human: Fold -> Mosh -> sfub -> OMP / Herdr
Machine: sfub -> xrctl -> Fold Termux -> local adb -> Android

Replaceable. SSH hostnames stay in local config, not in every XR project.
