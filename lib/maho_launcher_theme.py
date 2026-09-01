#!/usr/bin/env python3
"""Generate Maho Launcher's small Rasi palette include from active.json."""

from __future__ import annotations

import argparse
import colorsys
import json
import os
from pathlib import Path
import tempfile


FALLBACK = {
    "background": "#15171c",
    "surface": "#202228",
    "surface_high": "#2b2e35",
    "foreground": "#edf2f8",
    "muted": "#aeb8c7",
    "outline": "#7f8792",
    "primary": "#6a9fed",
}


def parse_hex(value: object, fallback: str) -> tuple[int, int, int]:
    if not isinstance(value, str):
        value = fallback
    text = value.strip().lstrip("#")
    if len(text) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in text):
        text = fallback.lstrip("#")
    return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))


def rgb_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def rgba(rgb: tuple[int, int, int], alpha: int) -> str:
    return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {alpha}%)"


def blend(first: tuple[int, int, int], second: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(round(a + (b - a) * amount) for a, b in zip(first, second))


def saturation(rgb: tuple[int, int, int]) -> float:
    red, green, blue = (value / 255 for value in rgb)
    return colorsys.rgb_to_hsv(red, green, blue)[1]


def neutralize(rgb: tuple[int, int, int], maximum_saturation: float) -> tuple[int, int, int]:
    red, green, blue = (value / 255 for value in rgb)
    hue, current_saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    adjusted = colorsys.hsv_to_rgb(hue, min(current_saturation, maximum_saturation), value)
    return tuple(round(channel * 255) for channel in adjusted)


def palette_color(colors: dict[str, object], names: tuple[str, ...], fallback: str) -> tuple[int, int, int]:
    for name in names:
        if name in colors:
            return parse_hex(colors[name], fallback)
    return parse_hex(fallback, fallback)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def readable_foreground(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    base = (14, 22, 33)
    if contrast(rgb, base) >= 4.5:
        return rgb
    return (237, 242, 248)


def restrained_accent(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    red, green, blue = (value / 255 for value in rgb)
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    saturation = min(saturation, 0.58)
    value = max(value, 0.62)
    adjusted = colorsys.hsv_to_rgb(hue, saturation, value)
    return tuple(round(channel * 255) for channel in adjusted)


def neutral_text(rgb: tuple[int, int, int], minimum_value: float, maximum_value: float) -> tuple[int, int, int]:
    red, green, blue = (value / 255 for value in rgb)
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    saturation = min(saturation, 0.06)
    value = min(max(value, minimum_value), maximum_value)
    adjusted = colorsys.hsv_to_rgb(hue, saturation, value)
    return tuple(round(channel * 255) for channel in adjusted)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.chmod(0o600)
    os.replace(temporary, path)


def load_colors(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return FALLBACK.copy()
    colors = data.get("colors", {})
    return colors if isinstance(colors, dict) else FALLBACK.copy()


def rasi_colors(colors: dict[str, object], icons_dir: Path) -> str:
    background = palette_color(colors, ("background",), FALLBACK["background"])
    surface = palette_color(colors, ("surface_container", "surface"), FALLBACK["surface"])
    surface_high = palette_color(
        colors,
        ("surface_container_high", "surface_container", "surface"),
        FALLBACK["surface_high"],
    )
    outline = palette_color(colors, ("outline_variant", "outline"), FALLBACK["outline"])
    foreground = readable_foreground(
        neutral_text(parse_hex(colors.get("foreground"), FALLBACK["foreground"]), 0.91, 0.97)
    )
    muted = neutral_text(parse_hex(colors.get("muted"), FALLBACK["muted"]), 0.74, 0.84)
    primary = parse_hex(colors.get("primary"), FALLBACK["primary"])
    accent = restrained_accent(primary)

    low_chroma = saturation(primary) < 0.12
    environment = neutralize(blend(background, surface, 0.55), 0.04 if low_chroma else 0.12)
    accent_light = neutralize(accent, 0.08 if low_chroma else 0.42)

    # The launcher is neutral graphite glass first. Palette V2 contributes only
    # a faint reflected environment to the body; focus/selection carries the
    # recognizable accent so warm wallpapers never repaint the full surface.
    neutral_glass = (22, 23, 27)
    panel = blend(neutral_glass, environment, 0.08)
    panel = blend(panel, accent_light, 0.004 if low_chroma else 0.010)
    panel_top = blend(blend(panel, neutralize(surface_high, 0.10), 0.12), foreground, 0.050)
    panel_bottom = blend(panel, neutralize(background, 0.10), 0.08)

    raised = blend(blend(panel, neutralize(surface_high, 0.10), 0.24), foreground, 0.035)
    raised_top = blend(raised, foreground, 0.080)
    segment = blend(panel, neutralize(surface, 0.08), 0.16)
    segment_top = blend(segment, foreground, 0.055)
    results = blend(panel, neutralize(surface, 0.06), 0.10)
    results_top = blend(results, foreground, 0.030)

    selected_mode = blend(raised, accent_light, 0.05 if low_chroma else 0.18)
    selected_mode_top = blend(selected_mode, foreground, 0.085)
    selected_result = blend(raised, accent_light, 0.04 if low_chroma else 0.15)
    selected_result = blend(selected_result, foreground, 0.065)
    selected_result_top = blend(selected_result, foreground, 0.120)

    rim = blend(neutralize(outline, 0.05), foreground, 0.36)
    border_soft = blend(neutralize(outline, 0.04), foreground, 0.22)
    focus = blend(neutralize(accent_light, 0.34), foreground, 0.20)
    divider = blend(panel, foreground, 0.18)

    # Chrome icons deliberately use icon-theme symbolic names instead of the
    # old baked raster copies. Rofi resolves these through GdkPixbuf/icon-theme,
    # so scalable Adwaita/Papirus/etc. assets stay crisp at fractional Wayland
    # scale while application icons remain untouched and native.
    _ = icons_dir

    return f"""/* Generated atomically from Maho Palette V2 active.json. */
* {{
    maho-glass: {rgba(panel, 64)};
    maho-panel-top: {rgba(panel_top, 60)};
    maho-panel-bottom: {rgba(panel_bottom, 68)};
    maho-inset: {rgba(raised, 22)};
    maho-inset-top: {rgba(raised_top, 28)};
    maho-segment: {rgba(segment, 16)};
    maho-segment-top: {rgba(segment_top, 22)};
    maho-result-surface: {rgba(results, 10)};
    maho-selection: {rgba(selected_result, 28)};
    maho-selection-top: {rgba(selected_result_top, 36)};
    maho-rim: {rgba(rim, 16)};
    maho-border-soft: {rgba(border_soft, 6)};
    maho-divider: {rgba(divider, 3)};
    maho-accent-rim: {rgba(focus, 18)};
    maho-accent-soft: {rgba(selected_mode, 24)};
    maho-accent-soft-top: {rgba(selected_mode_top, 32)};
    maho-panel-material: linear-gradient(to bottom, {rgba(panel_top, 60)}, {rgba(panel, 64)}, {rgba(panel_bottom, 68)});
    maho-inset-material: linear-gradient(to bottom, {rgba(raised_top, 28)}, {rgba(raised, 22)});
    maho-segment-material: linear-gradient(to bottom, {rgba(segment_top, 22)}, {rgba(segment, 16)});
    maho-result-material: linear-gradient(to bottom, {rgba(results_top, 13)}, {rgba(results, 10)});
    maho-active-mode-material: linear-gradient(to bottom, {rgba(selected_mode_top, 32)}, {rgba(selected_mode, 24)});
    maho-selection-material: linear-gradient(to bottom, {rgba(selected_result_top, 36)}, {rgba(selected_result, 28)});
    maho-foreground: {rgb_hex(foreground)};
    maho-muted: {rgb_hex(muted)};
    maho-icon-app-grid: "view-app-grid-symbolic";
    maho-icon-settings: "preferences-system-symbolic";
    maho-icon-search: "system-search-symbolic";
    maho-icon-chevron-right: "go-next-symbolic";
    maho-icon-chevron-down: "go-down-symbolic";
    maho-icon-chevron-up: "go-up-symbolic";
}}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--palette", required=True, type=Path)
    parser.add_argument("--static-theme", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    colors_path = args.output_dir / "generated-colors.rasi"
    runtime_path = args.output_dir / "runtime-theme.rasi"
    icons_dir = args.static_theme.resolve().parent / "icons"
    atomic_write(colors_path, rasi_colors(load_colors(args.palette), icons_dir))
    atomic_write(
        runtime_path,
        f'@import "{colors_path}"\n@import "{args.static_theme.resolve()}"\n',
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
