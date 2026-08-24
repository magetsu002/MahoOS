**Comparison Target**

- Source visual truth: `/home/magetsu/maho_launcher.png` (Reference A — Frozen).
- Rendered implementation: `docs/qa/maho-launcher-runtime-blue.png`.
- Full-view evidence: `docs/qa/maho-launcher-panel-comparison.png` (source left, implementation right).
- Focused evidence: `docs/qa/maho-launcher-focus-comparison.png` (header, search, segmented modes, and selected row; source left, implementation right).
- Runtime viewport: 1600 × 1000 logical pixels on a 2560 × 1600 monitor at 1.6 scale; native Wayland Rofi, not a browser/CSS surface.
- Source pixels: 1312 × 1199. The source panel was cropped to 1108 × 1102 and normalized to 1152 × 1146, then centered on a 1152 × 1152 comparison canvas.
- Implementation pixels: 1152 × 1152, corresponding to the 720 × 720 logical Rofi window at 1.6 density. No density resampling was applied to the implementation.
- State: Apps mode, immediate search focus, first result selected, eight visible installed desktop entries, cool/blue Palette V2 fixture.

**Findings**

- No actionable P0, P1, or P2 mismatch remains.
- [P3] Rofi text metrics are slightly more rigid than the reference rendering.
  Location: row primary/secondary labels and tab labels.
  Evidence: the aligned focus comparison shows the same hierarchy and wrapping, but Rofi/Pango uses fixed theme-wide optical metrics rather than the reference's individually tuned type treatment.
  Impact: minor optical difference only; scan order, contrast, eight-row density, and two-line metadata remain intact.
  Follow-up: revisit only if Rofi exposes more granular per-line typography without replacing mature `drun` rendering.
- [P3] The compositor material scope cannot be uniquely namespaced per invocation.
  Location: Hyprland blur rule.
  Evidence: Rofi 2.0 exposes the fixed Wayland namespace `rofi`; the launcher uses a runtime-only rule and disables it on exit.
  Impact: a second unrelated Rofi menu opened concurrently could receive the same blur for the launcher's short lifetime. Process ownership remains isolated.
  Follow-up: adopt a per-invocation namespace when the installed Rofi variant provides one.

**Required Fidelity Surfaces**

- Fonts and typography: Noto Sans/Pango hierarchy is readable, weight-balanced, untruncated, and visually close after normalization. The P3 optical-metric difference above is accepted.
- Spacing and layout rhythm: 720 × 720 logical frame, 24px radius, header symmetry, inset search, one segmented control, one shared result surface, eight-row rhythm, and bottom affordance align with the source. No clipping or overlap remains.
- Colors and visual tokens: neutral 91% cool glass remains dominant. Palette primary is restrained to selection/focus surfaces; foreground, muted labels, icons, chevrons, rim, and search affordances remain readable across monochrome, cool, warm, and saturated fixtures.
- Image quality and asset fidelity: all visible application imagery uses the installed desktop-entry icons without recoloring or substitution. Header/search/chevron controls use packaged Adwaita-derived raster icons with clean transparency and no placeholder, emoji, inline SVG, or CSS-drawn replacement.
- Copy and content: fixed product copy matches Reference A. Runtime application names/descriptions intentionally reflect installed desktop metadata rather than the reference's illustrative application list.
- Interaction/accessibility: immediate search focus, typing, clear, Up/Down, Return, Escape, mode changes, paging, Files, Commands, and exact `drun` activation were tested. Standard Rofi pointer semantics remain enabled. Automated compositor-level pointer injection was unavailable and is recorded as a runtime limitation, not a visual blocker.

**Comparison History**

1. Initial comparison found a P2 proportion/density mismatch: the 720 × 780 logical implementation was visibly more elongated than Reference A, with larger icons and looser row rhythm.
2. Fix applied in `config/rofi/maho-launcher/launcher.rasi`: height 780 → 720, vertical padding 24 → 20, main spacing 16 → 14, row padding 8 → 6, icon size 42 → 40.
3. Post-fix evidence in `docs/qa/maho-launcher-panel-comparison.png` and `docs/qa/maho-launcher-focus-comparison.png` shows aligned panel proportions, eight-row density, header/search/mode geometry, selected slab, and icon scale. No P0/P1/P2 issue remains.

**Open Questions**

- None blocking. The installed-app content difference is intentional product behavior, and the two Rofi limitations are classified as P3/expected.

**Implementation Checklist**

- [x] Match normalized full-view composition and focused header/result region.
- [x] Preserve eight visible results and native desktop-entry imagery.
- [x] Verify palette-neutral material and selected/focus accents.
- [x] Exercise primary modes and keyboard interactions in the real Wayland session.
- [x] Record Rofi-specific residual limitations without hiding them.

final result: passed
