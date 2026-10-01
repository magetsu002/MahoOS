#!/usr/bin/env python3
"""Generate MahoOS-owned fallback artwork without third-party source images."""
from __future__ import annotations

import math
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "config/quickshell/maho-lock/assets/maho-lock-dusk.jpg"
TERMINAL = ROOT / "share/maho/terminal/maho-orbit.apng"


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def require(name: str) -> str:
    value = shutil.which(name)
    if not value:
        raise SystemExit(f"missing required generator tool: {name}")
    return value


def lock_svg() -> str:
    # Deliberately abstract: geometry, gradients and light fields only.
    return """<svg xmlns="http://www.w3.org/2000/svg" width="1672" height="941" viewBox="0 0 1672 941">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#070a14"/><stop offset="0.45" stop-color="#121329"/><stop offset="1" stop-color="#250f24"/>
  </linearGradient>
  <radialGradient id="blue" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#4f78ff" stop-opacity="0.42"/><stop offset="1" stop-color="#4f78ff" stop-opacity="0"/></radialGradient>
  <radialGradient id="rose" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#ff6f9d" stop-opacity="0.34"/><stop offset="1" stop-color="#ff6f9d" stop-opacity="0"/></radialGradient>
  <linearGradient id="ring" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#8da7ff"/><stop offset="0.5" stop-color="#b087ff"/><stop offset="1" stop-color="#ff7ea8"/></linearGradient>
  <filter id="soft"><feGaussianBlur stdDeviation="44"/></filter>
  <filter id="glow"><feGaussianBlur stdDeviation="10"/></filter>
</defs>
<rect width="1672" height="941" fill="url(#bg)"/>
<ellipse cx="375" cy="250" rx="420" ry="330" fill="url(#blue)" filter="url(#soft)"/>
<ellipse cx="1390" cy="760" rx="510" ry="360" fill="url(#rose)" filter="url(#soft)"/>
<g transform="translate(836 470) rotate(-16)" fill="none">
  <ellipse rx="430" ry="180" stroke="#ffffff" stroke-opacity="0.035" stroke-width="2"/>
  <ellipse rx="340" ry="142" stroke="url(#ring)" stroke-opacity="0.30" stroke-width="3"/>
  <ellipse rx="255" ry="106" stroke="url(#ring)" stroke-opacity="0.12" stroke-width="16" filter="url(#glow)"/>
  <path d="M-145 90 L-145-90 L-45 35 L45-90 L145 90" stroke="url(#ring)" stroke-width="16" stroke-linecap="round" stroke-linejoin="round" opacity="0.78"/>
  <circle cx="340" cy="0" r="9" fill="#ff9bbb" opacity="0.92"/>
  <circle cx="-180" cy="-120" r="6" fill="#9fb3ff" opacity="0.8"/>
</g>
<g opacity="0.12" fill="#ffffff">
  <circle cx="170" cy="720" r="2"/><circle cx="255" cy="605" r="3"/><circle cx="505" cy="795" r="2"/>
  <circle cx="1180" cy="160" r="2"/><circle cx="1285" cy="270" r="3"/><circle cx="1510" cy="205" r="2"/>
</g>
</svg>"""


def orbit_svg(frame: int, frames: int = 24) -> str:
    angle = (360.0 * frame) / frames
    a = math.radians(angle)
    x = 130 + math.cos(a) * 82
    y = 107.5 + math.sin(a) * 47
    x2 = 130 + math.cos(a + math.pi) * 82
    y2 = 107.5 + math.sin(a + math.pi) * 47
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="260" height="215" viewBox="0 0 260 215">
<defs>
  <linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#91a9ff"/><stop offset="0.5" stop-color="#b78dff"/><stop offset="1" stop-color="#ff82ad"/></linearGradient>
  <filter id="glow"><feGaussianBlur stdDeviation="4"/></filter>
</defs>
<g fill="none" stroke-linecap="round" stroke-linejoin="round">
  <ellipse cx="130" cy="107.5" rx="82" ry="47" stroke="url(#g)" stroke-width="3" opacity="0.28" transform="rotate(-18 130 107.5)"/>
  <ellipse cx="130" cy="107.5" rx="61" ry="35" stroke="#ffffff" stroke-width="1.5" opacity="0.10" transform="rotate(28 130 107.5)"/>
  <path d="M82 142 L82 73 L116 119 L144 73 L178 142" stroke="url(#g)" stroke-width="10" opacity="0.90"/>
</g>
<circle cx="{x:.2f}" cy="{y:.2f}" r="7" fill="#ff91b5" opacity="0.35" filter="url(#glow)"/>
<circle cx="{x:.2f}" cy="{y:.2f}" r="3.6" fill="#ffd4e2"/>
<circle cx="{x2:.2f}" cy="{y2:.2f}" r="5" fill="#7f9fff" opacity="0.30" filter="url(#glow)"/>
<circle cx="{x2:.2f}" cy="{y2:.2f}" r="2.8" fill="#c9d3ff"/>
</svg>"""


def main() -> None:
    magick = require("magick")
    ffmpeg = require("ffmpeg")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    TERMINAL.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="maho-owned-assets-") as raw:
        tmp = Path(raw)
        lock_source = tmp / "maho-lock-fallback.svg"
        lock_source.write_text(lock_svg(), encoding="utf-8")
        run(magick, str(lock_source), "-strip", "-sampling-factor", "1x1", "-quality", "96", str(LOCK))
        for frame in range(24):
            svg = tmp / f"orbit-{frame:02d}.svg"
            png = tmp / f"orbit-{frame:02d}.png"
            svg.write_text(orbit_svg(frame), encoding="utf-8")
            run(magick, str(svg), "-background", "none", "-alpha", "on", "-strip", f"PNG32:{png}")
        run(
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-framerate", "12", "-i", str(tmp / "orbit-%02d.png"),
            "-map_metadata", "-1", "-plays", "0", "-f", "apng", str(TERMINAL),
        )


if __name__ == "__main__":
    main()
