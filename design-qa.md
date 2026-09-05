# Maho Lock visual fidelity QA

- Source visual truth: `/home/magetsu/Downloads/maho-lock-target.png`
- Corner-action feedback crops: `/tmp/codex-clipboard-af295688-c6db-433f-a06d-bd38ae26f614.png`, `/tmp/codex-clipboard-de1dfcf1-5d69-4faf-bc18-32062ed75bc0.png`
- Baseline live screenshot: `/home/magetsu/Downloads/maho-lock-before-fidelity-20260905.png`
- Implementation screenshot: `/home/magetsu/Downloads/maho-lock-final-installed-20260905.png`
- Full comparison: `/home/magetsu/Downloads/maho-lock-target-vs-final-installed-20260905.png`
- Focused comparison: `/home/magetsu/Downloads/maho-lock-target-vs-final-installed-focus-20260905.png`
- Real viewport: 1600 × 1000 logical pixels at 1.6 output scale; 2560 × 1600 captured pixels
- Source pixels: 1672 × 941 (16:9)
- Implementation pixels: 2560 × 1600 (16:10)
- Normalization: source was proportionally fit and letterboxed into 1280 × 800; implementation was proportionally resized to 1280 × 800. No geometry was inferred from the source because its aspect ratio differs from the real output and the real clock/layout geometry is an explicit product constraint.
- State: live wallpaper and avatar, customization preview, password field focused, default controls visible

## Full-view comparison evidence

The final frame preserves the live wallpaper crop, clock implementation, two-dot colon, typography family, component placement, and control dimensions. Compared with the baseline, foreground hierarchy no longer collapses into the wallpaper: the date, greeting, authentication controls, helper copy, top status, and corner actions are immediately visible. The wallpaper remains vivid and no panel boundary is visible around the central stack.

## Focused comparison evidence

The focused comparison covers clock, date, greeting, avatar, password field, Unlock button, and preview helper. It confirms that the field now has a distinct cool-glass silhouette, luminous edge, internal highlight, and restrained shadow; the avatar has a cool ring and shadow; and the major text has stronger off-white contrast with a restrained separation shadow. The target's larger generated control geometry was intentionally not copied.

## Required fidelity surfaces

- Fonts and typography: existing family, sizes, weights, letter spacing, clock geometry, and two-dot colon are preserved. Only foreground alpha and restrained raised-text separation changed.
- Spacing and layout rhythm: no positions, gaps, margins, dimensions, radii, or wallpaper crop rules changed.
- Colors and visual tokens: primary/secondary/tertiary off-whites were strengthened; password/Unlock glass uses a cool blue tint with clearer borders; a broad radial focus veil was added without a detectable edge.
- Image quality and asset fidelity: the wallpaper and avatar sources, crop modes, decode quality, and artwork are unchanged. The avatar only gained edge/halo separation.
- Copy and content: all visible labels and status text are unchanged.

## Comparison history

1. Baseline — blocked.
   - P1: password glass, placeholder/icons, date/greeting, helper text, and corner actions were washed out against the sky/reflection.
   - P2: avatar edge merged into the blue scene; the interaction stack lacked local atmospheric separation.
2. Pass 1 — blocked.
   - Fixes: initial off-white tokens, focus veil, glass borders/shadows, avatar ring, and corner-action glass.
   - Remaining P2: password silhouette and secondary copy still read too softly at normalized viewing scale.
3. Passes 2–3 — blocked.
   - Fixes: increased secondary/tertiary foreground strength, cool-glass opacity/edge definition, and veil strength while retaining the wallpaper.
   - Remaining P2: corner labels still needed local contrast over the pale lower reflection.
4. Pass 4 — passed.
   - Fix: added a restrained dark-cool glass plate behind each corner action and strengthened its one-pixel text separation.
   - Post-fix evidence: both corner actions are immediately readable while remaining tertiary; no actionable P0/P1/P2 mismatch remains within the explicit geometry-preservation scope.
5. Corner-action polish — passed.
   - User feedback: the inner circular icon plate created cramped, uneven negative space inside the outer capsule.
   - Fix: removed the inner circle fill and border while retaining its 34-pixel alignment slot, leaving one clean glass button with balanced 8–9-pixel optical edge spacing.
   - Post-fix evidence: `/home/magetsu/Downloads/maho-lock-clean-action-sleep-20260905.png` and `/home/magetsu/Downloads/maho-lock-clean-action-switch-user-20260905.png`.

## Findings

No actionable P0, P1, or P2 visual differences remain within scope. The target and live output have different aspect ratios and generated geometry; those differences are expected and intentionally preserved rather than reproduced.

## Follow-up polish

No P3 change is recommended before user inspection. Additional opacity would risk turning the focus treatment into a visible panel or flattening the wallpaper.

final result: passed
