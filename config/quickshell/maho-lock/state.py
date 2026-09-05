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


def load_profile_payload():
    try:
        payload = json.loads(profile_state_path().read_text())
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_profile_payload(payload):
    profile = profile_state_path()
    try:
        profile.parent.mkdir(parents=True, exist_ok=True)
        tmp = profile.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")))
        tmp.replace(profile)
    except OSError:
        return False
    return True


def resolve_image(raw):
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw).expanduser()
    try:
        path = path.resolve(strict=True)
    except OSError:
        return None
    return path if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS else None


def home_dir():
    try:
        return Path.home().resolve(strict=True)
    except OSError:
        return Path.home().resolve()


def inside_home(path, home=None):
    home = home or home_dir()
    try:
        path.relative_to(home)
        return True
    except ValueError:
        return path == home


def resolve_home_directory(raw):
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw).expanduser()
    try:
        path = path.resolve(strict=True)
    except OSError:
        return None
    return path if path.is_dir() and inside_home(path) else None


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


def saved_wallpaper():
    return resolve_image(load_profile_payload().get("wallpaperPath"))


def save_wallpaper(path):
    target = resolve_image(str(path))
    if target is None:
        return None

    payload = load_profile_payload()
    payload["wallpaperPath"] = str(target)
    if inside_home(target.parent):
        payload["wallpaperBrowsePath"] = str(target.parent)
    return target if write_profile_payload(payload) else None


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


def choose_lock_wallpaper(use_saved=True):
    explicit = explicit_wallpaper_file()
    if explicit is not None:
        return explicit

    if use_saved:
        saved = saved_wallpaper()
        if saved is not None:
            return saved

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
    return resolve_image(load_profile_payload().get("avatarPath"))


def save_avatar(path):
    target = resolve_image(str(path))
    if target is None:
        return False

    payload = load_profile_payload()
    payload["avatarPath"] = str(target)
    if inside_home(target.parent):
        payload["avatarBrowsePath"] = str(target.parent)
    return write_profile_payload(payload)


def clear_avatar():
    payload = load_profile_payload()
    payload.pop("avatarPath", None)
    if not payload:
        try:
            profile_state_path().unlink(missing_ok=True)
        except OSError:
            return False
        return True
    return write_profile_payload(payload)


def default_browse_path(mode, payload=None):
    payload = payload or load_profile_payload()
    home = home_dir()
    pictures = home / "Pictures"
    fallback = pictures if pictures.is_dir() else home

    key = "avatarBrowsePath" if mode == "avatar" else "wallpaperBrowsePath"
    remembered = resolve_home_directory(payload.get(key))
    if remembered is not None:
        return remembered

    selected = saved_avatar() if mode == "avatar" else saved_wallpaper()
    if selected is not None and inside_home(selected.parent, home):
        return selected.parent

    if mode == "wallpaper":
        active = active_wallpaper()
        if active is not None and inside_home(active.parent, home):
            return active.parent
        for root in wallpaper_roots(active):
            if inside_home(root, home):
                return root

    return fallback


def ambient_payload():
    username, display_name = user_identity()
    network_kind, network_name = network_info()
    avatar = saved_avatar()
    wallpaper = saved_wallpaper()
    payload = load_profile_payload()
    return {
        "userName": username,
        "displayName": display_name,
        "networkKind": network_kind,
        "networkName": network_name,
        "keyboardLayout": keyboard_layout(),
        "switchUserCommand": switch_user_command(),
        "avatarPath": str(avatar) if avatar else "",
        "savedWallpaperPath": str(wallpaper) if wallpaper else "",
        "avatarBrowsePath": str(default_browse_path("avatar", payload)),
        "wallpaperBrowsePath": str(default_browse_path("wallpaper", payload)),
    }


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--pick-wallpaper":
        selected = choose_lock_wallpaper(use_saved=True)
        print(json.dumps({"path": str(selected) if selected else ""}, separators=(",", ":")))
        return 0

    if len(sys.argv) == 2 and sys.argv[1] == "--shuffle-wallpaper":
        selected = choose_lock_wallpaper(use_saved=False)
        print(json.dumps({"path": str(selected) if selected else ""}, separators=(",", ":")))
        return 0

    if len(sys.argv) == 3 and sys.argv[1] == "--set-wallpaper":
        selected = save_wallpaper(sys.argv[2])
        print(json.dumps({"ok": selected is not None, "path": str(selected) if selected else ""}, separators=(",", ":")))
        return 0 if selected is not None else 1

    if len(sys.argv) == 2 and sys.argv[1] == "--avatar-candidates":
        print(json.dumps({"paths": [str(path) for path in avatar_candidates()]}, separators=(",", ":")))
        return 0

    if len(sys.argv) == 3 and sys.argv[1] == "--set-avatar":
        ok = save_avatar(sys.argv[2])
        resolved = saved_avatar() if ok else None
        print(json.dumps({"ok": ok, "path": str(resolved) if resolved else ""}, separators=(",", ":")))
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
            "usage: state.py [--pick-wallpaper|--shuffle-wallpaper|--set-wallpaper PATH|--avatar-candidates|--set-avatar PATH|--clear-avatar|--switch-layout]",
            file=sys.stderr,
        )
        return 2

    print(json.dumps(ambient_payload(), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
