#!/usr/bin/env python3

import json
import os
import pwd
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp"}
MAX_WALLPAPER_CANDIDATES = 800


def run(args):
    try:
        completed = subprocess.run(
            args,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout if completed.returncode == 0 else ""


def user_identity():
    username = os.environ.get("USER", "")
    display = ""
    try:
        entry = pwd.getpwnam(username)
        display = entry.pw_gecos.split(",", 1)[0].strip()
    except (KeyError, OSError):
        pass

    if not display:
        display = username.replace("_", " ").replace("-", " ").strip().title()
    if not display:
        display = "User"

    return username, display


def network_kind():
    output = run(["nmcli", "-t", "-f", "TYPE,STATE", "device", "status"])
    connected = set()
    for line in output.splitlines():
        kind, sep, state = line.partition(":")
        if sep and state == "connected":
            connected.add(kind)
    if "wifi" in connected:
        return "wifi"
    if "ethernet" in connected:
        return "ethernet"
    return "none"


def keyboard_layout():
    output = run(["hyprctl", "devices", "-j"])
    if output:
        try:
            data = json.loads(output)
            keyboards = data.get("keyboards") or []
            candidates = [
                keyboard
                for keyboard in keyboards
                if keyboard.get("main") or keyboard.get("active_keymap")
            ]
            for keyboard in candidates:
                keymap = str(keyboard.get("active_keymap") or "").strip()
                match = re.search(r"\(([A-Za-z]{2,5})\)\s*$", keymap)
                if match:
                    return match.group(1).upper()
                if keymap:
                    words = re.findall(r"[A-Za-z]+", keymap)
                    if words:
                        return words[-1][:3].upper()
        except (TypeError, ValueError):
            pass

    fallback = os.environ.get("XKB_DEFAULT_LAYOUT", "us").split(",", 1)[0].strip()
    return (fallback or "us").upper()[:3]


def switch_user_command():
    if shutil.which("dm-tool"):
        return ["dm-tool", "switch-to-greeter"]
    if shutil.which("gdmflexiserver"):
        return ["gdmflexiserver"]
    return []


def wallpaper_state_path():
    state_home = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    return state_home / "maho/wallpaper/current.json"


def active_wallpaper():
    try:
        payload = json.loads(wallpaper_state_path().read_text())
    except (OSError, ValueError, TypeError):
        return None

    if payload.get("kind") != "image":
        return None

    raw = payload.get("path")
    if not isinstance(raw, str) or not raw:
        return None

    path = Path(raw).expanduser()
    try:
        path = path.resolve(strict=True)
    except OSError:
        return None

    return path if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS else None


def explicit_wallpaper_file():
    raw = os.environ.get("MAHO_LOCK_WALLPAPER_FILE", "").strip()
    if not raw:
        return None

    path = Path(raw).expanduser()
    try:
        path = path.resolve(strict=True)
    except OSError:
        return None

    return path if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS else None


def wallpaper_roots(active):
    roots = []

    configured = os.environ.get("MAHO_LOCK_WALLPAPER_DIR", "").strip()
    if configured:
        roots.extend(Path(value).expanduser() for value in configured.split(os.pathsep) if value)

    home = Path.home()
    roots.extend(
        [
            home / "Pictures/Wallpapers",
            home / "Pictures/wallpapers",
            home / "Wallpapers",
            home / "wallpapers",
        ]
    )

    if active is not None:
        parent_name = active.parent.name.lower()
        if any(token in parent_name for token in ("wallpaper", "background", "walls")):
            roots.append(active.parent)

    unique = []
    seen = set()
    for root in roots:
        try:
            resolved = root.resolve(strict=True)
        except OSError:
            continue
        if not resolved.is_dir() or resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def wallpaper_candidates():
    active = active_wallpaper()
    candidates = []
    seen = set()

    def add(path):
        if path is None or path in seen:
            return
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            seen.add(path)
            candidates.append(path)

    add(active)

    for root in wallpaper_roots(active):
        try:
            iterator = root.rglob("*")
            for path in iterator:
                if len(candidates) >= MAX_WALLPAPER_CANDIDATES:
                    break
                if path.name.startswith("."):
                    continue
                try:
                    if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                        continue
                    add(path.resolve(strict=True))
                except OSError:
                    continue
        except OSError:
            continue

        if len(candidates) >= MAX_WALLPAPER_CANDIDATES:
            break

    return candidates


def last_wallpaper_file():
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
    return runtime / f"maho-lock-last-wallpaper-{os.getuid()}"


def choose_lock_wallpaper():
    explicit = explicit_wallpaper_file()
    if explicit is not None:
        return explicit

    candidates = wallpaper_candidates()
    if not candidates:
        return None

    last = None
    try:
        raw = last_wallpaper_file().read_text().strip()
        if raw:
            last = Path(raw)
    except OSError:
        pass

    pool = [path for path in candidates if path != last]
    if not pool:
        pool = candidates

    choice = random.SystemRandom().choice(pool)

    try:
        last_wallpaper_file().write_text(str(choice))
    except OSError:
        pass

    return choice


def ambient_payload():
    username, display_name = user_identity()
    return {
        "userName": username,
        "displayName": display_name,
        "networkKind": network_kind(),
        "keyboardLayout": keyboard_layout(),
        "switchUserCommand": switch_user_command(),
    }


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--pick-wallpaper":
        selected = choose_lock_wallpaper()
        print(json.dumps({"path": str(selected) if selected else ""}, separators=(",", ":")))
        return 0

    if len(sys.argv) != 1:
        print("usage: state.py [--pick-wallpaper]", file=sys.stderr)
        return 2

    print(json.dumps(ambient_payload(), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
