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
MAX_AVATAR_CANDIDATES = 24


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


def network_info():
    kind = "none"
    name = ""

    output = run(["nmcli", "-t", "-f", "TYPE,STATE", "device", "status"])
    connected = set()
    for line in output.splitlines():
        device_kind, sep, device_state = line.partition(":")
        if sep and device_state == "connected":
            connected.add(device_kind)

    if "wifi" in connected:
        kind = "wifi"
        name = run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"]).strip()
        for line in name.splitlines():
            if line.startswith("yes:"):
                name = line.partition(":")[2].strip()
                break
        else:
            name = "Wi-Fi"
    elif "ethernet" in connected:
        kind = "ethernet"
        name = "Ethernet"

    return kind, name


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


def state_home():
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")


def wallpaper_state_path():
    return state_home() / "maho/wallpaper/current.json"


def profile_state_path():
    return state_home() / "maho/lock/profile.json"


def resolve_image(raw):
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw).expanduser()
    try:
        path = path.resolve(strict=True)
    except OSError:
        return None
    return path if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS else None


def active_wallpaper():
    try:
        payload = json.loads(wallpaper_state_path().read_text())
    except (OSError, ValueError, TypeError):
        return None

    if payload.get("kind") != "image":
        return None
    return resolve_image(payload.get("path"))


def explicit_wallpaper_file():
    return resolve_image(os.environ.get("MAHO_LOCK_WALLPAPER_FILE", "").strip())


def wallpaper_roots(active):
    roots = []
    configured = os.environ.get("MAHO_LOCK_WALLPAPER_DIR", "").strip()
    if configured:
        roots.extend(Path(value).expanduser() for value in configured.split(os.pathsep) if value)

    home = Path.home()
    roots.extend([
        home / "Pictures/Wallpapers",
        home / "Pictures/wallpapers",
        home / "Wallpapers",
        home / "wallpapers",
    ])

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
            for path in root.rglob("*"):
                if len(candidates) >= MAX_WALLPAPER_CANDIDATES:
                    break
                if path.name.startswith("."):
                    continue
                try:
                    if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
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

    pool = [path for path in candidates if path != last] or candidates
    choice = random.SystemRandom().choice(pool)

    try:
        last_wallpaper_file().write_text(str(choice))
    except OSError:
        pass

    return choice


def avatar_roots():
    home = Path.home()
    roots = []
    configured = os.environ.get("MAHO_LOCK_AVATAR_DIR", "").strip()
    if configured:
        roots.extend(Path(value).expanduser() for value in configured.split(os.pathsep) if value)

    roots.extend([
        home / "Pictures/Avatars",
        home / "Pictures/avatars",
        home / "Pictures/Profile",
        home / "Pictures/Profiles",
        home / "Pictures/profile",
    ])

    unique = []
    seen = set()
    for root in roots:
        try:
            resolved = root.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_dir() and resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def avatar_candidates():
    candidates = []
    seen = set()

    def add(path):
        if path in seen or len(candidates) >= MAX_AVATAR_CANDIDATES:
            return
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            return
        if resolved.is_file() and resolved.suffix.lower() in IMAGE_EXTENSIONS:
            seen.add(resolved)
            candidates.append(resolved)

    for root in avatar_roots():
        try:
            for path in root.rglob("*"):
                if len(candidates) >= MAX_AVATAR_CANDIDATES:
                    break
                if not path.name.startswith("."):
                    add(path)
        except OSError:
            continue

    # If dedicated avatar folders are empty, expose a small shallow selection
    # from Pictures rather than recursively indexing the user's entire library.
    if not candidates:
        pictures = Path.home() / "Pictures"
        try:
            for path in pictures.iterdir():
                add(path)
                if len(candidates) >= MAX_AVATAR_CANDIDATES:
                    break
        except OSError:
            pass

    random.SystemRandom().shuffle(candidates)
    return candidates


def saved_avatar():
    try:
        payload = json.loads(profile_state_path().read_text())
    except (OSError, ValueError, TypeError):
        return None
    return resolve_image(payload.get("avatarPath"))


def save_avatar(path):
    target = resolve_image(str(path))
    if target is None:
        return False

    profile = profile_state_path()
    try:
        profile.parent.mkdir(parents=True, exist_ok=True)
        tmp = profile.with_suffix(".tmp")
        tmp.write_text(json.dumps({"avatarPath": str(target)}, separators=(",", ":")))
        tmp.replace(profile)
    except OSError:
        return False
    return True


def clear_avatar():
    try:
        profile_state_path().unlink(missing_ok=True)
    except OSError:
        return False
    return True


def ambient_payload():
    username, display_name = user_identity()
    network_kind, network_name = network_info()
    avatar = saved_avatar()
    return {
        "userName": username,
        "displayName": display_name,
        "networkKind": network_kind,
        "networkName": network_name,
        "keyboardLayout": keyboard_layout(),
        "switchUserCommand": switch_user_command(),
        "avatarPath": str(avatar) if avatar else "",
    }


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--pick-wallpaper":
        selected = choose_lock_wallpaper()
        print(json.dumps({"path": str(selected) if selected else ""}, separators=(",", ":")))
        return 0

    if len(sys.argv) == 2 and sys.argv[1] == "--avatar-candidates":
        print(json.dumps({"paths": [str(path) for path in avatar_candidates()]}, separators=(",", ":")))
        return 0

    if len(sys.argv) == 3 and sys.argv[1] == "--set-avatar":
        ok = save_avatar(sys.argv[2])
        print(json.dumps({"ok": ok, "path": sys.argv[2] if ok else ""}, separators=(",", ":")))
        return 0 if ok else 1

    if len(sys.argv) == 2 and sys.argv[1] == "--clear-avatar":
        ok = clear_avatar()
        print(json.dumps({"ok": ok}, separators=(",", ":")))
        return 0 if ok else 1

    if len(sys.argv) == 2 and sys.argv[1] == "--switch-layout":
        run(["hyprctl", "switchxkblayout", "all", "next"])
        print(json.dumps({"keyboardLayout": keyboard_layout()}, separators=(",", ":")))
        return 0

    if len(sys.argv) != 1:
        print(
            "usage: state.py [--pick-wallpaper|--avatar-candidates|--set-avatar PATH|--clear-avatar|--switch-layout]",
            file=sys.stderr,
        )
        return 2

    print(json.dumps(ambient_payload(), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
