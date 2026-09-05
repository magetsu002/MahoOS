#!/usr/bin/env python3
"""Bounded helpers for the native Maho Launcher.

Desktop-app discovery, application identity, icon resolution, and trusted XDG
launching live in ``maho_app_model`` and are shared with Maho Dock. Launcher
keeps only its launcher-specific file search/open and curated command helpers.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterable

# The backend is both executed as a script and imported directly by the
# launcher contract tests. Make the sibling shared model resolvable in both
# modes without relying on the caller's working directory.
LIB_DIR = Path(__file__).resolve().parent
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from maho_app_model import (
    discover_apps as shared_discover_apps,
    find_desktop_file,
    launch_app,
    resolve_icon_paths as shared_resolve_icon_paths,
)


EXCLUDED_DIRS = {
    ".cache",
    ".git",
    ".local/share/Trash",
    ".npm",
    ".cargo/registry",
    ".rustup",
    "node_modules",
    "target",
    "__pycache__",
}


def discover_apps() -> list[dict[str, object]]:
    """Compatibility wrapper around the shared Maho application model."""
    return shared_discover_apps()


def resolve_icon_paths(entries: list[dict[str, object]]) -> None:
    """Compatibility wrapper; icon resolution authority lives in maho_app_model."""
    shared_resolve_icon_paths(entries)


def list_apps() -> int:
    json.dump(discover_apps(), sys.stdout, ensure_ascii=False, separators=(",", ":"))
    return 0


def detached(argv: list[str]) -> int:
    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        print(f"maho-launcher-backend: {exc}", file=sys.stderr)
        return 1
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


def file_search(query: str, limit: int) -> int:
    home = Path.home()
    limit = max(1, min(limit, 120))
    candidate_limit = max(limit * 20, 1200)

    if not query.strip():
        try:
            candidates: Iterable[Path] = list(home.iterdir())
        except OSError:
            candidates = []
    else:
        fd_candidates = scan_files_fd(home, query, candidate_limit)
        candidates = fd_candidates if fd_candidates is not None else scan_files_python(home, query)

    ranked: list[tuple[float, str, Path]] = []
    for path in candidates:
        try:
            relative = str(path.relative_to(home))
        except ValueError:
            relative = str(path)
        score = fuzzy_score(path.name, relative, query)
        if score < 0:
            continue
        depth = len(Path(relative).parts)
        if depth <= 1:
            score += 180
        try:
            is_dir = path.is_dir()
        except OSError:
            is_dir = False
        if is_dir:
            score += 40
        ranked.append((score, relative.casefold(), path))

    ranked.sort(key=lambda row: (-row[0], row[1]))
    output = []
    for _, _, path in ranked[:limit]:
        relative = str(path.relative_to(home)) if path.is_absolute() else str(path)
        try:
            is_dir = path.is_dir()
        except OSError:
            is_dir = False
        output.append(
            {
                "name": path.name or str(path),
                "description": "Folder" if is_dir else relative,
                "path": str(path),
                "relative": relative,
                "icon": "folder" if is_dir else "text-x-generic",
                "iconPath": "",
                "kind": "directory" if is_dir else "file",
            }
        )

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
    aliases = sum(len(app.get("aliases", [])) for app in apps)
    result = {
        "gio": bool(shutil.which("gio")),
        "gtk_launch": bool(shutil.which("gtk-launch")),
        "xdg_open": bool(shutil.which("xdg-open")),
        "maho_files": bool(shutil.which("maho-files")),
        "fd": bool(shutil.which("fd")),
        "desktop_entries": len(apps),
        "resolved_icon_paths": icon_paths,
        "identity_aliases": aliases,
        "icon_theme": os.environ.get("QS_ICON_THEME", ""),
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
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
