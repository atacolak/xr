# Architecture note

This is the current **hypothesis**, not a final decision.

The long-term system should not be conceptualized merely as:

    "an Android app that draws floating Android windows."

A more useful conceptual model:

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

We are currently learning the abstractions. Do not lock implementation
to Stardust, OpenXR, Android XR, UxSpace, or any other one runtime.

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

Replaceable. Do not spread SSH hostnames through every XR project.
