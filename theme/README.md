# Theme engine

MahoOS derives one shared color palette from the active wallpaper and uses it
across desktop components.

Wallpaper analysis and theme application are separate. A generated palette is
validated before it becomes active, and the previous working palette is kept so
a failed theme change can be rolled back.

## Palette generation

The generator samples the wallpaper in OKLab color space and looks for colors
that occupy a meaningful part of the image.

This avoids choosing tiny compression artifacts, antialiased edges, or isolated
bright pixels as the main accent.

Near-monochrome wallpapers use a restrained neutral accent. Wallpapers with a
clear color region preserve that color as the main accent after lightness and
gamut correction.

Foreground/background pairs are checked for readable contrast. Error, warning,
and success colors remain recognizable instead of being recolored from the
wallpaper.

## Active palette

The current palette is written to:

```text
~/.cache/maho/theme/active.json
```
Desktop components consume semantic roles such as:

- background and elevated surfaces
- foreground and muted text
- primary, secondary, and tertiary accents
- borders and focus state
- success, warning, and error

The palette format keeps compatibility fields used by older consumers while
also exposing the newer semantic roles.

## Backends

Palette extraction is deterministic and runs as part of a wallpaper transaction.
It is not a background polling service.

The built-in generator owns the final Maho palette. Matugen remains available as
an optional input backend, but its output is still normalized and validated
before it becomes active.
