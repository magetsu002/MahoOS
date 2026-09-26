#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _color(value: Any, name: str) -> str:
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise ValueError(f"invalid Palette V2 color {name}: {value!r}")
    return value.lower()


def _role(document: Mapping[str, Any], name: str, *fallbacks: str) -> str:
    semantic = document.get("semantic")
    colors = document.get("colors")
    semantic = semantic if isinstance(semantic, Mapping) else {}
    colors = colors if isinstance(colors, Mapping) else {}

    for key in (name, *fallbacks):
        if key in semantic:
            return _color(semantic[key], f"semantic.{key}")
        if key in colors:
            return _color(colors[key], f"colors.{key}")
    raise ValueError(f"Palette V2 role is missing: {name}")


def render_kitty(document: Mapping[str, Any]) -> str:
    if document.get("palette_version") != 2:
        raise ValueError("terminal theming requires Palette V2")

    mode = str(document.get("mode") or "dark")
    background = _role(document, "background")
    surface = _role(document, "surface", "surface_container")
    elevated = _role(document, "surface_elevated", "surface_container_high", "surface")
    foreground = _role(document, "foreground")
    muted = _role(document, "foreground_muted", "muted")
    border = _role(document, "border", "outline")
    accent = _role(document, "accent", "primary")
    accent_fg = _role(document, "accent_foreground", "on_primary", "foreground")
    accent_soft = _role(document, "accent_soft", "surface_elevated", "surface")
    success = _role(document, "success", "secondary")
    warning = _role(document, "warning", "primary")
    critical = _role(document, "critical", "error")
    primary = _role(document, "primary", "accent")
    secondary = _role(document, "secondary", "success")
    tertiary = _role(document, "tertiary", "accent")

    ansi0 = background if mode != "light" else muted
    ansi7 = muted if mode != "light" else foreground
    ansi8 = elevated if mode != "light" else border
    ansi15 = foreground

    entries = [
        ("foreground", foreground),
        ("background", background),
        ("cursor", accent),
        ("cursor_text_color", accent_fg),
        ("selection_foreground", foreground),
        ("selection_background", accent_soft),
        ("url_color", accent),
        ("active_border_color", accent),
        ("inactive_border_color", border),
        ("bell_border_color", warning),
        ("active_tab_foreground", accent_fg),
        ("active_tab_background", accent),
        ("inactive_tab_foreground", muted),
        ("inactive_tab_background", elevated),
        ("tab_bar_background", surface),
        ("color0", ansi0),
        ("color1", critical),
        ("color2", success),
        ("color3", warning),
        ("color4", primary),
        ("color5", tertiary),
        ("color6", secondary),
        ("color7", ansi7),
        ("color8", ansi8),
        ("color9", critical),
        ("color10", success),
        ("color11", accent),
        ("color12", primary),
        ("color13", tertiary),
        ("color14", secondary),
        ("color15", ansi15),
    ]

    lines = [
        "# generated-by: Maho Palette V2 terminal theme",
        "# source-of-truth: ~/.cache/maho/theme/active.json",
    ]
    lines.extend(f"{key} {value}" for key, value in entries)
    return "\n".join(lines) + "\n"


def load_palette(path: Path) -> Mapping[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, Mapping):
        raise ValueError("palette document must be an object")
    return data


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(raw)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def render_file(palette: Path, output: Path) -> None:
    atomic_write(output, render_kitty(load_palette(palette)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Kitty colors from Maho Palette V2")
    parser.add_argument("palette", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    render_file(args.palette, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
