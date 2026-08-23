# Theme engine and Palette V2

Maho OS derives one palette from an image and passes that palette to desktop
components such as Hyprland and Kitty.

Color generation and theme application are separate. A new palette is checked
before it becomes active, and the previous working theme is kept for recovery.

## Why Palette V2 exists

The most saturated pixel is not necessarily visually important. Compression
fringes and antialiased edges can be strongly colored while occupying almost no
area, and a saturation-first seed can turn an essentially black-and-white image
into a bright orange desktop. Palette V2 represents the wallpaper's visual
character instead of its most exotic pixel.

The generator downsamples each image to at most 96 by 96 pixels, converts sRGB
samples to OKLab, and measures neutral ratio, median and 90th-percentile chroma,
and populated hue neighborhoods. Hue candidates are scored by coverage,
perceptual chroma, and lightness salience. A candidate must cover at least 6%
of the sampled image with meaningful chroma before it can override otherwise
neutral statistics. This rejects tiny fringe colors while allowing a real
colored region such as a red scarf to remain the accent.

Near-monochrome mode requires all of these robust signals:

- at least 82% of samples are perceptually neutral,
- median OKLab chroma is at most 0.035,
- 90th-percentile chroma is at most 0.075, and
- no qualifying hue neighborhood has meaningful coverage and chroma.

Monochrome palettes use a low-chroma cool neutral accent. Chromatic palettes
preserve the selected OKLCH hue while correcting lightness and, only when
needed, gamut chroma. Semantic foreground pairs receive a 4.5:1 contrast guard.
Error, warning, and success remain recognizable fixed semantic families rather
than being recolored from the wallpaper.

## Contract and stability

Palette documents keep the version-1 public envelope because existing
wallpaper transactions validate it. The additive `palette_version: 2` marker,
existing `mode` field, and every version-1 key under `colors` let Edge, Notify,
Launcher, and older consumers continue to work in either integration order.
New consumers can read `palette_mode`, bounded analysis metadata, and roles
under `semantic`, including accent foreground, elevated surface, focus, border,
shadow, success, warning, and critical.

Sampling, clustering, gamut mapping, and serialization are deterministic. The
extractor runs once as part of a wallpaper theme transaction; it does not poll
or create a continuous analysis daemon. Synthetic behavioral fixtures cover
grayscale, manga-like black and white, tiny color fringe, meaningful color,
major hue families, dark/bright scenes, and multicolor input.

The Matugen backend remains available explicitly for compatibility, but the
central Palette V2 canonicalizer owns final analysis, semantic correction, and
the active palette contract regardless of the raw backend.
