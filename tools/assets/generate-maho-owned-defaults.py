#!/usr/bin/env python3
"""Generate MahoOS-owned fallback artwork without third-party source images."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "config/quickshell/maho-lock/assets/maho-lock-dusk.jpg"


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


def main() -> None:
    magick = require("magick")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="maho-owned-assets-") as raw:
        tmp = Path(raw)
        lock_source = tmp / "maho-lock-fallback.svg"
        lock_source.write_text(lock_svg(), encoding="utf-8")
        run(magick, str(lock_source), "-strip", "-sampling-factor", "1x1", "-quality", "96", str(LOCK))


if __name__ == "__main__":
    main()
