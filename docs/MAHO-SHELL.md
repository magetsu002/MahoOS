# Maho Shell

Maho Shell is the human-facing surface of Maho OS.

The resting desktop surface is called **Maho Edge**. It is intentionally not a
conventional status bar: Maho Edge stays small at the selected screen edge,
shows only ambient information, morphs into transient feedback when context
matters, and expands inward into the larger control center when requested.

## Design goals

- **Quiet at rest.** Time and compact system state should not compete with the
  active application.
- **Context earns space.** Workspace changes, volume, brightness and later
  notifications temporarily replace the idle view instead of permanently
  occupying screen space.
- **One interaction target.** Tiny status glyphs are indicators. Maho Edge is
  the reliable click target for the control center.
- **Immediate feedback.** Workspace state is driven from Hyprland socket2
  events, audio directly from PipeWire, media directly from MPRIS, and battery
  directly from UPower rather than periodic shell commands.
- **Wallpaper-native color.** Maho Shell reads Maho's active palette directly
  and transitions surfaces, foregrounds and accents when the wallpaper-derived
  theme changes.
- **One physical object.** Opening, closing and transient feedback should feel
  like the same edge-attached surface changing shape rather than separate
  popups stacked over one another.
- **Compositor-aware placement.** The resting Edge reserves only its collapsed
  thickness plus a small breathing gap, so tiled windows never look pasted
  underneath it.
- **User authority first.** Shell controls expose explicit user actions; they do
  not bypass Maho's ownership and policy model.

## Maho Edge interaction model

At rest:

- left click: open the control center
- left drag: move Maho Edge and snap it to the nearest screen edge
- mouse wheel: change output volume in 5% steps
- middle click: toggle output mute
- workspace switch: temporarily replace the clock with workspace indicators
- volume change: temporarily morph into a volume OSD
- brightness change: temporarily morph into a brightness OSD

The Wi-Fi and battery glyphs are status, not precision click targets.

## Workspace feedback

Workspace feedback is event-sequenced rather than boolean-triggered.

Hyprland's `workspacev2` socket2 event is the animation authority. Every valid
workspace event:

1. updates the immediate visual workspace id,
2. increments `workspaceEventSerial`,
3. restarts the transient workspace timeout, and
4. restarts the workspace pulse animation even if the previous workspace
   feedback is still visible.

This means a rapid sequence such as `1 -> 2 -> 3 -> 4` produces four distinct
visual updates instead of one initial transition followed by a stuck `true`
state. `focusedWorkspaceChanged` remains only as a reconnect/startup fallback.

## Edge docking

Docking is deliberately bounded instead of arbitrary free-floating placement.
Dragging Maho Edge lets the visible surface follow the pointer across the
display; releasing it commits the nearest edge and preserves the along-edge
position.

The shell supports four persistent dock modes:

- **top:** horizontal Edge; control center expands downward
- **bottom:** horizontal Edge; control center expands upward
- **left:** vertical Edge; control center expands rightward
- **right:** vertical Edge; control center expands leftward

The selected edge and normalized along-edge position are stored in Quickshell's
per-shell state directory as `dock.json`. The default is top-center. Position is
clamped away from extreme corners so the resting surface and expanded control
center can remain on-screen.

The visible shell uses a transparent full-screen geometry layer during normal
operation so Maho Edge can follow the pointer across the display. Input remains
masked to the visible Edge surface; the rest of the desktop stays click-through.
A small accent marker previews the candidate snap edge during movement.

The runtime-proven `DragHandler` path is intentionally isolated from control
center click semantics and from compositor reservation. Changes to workspace
feedback, naming, or reserved space must not rewrite that drag contract.

Side docks use a dedicated vertical layout rather than rotating text. Time is
stacked, workspace feedback becomes vertical, and volume/brightness tracks fill
vertically. The expanded control center keeps normal readable orientation and
reuses the same controls on every edge.

## Compositor reservation

Maho Edge should look integrated with the desktop rather than pasted over tiled
windows. A separate transparent `DockReservation` layer-shell surface owns that
layout responsibility.

The reservation follows only the persisted `dock.edge` and reserves:

- horizontal Edge thickness: 40 px
- vertical Edge thickness: 46 px
- breathing room: 8 px

The visible Maho Edge surface itself remains on the overlay layer. This keeps
visual geometry and compositor layout ownership separate.

Important invariants:

- the reservation has an empty input mask and never intercepts desktop input,
- the expanded control center does not increase the exclusive zone,
- tiled windows therefore do not jump when the control center opens/closes,
- while dragging, the old persisted edge keeps its reservation,
- the reservation switches only when `dock.setDock(...)` commits the snap on
  release, causing at most one compositor reflow per move.

## Expanded control center

The control center currently exposes:

- Wi-Fi status and network entry point
- Bluetooth status and command entry point
- native UPower battery state
- live output-volume slider
- live brightness slider
- wallpaper picker entry point
- native MPRIS media information and playback controls
- lock, capture and launcher quick actions

Slider values keep following the underlying service while the panel is open.
Local drag preview exists only while the pointer is actively manipulating the
slider.

Media does not depend on `playerctl`. `Media.qml` selects an active MPRIS player
from Quickshell's service model, follows its title/artist/playback properties
reactively, and invokes previous/play-pause/next on that player directly.

Battery does not scrape `/sys/class/power_supply`. `Battery.qml` follows
Quickshell's UPower display device directly, so percentage and charging state
are reactive properties shared by Maho Edge and the control center. Battery UI
disappears cleanly on systems without a usable display battery.

The remaining Python ambient probe is intentionally narrow: it currently covers
network and Bluetooth summary state only. Those paths stay isolated so they can
be replaced independently after their Quickshell service contracts are
runtime-validated on the target Arch session.

## Dynamic color contract

The source of truth is:

```text
~/.cache/maho/theme/active.json
```

`MahoTheme.qml` watches that file directly. Shell components consume semantic
roles such as `surfaceHigh`, `foreground`, `muted`, `primary`, `secondary`,
`tertiary`, `outline` and `error` rather than hard-coded wallpaper colors.

## Runtime safety and diagnostics

Maho Shell is packaged with a managed launcher and user service. The launcher
ensures that only one Maho Shell instance owns Maho Edge. Waybar is hidden only
after Quickshell survives startup, and is restored if Maho Shell exits
unexpectedly.

The runtime exposes bounded diagnostics:

```text
maho-shell doctor
maho-shell status --json
maho-shell logs 120
maho-shell reload
```

`doctor` checks the live configuration, palette JSON, singleton state, session
environment, user service and optional capabilities. `logs` is intentionally
bounded to at most 500 lines. `status --json` exposes machine-readable runtime
state for tooling and future Maho support surfaces.

## Validation gate

Before adding multi-monitor selection, edge magnetism, or more motion behavior,
the current Maho Edge architecture must be runtime-tested for:

- rapid workspace sequences such as `1 -> 2 -> 3 -> 4 -> 5`
- drag/tap arbitration
- pointer tracking and nearest-edge preview
- snap position persistence across shell restart
- one compositor reflow after a completed dock move
- stable 8 px breathing room between Edge and tiled windows
- no window reflow while the control center expands/collapses
- top/bottom and left/right expansion direction
- side readability and transient OSD behavior
- input-mask correctness around both transparent shell surfaces
- no return of the post-close rectangle artifact

Only after those are clean should docking gain multi-monitor selection or more
advanced edge magnetism.
