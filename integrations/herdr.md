# Herdr (external)

Daily Herdr is the fork https://github.com/atacolak/herdr
(`~/workspace/herdr`), based on upstream Herdr 0.9.1.

Herdr is the terminal runtime agents live in. OMP stays on **sfub**.
The Fold is a thin client / remote-control target.

## What it provides to XR

- Interactive agent session: `mosh -p 60022 sfub -- herdr`
- Pane/workspace layout that survives SSH drop (Herdr server)
- Semantic paste via `herdr pane send-text` (`fold-thinclient/scripts/herdr-paste`)

## How to run from the Fold

Desired DeX path: click **HERDR** in the DeX Apps list -> visible Termux
-> `mosh -p 60022 sfub -- herdr`. See `tools/herdr-launcher/`.

Human path remains Fold -> Mosh -> sfub -> Herdr / OMP.

## Interfaces XR cares about

- `herdr` CLI / socket API for panes (owned by Herdr)
- Launch command string used by the DeX launcher (owned by this repo's glue)
- Future: spatial agent actions should beat "send keystrokes to a pane"

## What XR expects

A durable interactive session on sfub. The Fold must not host OMP.

## Owned by Herdr

Terminal runtime, persistence, agent pane protocol.
