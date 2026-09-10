# Maho Shell

Maho Shell is the desktop shell for MahoOS. It runs in Quickshell and provides
Maho Edge, Maho Dock, system feedback, and the shared control center.

## Maho Edge

Maho Edge is the compact surface attached to a screen edge. It stays small at
rest and expands only when the user asks for more controls or when the system
needs to show short-lived feedback.

At rest:

- left click opens the control center
- left drag moves Edge and snaps it to the nearest screen edge
- mouse wheel changes output volume
- middle click toggles mute
- workspace changes temporarily show workspace feedback
- volume and brightness changes temporarily show an OSD
- Guardian incidents can temporarily replace normal Edge content

Edge can be docked to the top, bottom, left, or right side of the display.
Its saved position is kept away from extreme corners so both the resting and
expanded surfaces remain on-screen.

## Control center

The expanded control center provides:

- Wi-Fi and Bluetooth entry points
- battery state
- output volume
- brightness
- media playback
- notifications
- wallpaper controls
- lock, capture, launcher, and power actions

Wi-Fi and Bluetooth open Maho Link rather than duplicating connectivity controls
inside the shell.

## Maho Dock

Maho Dock shows pinned applications and currently running applications.
It uses desktop-entry identity and Hyprland toplevel data to avoid duplicate app
entries and to focus the correct existing window when possible.

Pinned state persists across application exit and shell restart.

## Live system state

Shell state is event-driven where native sources are available:

- workspaces and windows from Hyprland
- audio from PipeWire
- media from MPRIS
- battery from UPower
- brightness from the system brightness interface

Network and Bluetooth summary state use a narrow helper until their direct
Quickshell service paths are fully proven on the target system.

## Layout ownership

The visible Edge surface stays on the compositor overlay layer.
A separate transparent reservation surface owns the small amount of space kept
clear for tiled windows.

Opening the control center does not increase the reserved area, so tiled windows
do not move when Edge expands or collapses.

## Theme

Shell components read semantic colors from:

```text
~/.cache/maho/theme/active.json
```

The palette is derived from the active wallpaper. Components consume roles such
as foreground, muted text, surfaces, accent, outline, warning, and error rather
than hard-coded wallpaper-specific colors.

## Runtime

Maho Shell runs as a managed user service and keeps one shell instance active.
The launcher provides bounded diagnostics:

```text
maho-shell status --json
maho-shell doctor
maho-shell logs 120
maho-shell reload
```

If the managed shell cannot stay running, the session can restore its fallback
status bar instead of leaving the desktop without basic controls.
