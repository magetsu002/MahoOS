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
    "foreground": "#edf2f8",
    "muted": "#aeb8c7",
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
    saturation = min(saturation, 0.62)
    value = max(value, 0.62)
    adjusted = colorsys.hsv_to_rgb(hue, saturation, value)
    return tuple(round(channel * 255) for channel in adjusted)


def neutral_text(rgb: tuple[int, int, int], minimum_value: float, maximum_value: float) -> tuple[int, int, int]:
    red, green, blue = (value / 255 for value in rgb)
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    saturation = min(saturation, 0.07)
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
    foreground = readable_foreground(
        neutral_text(parse_hex(colors.get("foreground"), FALLBACK["foreground"]), 0.91, 0.97)
    )
    muted = neutral_text(parse_hex(colors.get("muted"), FALLBACK["muted"]), 0.66, 0.76)
    accent = restrained_accent(parse_hex(colors.get("primary"), FALLBACK["primary"]))
    ar, ag, ab = accent
    return f"""/* Generated atomically from Maho Palette V2 active.json. */
* {{
    maho-glass: rgba(14, 22, 33, 91%);
    maho-inset: rgba(255, 255, 255, 4%);
    maho-result-surface: rgba(255, 255, 255, 2%);
    maho-selection: rgba({ar}, {ag}, {ab}, 20%);
    maho-rim: rgba(226, 236, 247, 25%);
    maho-border-soft: rgba(226, 236, 247, 12%);
    maho-accent-rim: rgba({ar}, {ag}, {ab}, 62%);
    maho-accent-soft: rgba({ar}, {ag}, {ab}, 17%);
    maho-foreground: {rgb_hex(foreground)};
    maho-muted: {rgb_hex(muted)};
    maho-icon-app-grid: "{icons_dir / 'app-grid.png'}";
    maho-icon-settings: "{icons_dir / 'settings.png'}";
    maho-icon-search: "{icons_dir / 'search.png'}";
    maho-icon-chevron-right: "{icons_dir / 'chevron-right.png'}";
    maho-icon-chevron-down: "{icons_dir / 'chevron-down.png'}";
    maho-icon-chevron-up: "{icons_dir / 'chevron-up.png'}";
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
