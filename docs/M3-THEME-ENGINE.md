# M3 — Canonical Dynamic Theme Engine

## Goal

Create a single dynamic color source for Maho OS.

M3 does not restore the old ML4W theming architecture.

It replaces it with a deterministic Maho-owned pipeline.

## Architecture

### Generator

Responsible only for deriving a canonical palette from a source.

Possible sources:

- wallpaper
- static user-selected palette
- future profile or policy input

### Canonical state

The generated palette is stored as structured data.

Consumers do not inspect the wallpaper.

### Consumers

Each consumer converts the canonical palette into its own configuration format.

Examples:

- Hyprland Lua
- Kitty config
- CSS
- GTK CSS
- launcher theme

### Activation

Generated output must be staged before it becomes live.

Activation should be atomic where possible.

### Verification

Each consumer must define its own verification contract.

Hyprland:
- reload succeeds
- `hyprctl configerrors` is empty

Kitty:
- generated config exists
- reload signal succeeds when Kitty is running

### Recovery

The previous generated theme must remain available until the new theme is verified.

## Non-goals

M3 does not implement:
- the Maho state engine
- policy-based theme switching
- performance adaptation
- the full desktop shell
