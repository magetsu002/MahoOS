# Maho Launcher

Maho Launcher is Maho's production application launcher. Rofi is the mature underlying engine; Maho owns the bounded launcher command, safe mode integration, Palette V2 translation, visual theme, compositor material rule, and Maho Edge bridge.

## Architecture

`maho-launcher open` starts native Rofi `drun`, so installed desktop-entry discovery, fuzzy matching, native icon resolution, keyboard/mouse navigation, launch semantics, and history remain Rofi responsibilities.

The visible modes are:

- **Apps** — native Rofi `drun`.
- **Files** — Rofi's built-in `filebrowser`.
- **Commands** — a short exact allowlist; search text is never evaluated as shell input.

The former custom Quickshell launcher remains historical/experimental on `feat/maho-launcher`. Production does not import it.

## Reference-fidelity composition

`config/rofi/maho-launcher/launcher.rasi` keeps the accepted product structure while converging on the current reference: a centered 720×720 logical frosted panel, 20px outer radius, calm centered title, inset search, one shared segmented-mode shelf, one shared results surface, eight visible rows, native application icons, two-line desktop metadata when available, quiet chevrons, and a low-hierarchy footer.

The visual controls stay functional through supported Rofi actions. The app-grid control clears the current query, the settings control performs bounded previous-mode navigation into Commands from the initial Apps mode, result chevrons accept entries, and “Show more apps” performs real next-page navigation.

No mascot, decorative branding, shortcut-number badges, tutorial footer, replacement application branding, or second launcher engine is introduced.

## Frosted material and Palette V2

`lib/maho_launcher_theme.py` reads the canonical `~/.cache/maho/theme/active.json` at launch and atomically emits the runtime Rasi palette. Same-directory temporary files, `fsync`, and `os.replace` preserve atomicity.

The material is graphite-first. Palette/environment color is treated as reflected light rather than a background paint:

- panel center alpha is 64%, with 60/64/68% vertical stops;
- search is a 22/28% inset layer over the panel;
- the segmented shelf is a 16/22% layer;
- the results surface is a 10/13% layer;
- active mode is a 24/32% illuminated accent layer;
- selected result is a 28/36% illuminated accent layer;
- the outer rim is 16%, soft inset borders 6%, separators 3%, and accent rims 18%.

Because those inner surfaces composite over the panel, their effective opacity is intentionally bounded rather than simply adding more dark alpha. At the center panel stop this is roughly 72% for search, 70% for the segmented shelf, 68% for results, and 74% for the selected result. The objective is for wallpaper luminance/color masses to remain optically present while the compositor diffuses fine detail.

The base panel receives only a small neutralized environment contribution and an even smaller primary-accent contribution. Accent remains much stronger in selected/focus material. Monochrome palettes collapse to graphite/silver behavior instead of acquiring a synthetic hue.

Five fixture families are contract-tested: monochrome, cool blue, warm orange, pink/purple, and muted green. Tests bound panel chroma, cross-palette panel distance, selected-surface accent separation, and effective stacked opacity.

## Hyprland material

While the launcher is open, the wrapper installs its existing runtime-only Hyprland layer rule for the `rofi` namespace with:

- `blur = true`
- `ignore_alpha = 0.06`
- `xray = true`

The rule is disabled on launcher exit. This pass does not call `hl.config` and does not mutate global compositor decoration settings.

The repository's known-good Hyprland baseline configures blur kernel size and pass count globally. Layer rules provide scoped participation but do not independently own the full kernel in the version previously validated. A fresh native acceptance run must inspect the user's currently installed Hyprland version/settings before making any stronger capability claim.

Rofi 2.0 exposes the fixed Wayland namespace `rofi`; therefore another concurrent Rofi surface can temporarily inherit the same material rule. The launcher wrapper still isolates its own process lifecycle using a lock and owned PID files and does not kill unrelated Rofi processes.

## Safety, performance, and rollback

The fidelity pass does not change `drun`, Files, Commands dispatch, native icon resolution, filtering, navigation, launch semantics, Edge integration, singleton behavior, lifecycle, or the safe execution boundary. It adds no daemon, polling loop, wallpaper processing path, or persistent visual helper.

The last fully measured production baseline (2026-08-24, before this fidelity pass) was 123 ms for the first process-visible open, 115–147 ms across five warm opens (124.8 ms mean), and 20,112 KiB Rofi RSS, with 50 open/close cycles completing without duplicate/zombie processes. Those figures are historical baseline evidence, not measurements for the new material. The bounded native acceptance run must measure the exact new commit before performance is re-certified.

The global launcher keybind and old rollback launcher remain untouched until visual approval. Repository rollback remains a normal revert of the production branch commits; no history rewriting or automatic merge is used.

## Current acceptance state

Source-level fidelity and five-palette material checks are required before commit. Final visual acceptance requires a fresh screenshot from the exact committed native runtime and belongs to the user. `design-qa.md` records that state and no longer treats the older synthetic comparison as final acceptance evidence.
