#!/usr/bin/env python3

import json
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


print(json.dumps({
    "networkKind": network_kind,
    "networkName": network_name,
}, separators=(",", ":")))
