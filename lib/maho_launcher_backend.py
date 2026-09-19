#!/usr/bin/env python3
"""Bounded helpers for the native Maho Launcher.

Desktop-app discovery, canonical application identity, icon resolution, and
trusted XDG launching are delegated to ``maho_app_model`` so Launcher and Dock
share one application authority. Launcher keeps its own search/ranking policy,
Files mode, Commands mode, and QML activation flow.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Iterable

# The backend is both executed as a script and imported directly by contract
# tests. Make the sibling shared model resolvable without depending on cwd.
LIB_DIR = Path(__file__).resolve().parent
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from maho_app_model import (
    detached,
    desktop_roots,
    discover_apps as shared_discover_apps,
    find_desktop_file,
    launch_app,
    resolve_icon_paths as shared_resolve_icon_paths,
)


EXCLUDED_DIRS = {
    ".cache",
    ".git",
    ".local/share/Trash",
    ".local/share/Steam",
    ".local/share/flatpak",
    ".local/share/containers",
    ".steam",
    ".var/app",
    ".mozilla",
    ".npm",
    ".cargo/registry",
    ".rustup",
    "node_modules",
    "target",
    "__pycache__",
}

APP_CACHE_VERSION = 1
APP_CACHE_MAX_AGE_SECONDS = 300
FILE_INDEX_VERSION = 1
FILE_INDEX_MAX_AGE_SECONDS = 120
FILE_INDEX_LIMIT = 24000


def cache_root() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME", "").strip()
    root = Path(configured).expanduser() if configured else Path.home() / ".cache"
    return root / "maho" / "launcher"


def read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(path)


def app_cache_signature() -> list[list[object]]:
    result: list[list[object]] = []
    for root in desktop_roots():
        try:
            stat = root.stat()
            result.append([str(root), stat.st_mtime_ns])
        except OSError:
            result.append([str(root), 0])
    return result


def cached_apps() -> list[dict[str, object]] | None:
    path = cache_root() / "apps-v1.json"
    payload = read_json(path)
    if not isinstance(payload, dict):
        return None
    if payload.get("version") != APP_CACHE_VERSION:
        return None
    if payload.get("signature") != app_cache_signature():
        return None
    generated = payload.get("generated_at")
    if not isinstance(generated, (int, float)) or time.time() - generated > APP_CACHE_MAX_AGE_SECONDS:
        return None
    entries = payload.get("entries")
    return entries if isinstance(entries, list) else None


def load_apps_cached() -> list[dict[str, object]]:
    entries = cached_apps()
    if entries is not None:
        return entries
    entries = discover_apps()
    atomic_json(cache_root() / "apps-v1.json", {
        "version": APP_CACHE_VERSION,
        "generated_at": time.time(),
        "signature": app_cache_signature(),
        "entries": entries,
    })
    return entries


def discover_apps() -> list[dict[str, object]]:
    """Compatibility wrapper around the shared Maho application authority."""
    return shared_discover_apps()


def resolve_icon_paths(entries: list[dict[str, object]]) -> None:
    """Compatibility wrapper around shared icon-resolution authority."""
    shared_resolve_icon_paths(entries)


def list_apps() -> int:
    json.dump(load_apps_cached(), sys.stdout, ensure_ascii=False, separators=(",", ":"))
    return 0


def fuzzy_score(label: str, relative: str, raw_query: str) -> float:
    query = raw_query.casefold().strip()
    if not query:
        return 0.0

    name = label.casefold()
    haystack = f"{name} {relative.casefold()}"
    if name == query:
        return 10000.0
    if name.startswith(query):
        return 8000.0 - len(name) * 0.1
    if query in name:
        return 6500.0 - name.index(query) * 8
    if query in haystack:
        return 4500.0 - haystack.index(query) * 2

    qi = 0
    previous = -1
    gap = 0
    streak_bonus = 0
    for index, char in enumerate(haystack):
        if qi >= len(query):
            break
        if char != query[qi]:
            continue
        if previous >= 0:
            distance = index - previous - 1
            gap += distance
            if distance == 0:
                streak_bonus += 14
        previous = index
        qi += 1

    if qi != len(query):
        return -1.0
    return 1800.0 + streak_bonus - gap * 6 - len(haystack) * 0.02


def is_excluded(path: Path, home: Path) -> bool:
    try:
        relative = path.relative_to(home)
    except ValueError:
        return False
    text = str(relative)
    return any(text == item or text.startswith(item + os.sep) for item in EXCLUDED_DIRS)


def scan_files_python(home: Path, query: str, candidate_limit: int = 24000) -> Iterable[Path]:
    count = 0
    for root, dirs, files in os.walk(home, followlinks=False):
        root_path = Path(root)
        dirs[:] = [
            name
            for name in dirs
            if not is_excluded(root_path / name, home)
            and not name.startswith(".git")
        ]
        for name in dirs:
            yield root_path / name
            count += 1
            if count >= candidate_limit:
                return
        for name in files:
            path = root_path / name
            if is_excluded(path, home):
                continue
            yield path
            count += 1
            if count >= candidate_limit:
                return


def scan_files_fd(home: Path, query: str, candidate_limit: int) -> list[Path] | None:
    if not shutil.which("fd"):
        return None

    command = ["fd", "--color", "never", "--absolute-path", "--max-results", str(candidate_limit)]
    if query:
        command += ["--ignore-case", "--fixed-strings", query]
    else:
        command += ["--max-depth", "1", "."]
    command.append(str(home))

    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if completed.returncode not in (0, 1):
        return None
    return [Path(line) for line in completed.stdout.splitlines() if line]


def file_index_path() -> Path:
    return cache_root() / "files-v1.json"


def load_file_index(home: Path) -> list[dict[str, object]] | None:
    payload = read_json(file_index_path())
    if not isinstance(payload, dict) or payload.get("version") != FILE_INDEX_VERSION:
        return None
    generated = payload.get("generated_at")
    if not isinstance(generated, (int, float)) or time.time() - generated > FILE_INDEX_MAX_AGE_SECONDS:
        return None
    if payload.get("home") != str(home):
        return None
    entries = payload.get("entries")
    return entries if isinstance(entries, list) else None


def build_file_index(home: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for path in scan_files_python(home, "", FILE_INDEX_LIMIT):
        try:
            relative = str(path.relative_to(home))
            is_dir = path.is_dir()
        except (OSError, ValueError):
            continue
        entries.append({
            "name": path.name or relative,
            "path": str(path),
            "relative": relative,
            "is_dir": is_dir,
        })
    atomic_json(file_index_path(), {
        "version": FILE_INDEX_VERSION,
        "generated_at": time.time(),
        "home": str(home),
        "entries": entries,
    })
    return entries


def file_index(home: Path) -> list[dict[str, object]]:
    cached = load_file_index(home)
    return cached if cached is not None else build_file_index(home)


def query_score(name: str, relative: str, raw_query: str) -> float:
    tokens = [token for token in raw_query.casefold().split() if token]
    if not tokens:
        return 0.0
    scores = [fuzzy_score(name, relative, token) for token in tokens]
    if any(score < 0 for score in scores):
        return -1.0
    return sum(scores) + max(0, len(tokens) - 1) * 180


def warm_cache() -> int:
    load_apps_cached()
    home = Path.home()
    file_index(home)
    return 0


def file_search(query: str, limit: int) -> int:
    home = Path.home()
    limit = max(1, min(limit, 120))
    normalized = query.strip()

    if not normalized:
        try:
            candidates = [
                {
                    "name": path.name or str(path),
                    "path": str(path),
                    "relative": str(path.relative_to(home)),
                    "is_dir": path.is_dir(),
                }
                for path in home.iterdir()
                if not path.name.startswith(".")
            ]
        except OSError:
            candidates = []
    else:
        candidates = file_index(home)

    ranked: list[tuple[float, str, dict[str, object]]] = []
    for item in candidates:
        name = str(item.get("name") or "")
        relative = str(item.get("relative") or name)
        score = query_score(name, relative, normalized)
        if score < 0:
            continue
        depth = len(Path(relative).parts)
        if depth <= 1:
            score += 180
        if bool(item.get("is_dir")):
            score += 40
        ranked.append((score, relative.casefold(), item))

    ranked.sort(key=lambda row: (-row[0], row[1]))
    output = []
    for _, _, item in ranked[:limit]:
        relative = str(item.get("relative") or "")
        is_dir = bool(item.get("is_dir"))
        output.append({
            "name": str(item.get("name") or relative),
            "description": "Folder" if is_dir else relative,
            "path": str(item.get("path") or ""),
            "relative": relative,
            "icon": "folder" if is_dir else "text-x-generic",
            "iconPath": "",
            "kind": "directory" if is_dir else "file",
        })

    json.dump(output, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    return 0


def open_path(path_text: str) -> int:
    path = Path(path_text).expanduser()
    if not path.exists():
        print(f"maho-launcher-backend: path does not exist: {path}", file=sys.stderr)
        return 2

    maho_files = shutil.which("maho-files")
    if path.is_dir() and maho_files:
        return detached([maho_files, "run", str(path)])

    if not shutil.which("xdg-open"):
        print("maho-launcher-backend: xdg-open is required", file=sys.stderr)
        return 127
    return detached(["xdg-open", str(path)])


def run_command(action: str) -> int:
    if action == "terminal":
        for terminal in ("kitty", "foot", "alacritty", "wezterm"):
            if shutil.which(terminal):
                return detached([terminal])
        return 127
    if action == "files":
        maho_files = shutil.which("maho-files")
        if maho_files:
            return detached([maho_files, "run", str(Path.home())])
        if shutil.which("thunar"):
            return detached(["thunar", str(Path.home())])
        if shutil.which("xdg-open"):
            return detached(["xdg-open", str(Path.home())])
        return 127
    if action == "lock":
        if shutil.which("hyprlock"):
            return detached(["hyprlock"])
        return 127
    if action == "diagnostics":
        launcher = str(Path.home() / ".local/bin/maho-launcher")
        if shutil.which("kitty"):
            return detached(["kitty", "--hold", "-e", launcher, "doctor"])
        return 127

    print(f"maho-launcher-backend: unknown command action: {action}", file=sys.stderr)
    return 2


def doctor() -> int:
    apps = discover_apps()
    icon_paths = sum(1 for app in apps if app.get("iconPath"))
    result = {
        "gio": bool(shutil.which("gio")),
        "gtk_launch": bool(shutil.which("gtk-launch")),
        "xdg_open": bool(shutil.which("xdg-open")),
        "maho_files": bool(shutil.which("maho-files")),
        "fd": bool(shutil.which("fd")),
        "desktop_entries": len(apps),
        "resolved_icon_paths": icon_paths,
        "icon_theme": os.environ.get("QS_ICON_THEME", ""),
        "desktop_roots": [str(path) for path in desktop_roots() if path.is_dir()],
    }
    json.dump(result, sys.stdout, separators=(",", ":"))
    return 0 if apps and (result["gio"] or result["gtk_launch"]) and result["xdg_open"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("apps")

    launch = sub.add_parser("launch-app")
    launch.add_argument("desktop_id")

    files = sub.add_parser("files")
    files.add_argument("--query", default="")
    files.add_argument("--limit", type=int, default=60)

    opening = sub.add_parser("open-path")
    opening.add_argument("path")

    command = sub.add_parser("command")
    command.add_argument("action", choices=("terminal", "files", "lock", "diagnostics"))

    sub.add_parser("doctor")
    sub.add_parser("warm-cache")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "apps":
        return list_apps()
    if args.command == "launch-app":
        return launch_app(args.desktop_id)
    if args.command == "files":
        return file_search(args.query, args.limit)
    if args.command == "open-path":
        return open_path(args.path)
    if args.command == "command":
        return run_command(args.action)
    if args.command == "doctor":
        return doctor()
    if args.command == "warm-cache":
        return warm_cache()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
