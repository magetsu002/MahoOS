#!/usr/bin/env python3

import json
import shutil
import subprocess
import sys
from typing import Iterable

DEFAULT_SCAN_ARGS = ("--rescan", "auto")


def emit(payload):
    print(json.dumps(payload, separators=(",", ":")))


def run(args: Iterable[str], *, timeout=4.0, stdin_text=None):
    try:
        proc = subprocess.run(
            list(args),
            input=stdin_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as exc:
        return 127, "", str(exc)


def split_nmcli(line: str):
    result = []
    current = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            result.append("".join(current))
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    result.append("".join(current))
    return result


def quality(signal: int):
    if signal >= 80:
        return "Excellent"
    if signal >= 60:
        return "Very Good"
    if signal >= 42:
        return "Good"
    if signal >= 25:
        return "Fair"
    return "Weak"


def security_info(raw: str):
    normalized = raw.strip()
    lowered = normalized.lower()
    open_network = normalized in ("", "--")
    enterprise = any(token in lowered for token in ("802.1x", "wpa-eap", "eap"))
    return {
        "security": "Open" if open_network else normalized,
        "secured": not open_network,
        "enterprise": enterprise,
    }


def band_from_frequency(freq: int):
    if freq >= 5925:
        return "6 GHz"
    if freq >= 4900:
        return "5 GHz"
    if freq >= 2300:
        return "2.4 GHz"
    return ""


def wifi_enabled():
    code, out, _ = run(["nmcli", "-t", "-f", "WIFI", "general"])
    return code == 0 and out.lower().splitlines()[:1] == ["enabled"]


def wifi_device():
    code, out, _ = run(["nmcli", "-t", "-e", "yes", "-f", "DEVICE,TYPE,STATE", "device", "status"])
    if code != 0:
        return ""
    fallback = ""
    for line in out.splitlines():
        fields = split_nmcli(line)
        if len(fields) < 3 or fields[1] != "wifi":
            continue
        if not fallback:
            fallback = fields[0]
        if fields[2] == "connected":
            return fields[0]
    return fallback


def ip_details(device: str):
    if not device:
        return {"ipv4": "", "gateway": ""}
    code, out, _ = run([
        "nmcli", "-t", "-e", "yes", "-f", "IP4.ADDRESS,IP4.GATEWAY", "device", "show", device
    ])
    if code != 0:
        return {"ipv4": "", "gateway": ""}
    ipv4 = ""
    gateway = ""
    for line in out.splitlines():
        fields = split_nmcli(line)
        if len(fields) < 2:
            continue
        key, value = fields[0], fields[1]
        if key.startswith("IP4.ADDRESS") and not ipv4:
            ipv4 = value
        elif key == "IP4.GATEWAY" and not gateway:
            gateway = value
    return {"ipv4": ipv4, "gateway": gateway}


def active_connection(device: str):
    if not device:
        return None
    code, out, _ = run([
        "nmcli", "-t", "-e", "yes", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show", "--active"
    ])
    if code != 0:
        return None

    profile = ""
    connection_uuid = ""
    for line in out.splitlines():
        fields = split_nmcli(line)
        if len(fields) < 4 or fields[3] != device:
            continue
        if fields[2] in ("802-11-wireless", "wifi", "wireless"):
            profile = fields[0]
            connection_uuid = fields[1]
            break
    if not profile or not connection_uuid:
        return None

    code, ssid, _ = run([
        "nmcli", "-t", "-g", "802-11-wireless.ssid", "connection", "show", "uuid", connection_uuid
    ])
    if code != 0 or not ssid.strip():
        ssid = profile

    current = {
        "profile": profile,
        "uuid": connection_uuid,
        "device": device,
        "ssid": ssid.splitlines()[0].strip(),
        "signal": -1,
        "quality": "",
        "frequency": 0,
        "band": "",
        "security": "",
        "secured": False,
        "enterprise": False,
        "state": "Connected",
    }
    current.update(ip_details(device))
    return current


def scan_networks(enabled: bool, *, rescan="auto"):
    if not enabled:
        return [], None
    code, out, _ = run([
        "nmcli", "-t", "-e", "yes", "-f",
        "IN-USE,SSID,SIGNAL,SECURITY,FREQ", "device", "wifi", "list", "--rescan", rescan
    ], timeout=5.0)
    if code != 0:
        return [], None

    strongest = {}
    current = None
    for line in out.splitlines():
        fields = split_nmcli(line)
        if len(fields) < 5:
            continue
        in_use, ssid, signal_raw, security_raw, freq_raw = fields[:5]
        if not ssid:
            continue
        try:
            signal = max(0, min(100, int(signal_raw or 0)))
        except ValueError:
            signal = 0
        try:
            freq = int(freq_raw or 0)
        except ValueError:
            freq = 0
        entry = {
            "ssid": ssid,
            "signal": signal,
            "quality": quality(signal),
            "frequency": freq,
            "band": band_from_frequency(freq),
            **security_info(security_raw),
        }
        previous = strongest.get(ssid)
        if previous is None or signal > previous["signal"]:
            strongest[ssid] = entry
        if in_use.strip() == "*":
            current = entry.copy()

    networks = sorted(strongest.values(), key=lambda row: (-row["signal"], row["ssid"].lower()))
    if current:
        networks = [row for row in networks if row["ssid"] != current["ssid"]]
    return networks, current


def unavailable_payload():
    return {
        "available": False,
        "enabled": False,
        "device": "",
        "current": None,
        "networks": [],
        "error": "NetworkManager nmcli is unavailable.",
    }


def status_snapshot():
    if not shutil.which("nmcli"):
        emit(unavailable_payload())
        return 0

    enabled = wifi_enabled()
    device = wifi_device()
    current = active_connection(device) if enabled else None
    emit({
        "available": True,
        "enabled": enabled,
        "device": device,
        "current": current,
        "error": "" if device or not enabled else "No Wi-Fi adapter is available.",
    })
    return 0


def networks_snapshot():
    if not shutil.which("nmcli"):
        emit(unavailable_payload())
        return 0

    enabled = wifi_enabled()
    device = wifi_device()
    networks, current = scan_networks(enabled, rescan="no")
    if current:
        current.update(ip_details(device))
        current["state"] = "Connected"
    elif enabled:
        current = active_connection(device)
    emit({
        "available": True,
        "enabled": enabled,
        "device": device,
        "current": current,
        "networks": networks,
        "error": "" if device or not enabled else "No Wi-Fi adapter is available.",
    })
    return 0


def snapshot():
    if not shutil.which("nmcli"):
        emit(unavailable_payload())
        return 0

    enabled = wifi_enabled()
    device = wifi_device()
    networks, current = scan_networks(enabled)
    if current:
        current.update(ip_details(device))
        current["state"] = "Connected"
    emit({
        "available": True,
        "enabled": enabled,
        "device": device,
        "current": current,
        "networks": networks,
        "error": "" if device or not enabled else "No Wi-Fi adapter is available.",
    })
    return 0


def matching_security(ssid: str):
    networks, current = scan_networks(True)
    candidates = ([current] if current else []) + networks
    for row in candidates:
        if row and row.get("ssid") == ssid:
            return row
    return None


def reconnect_current():
    device = wifi_device()
    current = active_connection(device)
    if not device or not current or not current.get("uuid"):
        emit({"ok": False, "message": "No saved Wi-Fi connection is currently active."})
        return 1

    profile = str(current["profile"])
    connection_uuid = str(current["uuid"])
    code, _, err = run(
        ["nmcli", "--wait", "15", "connection", "down", "uuid", connection_uuid],
        timeout=20.0,
    )
    if code != 0:
        emit({"ok": False, "message": err or "Could not disconnect the current Wi-Fi connection."})
        return 1
    if active_connection(device) is not None:
        emit({"ok": False, "message": "NetworkManager did not confirm the Wi-Fi disconnect."})
        return 1

    code, _, err = run(
        ["nmcli", "--wait", "20", "connection", "up", "uuid", connection_uuid, "ifname", device],
        timeout=25.0,
    )
    if code != 0:
        emit({"ok": False, "message": err or "Could not reconnect the Wi-Fi connection."})
        return 1
    restored = active_connection(device)
    if restored is None or restored.get("uuid") != connection_uuid:
        emit({"ok": False, "message": "NetworkManager did not confirm the Wi-Fi reconnection."})
        return 1

    emit({"ok": True, "message": "Reconnected to " + str(restored.get("ssid") or profile) + "."})
    return 0


def action(argv):
    if not shutil.which("nmcli"):
        emit({"ok": False, "message": "NetworkManager nmcli is unavailable."})
        return 1
    if not argv:
        emit({"ok": False, "message": "No Wi-Fi action was supplied."})
        return 2

    command = argv[0]
    if command == "reconnect" and len(argv) == 1:
        return reconnect_current()

    if command == "toggle" and len(argv) == 2 and argv[1] in ("on", "off"):
        code, _, err = run(["nmcli", "radio", "wifi", argv[1]], timeout=5.0)
        emit({"ok": code == 0, "message": "Wi-Fi enabled." if argv[1] == "on" and code == 0 else "Wi-Fi disabled." if code == 0 else (err or "Could not change Wi-Fi state.")})
        return 0 if code == 0 else 1

    if command == "rescan":
        code, _, err = run(["nmcli", "device", "wifi", "rescan"], timeout=8.0)
        emit({"ok": code == 0, "message": "Scan refreshed." if code == 0 else (err or "Wi-Fi scan failed.")})
        return 0 if code == 0 else 1

    if command == "disconnect":
        device = argv[1] if len(argv) > 1 else wifi_device()
        if not device:
            emit({"ok": False, "message": "No Wi-Fi adapter is available."})
            return 1
        code, _, err = run(["nmcli", "device", "disconnect", device], timeout=8.0)
        emit({"ok": code == 0, "message": "Disconnected." if code == 0 else (err or "Disconnect failed.")})
        return 0 if code == 0 else 1

    if command == "connect" and len(argv) >= 2:
        ssid = argv[1]
        hidden = len(argv) >= 3 and argv[2] == "hidden"
        network = matching_security(ssid) if not hidden else None
        if network and network.get("enterprise"):
            emit({"ok": False, "message": "Enterprise Wi-Fi needs an existing NetworkManager profile in this milestone."})
            return 1

        password = sys.stdin.readline().rstrip("\n")
        args = ["nmcli", "--wait", "20"]
        if password:
            args.append("--ask")
        args.extend(["device", "wifi", "connect", ssid])
        device = wifi_device()
        if device:
            args.extend(["ifname", device])
        if hidden:
            args.extend(["hidden", "yes"])

        code, _, err = run(args, timeout=25.0, stdin_text=(password + "\n") if password else None)
        message = "Connected to " + ssid + "." if code == 0 else (err or "Could not connect to " + ssid + ".")
        emit({"ok": code == 0, "message": message})
        return 0 if code == 0 else 1

    emit({"ok": False, "message": "Unsupported Wi-Fi action."})
    return 2


def main():
    if len(sys.argv) < 2 or sys.argv[1] == "snapshot":
        return snapshot()
    if sys.argv[1] == "status":
        return status_snapshot()
    if sys.argv[1] == "networks":
        return networks_snapshot()
    if sys.argv[1] == "action":
        return action(sys.argv[2:])
    emit({"ok": False, "message": "Unknown mode."})
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
