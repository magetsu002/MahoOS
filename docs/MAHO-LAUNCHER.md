# Maho Launcher

Maho Launcher is MahoOS's production application launcher. Rofi remains the mature engine for application discovery, file browsing, fuzzy matching, native icon resolution, keyboard/mouse navigation, launch semantics, history, and the existing Apps / Files / Commands mode model.

## Current visual authority

The current approved launcher target is the implementation target. Maho Edge, Maho Link, and Maho Notify are the product-family material authority.

This convergence pass deliberately reuses their shared grammar instead of inventing a launcher-specific dark theme:

- Palette V2 `~/.cache/maho/theme/active.json` remains the only runtime color authority.
- Maho Link's shell base is derived from `mix(surfaceHigh, background, 0.28)` and its inset base from `mix(surfaceHigh, background, 0.36)`.
- Maho Link's stable accent behavior is mirrored for chromatic and low-chroma palettes.
- Edge's card language remains low-contrast fill plus thin semantic rim.
- Notify's material hierarchy remains surface-first with restrained accent luminance rather than a hard colored outline.

Rofi cannot import QML material code directly, so `lib/maho_launcher_theme.py` translates those same semantic roles into a small generated Rasi palette. The translation is atomic and contains no wallpaper-specific fixed hue.

## Approved composition

The launcher keeps the approved information architecture and real behavior while moving to the target proportions:

- centered 760×730 logical surface;
- 24 px outer radius;
- centered title with two real bounded header actions;
- inset search field;
- one cohesive Apps / Files / Commands segmented surface;
- nine visible result rows using native application icons and two-line metadata;
- a softly filled selected row;
- quiet centered “Show more apps” footer.

The top-left control returns to native Apps with a clean query through Rofi custom action 1. The top-right control opens the existing curated Commands mode through custom action 2. Both remain bounded by the production wrapper and do not evaluate launcher input.

## Material translation

The shell now follows Palette V2 at panel scale instead of suppressing wallpaper color into near-neutral graphite. The generated material uses:

- shell base: `surface_container_high` mixed toward `background` by 28%;
- inset base: the same semantic mix at 36%;
- stable accent: Maho Link's bounded saturation/value behavior;
- 84/87/90% shell gradient stops for real compositor participation without reading as a black hole;
- low-alpha search, segment, and results layers over the shell;
- selected segment and selected result as accent-tinted filled material;
- 12% outer outline, 8–9% quiet inner rims, and 6% separators;
- raw Palette V2 foreground/muted roles for typography instead of launcher-only desaturation.

The current reddish approved screenshot is therefore just one wallpaper-derived state. Cool, monochrome, pink/purple, green, and warm palettes remain explicitly contract-tested.

## Hyprland / Rofi boundary

The existing scoped Hyprland `rofi` layer rule remains unchanged: blur participation, `ignore_alpha = 0.06`, and `xray = true`. No global blur kernel or compositor decoration setting is mutated.

Rofi remains the backend. This pass does not add another process, daemon, polling loop, image pipeline, or launcher UI toolkit.

A practical Rofi limitation remains: custom header icon widgets can be real click actions and can have a static Maho hit-target material, but Rofi does not expose the same independent per-widget hover/pressed state machinery that the QML Edge/Link/Notify controls use. Replacing the backend for that detail would violate the task's architecture constraint and is not justified.

## Verification and rollback

Source contracts cover engine/mode preservation, bounded header actions, approved geometry, semantic palette translation, five palette families, effective layered opacity, singleton behavior, Edge invocation, and parser checks when Rofi is available.

Final visual and interaction acceptance still requires the native Hyprland/Rofi screenshot and real-machine run from the exact commit.

The pre-convergence rollback anchor is:

`safety/maho-launcher-pre-family-convergence` -> `20677ffb08bed235e264942448e93dae8bf7d610`

A normal Git revert of the convergence commit is also sufficient. No force-push or history rewrite is required.
