# Maho Launcher L1 Design QA

## Evidence

- Source visual truth: `/tmp/codex-clipboard-50c49626-d2eb-4e14-866d-a02d7cc93cee.png`
- Implementation screenshot: `/home/magetsu/Projects/Maho-OS-launcher/docs/MAHO-LAUNCHER-L1.png`
- Full-view combined comparison: `/tmp/maho-launcher-full-comparison-final.png`
- Focused header/search comparison: `/tmp/maho-launcher-header-comparison-final.png`
- Focused results/footer comparison: `/tmp/maho-launcher-results-comparison-final.png`
- State: native Wayland overlay, Apps selected, empty search, first result selected, live adaptive palette
- Viewport: 640 x 780 CSS px on the current monitor
- Source pixels: 1396 x 1313. The launcher region was cropped to 1027 x 1265 and normalized to 1024 x 1248.
- Implementation pixels: 1024 x 1248 from a 640 x 780 layer surface at the monitor's 1.6 scale.
- Density normalization: both full-view sides are 1024 x 1248 before comparison.

## Findings

No actionable P0, P1, or P2 mismatch remains.

- Fonts and typography: the implementation uses Inter with Noto Sans and system sans fallbacks. Header weight contrast, search size, row hierarchy, footer labels, line heights, elision, and antialiasing closely match the source at normalized density.
- Spacing and layout rhythm: the 640 px bounded panel, centered overlay, header/search/tab order, dividers, selected-row treatment, compact 60 px rows, bottom footer, radii, and mascot overlap reproduce Reference A's composition. Six complete live rows fit at this monitor-safe height; the reference's seventh example row is content-density guidance rather than fixed data.
- Colors and visual tokens: all chrome uses the current Maho palette. The captured amber/olive palette intentionally differs from Reference A's violet example; live validation also observed sakura-pink and amber states without source changes. Selected fills remain restrained and outlines use the adaptive accent.
- Image quality and asset fidelity: real application icons remain unmodified. Missing theme icons use a bundled Adwaita fallback. The Maho mark and mascot are real transparent raster assets, not code drawings. The exact reference mascot was unavailable, so an original artwork asset occupies the required independent, pointer-passive layer with the same peeking composition.
- Copy and content: header, placeholder, Apps / Files / Commands labels, row metadata, and footer instructions match the approved target. Live application names and descriptions intentionally reflect installed desktop entries rather than fixed mock data.
- Interaction states: search focus, filtered results, Up, Down, Enter launch, Escape, mouse hover, tab selection, bounded scrolling, empty L1 tab states, and selected-row motion were checked on the live Wayland surface.
- Runtime diagnostics: the final Quickshell log contains no QML, JavaScript, or launch errors. One non-blocking Qt SVG buffer-size warning remains; the affected visible app icon rendered correctly in the captured state.

## Comparison History

### Iteration 1

- Earlier P1: the mascot was oversized and obscured the centered header.
- Earlier P2: unavailable desktop icons exposed Qt's checkerboard error image.
- Earlier P2: background text competed with the panel because the tint was too transparent.
- Fixes: reduced and repositioned the mascot, resolved theme-icon availability before rendering, added a real Adwaita fallback asset, and increased adaptive panel/search opacity.
- Post-fix evidence: `implementation-launcher-v3.png` and the later full-view comparison show an unobstructed header, stable icon fallbacks, and legible material.

### Iteration 2

- Earlier P2: header/search content sat about 20 CSS px lower than Reference A.
- Fix: reduced the panel content top margin from 28 px to 8 px.
- Post-fix evidence: `/tmp/maho-launcher-header-comparison-final.png` shows aligned header, search, and tab rhythm.

### Iteration 3

- Earlier P2: 68 px rows were roughly 12% taller than the reference and reduced visible result density.
- Fix: reduced row height to 60 px and real app icons to 38 px.
- Post-fix evidence: `/tmp/maho-launcher-results-comparison-final.png` shows the reference's compact row rhythm with six complete live results and the footer fully visible.

## Follow-up Polish

- P3: replace the generated mascot with the exact approved character artwork if a standalone licensed source asset becomes available.
- P3: compositor-backed blur could further approximate the reference glass treatment, but the current tint intentionally avoids any Hyprland rule or Edge choreography change in L1.

## Implementation Checklist

- [x] Centered bounded native launcher
- [x] Dynamic Maho material and focus tokens
- [x] Separate mascot and logo assets
- [x] Real desktop-entry discovery and icons
- [x] Reference-matched search, tabs, rows, and footer
- [x] Keyboard and mouse states validated
- [x] Full and focused normalized comparisons reviewed

final result: passed
