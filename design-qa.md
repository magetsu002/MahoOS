**Comparison Target**

- Source visual truth: `/home/magetsu/maho_launcher.png` (Reference A — Frozen).
- Rendered implementation: `docs/qa/maho-launcher-runtime-blue.png`.
- Full-view evidence: `docs/qa/maho-launcher-panel-comparison.png` (source left, implementation right).
- Focused evidence: `docs/qa/maho-launcher-focus-comparison.png` (header, search, segmented modes, and selected row; source left, implementation right).
- Runtime viewport: 1600 × 1000 logical pixels on a 2560 × 1600 monitor at 1.6 scale; native Wayland Rofi, not a browser or CSS surface.
- Source pixels: 1312 × 1199. The source panel was cropped to 1108 × 1102, normalized to 1152 × 1146, and placed on a 1152 × 1152 comparison canvas.
- Implementation pixels: 1152 × 1152, corresponding to the frozen 720 × 720 logical Rofi window at 1.6 density. No density resampling was applied to the implementation.
- State: Apps mode, immediate search focus, first result selected, eight visible installed desktop entries, cool-blue Palette V2 fixture, detailed wallpaper backdrop, production `blur + ignore_alpha + xray` layer material.

**Findings**

- No actionable P0, P1, or P2 mismatch remains.
- [P3] Rofi text metrics are slightly more rigid than the reference rendering.
  Location: row primary/secondary labels and tab labels.
  Evidence: the aligned focused comparison preserves hierarchy and wrapping, but Rofi/Pango uses fixed optical metrics rather than the reference's individually tuned type treatment.
  Impact: minor optical difference only; scan order, contrast, eight-row density, and two-line metadata remain intact.
  Follow-up: revisit only if Rofi exposes more granular per-line typography without replacing mature `drun` rendering.
- [P3] Launcher-local blur strength inherits the compositor kernel.
  Location: Hyprland layer material.
  Evidence: the final comparison shows broad softened wallpaper forms through the panel, while Hyprland exposes per-layer `blur`, `ignore_alpha`, and `xray` but keeps size, passes, noise, contrast, brightness, and vibrancy in global decoration settings.
  Impact: the launcher cannot independently increase blur radius further without changing system-wide decoration behavior. The current scoped rule remains compelling and readable without persistent side effects.
  Follow-up: adopt per-layer kernel controls if Hyprland exposes them later.
- [P3] The compositor material scope cannot be uniquely namespaced per invocation.
  Location: Hyprland layer rule.
  Evidence: Rofi 2.0 exposes the fixed Wayland namespace `rofi`; the launcher uses a named runtime rule and disables it on exit.
  Impact: an unrelated Rofi surface opened concurrently could receive the same blur during the launcher's short lifetime. Process ownership remains isolated.
  Follow-up: adopt a per-invocation namespace when the installed Rofi variant provides one.

**Required Fidelity Surfaces**

- Fonts and typography: Noto Sans/Pango hierarchy is readable, weight-balanced, untruncated, and visually close after normalization. The P3 optical-metric difference above is accepted.
- Spacing and layout rhythm: the frozen 720 × 720 logical frame, 24px radius, header symmetry, inset search, one segmented control, one shared result surface, eight-row rhythm, and bottom affordance remain unchanged. No clipping or overlap is visible.
- Colors and visual tokens: the panel uses a neutral graphite foundation with subtle environment mixing, 76/80/82% vertical material depth, restrained palette accents, a faint outer rim, quiet separators, and a brighter selected-state edge. Monochrome, cool blue, warm orange, pink/purple, and muted green fixtures remain neutral at panel scale and expressive at focus scale.
- Image quality and asset fidelity: all application imagery uses installed desktop-entry icons without recoloring or substitution. Header, search, and chevron controls use packaged Adwaita-derived raster icons with clean transparency and no placeholders, emoji, inline SVG, or CSS-drawn replacement.
- Copy and content: fixed product copy matches Reference A. Runtime application names and descriptions intentionally reflect installed desktop metadata rather than the reference's illustrative list.
- Interaction/accessibility: immediate search focus, typing, clear, Up/Down, Return, Escape, mode changes, paging, Files, Commands, and exact `drun` activation remain covered. Focus rims, foreground text, muted metadata, icons, and chevrons remain legible across all five fixtures.

**Comparison History**

1. The earlier layout milestone found and fixed a P2 proportion/density mismatch: 720 × 780 became the frozen 720 × 720 Reference A geometry, with aligned eight-row rhythm and icon scale.
2. Material baseline comparison found a P2 mismatch: a fixed dark-navy fill read as flat and opaque, with little wallpaper blur, excessive blue cast, and weak depth separation.
3. First material iteration added semantic graphite-first gradients and palette restraint, but the normalized comparison still found a P2 density mismatch because the panel's base color and gradient were both composited. Fix: make every gradient-backed surface transparent underneath so material alpha is applied once.
4. Second material iteration found the blur backdrop incomplete over application windows. Fix: keep the scoped runtime-only layer rule, lower `ignore_alpha` to 0.06, and enable `xray` so the blur samples the full backdrop without changing global decoration settings.
5. Post-fix evidence in `docs/qa/maho-launcher-panel-comparison.png` and `docs/qa/maho-launcher-focus-comparison.png` shows neutral frosted glass, softened wallpaper forms, subtle cool environmental tint, differentiated search/mode/result surfaces, a selected slab with a brighter focus edge, restrained separators, readable two-line metadata, and unchanged geometry. No actionable P0/P1/P2 finding remains.

**Open Questions**

- None blocking. Installed-app content differences are intentional product behavior; the Rofi/Hyprland constraints above are expected P3 limitations.

**Implementation Checklist**

- [x] Match the normalized full-view composition and focused header/result region.
- [x] Replace the fixed opaque navy with a single-pass graphite-first material gradient.
- [x] Scope full-backdrop blur to the launcher layer and restore the rule on close.
- [x] Verify five palette families, including neutral monochrome behavior.
- [x] Preserve eight visible results, installed desktop-entry imagery, layout, and behavior.
- [x] Complete lifecycle, performance, parser, contract, and comparison checks.

final result: passed
