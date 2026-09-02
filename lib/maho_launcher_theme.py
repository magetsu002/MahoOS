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
    background = palette_color(
        colors,
        ("background",),
        FALLBACK["background"],
    )
    surface = palette_color(
        colors,
        ("surface_container", "surface"),
        FALLBACK["surface"],
    )
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
    outline = palette_color(
        colors,
        ("outline_variant", "outline"),
        FALLBACK["outline"],
    )
    primary = parse_hex(colors.get("primary"), FALLBACK["primary"])
    accent = stable_accent(primary, foreground, surface_high)

    # Share the current Edge / Link / Notify material grammar instead of
    # repainting Palette V2 through a launcher-specific neutralization pass.
    # Link's shell uses mix(surfaceHigh, background, 0.28), and its insets use
    # mix(surfaceHigh, background, 0.36). Rofi gets the same semantic bases,
    # then keeps just enough real alpha for Hyprland's scoped blur to breathe.
    shell = blend(surface_high, background, 0.28)
    shell_top = blend(shell, accent, 0.055)
    shell_mid = blend(shell, surface, 0.055)
    shell_bottom = blend(shell, background, 0.12)

    inset = blend(surface_high, background, 0.36)
    inset_top = blend(inset, surface_highest, 0.12)
    segment = blend(inset, background, 0.08)
    segment_top = blend(segment, surface_high, 0.12)
    results = blend(inset, background, 0.18)
    results_top = blend(results, surface_low, 0.08)

    selected_mode = blend(inset, accent, 0.16)
    selected_mode_top = blend(selected_mode, foreground, 0.035)
    selected_result = blend(inset, accent, 0.18)
    selected_result_top = blend(selected_result, foreground, 0.045)

    control = blend(inset, accent, 0.055)
    control_rim = blend(outline, accent, 0.24)

    # Symbolic chrome intentionally stays icon-theme based. Rofi resolves the
    # same installed icon theme as the desktop while app icons stay untouched.
    _ = icons_dir

    return f"""/* Generated atomically from Maho Palette V2 active.json. */
* {{
    maho-glass: {rgba(shell, 87)};
    maho-panel-top: {rgba(shell_top, 84)};
    maho-panel-bottom: {rgba(shell_bottom, 90)};
    maho-inset: {rgba(inset, 28)};
    maho-inset-top: {rgba(inset_top, 34)};
    maho-segment: {rgba(segment, 18)};
    maho-segment-top: {rgba(segment_top, 24)};
    maho-result-surface: {rgba(results, 8)};
    maho-result-top: {rgba(results_top, 11)};
    maho-selection: {rgba(selected_result, 42)};
    maho-selection-top: {rgba(selected_result_top, 48)};
    maho-rim: {rgba(outline, 12)};
    maho-border-soft: {rgba(outline, 9)};
    maho-result-rim: {rgba(outline, 8)};
    maho-divider: {rgba(outline, 6)};
    maho-accent-rim: {rgba(accent, 24)};
    maho-accent-soft: {rgba(selected_mode, 38)};
    maho-accent-soft-top: {rgba(selected_mode_top, 44)};
    maho-control-fill: {rgba(control, 12)};
    maho-control-rim: {rgba(control_rim, 14)};
    maho-panel-material: linear-gradient(to bottom, {rgba(shell_top, 84)}, {rgba(shell_mid, 87)}, {rgba(shell_bottom, 90)});
    maho-inset-material: linear-gradient(to bottom, {rgba(inset_top, 34)}, {rgba(inset, 28)});
    maho-segment-material: linear-gradient(to bottom, {rgba(segment_top, 24)}, {rgba(segment, 18)});
    maho-result-material: linear-gradient(to bottom, {rgba(results_top, 11)}, {rgba(results, 8)});
    maho-active-mode-material: linear-gradient(to bottom, {rgba(selected_mode_top, 44)}, {rgba(selected_mode, 38)});
    maho-selection-material: linear-gradient(to bottom, {rgba(selected_result_top, 48)}, {rgba(selected_result, 42)});
    maho-foreground: {rgb_hex(foreground)};
    maho-muted: {rgb_hex(muted)};
    maho-muted-soft: {rgba(muted, 78)};
    maho-icon-muted: {rgba(muted, 82)};
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
