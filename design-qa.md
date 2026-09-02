# Maho Launcher visual QA

## Authority

The newly approved launcher target is the visual source of truth for Maho Launcher.

Maho Edge, Maho Link, and Maho Notify are the shared product-family authority for material, palette behavior, geometry, density, and state language. The launcher must converge toward them without redesigning those surfaces and without replacing the mature Rofi backend unless a hard blocker is proven.

Earlier launcher screenshots and previous claims of final visual acceptance are historical evidence only.

## What changed in this convergence pass

This is a visual-material pass, not a launcher redesign.

The production layout keeps its centered title, real header actions, search field, Apps / Files / Commands modes, real desktop icons, two-line results, keyboard/mouse navigation, selected row, and “Show more apps” continuation action.

The implementation now targets the approved proportions and family grammar:

- 760×730 logical frame instead of the previous tall 720×780 silhouette;
- 24 px outer radius;
- 14 px major-group rhythm;
- compact 32–33 px header hit targets with visible low-contrast material;
- 16 px search radius and restrained secondary text;
- one cohesive 14 px segmented shelf;
- nine visible results;
- 30 px app icons;
- 6×14 px row padding;
- 15 px results-container radius;
- subdued result rim and 6% separators;
- selected tab/result hierarchy from filled tinted material instead of a primarily bright outline;
- quieter centered footer.

## Shared material evidence

The current authority sources were inspected on `feat/maho-link-wifi`.

Maho Link derives its shell from `mix(surfaceHigh, background, 0.28)` and its inset color from `mix(surfaceHigh, background, 0.36)`, with a stable accent that clamps saturation/value and becomes a neutral foreground/surface mixture for low-chroma palettes.

Maho Edge cards use very low semantic fill with thin outline/primary rims.

Maho Notify uses a surface-high shell with a restrained primary/surface gradient and low-contrast card hierarchy.

The launcher generator now translates those same semantic roles from Palette V2 instead of neutralizing the palette into a launcher-specific graphite theme. The current red/brown state remains wallpaper-derived; it is not hardcoded.

## Contracted palette behavior

Five representative palette families remain mandatory: monochrome, cool blue, warm orange, pink/purple, and muted green.

Contracts require:

- shell tint to respond materially to all five Palette V2 families;
- monochrome palettes to remain neutral;
- selected states to carry stronger accent separation than the shell;
- effective alpha to stay within bounded glass/material ranges;
- active.json to remain the authority;
- atomic generated-theme replacement to remain intact.

## Backend boundary

Rofi remains the production engine. Apps, Files, Commands, native desktop-entry behavior, icon resolution, keyboard/mouse navigation, singleton handling, Edge invocation, and the existing safe Commands allowlist are unchanged.

The current Rofi-backed header controls remain genuine bounded actions. Their static rounded hit targets can match Maho geometry/material, but independent QML-style hover/pressed animation for those arbitrary header widgets is a known Rofi theming limitation. That is not a sufficient reason to introduce another launcher backend.

## Acceptance state

Repository/source convergence is not final visual acceptance.

The next required evidence is a native screenshot and interaction run from the exact committed head on the user's Hyprland/Rofi environment. Compare that screenshot directly against the approved target for:

- overall silhouette and proportions;
- warm/cool wallpaper-derived material;
- outer rim;
- search field;
- segmented control;
- selected tab;
- selected row;
- results-container subtlety;
- typography hierarchy;
- icon/chevron scale;
- footer placement;
- immediate family resemblance to Edge, Link, and Notify.

**Status: implementation ready for exact-head native acceptance; not yet visually signed off.**
