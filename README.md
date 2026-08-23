# Maho OS

Maho OS is an Arch-based operating-system project built around a strong,
modular and adaptive foundation.

The goal is not to create another static Arch rice.

Maho OS is intended to observe system state, make policy-driven adaptations,
verify their effects, recover safely from failure, and always preserve manual
user authority.

## Maho Shell

Maho also ships an experimental Quickshell desktop surface. It is not a second
static bar layered on top of the adaptation engine: it is the human-facing
surface for that engine.

The collapsed shell stays deliberately small and edge-fused. The same surface
morphs when context matters:

- workspace changes arrive directly from Hyprland instead of a slow polling loop
- PipeWire volume changes produce an immediate in-shell OSD
- brightness changes produce the same transient feedback language
- clicking the shell opens large, usable controls instead of tiny status targets
- Wi-Fi, Bluetooth, battery, volume, brightness, wallpaper and media state live
  in one control center without duplicating controls
- every surface reads `~/.cache/maho/theme/active.json` directly, so wallpaper
  adaptation recolors the shell without a Waybar/CSS bridge
- if Maho Shell exits, its runtime wrapper restores Waybar as a session fallback

The shell source is packaged under `config/quickshell/maho-shell/` and is wired
by `maho-setup` when Quickshell is available. Existing unmanaged Quickshell
configuration is never overwritten.

## Core principles

- stable core behavior
- modular configuration
- explicit system state
- policy separated from mutation
- reversible adapters
- verification after mutation
- automatic rollback
- explainable adaptation
- manual override
- reproducible deployment

## Current status

Foundation development.

- M0: known-good system baseline
- M1: modular Hyprland configuration
- M2: source of truth and safe configuration control
- M3: adaptive theme engine and Maho Shell integration in active development
