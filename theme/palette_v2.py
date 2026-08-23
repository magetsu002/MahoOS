#!/usr/bin/env python3
"""Maho Palette V2: deterministic, coverage-aware perceptual palettes."""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


LEGACY_KEYS = (
    "background",
    "surface",
    "surface_container",
    "surface_container_high",
    "foreground",
    "muted",
    "primary",
    "on_primary",
    "secondary",
    "on_secondary",
    "tertiary",
    "on_tertiary",
    "error",
    "on_error",
    "outline",
    "outline_variant",
)
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
SAMPLE_SIZE = 96
NEUTRAL_CHROMA = 0.035
CHROMATIC_CHROMA = 0.04
MIN_ACCENT_COVERAGE = 0.06
MIN_ACCENT_CHROMA = 0.055


@dataclass(frozen=True)
class Analysis:
    palette_mode: str
    pixel_count: int
    neutral_ratio: float
    median_chroma: float
    p90_chroma: float
    chromatic_coverage: float
    accent_coverage: float
    accent_lightness: float
    accent_chroma: float
    accent_hue: float


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def srgb_channel_to_linear(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def linear_channel_to_srgb(value: float) -> float:
    if value <= 0.0031308:
        return 12.92 * value
    return 1.055 * (max(0.0, value) ** (1.0 / 2.4)) - 0.055


def rgb_to_oklab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    red, green, blue = (srgb_channel_to_linear(value / 255.0) for value in rgb)
    light = 0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue
    medium = 0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue
    short = 0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue
    light, medium, short = (
        math.copysign(abs(value) ** (1.0 / 3.0), value)
        for value in (light, medium, short)
    )
    return (
        0.2104542553 * light + 0.7936177850 * medium - 0.0040720468 * short,
        1.9779984951 * light - 2.4285922050 * medium + 0.4505937099 * short,
        0.0259040371 * light + 0.7827717662 * medium - 0.8086757660 * short,
    )


def oklab_to_linear_rgb(lightness: float, a_axis: float, b_axis: float) -> tuple[float, float, float]:
    light = lightness + 0.3963377774 * a_axis + 0.2158037573 * b_axis
    medium = lightness - 0.1055613458 * a_axis - 0.0638541728 * b_axis
    short = lightness - 0.0894841775 * a_axis - 1.2914855480 * b_axis
    light, medium, short = light**3, medium**3, short**3
    return (
        4.0767416621 * light - 3.3077115913 * medium + 0.2309699292 * short,
        -1.2684380046 * light + 2.6097574011 * medium - 0.3413193965 * short,
        -0.0041960863 * light - 0.7034186147 * medium + 1.7076147010 * short,
    )


def oklch_to_hex(lightness: float, chroma: float, hue: float) -> str:
    angle = math.radians(hue % 360.0)
    candidate_chroma = max(0.0, chroma)
    linear = (0.0, 0.0, 0.0)

    # Preserve lightness and hue while reducing only the chroma needed to fit
    # sRGB. The fixed iteration count keeps output deterministic.
    for _ in range(28):
        linear = oklab_to_linear_rgb(
            clamp(lightness),
            candidate_chroma * math.cos(angle),
            candidate_chroma * math.sin(angle),
        )
        if all(-1e-7 <= value <= 1.0000001 for value in linear):
            break
        candidate_chroma *= 0.88

    channels = [clamp(linear_channel_to_srgb(value)) for value in linear]
    return "#{:02x}{:02x}{:02x}".format(*(round(value * 255) for value in channels))


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def hex_to_oklch(value: str) -> tuple[float, float, float]:
    lightness, a_axis, b_axis = rgb_to_oklab(hex_to_rgb(value))
    return lightness, math.hypot(a_axis, b_axis), math.degrees(math.atan2(b_axis, a_axis)) % 360.0


def relative_luminance(value: str) -> float:
    red, green, blue = (srgb_channel_to_linear(channel / 255.0) for channel in hex_to_rgb(value))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def blend(foreground: str, background: str, alpha: float) -> str:
    front = hex_to_rgb(foreground)
    back = hex_to_rgb(background)
    channels = [round(alpha * f + (1.0 - alpha) * b) for f, b in zip(front, back)]
    return "#{:02x}{:02x}{:02x}".format(*channels)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    index = round((len(values) - 1) * clamp(fraction))
    return sorted(values)[index]


def read_ppm(path: Path) -> list[tuple[int, int, int]]:
    """Read deterministic P6 fixtures without adding an image-library dependency."""
    data = path.read_bytes()
    if not data.startswith(b"P6"):
        raise ValueError("unsupported PPM fixture")
    offset = 2
    tokens = []
    while len(tokens) < 3:
        while offset < len(data) and chr(data[offset]).isspace():
            offset += 1
        if offset < len(data) and data[offset] == ord("#"):
            offset = data.find(b"\n", offset)
            if offset < 0:
                raise ValueError("invalid PPM fixture")
            continue
        end = offset
        while end < len(data) and not chr(data[end]).isspace():
            end += 1
        tokens.append(int(data[offset:end]))
        offset = end
    width, height, maximum = tokens
    if maximum != 255 or width <= 0 or height <= 0:
        raise ValueError("unsupported PPM fixture geometry")
    if offset >= len(data) or not chr(data[offset]).isspace():
        raise ValueError("invalid PPM fixture header")
    if data[offset : offset + 2] == b"\r\n":
        offset += 2
    else:
        offset += 1
    pixels = data[offset:]
    if len(pixels) != width * height * 3:
        raise ValueError("invalid PPM fixture pixel data")
    return [tuple(pixels[index : index + 3]) for index in range(0, len(pixels), 3)]


def sample_image(path: Path, sample_size: int = SAMPLE_SIZE) -> list[tuple[int, int, int]]:
    if not path.is_file():
        raise ValueError("wallpaper does not exist")

    if path.suffix.lower() == ".ppm":
        return read_ppm(path)

    try:
        result = subprocess.run(
            [
                "magick",
                f"{path}[0]",
                "-auto-orient",
                "-resize",
                f"{sample_size}x{sample_size}>",
                "-alpha",
                "off",
                "-colorspace",
                "sRGB",
                "-depth",
                "8",
                "rgb:-",
            ],
            check=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise ValueError("ImageMagick is required for Palette V2") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.decode("utf-8", "replace").strip()
        raise ValueError(f"wallpaper sampling failed: {message or 'invalid image'}") from exc

    data = result.stdout
    if not data or len(data) % 3:
        raise ValueError("wallpaper sampling returned invalid RGB data")
    return [tuple(data[index : index + 3]) for index in range(0, len(data), 3)]


def analyze_pixels(pixels: list[tuple[int, int, int]]) -> Analysis:
    if not pixels:
        raise ValueError("no wallpaper pixels to analyze")

    labs = []
    chromas = []
    hue_bins = [[0.0, 0.0, 0.0, 0.0, 0.0] for _ in range(24)]

    for rgb in pixels:
        lightness, a_axis, b_axis = rgb_to_oklab(rgb)
        chroma = math.hypot(a_axis, b_axis)
        labs.append((lightness, a_axis, b_axis, chroma))
        chromas.append(chroma)

        if chroma < CHROMATIC_CHROMA:
            continue
        hue = math.atan2(b_axis, a_axis) % (2.0 * math.pi)
        bucket = int(hue * len(hue_bins) / (2.0 * math.pi)) % len(hue_bins)
        weight = chroma
        hue_bins[bucket][0] += 1.0
        hue_bins[bucket][1] += a_axis * weight
        hue_bins[bucket][2] += b_axis * weight
        hue_bins[bucket][3] += lightness * weight
        hue_bins[bucket][4] += weight

    total = len(labs)
    neutral_ratio = sum(chroma < NEUTRAL_CHROMA for chroma in chromas) / total
    chromatic_coverage = sum(chroma >= CHROMATIC_CHROMA for chroma in chromas) / total
    median_chroma = percentile(chromas, 0.5)
    p90_chroma = percentile(chromas, 0.9)

    best_score = -1.0
    best = (0.0, 0.0, 0.0, 0.0, 0.0)
    for center in range(len(hue_bins)):
        rows = (hue_bins[(center - 1) % 24], hue_bins[center], hue_bins[(center + 1) % 24])
        count = sum(row[0] for row in rows)
        chroma_weight = sum(row[4] for row in rows)
        if count <= 0 or chroma_weight <= 0:
            continue
        mean_chroma = chroma_weight / count
        mean_lightness = sum(row[3] for row in rows) / chroma_weight
        coverage = count / total
        lightness_salience = 0.72 + 0.28 * (1.0 - min(1.0, abs(mean_lightness - 0.58) / 0.58))
        score = coverage * (mean_chroma**1.15) * lightness_salience
        if score > best_score:
            best_score = score
            best = (
                coverage,
                mean_lightness,
                mean_chroma,
                sum(row[1] for row in rows),
                sum(row[2] for row in rows),
            )

    coverage, lightness, chroma, a_sum, b_sum = best
    meaningful_accent = coverage >= MIN_ACCENT_COVERAGE and chroma >= MIN_ACCENT_CHROMA
    neutral_statistics = (
        neutral_ratio >= 0.82
        and median_chroma <= 0.035
        and p90_chroma <= 0.075
    )
    palette_mode = "monochrome" if neutral_statistics and not meaningful_accent else "chromatic"

    if palette_mode == "monochrome":
        lightness, chroma, hue = percentile([lab[0] for lab in labs], 0.62), 0.018, 250.0
    else:
        hue = math.degrees(math.atan2(b_sum, a_sum)) % 360.0 if a_sum or b_sum else 250.0
        if coverage <= 0:
            lightness, chroma = 0.62, 0.065

    return Analysis(
        palette_mode=palette_mode,
        pixel_count=total,
        neutral_ratio=neutral_ratio,
        median_chroma=median_chroma,
        p90_chroma=p90_chroma,
        chromatic_coverage=chromatic_coverage,
        accent_coverage=coverage,
        accent_lightness=lightness,
        accent_chroma=chroma,
        accent_hue=hue,
    )


def analyze_image(path: Path) -> Analysis:
    return analyze_pixels(sample_image(path))


def build_colors(analysis: Analysis, mode: str) -> dict[str, str]:
    if mode not in ("dark", "light"):
        raise ValueError("mode must be dark or light")

    hue = analysis.accent_hue
    monochrome = analysis.palette_mode == "monochrome"
    accent_chroma = 0.018 if monochrome else clamp(analysis.accent_chroma * 1.05, 0.065, 0.18)
    tint_chroma = 0.009 if monochrome else min(0.028, accent_chroma * 0.20)

    if mode == "dark":
        colors = {
            "background": oklch_to_hex(0.105, tint_chroma * 0.55, hue),
            "surface": oklch_to_hex(0.135, tint_chroma * 0.65, hue),
            "surface_container": oklch_to_hex(0.180, tint_chroma * 0.80, hue),
            "surface_container_high": oklch_to_hex(0.230, tint_chroma, hue),
            "foreground": oklch_to_hex(0.935, tint_chroma * 0.45, hue),
            "muted": oklch_to_hex(0.715, tint_chroma * 0.70, hue),
            "primary": oklch_to_hex(0.780, accent_chroma, hue),
            "on_primary": oklch_to_hex(0.185, min(0.045, accent_chroma * 0.32), hue),
            "secondary": oklch_to_hex(0.745, 0.016 if monochrome else accent_chroma * 0.50, hue + (0 if monochrome else 28)),
            "on_secondary": oklch_to_hex(0.175, min(0.040, accent_chroma * 0.28), hue + (0 if monochrome else 28)),
            "tertiary": oklch_to_hex(0.755, 0.014 if monochrome else accent_chroma * 0.56, hue - (0 if monochrome else 34)),
            "on_tertiary": oklch_to_hex(0.175, min(0.040, accent_chroma * 0.28), hue - (0 if monochrome else 34)),
            "error": "#ffb4ab",
            "on_error": "#690005",
            "outline": oklch_to_hex(0.585, tint_chroma * 0.90, hue),
            "outline_variant": oklch_to_hex(0.355, tint_chroma * 0.85, hue),
        }
    else:
        colors = {
            "background": oklch_to_hex(0.982, tint_chroma * 0.35, hue),
            "surface": oklch_to_hex(0.958, tint_chroma * 0.45, hue),
            "surface_container": oklch_to_hex(0.915, tint_chroma * 0.60, hue),
            "surface_container_high": oklch_to_hex(0.875, tint_chroma * 0.75, hue),
            "foreground": oklch_to_hex(0.185, tint_chroma * 0.75, hue),
            "muted": oklch_to_hex(0.430, tint_chroma * 0.85, hue),
            "primary": oklch_to_hex(0.465, accent_chroma, hue),
            "on_primary": "#ffffff",
            "secondary": oklch_to_hex(0.440, 0.016 if monochrome else accent_chroma * 0.52, hue + (0 if monochrome else 28)),
            "on_secondary": "#ffffff",
            "tertiary": oklch_to_hex(0.445, 0.014 if monochrome else accent_chroma * 0.58, hue - (0 if monochrome else 34)),
            "on_tertiary": "#ffffff",
            "error": "#ba1a1a",
            "on_error": "#ffffff",
            "outline": oklch_to_hex(0.510, tint_chroma, hue),
            "outline_variant": oklch_to_hex(0.785, tint_chroma * 0.70, hue),
        }

    for foreground, background in (
        ("foreground", "background"),
        ("foreground", "surface_container_high"),
        ("on_primary", "primary"),
        ("on_secondary", "secondary"),
        ("on_tertiary", "tertiary"),
        ("on_error", "error"),
    ):
        if contrast_ratio(colors[foreground], colors[background]) < 4.5:
            # This is a last-resort semantic guard. Generated tones normally
            # pass directly; choosing black/white changes no accent hue.
            black_ratio = contrast_ratio("#000000", colors[background])
            white_ratio = contrast_ratio("#ffffff", colors[background])
            colors[foreground] = "#000000" if black_ratio >= white_ratio else "#ffffff"

    return colors


def build_semantic(colors: dict[str, str], mode: str) -> dict[str, str]:
    return {
        "background": colors["background"],
        "surface": colors["surface_container"],
        "surface_elevated": colors["surface_container_high"],
        "foreground": colors["foreground"],
        "foreground_muted": colors["muted"],
        "accent": colors["primary"],
        "accent_foreground": colors["on_primary"],
        "accent_soft": blend(colors["primary"], colors["surface_container"], 0.18),
        "border": colors["outline"],
        "focus": colors["primary"],
        "shadow": "#000000" if mode == "dark" else "#202124",
        "success": "#7bdc87" if mode == "dark" else "#176b2c",
        "on_success": "#06210c" if mode == "dark" else "#ffffff",
        "warning": "#ffca6b" if mode == "dark" else "#7a4e00",
        "on_warning": "#2b1700" if mode == "dark" else "#ffffff",
        "critical": colors["error"],
        "on_critical": colors["on_error"],
    }


def validate_raw(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("palette backend output must be an object")
    missing = sorted(set(LEGACY_KEYS) - set(raw))
    extra = sorted(set(raw) - set(LEGACY_KEYS))
    if missing or extra:
        raise ValueError(f"palette contract mismatch; missing={missing}, extra={extra}")
    for name in LEGACY_KEYS:
        if not isinstance(raw[name], str) or not HEX_COLOR.fullmatch(raw[name]):
            raise ValueError(f"invalid color {name}: {raw[name]!r}")
    return {name: raw[name].lower() for name in LEGACY_KEYS}


def palette_document(wallpaper: Path, mode: str, analysis: Analysis) -> dict[str, object]:
    colors = build_colors(analysis, mode)
    return {
        # The transaction adapter intentionally still accepts the version-1
        # envelope. Palette V2 is additive inside that stable public contract.
        "version": 1,
        "palette_version": 2,
        "mode": mode,
        "palette_mode": analysis.palette_mode,
        "source": {"type": "wallpaper", "path": str(wallpaper)},
        "analysis": {
            "color_space": "oklab",
            "sample_pixels": analysis.pixel_count,
            "neutral_ratio": round(analysis.neutral_ratio, 6),
            "median_chroma": round(analysis.median_chroma, 6),
            "p90_chroma": round(analysis.p90_chroma, 6),
            "chromatic_coverage": round(analysis.chromatic_coverage, 6),
            "accent_coverage": round(analysis.accent_coverage, 6),
        },
        "colors": colors,
        "semantic": build_semantic(colors, mode),
    }


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def main(arguments: list[str]) -> int:
    if len(arguments) < 1:
        raise ValueError("usage: palette_v2.py raw|canonicalize ...")

    command = arguments[0]
    if command == "raw" and len(arguments) == 4:
        wallpaper, mode, output = Path(arguments[1]).resolve(), arguments[2], Path(arguments[3])
        analysis = analyze_image(wallpaper)
        write_json(output, build_colors(analysis, mode))
        return 0

    if command == "canonicalize" and len(arguments) == 5:
        raw_path, output = Path(arguments[1]), Path(arguments[2])
        wallpaper, mode = Path(arguments[3]).resolve(), arguments[4]
        try:
            raw = json.loads(raw_path.read_text())
        except Exception as exc:
            raise ValueError(f"invalid backend JSON: {exc}") from exc
        validate_raw(raw)
        analysis = analyze_image(wallpaper)
        write_json(output, palette_document(wallpaper, mode, analysis))
        return 0

    raise ValueError("usage: palette_v2.py raw WALLPAPER MODE OUT | canonicalize RAW OUT WALLPAPER MODE")


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except ValueError as error:
        print(f"palette-v2: {error}", file=sys.stderr)
        raise SystemExit(1)
