#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("maho_terminal_theme", ROOT / "lib" / "maho_terminal_theme.py")
terminal = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(terminal)

HEX = re.compile(r"^#[0-9a-f]{6}$")


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


palette = {
    "version": 1,
    "palette_version": 2,
    "mode": "dark",
    "colors": {
        "background": "#101112",
        "foreground": "#f0f1f2",
        "primary": "#aabbcc",
        "secondary": "#88aa99",
        "tertiary": "#bb99aa",
        "error": "#ff8888",
        "surface_container": "#202224",
        "surface_container_high": "#303336",
        "muted": "#9a9b9c",
        "outline": "#707274",
        "on_primary": "#111111",
    },
    "semantic": {
        "accent": "#aabbcc",
        "accent_foreground": "#111111",
        "accent_soft": "#34383c",
        "background": "#101112",
        "border": "#707274",
        "critical": "#ff8888",
        "focus": "#aabbcc",
        "foreground": "#f0f1f2",
        "foreground_muted": "#9a9b9c",
        "success": "#77cc88",
        "surface": "#202224",
        "surface_elevated": "#303336",
        "warning": "#eec066",
    },
}

first = terminal.render_kitty(palette)
second = terminal.render_kitty(palette)
check("terminal theme output is deterministic", first == second)

required = (
    "foreground", "background", "cursor", "selection_background", "url_color",
    "active_border_color", "inactive_border_color",
    *(f"color{i}" for i in range(16)),
)
parsed = {}
for line in first.splitlines():
    if not line or line.startswith("#"):
        continue
    key, value = line.split(maxsplit=1)
    parsed[key] = value

check("terminal theme contains required Kitty keys", all(key in parsed for key in required))
check("terminal theme emits valid colors", all(HEX.fullmatch(value) for value in parsed.values()))
check("ANSI palette preserves semantic distinction", len({parsed[f"color{i}"] for i in range(16)}) >= 8)
check("ANSI critical/success/warning remain distinct", len({parsed["color1"], parsed["color2"], parsed["color3"]}) == 3)
check("terminal theme uses semantic accent", parsed["cursor"] == palette["semantic"]["accent"])
check("terminal theme uses semantic background", parsed["background"] == palette["semantic"]["background"])

invalid = dict(palette)
invalid["palette_version"] = 1
try:
    terminal.render_kitty(invalid)
except ValueError:
    print("PASS non-Palette-V2 input is rejected")
else:
    raise AssertionError("non-Palette-V2 input was accepted")

with tempfile.TemporaryDirectory(prefix="maho-terminal-theme-") as tmp:
    out = Path(tmp) / "kitty.conf"
    terminal.atomic_write(out, first)
    check("atomic theme write preserves exact output", out.read_text() == first)

print("ALL TERMINAL THEME TESTS PASS")
