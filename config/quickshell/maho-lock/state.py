#!/usr/bin/env python3

import json
import os
import pwd
import re
import shutil
import subprocess


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


username, display_name = user_identity()

print(
    json.dumps(
        {
            "userName": username,
            "displayName": display_name,
            "networkKind": network_kind(),
            "keyboardLayout": keyboard_layout(),
            "switchUserCommand": switch_user_command(),
        },
        separators=(",", ":"),
    )
)
