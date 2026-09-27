# Spatial agent (future direction)

This is an architectural direction. Do not implement the full API now.

An XR agent must not be merely a chat process that can send keystrokes
to Android. It should understand and operate the spatial environment.

    SEMANTIC SCENE ACCESS FIRST.
    VISUAL PERCEPTION SECOND.
    PIXEL-DRIVING ONLY AS A FALLBACK.

OMP/agents should eventually participate as native spatial actors.

## Scene query

A spatial agent should query the scene directly. Conceptual API:

    scene.snapshot()
    scene.list_nodes()
    scene.get(node_id)
    scene.query(type=..., app=..., visible=..., anchor=..., region=...)

Per node, expose useful semantic information **where the backend has it**.
Do not assume every property exists in every runtime.

    id
    type
    application / owner
    title / semantic role

    position
    orientation
    scale
    local transform
    world transform

    parent
    children

    reference frame
    anchor type:
        HEAD
        WORLD
        BODY/FOLLOW
        OBJECT
        ...

    bounds / AABB / OBB
    physical dimensions
    content dimensions

    visibility
    opacity
    focus state
    interaction state

    depth relative to user
    angular size
    viewport visibility
    occlusion relationships where knowable
    input target / hit-test state

## Geometric questions

The agent should eventually be able to ask:

- What panels are currently visible to the user?
- Where is the terminal relative to the user's head?
- What physical geometry lies behind this text?
- Which UI surface is nearest to the user's gaze direction?
- Is anything at <1 m depth competing with this panel?
- What object would this panel occlude?
- Which surfaces overlap in retinal projection?
- How far apart are these two panels?
- Which node currently has input focus?
- What is anchored to the world vs the head?

Primitives worth investigating:

    raycast(origin, direction)
    nearest(point/type)
    intersects(a, b)
    visible_from(viewpoint, node)
    screen_projection(viewpoint, node)
    depth_at(ray/pixel)
    semantic_hit_test(ray)

These matter for automatic panel placement, perceptual legibility,
distance-aware UI, avoiding close real-world geometry behind text,
agent-driven layout, and explaining what the user is looking at.

## Vision / capture

Semantic state is not sufficient. The compositor should eventually
produce diagnostic buffers, not just an undifferentiated screenshot.

    capture.user_view()          # composited view close to what the user sees
    capture.eye("left"|"right")
    capture.layer(node_id)

Buffers:

    RGB / composited color
    depth
    object / node ID
    possibly normals / motion vectors

Example: image + depth + node-id lets the agent know "these pixels are
the terminal panel, 3.8 m virtual depth, and there is real-world
geometry about 0.7 m behind that retinal region."

## Agent observer / probe camera

An agent should traverse the 3D world **without moving the user's head**.

    observer.spawn(position, orientation)
    observer.move(...)
    observer.look_at(...)
    observer.capture()
    observer.raycast(...)
    observer.inspect(node)

Use cases: inspect the back of a layout, objects outside the FOV,
verify a move, debug clipping/occlusion, inspect world anchors, look
at an app surface without forcing the wearer to turn.

Loop:

    query scene
      -> choose probe viewpoint
      -> render screenshot / depth / id buffers
      -> reason
      -> semantic action
      -> render again
      -> verify

This is not WASD from screenshots. The semantic scene graph remains
the primary ground truth.

## Spatial actions

Prefer semantic operations over pixel guessing:

    spawn_app(...)
    close(node)
    focus(node)
    move(node, position)
    rotate(node, orientation)
    scale(node, scale)
    set_anchor(node, WORLD|HEAD|FOLLOW)
    parent(node, other)
    unparent(node)
    place_relative_to(node, target, relation)
    send_text(node, text)
    invoke_action(node, action)

Pixel/input synthesis remains an escape hatch for legacy apps.

## Safety / user agency

Semantic scene access does **not** imply the agent may move everything.

Distinguish:

    observe
    propose
    act

Allow, later:

- user-owned regions
- protected objects
- permission boundaries
- reversible actions
- transaction / undo where feasible

Spatial mutation needs the same seriousness as filesystem mutation.
Do not design the permission model in this task; record it so we do
not bolt permissions onto an omnipotent scene API later.
