# Lock Screen Fidelity QA

## Evidence

- Source visual truth: `/home/magetsu/Downloads/target-lock2.png`
- Native implementation capture: `/home/magetsu/.codex/visualizations/2026/09/01/01a05dbc-4cec-7bd1-a571-3f5ffb1de79d/lock-screen-refinement/final-2560x1600.png`
- Full-view comparison: `/home/magetsu/.codex/visualizations/2026/09/01/01a05dbc-4cec-7bd1-a571-3f5ffb1de79d/lock-screen-refinement/full-comparison-3344x941.png`
- Focused authentication comparison: `/home/magetsu/.codex/visualizations/2026/09/01/01a05dbc-4cec-7bd1-a571-3f5ffb1de79d/lock-screen-refinement/auth-comparison-1520x520.png`
- Secure-parity refinement capture: `/home/magetsu/.codex/visualizations/2026/09/01/01a05dbc-4cec-7bd1-a571-3f5ffb1de79d/lock-screen-refinement/live-parity-fixes.png`
- Final bottom-action geometry capture: `/home/magetsu/.codex/visualizations/2026/09/01/01a05dbc-4cec-7bd1-a571-3f5ffb1de79d/lock-screen-refinement/final-action-icon-geometry-settled.png`
- Recovered PR branch capture: `/home/magetsu/Downloads/maho-lock-pr17-restored-centered-20260906.png`
- Explicit bundled-fallback decode capture: `/home/magetsu/Downloads/maho-lock-pr17-explicit-fallback-20260906.png`
- Source pixels: 1672 x 941 at 1x image density.
- Implementation pixels: 2560 x 1600 captured from the 1600 x 1000 logical-pixel eDP-1 output at 1.6x display scale.
- Comparison normalization: the native capture was scaled to 1672 x 941 to compare proportional placement against the 16:9 concept image. The untouched 16:10 native capture remains the authority for runtime sharpness and layout safety.
- State: settled preview, password focused and empty, avatar loaded, personalization controls idle, no picker open.

## Full-view comparison

The implementation preserves the target's centered clock/date/greeting hierarchy, right-side character composition, centered authentication cluster, top status row, and bottom-left/center/right utility actions. The source and implementation differ in displayed time and time-dependent greeting by design; the real clock state is authoritative.

## Focused comparison

The focused crop confirms that the clock scale, date and greeting hierarchy, avatar diameter and ring, password-field width and height, lock/divider/text alignment, eye control, and cool glass treatment now follow the source proportions closely. The crop was necessary because the small icons, divider, and text weight were not reliably judgeable in the full-view composite.

## Comparison history

### Pass 1 — blocked

- P2: The avatar was visibly smaller than the source and read as detached from the input.
- P2: The password field was too narrow, too transparent over clouds, and had no divider after the lock icon.
- P2: The clock and supporting text were underscaled relative to the source.
- P2: Helper text and bottom utility actions had insufficient contrast.

Fixes: enlarged and optically recentered the avatar; widened and raised the password capsule; added a focus-responsive divider; strengthened glass fill, edge, and shadow tokens; increased the clock and supporting type scale; clarified the helper line; and unified the bottom action sizes and glass weights.

### Pass 2 — passed

Post-fix evidence is recorded in the full-view and focused comparison files listed above. No actionable P0, P1, or P2 visual differences remain.

### Pass 3 — passed

The secure-parity follow-up confirms the selected avatar is present on the first captured frame and the password-field divider remains visible. Battery hover geometry now measures the complete rendered percentage label, including the three-digit `100%` state, instead of assuming a two-digit fixed width. The accepted composition and density are unchanged.

### Pass 4 — passed

The bottom-corner actions retain their accepted pill sizes and screen anchors. Their icon and label are now centered as one measured visual group, so the power icon moves farther inward for the short `Sleep` label while the wider `Switch user` group receives the smaller optical correction appropriate to its label width.

### Pass 5 — passed

The exact nine-file polished runtime was recovered from `/home/magetsu/Projects/MahoOS-guardian`, matched against the live deployed runtime, and promoted into PR #17. The centered bottom action group, larger glass controls, first-frame avatar loading, battery-label hover geometry, and accepted 2560 × 1600 composition are present in the recovered branch capture. The corrupt 12 KB fallback blob was replaced with a valid 1672 × 941 sRGB JPEG, and a JPEG-signature/truncation contract now prevents recurrence.

## Required fidelity surfaces

- Fonts and typography: passed. The clean native-rendered clock, bundled Nunito UI face, optical weights, and hierarchy align with the target. Dynamic time and greeting content intentionally remain real.
- Spacing and layout rhythm: passed. The original composition is unchanged; the avatar, input, button, helper line, and bottom utilities now match the target's visual proportions and grouping.
- Colors and visual tokens: passed. The central veil is stronger without becoming a card, and glass/foreground contrast remains cool, translucent, and wallpaper-aware.
- Image quality and asset fidelity: passed. The active wallpaper crop and right-side character placement are preserved; the avatar uses the existing high-resolution masked source and SVG icon family. The bundled fallback is now valid JPEG data and launches without the previous decode error.
- Copy and content: passed. Labels match the target's functional wording, while live time, greeting, keyboard layout, battery, and network values remain system-driven.
- Interaction states: passed by native preview and lock contracts. Initial password focus was confirmed in runtime logs; hover/press/focus/error behaviors remain wired through the existing components.
- Accessibility: passed for this scope. Contrast and target sizes improved, the password field retains keyboard focus and Enter/Escape behavior, and no persistent controls overlap at the native 1600 x 1000 logical viewport.

## Follow-up polish

- P3: The 16:9 source and the user's native 16:10 display necessarily show slightly different vertical whitespace; the hierarchy and anchors remain equivalent.

## Implementation checklist

- [x] Preserve wallpaper and composition.
- [x] Strengthen the central atmospheric veil.
- [x] Improve clock, supporting text, and top-status clarity.
- [x] Enlarge and integrate the avatar.
- [x] Improve password glass, icons, divider, and alignment.
- [x] Strengthen the unlock control and helper line.
- [x] Unify bottom utility pills.
- [x] Run all Maho Lock contract tests.
- [x] Eliminate first-frame fallback-avatar flash.
- [x] Size the battery hover surface from the complete percentage label.
- [x] Verify source/runtime parity through the permanent installer.
- [x] Geometrically center the bottom action icon-and-label groups.
- [x] Recover the exact polished runtime into PR #17.
- [x] Replace the invalid fallback blob with decodable JPEG data and a regression contract.

final result: passed
