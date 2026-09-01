# Maho Launcher visual QA

## Authority

The current Maho Launcher reference supplied for the visual-fidelity pass is the visual source of truth. The older checked-in comparison images remain historical evidence only. Their previous `final result: passed` conclusion is superseded because the production runtime was subsequently rejected as visually final.

Acceptance is now deliberately split into two stages:

1. source-level convergence and regression checks;
2. a fresh native Hyprland/Rofi screenshot compared directly with the current reference.

Only the user can make final visual acceptance after stage 2.

## Source-level convergence in this pass

The launcher structure and product behavior remain frozen: native Rofi `drun`, Files, curated Commands, centered 720×720 frame, header, search, three modes, eight visible results, footer, native application icons, Edge seam, singleton handling, and safe execution model.

The visual pass changes the material rather than redesigning the launcher:

- outer corner radius converges from 24px to 20px;
- header/search chrome is slightly smaller and quieter;
- application icons converge from 38px to 32px;
- result/footer chevrons converge from 14px to 10px;
- normal-row separators remain present but drop to a 3% material token;
- the panel base is reduced from an 80% center alpha to 64%, with 60/64/68% top/center/bottom stops;
- inset surfaces are intentionally low-alpha layers over the panel instead of opaque cards;
- active mode and selected-result emphasis now comes primarily from illuminated material fill, while the accent rim drops from 36% to 18%;
- palette/environment influence on the panel is sharply reduced while selection surfaces retain substantially stronger accent response.

The resulting composited opacity is bounded by contract tests. With a 64% panel center, representative effective alpha is about 72% for search, 70% for the segmented shelf, 68% for the results surface, and 74% for the selected row. This keeps broad wallpaper luminance available to the compositor blur instead of stacking the UI into an effectively opaque dark window.

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

The repository's known-good Hyprland baseline exposes blur kernel size/passes globally while layer rules provide scoped blur participation. Because this pass is being performed without direct access to the user's active compositor session, installed runtime capabilities and the optical effect of the current kernel must be re-confirmed by the bounded native acceptance run rather than inferred from source.

Rofi 2.0 also exposes the fixed Wayland namespace `rofi`, so the temporary scoped layer rule can affect another concurrent Rofi surface while Maho Launcher is open. Process ownership itself remains isolated by the launcher lock and PID files.

## Required fresh evidence

The native acceptance run must capture the exact commit, Rofi/Hyprland versions, active blur settings, contract/doctor output, launch timing, RSS, and a real screenshot. That screenshot must be compared against the current reference for silhouette, translucency, wallpaper participation/diffusion, neutral hue, rim, internal layering, search, tabs, selected tab, results, selected row, normal rows, separators, typography, icons, chevrons, footer, spacing, and immediate overall impression.

**Status: source-level fidelity pass ready for native acceptance; not visually accepted.**
