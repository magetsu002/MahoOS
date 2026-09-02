#!/usr/bin/env python3
"""Bounded helpers for the native Maho Launcher.

Maho owns desktop-app discovery, launch, file search/open, and the curated
Commands mode. Search text is never evaluated as shell input.
"""

from __future__ import annotations

import argparse
import configparser
import json
import locale
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterable


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


def desktop_roots() -> list[Path]:
    home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    roots = [home / "applications"]
    for raw in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        if raw:
            roots.append(Path(raw) / "applications")
    return roots


def desktop_id_for(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace(os.sep, "-")


def find_desktop_file(desktop_id: str) -> Path | None:
    if not desktop_id or "\x00" in desktop_id:
        return None

    for root in desktop_roots():
        if not root.is_dir():
            continue
        direct = root / desktop_id
        if direct.is_file():
            return direct
        try:
            for candidate in root.rglob("*.desktop"):
                if desktop_id_for(candidate, root) == desktop_id:
                    return candidate
        except OSError:
            continue
    return None


def _truthy(value: str | None) -> bool:
    return (value or "").strip().casefold() in {"1", "true", "yes"}


def _split_semicolon(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(";") if item.strip()]


def _locale_candidates() -> list[str]:
    raw = os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
    raw = raw.split(".", 1)[0].split("@", 1)[0]
    candidates: list[str] = []
    if raw and raw not in {"C", "POSIX"}:
        candidates.append(raw)
        if "_" in raw:
            candidates.append(raw.split("_", 1)[0])
    try:
        current = locale.getlocale()[0]
    except Exception:
        current = None
    if current and current not in candidates:
        candidates.append(current)
        if "_" in current:
            language = current.split("_", 1)[0]
            if language not in candidates:
                candidates.append(language)
    return candidates


def _localized(section: configparser.SectionProxy, key: str) -> str:
    for locale_name in _locale_candidates():
        localized = section.get(f"{key}[{locale_name}]", fallback="").strip()
        if localized:
            return localized
    return section.get(key, fallback="").strip()


def _desktop_environment() -> set[str]:
    raw = os.environ.get("XDG_CURRENT_DESKTOP", "")
    normalized = raw.replace(";", ":")
    return {item.strip().casefold() for item in normalized.split(":") if item.strip()}


def _desktop_visible(section: configparser.SectionProxy) -> bool:
    if section.get("Type", fallback="Application").strip() != "Application":
        return False
    if _truthy(section.get("Hidden")) or _truthy(section.get("NoDisplay")):
        return False

    try_exec = section.get("TryExec", fallback="").strip()
    if try_exec and not (Path(try_exec).is_file() or shutil.which(try_exec)):
        return False

    desktops = _desktop_environment()
    only = {item.casefold() for item in _split_semicolon(section.get("OnlyShowIn"))}
    blocked = {item.casefold() for item in _split_semicolon(section.get("NotShowIn"))}
    if only and desktops and not (only & desktops):
        return False
    if blocked and desktops and (blocked & desktops):
        return False
    return True


def parse_desktop_entry(path: Path, desktop_id: str) -> dict[str, object] | None:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error):
        return None

    if not parser.has_section("Desktop Entry"):
        return None
    section = parser["Desktop Entry"]
    if not _desktop_visible(section):
        return None

    name = _localized(section, "Name")
    if not name:
        return None

    return {
        "id": desktop_id,
        "name": name,
        "genericName": _localized(section, "GenericName"),
        "comment": _localized(section, "Comment"),
        "icon": section.get("Icon", fallback="").strip(),
        "keywords": _split_semicolon(_localized(section, "Keywords")),
        "categories": _split_semicolon(section.get("Categories", fallback="")),
    }


def discover_apps() -> list[dict[str, object]]:
    """Return real installed desktop applications in XDG precedence order."""
    seen: set[str] = set()
    output: list[dict[str, object]] = []

    for root in desktop_roots():
        if not root.is_dir():
            continue
        try:
            candidates = sorted(root.rglob("*.desktop"), key=lambda item: str(item).casefold())
        except OSError:
            continue

        for path in candidates:
            try:
                desktop_id = desktop_id_for(path, root)
            except ValueError:
                continue
            if desktop_id in seen:
                continue
            seen.add(desktop_id)
            entry = parse_desktop_entry(path, desktop_id)
            if entry is not None:
                output.append(entry)

    output.sort(key=lambda item: str(item["name"]).casefold())
    return output


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


def launch_app(desktop_id: str) -> int:
    desktop_file = find_desktop_file(desktop_id)
    if desktop_file is None:
        print(f"maho-launcher-backend: desktop entry not found: {desktop_id}", file=sys.stderr)
        return 2

    if shutil.which("gio"):
        return detached(["gio", "launch", str(desktop_file)])

    if shutil.which("gtk-launch"):
        app_id = desktop_id[:-8] if desktop_id.endswith(".desktop") else desktop_id
        return detached(["gtk-launch", app_id])

    print("maho-launcher-backend: gio or gtk-launch is required", file=sys.stderr)
    return 127


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
            candidates = list(home.iterdir())
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
    result = {
        "gio": bool(shutil.which("gio")),
        "gtk_launch": bool(shutil.which("gtk-launch")),
        "xdg_open": bool(shutil.which("xdg-open")),
        "fd": bool(shutil.which("fd")),
        "desktop_entries": len(apps),
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
