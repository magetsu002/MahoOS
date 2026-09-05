#!/usr/bin/env python3
"""Behavioral regression corpus for Maho Palette V2."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("maho_palette_v2", ROOT / "theme" / "palette_v2.py")
palette = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = palette
SPEC.loader.exec_module(palette)


def fail(message: str) -> None:
    raise AssertionError(message)


def hue_distance(first: float, second: float) -> float:
    distance = abs(first - second) % 360.0
    return min(distance, 360.0 - distance)


def write_ppm(path: Path, pixels: list[tuple[int, int, int]], width: int = 100) -> None:
    height = len(pixels) // width
    if width * height != len(pixels):
        fail("fixture pixel count is not rectangular")
    with path.open("wb") as stream:
        stream.write(f"P6\n{width} {height}\n255\n".encode())
        stream.write(bytes(channel for pixel in pixels for channel in pixel))


def rows(*bands: tuple[int, tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    pixels = []
    for count, color in bands:
        pixels.extend([color] * (count * 100))
    return pixels


def build_corpus(directory: Path) -> dict[str, Path]:
    fixtures: dict[str, list[tuple[int, int, int]]] = {
        "pure_grayscale": [(value, value, value) for value in range(20, 220, 2) for _ in range(100)],
        "manga": [
            ((18, 18, 18) if (x // 12 + y // 10) % 3 == 0 else (238, 238, 238) if x % 17 else (112, 112, 112))
            for y in range(100)
            for x in range(100)
        ],
        "tiny_orange_fringe": rows((98, (122, 122, 122)), (2, (255, 96, 12))),
        "meaningful_red": rows((82, (126, 126, 126)), (18, (210, 28, 42))),
        "violet": rows((55, (92, 44, 166)), (45, (135, 76, 214))),
        "blue": rows((50, (24, 72, 178)), (50, (35, 132, 220))),
        "green_landscape": rows((42, (27, 86, 44)), (35, (72, 132, 62)), (23, (144, 171, 101))),
        "warm": rows((55, (214, 70, 28)), (45, (244, 143, 43))),
        "very_dark": rows((35, (2, 2, 3)), (35, (10, 10, 12)), (30, (22, 22, 25))),
        "very_bright": rows((35, (248, 248, 248)), (35, (232, 232, 235)), (30, (218, 218, 222))),
        "multicolor": rows(
            (15, (180, 34, 44)),
            (15, (226, 125, 30)),
            (14, (210, 194, 48)),
            (14, (40, 145, 65)),
            (14, (35, 115, 194)),
            (14, (97, 64, 181)),
            (14, (180, 55, 155)),
        ),
    }

    paths = {}
    for name, pixels in fixtures.items():
        path = directory / f"{name}.ppm"
        write_ppm(path, pixels)
        paths[name] = path
    return paths


def assert_hue_family(document: dict[str, object], target: float, tolerance: float, name: str) -> None:
    primary = document["colors"]["primary"]
    _, chroma, hue = palette.hex_to_oklch(primary)
    if chroma < 0.055:
        fail(f"{name}: accent was over-neutralized ({primary}, C={chroma:.4f})")
    if hue_distance(hue, target) > tolerance:
        fail(f"{name}: accent hue {hue:.1f} is outside target family {target:.1f}±{tolerance:.1f}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maho-palette-v2-") as temp:
        directory = Path(temp)
        fixtures = build_corpus(directory)
        analyses = {name: palette.analyze_image(path) for name, path in fixtures.items()}
        documents = {
            name: palette.palette_document(path, "dark", analyses[name])
            for name, path in fixtures.items()
        }

        for name in ("pure_grayscale", "manga", "tiny_orange_fringe", "very_dark", "very_bright"):
            if analyses[name].palette_mode != "monochrome":
                fail(f"{name}: expected monochrome classification")
            primary = documents[name]["colors"]["primary"]
            _, chroma, _ = palette.hex_to_oklch(primary)
            if chroma >= 0.035:
                fail(f"{name}: monochrome accent is too chromatic: {primary}, C={chroma:.4f}")

        red = analyses["meaningful_red"]
        if red.palette_mode != "chromatic" or red.accent_coverage < 0.12:
            fail("meaningful 18% red region was rejected as fringe color")
        assert_hue_family(documents["meaningful_red"], 25.0, 30.0, "meaningful_red")
        assert_hue_family(documents["violet"], 305.0, 32.0, "violet")
        assert_hue_family(documents["blue"], 250.0, 32.0, "blue")
        assert_hue_family(documents["green_landscape"], 140.0, 34.0, "green_landscape")
        assert_hue_family(documents["warm"], 48.0, 32.0, "warm")

        if analyses["multicolor"].palette_mode != "chromatic":
            fail("multicolor wallpaper was over-neutralized")

        for fixture_name in fixtures:
            first = palette.palette_document(fixtures[fixture_name], "dark", palette.analyze_image(fixtures[fixture_name]))
            second = palette.palette_document(fixtures[fixture_name], "dark", palette.analyze_image(fixtures[fixture_name]))
            if first != second:
                fail(f"{fixture_name}: extraction is not deterministic")
            if set(first["colors"]) != set(palette.LEGACY_KEYS):
                fail(f"{fixture_name}: legacy color contract changed")
            required_semantics = {
                "background", "surface", "surface_elevated", "foreground",
                "foreground_muted", "accent", "accent_foreground", "accent_soft",
                "border", "focus", "shadow", "success", "warning", "critical",
            }
            if not required_semantics.issubset(first["semantic"]):
                fail(f"{fixture_name}: semantic palette is incomplete")

        for fixture_name in ("very_dark", "very_bright", "violet"):
            for mode in ("dark", "light"):
                colors = palette.build_colors(analyses[fixture_name], mode)
                if palette.contrast_ratio(colors["foreground"], colors["surface_container_high"]) < 4.5:
                    fail(f"{fixture_name}/{mode}: foreground is unreadable")
                if palette.contrast_ratio(colors["on_primary"], colors["primary"]) < 4.5:
                    fail(f"{fixture_name}/{mode}: accent foreground is unreadable")

        valid_raw = documents["violet"]["colors"]
        palette.validate_raw(valid_raw)
        packaged_raw = json.loads((ROOT / "theme" / "backends" / "basic" / "palette.raw.json").read_text())
        palette.validate_raw(packaged_raw)

        schema_example = json.loads((ROOT / "theme" / "schema" / "palette.example.json").read_text())
        if schema_example.get("version") != 1 or schema_example.get("palette_version") != 2:
            fail("packaged schema does not preserve the version-1 compatibility envelope")
        if set(schema_example.get("colors", {})) != set(palette.LEGACY_KEYS):
            fail("packaged schema does not preserve all legacy color keys")
        if not isinstance(schema_example.get("semantic"), dict):
            fail("packaged schema omits semantic palette roles")

        try:
            palette.validate_raw({"primary": "#ffffff"})
        except ValueError:
            pass
        else:
            fail("invalid backend schema was accepted")

        missing = directory / "missing.png"
        try:
            palette.analyze_image(missing)
        except ValueError:
            pass
        else:
            fail("missing wallpaper was accepted")

        encoded = json.dumps(documents["violet"], sort_keys=True)
        decoded = json.loads(encoded)
        if decoded["version"] != 1 or decoded["palette_version"] != 2:
            fail("Palette V2 document is not valid JSON")

        print("PALETTE V2 BEHAVIORAL TESTS PASS")
        for name in fixtures:
            analysis = analyses[name]
            primary = documents[name]["colors"]["primary"]
            print(
                f"{name}: mode={analysis.palette_mode} "
                f"neutral={analysis.neutral_ratio:.3f} "
                f"accent_coverage={analysis.accent_coverage:.3f} primary={primary}"
            )


if __name__ == "__main__":
    main()
