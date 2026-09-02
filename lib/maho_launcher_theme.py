#!/usr/bin/env python3
"""Generate Maho Launcher's Rasi palette from the shared active.json authority."""

from __future__ import annotations

import argparse
import colorsys
import json
import os
from pathlib import Path
import tempfile


FALLBACK = {
    "background": "#151313",
    "surface": "#211e1e",
    "surface_low": "#1b1919",
    "surface_high": "#2b2727",
    "surface_highest": "#363131",
    "foreground": "#eee9e7",
    "muted": "#c9c0bd",
    "outline": "#918986",
    "primary": "#b7a39d",
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


def blend(
    first: tuple[int, int, int],
    second: tuple[int, int, int],
    amount: float,
) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, amount))
    return tuple(round(a + (b - a) * amount) for a, b in zip(first, second))


def saturation(rgb: tuple[int, int, int]) -> float:
    red, green, blue = (value / 255 for value in rgb)
    return colorsys.rgb_to_hsv(red, green, blue)[1]


def stable_accent(
    source: tuple[int, int, int],
    foreground: tuple[int, int, int],
    surface_high: tuple[int, int, int],
) -> tuple[int, int, int]:
    """Mirror Maho Link's restrained stableAccent behavior for Rofi."""
    red, green, blue = (value / 255 for value in source)
    hue, current_saturation, value = colorsys.rgb_to_hsv(red, green, blue)

    if current_saturation < 0.08:
        return blend(foreground, surface_high, 0.38)

    current_saturation = max(0.20, min(0.62, current_saturation))
    value = max(0.62, min(0.88, value))
    adjusted = colorsys.hsv_to_rgb(hue, current_saturation, value)
    return tuple(round(channel * 255) for channel in adjusted)


def palette_color(
    colors: dict[str, object],
    names: tuple[str, ...],
    fallback: str,
) -> tuple[int, int, int]:
    for name in names:
        if name in colors:
            return parse_hex(colors[name], fallback)
    return parse_hex(fallback, fallback)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
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
    surface_low = palette_color(
        colors,
        ("surface_container_low", "surface_container", "surface"),
        FALLBACK["surface_low"],
    )
    surface_high = palette_color(
        colors,
        ("surface_container_high", "surface_container", "surface"),
        FALLBACK["surface_high"],
    )
    surface_highest = palette_color(
        colors,
        (
            "surface_container_highest",
            "surface_container_high",
            "surface_container",
            "surface",
        ),
        FALLBACK["surface_highest"],
    )
    foreground = parse_hex(colors.get("foreground"), FALLBACK["foreground"])
    muted = parse_hex(colors.get("muted"), FALLBACK["muted"])
    outline = palette_color(colors, ("outline_variant", "outline"), FALLBACK["outline"])
    primary = parse_hex(colors.get("primary"), FALLBACK["primary"])
    accent = stable_accent(primary, foreground, surface_high)

    # Maho iOS material: graphite glass first, wallpaper/environment second.
    # Broad wallpaper color should survive through Hyprland's blur, while the
    # launcher itself contributes only a restrained semantic tint. Selected
    # states carry the stronger accent instead of repainting the whole shell.
    neutral = (18, 18, 20)
    family_surface = blend(surface_high, background, 0.28)
    family_inset = blend(surface_high, background, 0.36)
    shell = blend(neutral, family_surface, 0.22)
    shell_top = blend(blend(shell, foreground, 0.035), accent, 0.035)
    shell_mid = blend(shell, surface, 0.045)
    shell_bottom = blend(shell, background, 0.10)

    inset = blend(neutral, family_inset, 0.30)
    inset_top = blend(inset, surface_highest, 0.14)
    segment = blend(inset, background, 0.10)
    segment_top = blend(segment, surface_high, 0.14)
    results = blend(inset, background, 0.18)
    results_top = blend(results, surface_low, 0.08)

    selected_mode = blend(inset, accent, 0.30)
    selected_mode_top = blend(selected_mode, foreground, 0.055)
    selected_result = blend(inset, accent, 0.24)
    selected_result_top = blend(selected_result, foreground, 0.060)

    control = blend(inset, foreground, 0.075)
    control_top = blend(control, foreground, 0.070)
    control_rim = blend(outline, accent, 0.18)
    rim = blend(outline, foreground, 0.18)
    icon_muted = blend(muted, foreground, 0.18)
    muted_lift = blend(muted, foreground, 0.08)

    _ = icons_dir

    return f"""/* Generated atomically from Maho Palette V2 active.json. */
* {{
    maho-glass: {rgba(shell, 72)};
    maho-panel-top: {rgba(shell_top, 68)};
    maho-panel-bottom: {rgba(shell_bottom, 76)};
    maho-inset: {rgba(inset, 12)};
    maho-inset-top: {rgba(inset_top, 18)};
    maho-segment: {rgba(segment, 8)};
    maho-segment-top: {rgba(segment_top, 13)};
    maho-result-surface: {rgba(results, 3)};
    maho-result-top: {rgba(results_top, 5)};
    maho-selection: {rgba(selected_result, 32)};
    maho-selection-top: {rgba(selected_result_top, 40)};
    maho-rim: {rgba(rim, 19)};
    maho-border-soft: {rgba(outline, 9)};
    maho-result-rim: {rgba(outline, 8)};
    maho-divider: {rgba(outline, 5)};
    maho-accent-rim: {rgba(accent, 25)};
    maho-selection-rim: {rgba(accent, 20)};
    maho-accent-soft: {rgba(selected_mode, 39)};
    maho-accent-soft-top: {rgba(selected_mode_top, 48)};
    maho-control-fill: {rgba(control, 9)};
    maho-control-rim: {rgba(control_rim, 13)};
    maho-panel-material: linear-gradient(to bottom, {rgba(shell_top, 68)}, {rgba(shell_mid, 72)}, {rgba(shell_bottom, 76)});
    maho-inset-material: linear-gradient(to bottom, {rgba(inset_top, 18)}, {rgba(inset, 12)});
    maho-segment-material: linear-gradient(to bottom, {rgba(segment_top, 13)}, {rgba(segment, 8)});
    maho-result-material: linear-gradient(to bottom, {rgba(results_top, 5)}, {rgba(results, 3)});
    maho-active-mode-material: linear-gradient(to bottom, {rgba(selected_mode_top, 48)}, {rgba(selected_mode, 39)});
    maho-selection-material: linear-gradient(to bottom, {rgba(selected_result_top, 40)}, {rgba(selected_result, 32)});
    maho-control-material: linear-gradient(to bottom, {rgba(control_top, 13)}, {rgba(control, 8)});
    maho-foreground: {rgb_hex(foreground)};
    maho-muted: {rgb_hex(muted_lift)};
    maho-muted-soft: {rgba(muted_lift, 78)};
    maho-icon-muted: {rgb_hex(icon_muted)};
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
