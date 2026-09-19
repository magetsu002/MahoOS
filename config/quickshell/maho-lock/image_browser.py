#!/usr/bin/env python3

import json
import os
import sys
import time
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp"}
MAX_ENTRIES = 120
MAX_SEARCH_SCAN = 4000
CACHE_VERSION = 1
CACHE_MAX_AGE_SECONDS = 45


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


def cache_path():
    configured = os.environ.get("XDG_CACHE_HOME", "").strip()
    root = Path(configured).expanduser() if configured else Path.home() / ".cache"
    return root / "maho" / "lock" / "image-browser-v1.json"


def load_cache(current):
    path = cache_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("version") != CACHE_VERSION:
        return None
    if payload.get("root") != str(current):
        return None
    generated = payload.get("generated_at")
    if not isinstance(generated, (int, float)) or time.time() - generated > CACHE_MAX_AGE_SECONDS:
        return None
    entries = payload.get("entries")
    return entries if isinstance(entries, list) else None


def save_cache(current, entries):
    target = cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps({
        "version": CACHE_VERSION,
        "generated_at": time.time(),
        "root": str(current),
        "entries": entries,
    }, separators=(",", ":")), encoding="utf-8")
    temporary.replace(target)


def build_search_index(current, home):
    entries = []
    stack = [current]
    scanned = 0
    while stack and scanned < MAX_SEARCH_SCAN:
        directory = stack.pop()
        try:
            children = list(directory.iterdir())
        except OSError:
            continue
        children.sort(key=lambda path: path.name.casefold(), reverse=True)
        for child in children:
            if scanned >= MAX_SEARCH_SCAN:
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
                elif resolved.is_file() and resolved.suffix.lower() in IMAGE_EXTENSIONS:
                    entries.append({
                        "name": resolved.name,
                        "path": str(resolved),
                        "relative": str(resolved.relative_to(current)),
                    })
            except OSError:
                continue
    save_cache(current, entries)
    return entries


def search_score(entry, query):
    tokens = [token for token in query.casefold().split() if token]
    name = str(entry.get("name") or "").casefold()
    relative = str(entry.get("relative") or name).casefold()
    score = 0
    for token in tokens:
        if name == token:
            score += 10000
        elif name.startswith(token):
            score += 8000 - len(name)
        elif token in name:
            score += 6500 - name.index(token) * 8
        elif token in relative:
            score += 4200 - relative.index(token) * 2
        else:
            return -1
    return score


def recursive_search(current, home, query):
    needle = query.casefold().strip()
    if not needle:
        return immediate_entries(current, home)

    entries = load_cache(current)
    if entries is None:
        entries = build_search_index(current, home)

    ranked = []
    for entry in entries:
        score = search_score(entry, needle)
        if score < 0:
            continue
        ranked.append((score, str(entry.get("relative") or "").casefold(), entry))

    ranked.sort(key=lambda row: (-row[0], row[1]))
    result = []
    for _, _, entry in ranked[:MAX_ENTRIES]:
        path = Path(str(entry.get("path") or ""))
        if path.is_file():
            result.append(path)
    return result


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
        print("usage: image_browser.py [DIRECTORY] [QUERY|--warm]", file=sys.stderr)
        return 2

    raw = sys.argv[1] if len(sys.argv) >= 2 else ""
    query = sys.argv[2] if len(sys.argv) == 3 else ""
    if query == "--warm":
        home = home_dir()
        current = resolve_directory(raw, home)
        build_search_index(current, home)
        return 0
    print(json.dumps(browse(raw, query), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
