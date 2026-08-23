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
- **Immediate feedback.** Workspace state is driven from Hyprland events and
  audio is driven directly from PipeWire rather than periodic shell commands.
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
- mouse wheel: change output volume in 5% steps
- middle click: toggle output mute
- workspace switch: temporarily replace the clock with workspace indicators
- volume change: temporarily morph into a volume OSD
- brightness change: temporarily morph into a brightness OSD

The small Wi-Fi and battery glyphs are status, not precision click targets.

### Expanded control center

The control center currently exposes:

- Wi-Fi status and network entry point
- Bluetooth status and command entry point
- battery state
- live output-volume slider
- live brightness slider
- wallpaper picker entry point
- media information and playback controls
- lock, capture and launcher quick actions

Slider values keep following the underlying service while the panel is open.
Local drag preview exists only while the pointer is actively manipulating the
slider.

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

## Runtime safety

Maho Shell is packaged with a managed launcher and user service. The launcher
ensures that only one Maho Shell instance owns the edge surface. Waybar is
hidden only after Quickshell survives startup, and is restored if Maho Shell
exits unexpectedly.

## Next geometry milestone

Docking should remain adaptive rather than arbitrary free-floating placement.
The intended model is snap-to-edge:

- **top:** horizontal edge island, control center expands downward
- **bottom:** horizontal edge island, control center expands upward
- **left:** vertical edge island, control center expands rightward
- **right:** vertical edge island, control center expands leftward

The same semantic modules and interaction state should survive every dock mode;
only geometry and motion direction should change. Dock preference should become
persistent user state once all four modes are runtime-tested.
