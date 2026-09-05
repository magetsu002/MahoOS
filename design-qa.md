# Maho Lock visual fidelity QA

- Original lock target: `/home/magetsu/Downloads/maho-lock-target.png`
- Wallpaper source visual truth: `/home/magetsu/Downloads/rize3.png`
- User-reported blurred baseline: `/tmp/codex-clipboard-4660f51b-de23-4aa7-b9fe-f0d078f17552.png`
- Installed implementation screenshot: `/home/magetsu/Downloads/maho-lock-final-installed-sharp-rounded-20260905.png`
- Baseline vs installed comparison: `/home/magetsu/Downloads/maho-lock-before-vs-sharp-rounded-20260905.png`
- Source vs installed full comparison: `/home/magetsu/Downloads/maho-lock-source-vs-sharp-rounded-20260905.png`
- Source vs installed focused comparison: `/home/magetsu/Downloads/maho-lock-source-vs-sharp-rounded-focus-20260905.png`
- Rounded vs classic typography comparison: `/home/magetsu/Downloads/maho-lock-rounded-vs-classic-font-20260905.png`
- Real viewport: 1600 × 1000 logical pixels at 1.6 output scale; 2560 × 1600 captured pixels
- Wallpaper source pixels: 1672 × 941 (16:9)
- Implementation pixels: 2560 × 1600 (16:10)
- Normalization: the source was center-cropped to 1506 × 941 using the production `PreserveAspectCrop` rule, then both source and implementation were resized to 1280 × 800 for equal-size comparison. The focused cloud region is 450 × 260 in each half.
- State: customization preview, password field focused, default controls visible. The avatar changed through user personalization during this iteration, so avatar content is intentionally excluded from this wallpaper/type QA.

## Full-view comparison evidence

The source and installed views now retain the same cloud contours, fine sky streaks, character edges, crop, saturation relationship, and reflected horizon structure. The implementation remains modestly darker because the existing foreground-contrast veil is intentional. The prior baseline visibly spread every cloud edge and character silhouette; the installed view no longer does.

On the same 900 × 520 top-left region, a Laplacian edge-deviation check increased from `0.0172671` in the blurred baseline to `0.0763066` in the installed render (4.42×). This metric is supporting evidence only; the equal-size visual comparison confirms that the added detail is real source detail rather than sharpening halos.

## Focused comparison evidence

The equal-size cloud crop shows that the installed render preserves the source's stepped painted cloud boundaries and thin white streaks. No visible blur halo, ringing, compression block, or texture duplication remains. The installed output is still an upscale because the 1672 × 941 source is smaller than the physical 2560 × 1600 panel, but it is no longer deliberately degraded by the lock renderer.

The typography comparison confirms that Nunito at the explicit `wght=600` axis has rounded terminals and more visual weight than the classic Noto Sans/normal path. The clock is excluded from the font override and retains its previous family, weight, letter spacing, geometry, and two-dot colon. `MAHO_LOCK_TYPOGRAPHY=classic` successfully launched the previous Noto Sans/normal body-text path.

## Required fidelity surfaces

- Fonts and typography: non-clock UI now uses the bundled OFL Nunito variable font at weight axis 600; primary labels use the stronger rounded treatment. Sizes, line heights, wrapping, and positions are unchanged. The clock remains untouched. The previous Noto Sans/normal path is retained behind the `classic` environment override.
- Spacing and layout rhythm: no frame positions, margins, component sizes, field geometry, radii, vertical rhythm, or wallpaper crop rule changed.
- Colors and visual tokens: the established off-white hierarchy, glass opacity, focus veil, borders, and shadows are unchanged in this iteration.
- Image quality and asset fidelity: the redundant logical-size decode, mipmap softening, `ShaderEffectSource`, and full-screen `MultiEffect` blur were removed. The wallpaper now renders directly from the user's original source with smooth aspect-crop scaling.
- Copy and content: all visible labels and status text are unchanged.

## Comparison history

1. Original contrast fidelity pass — passed.
   - Earlier P1/P2 findings covered washed-out text/glass, avatar separation, and disappearing corner actions.
   - Those fixes and the clean single-capsule corner actions remain intact.
2. Wallpaper/font baseline — blocked.
   - P1: the wallpaper was decoded at the 1600 × 1000 logical UI size and then passed through a full-screen blur with `blur=0.34` and `blurMax=32`, before the compositor scaled it to 2560 × 1600.
   - P2: the first rounded-font trial resolved the variable font's ExtraLight alias, producing rounded but thinner text than requested.
3. Wallpaper quality fix — passed.
   - Fix: direct native-source `Image` rendering, no logical `sourceSize`, no full-screen effect texture, and `mipmap: false`; crop and transition animation were preserved.
   - Post-fix evidence: `/home/magetsu/Downloads/maho-lock-source-vs-sharp-rounded-20260905.png` and `/home/magetsu/Downloads/maho-lock-source-vs-sharp-rounded-focus-20260905.png`.
4. Typography correction — passed.
   - Fix: resolve the loaded family explicitly as `Nunito`, pin rounded body text to variable axis 600, keep the clock outside the override, and preserve the exact classic body family/weight path.
   - Post-fix evidence: `/home/magetsu/Downloads/maho-lock-rounded-vs-classic-font-20260905.png` plus successful installed-runtime launches for default and `MAHO_LOCK_TYPOGRAPHY=classic` modes.

## Findings

No actionable P0, P1, or P2 difference remains in the wallpaper-quality and rounded-type scope. The unavoidable source-to-panel upscale is a source-resolution constraint, not a rendering regression.

## Follow-up polish

- P3: for literal 1:1 panel detail, use a wallpaper at least 2560 × 1600 (or larger with a compatible crop). The current 1672 × 941 source now receives the best faithful scaling available without inventing detail.

final result: passed
