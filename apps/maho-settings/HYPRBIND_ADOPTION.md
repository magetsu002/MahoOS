# Hyprbind adoption map

Hyprbind is a bootstrap/reference source for advanced Hyprland configuration. Existing Maho owners remain authoritative.

## KEEP
- Maho Settings bridge, search, readback and failure semantics
- Maho display, input, audio, wallpaper, notification, application and region authorities

## REWORK / WRAP
- Shortcuts: wrap live Hyprland inspection now; mutation needs one Maho config writer
- Rules: adapt window/workspace/layer-rule concepts behind a Maho-facing writer
- Motion: wrap live animation/curve inspection now; later adapt editing behind the same writer
- Session: adapt startup/session concepts after ownership is explicit
- Configuration: wrap variables, environment, backups and import/export only after one writer owns them
- Diagnostics: reuse useful health/config-error concepts without claiming Guardian trust

## ADAPT LATER
- Conflict detection and readable key representation
- Submaps
- Rule editors
- Bézier curve editor
- Managed startup editing
- Configuration backups/import/export

## DO NOT USE AS MAHO AUTHORITY
- Hyprbind audio
- Hyprbind wallpaper management
- Hyprbind monitor/input writers
- Waybar, Starship, VIA/Vial and screenshare experimental tools

## License boundary
The inspected Hyprbind tree currently carries the Hyprbind Source License 1.0. It restricts redistribution/rebranding without prior written permission. This branch therefore uses no copied Hyprbind implementation code in Maho Settings; the inspected project is reference material until written permission is received and reviewed.
