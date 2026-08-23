# Maho Shell

Maho Shell is the human-facing surface of Maho OS.

It is intentionally not a conventional status bar. The collapsed edge island
shows only ambient information; the same physical surface morphs into transient
feedback and a larger control center when interaction requires more room.

## Design goals

- **Quiet at rest.** Time and compact system state should not compete with the
  application underneath.
- **Context earns space.** Workspace changes, volume, brightness and later
  notifications can temporarily replace the idle view instead of permanently
  occupying screen space.
- **One interaction target.** Tiny status glyphs are indicators. The collapsed
  island itself is the reliable click target for the control center.
- **Immediate feedback.** Workspace state is driven from Hyprland events, audio
  is driven directly from PipeWire, media is driven directly from MPRIS, and
  battery state is driven directly from UPower rather than periodic shell
  commands.
- **Wallpaper-native color.** Maho Shell reads Maho's active palette directly
  and transitions surfaces, foregrounds and accents when the wallpaper-derived
  theme changes.
- **One physical object.** Opening, closing and transient feedback should feel
  like the same edge-attached object changing shape, not separate popups being
  stacked on top of one another.
- **User authority first.** Shell controls expose explicit user actions; they do
  not bypass Maho's ownership and policy model.

## Current interaction model

### Collapsed island

- left click: open the control center
- left drag: move the island and snap it to the nearest screen edge
- mouse wheel: change output volume in 5% steps
- middle click: toggle output mute
- workspace switch: temporarily replace the clock with workspace indicators
- volume change: temporarily morph into a volume OSD
- brightness change: temporarily morph into a brightness OSD

The small Wi-Fi and battery glyphs are status, not precision click targets.

### Edge docking

Docking is deliberately bounded instead of arbitrary free-floating placement.
Dragging the collapsed island lets it follow the pointer across the display;
releasing it commits the nearest edge and preserves the along-edge position.
The shell supports four persistent dock modes:

- **top:** horizontal island; control center expands downward
- **bottom:** horizontal island; control center expands upward
- **left:** vertical island; control center expands rightward
- **right:** vertical island; control center expands leftward

The selected edge and normalized along-edge position are stored in Quickshell's
per-shell state directory as `dock.json`. The default is top-center. Position is
clamped away from extreme corners so the island and expanded control center can
remain on-screen.

The shell uses a transparent full-screen layer only as geometry space for the
drag. Input remains masked to the visible island, so the rest of the desktop is
not turned into a click-blocking overlay. During a drag, a small accent marker
previews which edge will receive the island.

Side docks use a dedicated vertical collapsed layout rather than rotating text.
Time is stacked, workspace feedback becomes vertical, and volume/brightness OSD
tracks fill vertically. The expanded control center keeps normal readable
orientation and reuses the same controls on every edge.

### Expanded control center

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
reactively, and invokes previous/play-pause/next on that player directly. This
removes the old ambient polling delay from playback controls and keeps paused
players available in the control center.

Battery does not scrape `/sys/class/power_supply`. `Battery.qml` follows
Quickshell's UPower display device directly, so percentage and charging state
are reactive properties shared by the collapsed island and control center.
Battery UI disappears cleanly on systems without a usable display battery.

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

This keeps the shell visually synchronized with Maho's adaptation layer while
preserving stable contrast and hierarchy.

## Runtime safety and diagnostics

Maho Shell is packaged with a managed launcher and user service. The launcher
ensures that only one Maho Shell instance owns the edge surface. Waybar is
hidden only after Quickshell survives startup, and is restored if Maho Shell
exits unexpectedly.

The runtime also exposes bounded diagnostics so shell failures do not require
unstructured log dumps:

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

## Docking validation milestone

The first docking implementation intentionally keeps the state model small:
edge plus normalized along-edge position. Before adding more motion or monitor
selection behavior, all four orientations must be runtime-tested for:

- drag/tap arbitration: a click opens, a drag never opens by accident
- pointer tracking and nearest-edge preview
- snap position persistence across shell restart
- top and bottom expansion/close direction
- left and right expansion/close direction
- side collapsed readability and OSD behavior
- input mask correctness around the full-screen transparent layer
- no return of the post-close rectangle artifact

Only after those are clean should docking gain multi-monitor selection or more
advanced edge magnetism.
