#!/usr/bin/env python3

import json
import sys
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp"}
MAX_ENTRIES = 96


def home_dir():
    try:
        return Path.home().resolve(strict=True)
    except OSError:
        return Path.home().resolve()


def inside_home(path, home):
    try:
        path.relative_to(home)
        return True
    except ValueError:
        return path == home


def resolve_directory(raw, home):
    if raw:
        candidate = Path(raw).expanduser()
    else:
        pictures = home / "Pictures"
        candidate = pictures if pictures.is_dir() else home

    try:
        candidate = candidate.resolve(strict=True)
    except OSError:
        candidate = home

    if not candidate.is_dir() or not inside_home(candidate, home):
        return home
    return candidate


def entry_payload(path):
    return {
        "name": path.name or str(path),
        "path": str(path),
        "isDir": path.is_dir(),
    }


def browse(raw):
    home = home_dir()
    current = resolve_directory(raw, home)

    directories = []
    images = []

    try:
        children = list(current.iterdir())
    except OSError:
        children = []

    for child in children:
        if child.name.startswith("."):
            continue

        try:
            resolved = child.resolve(strict=True)
        except OSError:
            continue

        if not inside_home(resolved, home):
            continue

        try:
            if resolved.is_dir():
                directories.append(resolved)
            elif resolved.is_file() and resolved.suffix.lower() in IMAGE_EXTENSIONS:
                images.append(resolved)
        except OSError:
            continue

    directories.sort(key=lambda path: path.name.casefold())
    images.sort(key=lambda path: path.name.casefold())
    entries = (directories + images)[:MAX_ENTRIES]

    parent = ""
    if current != home:
        candidate = current.parent
        if inside_home(candidate, home):
            parent = str(candidate)

    return {
        "path": str(current),
        "parent": parent,
        "entries": [entry_payload(path) for path in entries],
    }


def main():
    if len(sys.argv) > 2:
        print("usage: image_browser.py [DIRECTORY]", file=sys.stderr)
        return 2

    raw = sys.argv[1] if len(sys.argv) == 2 else ""
    print(json.dumps(browse(raw), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
