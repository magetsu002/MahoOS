#!/usr/bin/env python3
"""Shared Maho application discovery, identity, icon resolution, and launch helpers.

Maho Launcher and Maho Dock both use this source of truth so one desktop entry
cannot become two incompatible app identities merely because it is shown by a
different surface. Discovery remains desktop-toolkit agnostic; normal launch
requests may use the current Hyprland toplevel set to focus an already-running
application before falling back to the trusted XDG launch path.
"""

from __future__ import annotations

import argparse
import configparser
import json
import locale
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from typing import Iterable

ICON_EXTENSIONS = {".svg": 60, ".png": 50, ".xpm": 20}
IDENTITY_TOKEN = re.compile(r"[^a-z0-9]+")
FIELD_CODE = re.compile(r"^%[fFuUdDnNickvm]$")
HYPRLAND_ADDRESS = re.compile(r"^0x[0-9a-fA-F]+$")


def desktop_roots() -> list[Path]:
    home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    roots = [home / "applications"]
    for raw in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        if raw:
            roots.append(Path(raw) / "applications")
    return roots


def icon_roots() -> list[Path]:
    roots = [
        Path.home() / ".icons",
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "icons",
    ]
    for raw in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        if raw:
            roots.append(Path(raw) / "icons")

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


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


def normalize_identity(value: object) -> str:
    text = str(value or "").strip().casefold()
    if text.endswith(".desktop"):
        text = text[:-8]
    return IDENTITY_TOKEN.sub("", text)


def _exec_identity_candidates(exec_line: str) -> list[str]:
    if not exec_line.strip():
        return []
    try:
        tokens = shlex.split(exec_line, posix=True)
    except ValueError:
        return []

    filtered = [token for token in tokens if not FIELD_CODE.match(token)]
    if not filtered:
        return []

    index = 0
    if Path(filtered[0]).name == "env":
        index = 1
        while index < len(filtered) and "=" in filtered[index] and not filtered[index].startswith("/"):
            name = filtered[index].split("=", 1)[0]
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                break
            index += 1
    if index >= len(filtered):
        return []

    executable = Path(filtered[index]).name
    result = [executable]

    # Flatpak and Snap frequently expose a generic launcher executable while
    # the following token is the useful application identity.
    if executable == "flatpak" and index + 2 < len(filtered) and filtered[index + 1] == "run":
        result.append(filtered[index + 2])
    elif executable == "snap" and index + 1 < len(filtered):
        if filtered[index + 1] == "run" and index + 2 < len(filtered):
            result.append(filtered[index + 2])
        elif not filtered[index + 1].startswith("-"):
            result.append(filtered[index + 1])

    return result


def _raw_identity_candidates(entry: dict[str, object]) -> set[str]:
    desktop_id = str(entry.get("id", "") or "")
    stem = desktop_id[:-8] if desktop_id.casefold().endswith(".desktop") else desktop_id
    parts = [part for part in re.split(r"[.\-_]+", stem) if part]

    values = {
        stem,
        parts[-1] if parts else "",
        str(entry.get("startupWmClass", "") or ""),
        str(entry.get("name", "") or ""),
    }
    values.update(_exec_identity_candidates(str(entry.get("exec", "") or "")))
    return {normalized for value in values if (normalized := normalize_identity(value))}


def _assign_unique_aliases(entries: list[dict[str, object]]) -> None:
    owners: dict[str, set[str]] = {}
    candidates: dict[str, set[str]] = {}

    for entry in entries:
        desktop_id = str(entry["id"])
        aliases = _raw_identity_candidates(entry)
        candidates[desktop_id] = aliases
        for alias in aliases:
            owners.setdefault(alias, set()).add(desktop_id)

    for entry in entries:
        desktop_id = str(entry["id"])
        # The normalized full desktop id remains safe even if a human-friendly
        # alias collides. Ambiguous short/name aliases are intentionally dropped.
        full_id = normalize_identity(desktop_id)
        aliases = {
            alias
            for alias in candidates.get(desktop_id, set())
            if len(owners.get(alias, set())) == 1
        }
        if full_id:
            aliases.add(full_id)
        entry["aliases"] = sorted(aliases)


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
        "desktopFile": str(path),
        "name": name,
        "genericName": _localized(section, "GenericName"),
        "comment": _localized(section, "Comment"),
        "icon": section.get("Icon", fallback="").strip(),
        "iconPath": "",
        "keywords": _split_semicolon(_localized(section, "Keywords")),
        "categories": _split_semicolon(section.get("Categories", fallback="")),
        "startupWmClass": section.get("StartupWMClass", fallback="").strip(),
        "exec": section.get("Exec", fallback="").strip(),
        "terminal": _truthy(section.get("Terminal")),
        "actions": _split_semicolon(section.get("Actions", fallback="")),
    }


def _icon_stem(value: str) -> str:
    name = Path(value).name
    suffix = Path(name).suffix.casefold()
    if suffix in ICON_EXTENSIONS:
        return Path(name).stem
    return name


def _icon_score(path: Path, theme_rank: int) -> int:
    score = 1000 - theme_rank * 100 + ICON_EXTENSIONS.get(path.suffix.casefold(), 0)
    text = str(path).casefold()
    if "/apps/" in text or "/applications/" in text:
        score += 30
    if "/scalable/" in text:
        score += 80
    for size in re.findall(r"(?:^|/)(\d+)x(?:\d+)(?:/|$)", text):
        try:
            numeric = int(size)
        except ValueError:
            continue
        score += min(numeric, 512) // 8
    return score


def resolve_icon_paths(entries: list[dict[str, object]]) -> None:
    unresolved: dict[str, list[dict[str, object]]] = {}
    for entry in entries:
        raw = str(entry.get("icon", "") or "").strip()
        if not raw:
            continue
        if raw.startswith("file://"):
            candidate = Path(raw[7:])
            if candidate.is_file():
                entry["iconPath"] = str(candidate)
            continue
        candidate = Path(raw).expanduser()
        if candidate.is_absolute() and candidate.is_file():
            entry["iconPath"] = str(candidate)
            continue
        stem = _icon_stem(raw)
        if stem:
            unresolved.setdefault(stem, []).append(entry)

    if not unresolved:
        return

    selected = (os.environ.get("QS_ICON_THEME") or "").strip()
    themes: list[str] = []
    for theme in (
        selected,
        "Papirus-Dark",
        "Papirus",
        "Tela-circle-dark",
        "Tela-circle",
        "Tela",
        "Adwaita",
        "hicolor",
    ):
        if theme and theme not in themes:
            themes.append(theme)

    best: dict[str, tuple[int, str]] = {}
    wanted = set(unresolved)
    for rank, theme in enumerate(themes):
        for root in icon_roots():
            base = root / theme
            if not base.is_dir():
                continue
            try:
                for path in base.rglob("*"):
                    if not path.is_file() or path.suffix.casefold() not in ICON_EXTENSIONS:
                        continue
                    stem = path.stem
                    if stem not in wanted:
                        continue
                    score = _icon_score(path, rank)
                    previous = best.get(stem)
                    if previous is None or score > previous[0]:
                        best[stem] = (score, str(path))
            except OSError:
                continue

    for root in (Path("/usr/local/share/pixmaps"), Path("/usr/share/pixmaps")):
        if not root.is_dir():
            continue
        try:
            for path in root.iterdir():
                if not path.is_file() or path.suffix.casefold() not in ICON_EXTENSIONS:
                    continue
                stem = path.stem
                if stem in wanted and stem not in best:
                    best[stem] = (100, str(path))
        except OSError:
            continue

    for stem, rows in unresolved.items():
        resolved = best.get(stem)
        if not resolved:
            continue
        for entry in rows:
            entry["iconPath"] = resolved[1]


def discover_apps(resolve_icons: bool = True) -> list[dict[str, object]]:
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

    if resolve_icons:
        resolve_icon_paths(output)
    _assign_unique_aliases(output)
    output.sort(key=lambda item: str(item["name"]).casefold())
    return output


_GRAPHICAL_ENVIRONMENT = (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "HYPRLAND_INSTANCE_SIGNATURE",
    "XDG_ACTIVATION_TOKEN",
    "XDG_CURRENT_DESKTOP",
    "XDG_SESSION_DESKTOP",
    "XDG_SESSION_TYPE",
)


def _application_unit_name() -> str:
    """Return an unguessable, systemd-safe application service name."""
    return f"app-maho-{os.getpid()}-{uuid.uuid4().hex}"


def _application_service_command(argv: list[str], unit: str) -> list[str] | None:
    systemd_run = shutil.which("systemd-run")
    if systemd_run is None:
        return None

    command = [
        systemd_run,
        "--user",
        "--collect",
        "--quiet",
        "--service-type=exec",
        f"--unit={unit}",
        "--property=Slice=app.slice",
        "--property=ExitType=cgroup",
        f"--property=Description=Maho application: {Path(argv[0]).name}",
    ]
    for name in _GRAPHICAL_ENVIRONMENT:
        value = os.environ.get(name)
        if value:
            command.append(f"--setenv={name}={value}")
    command.extend(("--", *argv))
    return command


def detached(argv: list[str]) -> int:
    """Launch outside the calling Maho surface's lifecycle/resource domain.

    A POSIX session is not a systemd ownership boundary.  Applications are
    therefore started as transient user services in ``app.slice``.  Type=exec
    makes a successful return authoritative for exec(2), while ExitType=cgroup
    keeps helper-launched descendants (for example from ``gio launch``) owned
    until the complete application cgroup exits.

    There is deliberately no direct-Popen fallback: if independent ownership
    cannot be established, launching fails instead of attaching the app to
    Dock, Launcher, or another desktop surface.
    """
    if not argv:
        print("maho-app-model: refusing empty launch request", file=sys.stderr)
        return 2

    unit = _application_unit_name()
    command = _application_service_command(argv, unit)
    if command is None:
        print("maho-app-model: systemd-run is required for isolated application ownership", file=sys.stderr)
        return 127

    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=8,
            check=False,
        )
    except subprocess.TimeoutExpired:
        # Scope only this launch attempt.  The command may have reached the
        # manager before the client timed out, so remove the ambiguous unit.
        subprocess.run(
            ("systemctl", "--user", "stop", f"{unit}.service"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
        print("maho-app-model: timed out establishing independent application ownership", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"maho-app-model: {exc}", file=sys.stderr)
        return 1
    if completed.returncode != 0:
        detail = (completed.stderr or "systemd-run failed").strip().splitlines()[-1]
        print(f"maho-app-model: independent application launch failed: {detail}", file=sys.stderr)
        return completed.returncode or 1
    return 0


def _hyprland_clients() -> list[dict[str, object]]:
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or not shutil.which("hyprctl"):
        return []
    try:
        completed = subprocess.run(
            ["hyprctl", "-j", "clients"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=0.8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    try:
        payload = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _entry_for_activation(desktop_id: str) -> dict[str, object] | None:
    for entry in discover_apps(resolve_icons=False):
        if str(entry.get("id", "")) == desktop_id:
            return entry
    return None


def _matching_hyprland_clients(desktop_id: str) -> list[dict[str, object]]:
    entry = _entry_for_activation(desktop_id)
    if entry is None:
        return []
    aliases = {normalize_identity(value) for value in entry.get("aliases", []) if value}
    if not aliases:
        return []

    matches: list[dict[str, object]] = []
    for client in _hyprland_clients():
        if client.get("mapped") is False:
            continue
        identities = {
            normalize_identity(client.get("class", "")),
            normalize_identity(client.get("initialClass", "")),
        }
        identities.discard("")
        if aliases & identities:
            matches.append(client)

    def client_rank(client: dict[str, object]) -> tuple[int, str]:
        try:
            history = int(client.get("focusHistoryID", 1_000_000))
        except (TypeError, ValueError):
            history = 1_000_000
        return history, str(client.get("address", ""))

    matches.sort(key=client_rank)
    return matches


def focus_existing_app(desktop_id: str) -> bool:
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or not shutil.which("hyprctl"):
        return False
    for client in _matching_hyprland_clients(desktop_id):
        address = str(client.get("address", ""))
        if not HYPRLAND_ADDRESS.fullmatch(address):
            continue
        try:
            completed = subprocess.run(
                ["hyprctl", "dispatch", "focuswindow", f"address:{address}"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=0.8,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if completed.returncode == 0:
            return True
    return False


def launch_new_app(desktop_id: str) -> int:
    desktop_file = find_desktop_file(desktop_id)
    if desktop_file is None:
        print(f"maho-app-model: desktop entry not found: {desktop_id}", file=sys.stderr)
        return 2

    if shutil.which("gio"):
        return detached(["gio", "launch", str(desktop_file)])

    if shutil.which("gtk-launch"):
        app_id = desktop_id[:-8] if desktop_id.endswith(".desktop") else desktop_id
        return detached(["gtk-launch", app_id])

    print("maho-app-model: gio or gtk-launch is required", file=sys.stderr)
    return 127


def launch_app(desktop_id: str) -> int:
    if find_desktop_file(desktop_id) is None:
        print(f"maho-app-model: desktop entry not found: {desktop_id}", file=sys.stderr)
        return 2
    if focus_existing_app(desktop_id):
        return 0
    return launch_new_app(desktop_id)


def list_apps() -> int:
    json.dump(discover_apps(), sys.stdout, ensure_ascii=False, separators=(",", ":"))
    return 0


def doctor() -> int:
    apps = discover_apps()
    result = {
        "desktop_entries": len(apps),
        "resolved_icon_paths": sum(1 for app in apps if app.get("iconPath")),
        "identity_aliases": sum(len(app.get("aliases", [])) for app in apps),
        "gio": bool(shutil.which("gio")),
        "gtk_launch": bool(shutil.which("gtk-launch")),
        "hyprctl": bool(shutil.which("hyprctl")),
        "icon_theme": os.environ.get("QS_ICON_THEME", ""),
    }
    json.dump(result, sys.stdout, separators=(",", ":"))
    return 0 if apps and (result["gio"] or result["gtk_launch"]) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("apps")
    launch = sub.add_parser("launch-app")
    launch.add_argument("desktop_id")
    launch_new = sub.add_parser("launch-new")
    launch_new.add_argument("desktop_id")
    sub.add_parser("doctor")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "apps":
        return list_apps()
    if args.command == "launch-app":
        return launch_app(args.desktop_id)
    if args.command == "launch-new":
        return launch_new_app(args.desktop_id)
    if args.command == "doctor":
        return doctor()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
