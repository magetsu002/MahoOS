#!/usr/bin/env python3

import glob
import json
import pathlib
import shutil
import subprocess


def run(args, timeout=0.7):
    try:
        return subprocess.check_output(
            args,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        ).strip()
    except Exception:
        return ""


network_kind = "none"
network_name = ""

if shutil.which("nmcli"):
    raw = run([
        "nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device", "status"
    ])

    for line in raw.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        kind, state, name = parts
        if state != "connected":
            continue
        if kind == "wifi":
            network_kind = "wifi"
            network_name = name
            break
        if kind == "ethernet" and network_kind == "none":
            network_kind = "ethernet"
            network_name = name


bluetooth_available = False
bluetooth_powered = False
bluetooth_connected = False

if shutil.which("bluetoothctl"):
    raw = run(["bluetoothctl", "show"])
    if raw:
        bluetooth_available = True
        bluetooth_powered = "Powered: yes" in raw
        connected = run(["bluetoothctl", "devices", "Connected"])
        bluetooth_connected = bool(connected.strip())


battery = 100
charging = False
batteries = sorted(glob.glob("/sys/class/power_supply/BAT*"))

if batteries:
    base = pathlib.Path(batteries[0])
    try:
        battery = int((base / "capacity").read_text().strip())
    except Exception:
        pass

    try:
        status = (base / "status").read_text().strip().lower()
        charging = status in {"charging", "full"}
    except Exception:
        pass


media_playing = False
media_title = ""
media_artist = ""

if shutil.which("playerctl"):
    status = run(["playerctl", "status"])
    media_playing = status == "Playing"
    media_title = run(["playerctl", "metadata", "--format", "{{title}}"])
    media_artist = run(["playerctl", "metadata", "--format", "{{artist}}"])

    if len(media_title) > 42:
        media_title = media_title[:39] + "…"
    if len(media_artist) > 34:
        media_artist = media_artist[:31] + "…"


print(json.dumps({
    "networkKind": network_kind,
    "networkName": network_name,
    "bluetoothAvailable": bluetooth_available,
    "bluetoothPowered": bluetooth_powered,
    "bluetoothConnected": bluetooth_connected,
    "battery": battery,
    "charging": charging,
    "mediaPlaying": media_playing,
    "mediaTitle": media_title,
    "mediaArtist": media_artist,
}, separators=(",", ":")))
