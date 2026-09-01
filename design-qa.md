# Maho Launcher visual QA

## Authority

The current Maho Launcher reference supplied for the visual-fidelity pass is the visual source of truth. The older checked-in comparison images remain historical evidence only. Their previous `final result: passed` conclusion is superseded because the production runtime was subsequently rejected as visually final.

Acceptance is now deliberately split into two stages:

1. source-level convergence and regression checks;
2. a fresh native Hyprland/Rofi screenshot compared directly with the current reference.

Only the user can make final visual acceptance after stage 2.

## Source-level convergence in this pass

The launcher keeps the same product structure: native Rofi `drun`, Files, curated Commands, centered 720px-wide frame, header, search, three modes, eight visible results, footer, native application icons, Edge seam, singleton handling, and safe execution model.

A focused density pass changes vertical composition without adding features:

- launcher height increases from 720px to 780px so the existing hierarchy can breathe;
- major vertical groups move from 13px to 16px separation;
- window padding increases to 24px top / 22px bottom;
- search vertical padding increases from 13px to 15px;
- segmented-mode vertical padding increases slightly;
- result rows increase from 6px to 9px vertical padding while keeping all eight visible rows;
- the footer gains a small vertical buffer;
- outer corner radius remains 20px;
- application icons remain 32px and tertiary chevrons remain 10px.

The two header icons are also promoted from weak/incidental behavior to explicit bounded controls. The app-grid icon uses Rofi `kb-custom-1`, and the wrapper maps return code 10 back to native Apps (`drun`) with a clean query. The settings icon uses `kb-custom-2`, and return code 11 jumps directly to the existing curated Commands mode. F13/F14 are used as isolated backing bindings, so existing common Alt+number shortcuts are not repurposed. No arbitrary shell execution is introduced.

The material pass remains unchanged:

- the panel base is reduced from an 80% center alpha to 64%, with 60/64/68% top/center/bottom stops;
- inset surfaces are intentionally low-alpha layers over the panel instead of opaque cards;
- active mode and selected-result emphasis comes primarily from illuminated material fill, while the accent rim remains 18%;
- palette/environment influence on the panel stays sharply reduced while selection surfaces retain substantially stronger accent response.

The resulting composited opacity remains bounded by contract tests. With a 64% panel center, representative effective alpha is about 72% for search, 70% for the segmented shelf, 68% for the results surface, and 74% for the selected row. This keeps broad wallpaper luminance available to the compositor blur instead of stacking the UI into an effectively opaque dark window.

## Palette invariants

Five fixture families remain mandatory: monochrome, cool blue, warm orange, pink/purple, and muted green. Across all five:

- the base panel remains low-chroma graphite;
- per-channel panel spread is capped so Palette V2 cannot repaint the launcher;
- cool/warm panel distance remains small;
- selected surfaces carry materially more environmental/accent variation than the panel;
- stacked surface opacity is bounded so glass does not collapse back into solid cards.

Palette V2 remains the only color authority. No wallpaper extractor or persistent helper is added.

## Compositor scope and limitations

The production wrapper still uses the existing runtime-only Hyprland layer rule with `blur`, `ignore_alpha = 0.06`, and `xray`, and disables the rule when the launcher exits. No global decoration setting is mutated by this pass.

The real acceptance machine previously reported Hyprland 0.56.2 with blur enabled, size 3, passes 4, `ignore_opacity=true`, `xray=true`, noise 0.0117, contrast 0.8916, brightness 1.0, and vibrancy 0.1696. The launcher scopes participation in that compositor configuration rather than mutating the global kernel.

Rofi 2.0 exposes the fixed Wayland namespace `rofi`, so the temporary scoped layer rule can affect another concurrent Rofi surface while Maho Launcher is open. Process ownership itself remains isolated by the launcher lock and PID files.

## Required fresh evidence

The native acceptance run must capture the exact commit, Rofi/Hyprland versions, active blur settings, contract/doctor output, launch timing, RSS, and a real screenshot. That screenshot must be compared against the current reference for silhouette, translucency, wallpaper participation/diffusion, neutral hue, rim, internal layering, search, tabs, selected tab, results, selected row, normal rows, separators, typography, icons, chevrons, footer, spacing, and immediate overall impression.

The run must also verify both header controls on the real Rofi 2.0 build: app-grid returns cleanly to Apps, and settings jumps to the existing Commands mode without breaking singleton/lifecycle behavior.

**Status: breathing-room and functional-header pass ready for native acceptance; not visually accepted.**
