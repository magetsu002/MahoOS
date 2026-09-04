#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "lib/maho_files_theme.py"
SPEC = importlib.util.spec_from_file_location("maho_files_theme", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def test_semantic_palette_wins() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        palette = root / "active.json"
        palette.write_text(
            json.dumps(
                {
                    "colors": {
                        "background": "#010101",
                        "surface_container": "#020202",
                        "surface_container_high": "#030303",
                        "foreground": "#eeeeee",
                        "muted": "#aaaaaa",
                        "primary": "#ff0000",
                        "outline": "#888888",
                        "error": "#ffbbbb",
                    },
                    "semantic": {
                        "background": "#111111",
                        "surface": "#222222",
                        "surface_elevated": "#333333",
                        "foreground": "#f1f1f1",
                        "foreground_muted": "#b1b1b1",
                        "accent": "#abcdef",
                        "accent_soft": "#334455",
                        "border": "#778899",
                        "focus": "#fedcba",
                        "shadow": "#000000",
                        "critical": "#ff9988",
                    },
                }
            ),
            encoding="utf-8",
        )
        resolved = MODULE.load_palette(palette)
        assert_true(resolved["background"] == "#111111", "semantic background must win")
        assert_true(resolved["accent"] == "#abcdef", "semantic accent must win")
        assert_true(resolved["focus"] == "#fedcba", "semantic focus must win")


def test_legacy_palette_remains_supported() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        palette = root / "active.json"
        palette.write_text(
            json.dumps(
                {
                    "colors": {
                        "background": "#101010",
                        "surface_container": "#202020",
                        "surface_container_high": "#303030",
                        "foreground": "#f0f0f0",
                        "muted": "#b0b0b0",
                        "primary": "#aa7788",
                        "outline": "#777777",
                        "error": "#ff8877",
                    }
                }
            ),
            encoding="utf-8",
        )
        resolved = MODULE.load_palette(palette)
        assert_true(resolved["background"] == "#101010", "legacy background must remain supported")
        assert_true(resolved["surface"] == "#202020", "legacy surface must remain supported")
        assert_true(resolved["accent"] == "#aa7788", "legacy primary must map to accent")


def test_rendered_theme_is_isolated_and_targeted() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        output = root / "MahoFiles"
        css_path, index_path = MODULE.write_theme(output, root / "missing-palette.json")
        css = css_path.read_text(encoding="utf-8")
        index = index_path.read_text(encoding="utf-8")

        assert_true(css_path == output / "gtk-3.0/gtk.css", "GTK3 theme path changed")
        assert_true("GTK_THEME" not in css, "theme file must not own process environment")
        assert_true("alpha(@maho_bg, 0.62)" in css, "window material must remain translucent")
        assert_true("treeview.view" in css and "iconview.view" in css, "native file views must be styled")
        assert_true("placessidebar" in css, "native places sidebar must be styled")
        assert_true("button.titlebutton.close:hover" in css, "premium native close styling missing")
        assert_true("Maho Files" in index, "named private theme metadata missing")


def main() -> int:
    tests = [
        test_semantic_palette_wins,
        test_legacy_palette_remains_supported,
        test_rendered_theme_is_isolated_and_targeted,
    ]
    for test in tests:
        test()
        print(f"PASS  {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
