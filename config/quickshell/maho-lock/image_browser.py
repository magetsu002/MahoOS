#!/usr/bin/env python3

import json
import sys
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp"}
MAX_ENTRIES = 120
MAX_SEARCH_SCAN = 4000


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


def immediate_entries(current, home):
    directories = []
    images = []

    try:
        children = list(current.iterdir())
    except OSError:
        children = []

    for child in children:
        if child.name.startswith(".") or child.is_symlink():
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
    return (directories + images)[:MAX_ENTRIES]


def recursive_search(current, home, query):
    needle = query.casefold().strip()
    if not needle:
        return immediate_entries(current, home)

    matches = []
    stack = [current]
    scanned = 0

    while stack and scanned < MAX_SEARCH_SCAN and len(matches) < MAX_ENTRIES:
        directory = stack.pop()
        try:
            children = list(directory.iterdir())
        except OSError:
            continue

        children.sort(key=lambda path: path.name.casefold(), reverse=True)
        for child in children:
            if scanned >= MAX_SEARCH_SCAN or len(matches) >= MAX_ENTRIES:
                break
            scanned += 1

            if child.name.startswith(".") or child.is_symlink():
                continue

            try:
                resolved = child.resolve(strict=True)
            except OSError:
                continue

            if not inside_home(resolved, home):
                continue

            try:
                if resolved.is_dir():
                    stack.append(resolved)
                    continue
                if not resolved.is_file() or resolved.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
            except OSError:
                continue

            if needle in resolved.name.casefold():
                matches.append(resolved)

    matches.sort(key=lambda path: (path.name.casefold(), str(path.parent).casefold()))
    return matches[:MAX_ENTRIES]


def browse(raw, query=""):
    home = home_dir()
    current = resolve_directory(raw, home)
    normalized_query = str(query or "").strip()
    entries = recursive_search(current, home, normalized_query)

    parent = ""
    if current != home:
        candidate = current.parent
        if inside_home(candidate, home):
            parent = str(candidate)

    return {
        "path": str(current),
        "parent": parent,
        "query": normalized_query,
        "entries": [entry_payload(path) for path in entries],
    }


def main():
    if len(sys.argv) > 3:
        print("usage: image_browser.py [DIRECTORY] [QUERY]", file=sys.stderr)
        return 2

    raw = sys.argv[1] if len(sys.argv) >= 2 else ""
    query = sys.argv[2] if len(sys.argv) == 3 else ""
    print(json.dumps(browse(raw, query), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
