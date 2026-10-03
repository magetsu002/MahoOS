# Hyprbind adoption map

Hyprbind is an authorized bootstrap/reference source for advanced Hyprland configuration in Maho Settings. Existing Maho owners remain authoritative.

Upstream provenance baseline:

- repository: `https://github.com/NullifiedSec/hyprbind`
- pinned adoption commit: `b55e527b439ffd3f97d4d8c1102052095dcf7b9a`
- permission: `LICENSES/HYPRBIND-MAHOOS-SPECIAL-LICENSE-EXCEPTION-v1.0.txt`

## KEEP

- Maho Settings native Qt/QML shell, palette, spacing and interaction language
- Maho bridge, search, readback, failure semantics and bounded owner refreshes
- Maho display, input, audio, wallpaper, notification, application and region authorities
- Guardian trust and security authority boundaries

## REWORK / WRAP NOW

- one Maho-owned Hyprland configuration writer
- Shortcuts: conflict-aware editing, submaps and readable key representation
- Rules: window, workspace and layer rules
- Motion: animation and Bézier editing
- Session: managed startup/session entries
- Configuration: variables, environment, health, backups and import/export

Hyprbind parsing/writing and safety ideas may be adapted behind Maho's authority model. Hyprbind must not become a second runtime authority or replace Maho's Settings UI.

## DO NOT USE AS MAHO AUTHORITY

- Hyprbind audio
- Hyprbind wallpaper management
- Hyprbind monitor/input writers
- Waybar, Starship, VIA/Vial and screenshare experimental tools

## Attribution and license boundary

MahoOS has a signed project-specific Hyprbind exception. It permits MahoOS/Maho Settings to copy, adapt, refactor, rebrand and integrate authorized Hyprbind material and distribute the resulting MahoOS derivative under GPL-3.0-only.

Required attribution is recorded in `THIRD_PARTY_NOTICES.md`. The signed exception is preserved in `LICENSES/HYPRBIND-MAHOOS-SPECIAL-LICENSE-EXCEPTION-v1.0.txt`.

When adapting upstream implementation code:

1. record the upstream file and pinned commit in the Maho source/module header or adjacent provenance note;
2. keep only functionality that fits Maho's single-owner model;
3. add Maho-specific tests before enabling mutation;
4. never silently broaden Hyprbind's authority into Maho-owned domains listed above.
