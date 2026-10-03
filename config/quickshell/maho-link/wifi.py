#!/usr/bin/env python3

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid
from typing import Iterable

DEFAULT_SCAN_ARGS = ("--rescan", "auto")
_ENTERPRISE_CANCEL_REQUESTED = False


class EnterpriseConnectionCancelled(Exception):
    pass


def _enterprise_cancel_handler(signum, frame):
    global _ENTERPRISE_CANCEL_REQUESTED
    _ENTERPRISE_CANCEL_REQUESTED = True
    raise EnterpriseConnectionCancelled("Enterprise connection cancelled.")


def emit(payload):
    print(json.dumps(payload, separators=(",", ":")), flush=True)


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


def friendly_wifi_error(raw: str, fallback: str):
    text = str(raw or "").strip()
    lowered = text.lower()
    mappings = (
        (
            ("secrets were required", "no secrets", "wrong password",
             "authentication failed", "802.1x supplicant"),
            "Authentication failed. Check the Wi-Fi password or enterprise credentials.",
        ),
        (
            ("no network with ssid", "ssid not found", "network could not be found"),
            "This Wi-Fi network is no longer in range.",
        ),
        (
            ("timed out", "timeout", "association took too long"),
            "The Wi-Fi connection timed out. Move closer and try again.",
        ),
        (
            ("not authorized", "permission denied", "insufficient privileges"),
            "NetworkManager denied this connectivity change.",
        ),
    )
    for needles, message in mappings:
        if any(needle in lowered for needle in needles):
            return message
    return text[:280] if text else fallback


def connection_properties(connection_uuid: str):
    fields = (
        "connection.id,connection.uuid,connection.autoconnect,"
        "802-11-wireless.ssid,802-11-wireless-security.key-mgmt,802-1x.eap"
    )
    code, out, _ = run([
        "nmcli", "-t", "-e", "yes", "-f", fields,
        "connection", "show", "uuid", connection_uuid,
    ])
    if code != 0:
        return {}

    result = {}
    for line in out.splitlines():
        parts = split_nmcli(line)
        if len(parts) < 2:
            continue
        result[parts[0]] = ":".join(parts[1:]).strip()
    return result


def saved_wifi_profiles():
    code, out, _ = run([
        "nmcli", "-t", "-e", "yes", "-f",
        "NAME,UUID,TYPE,TIMESTAMP,AUTOCONNECT,ACTIVE,DEVICE",
        "connection", "show",
    ])
    if code != 0:
        return []

    profiles = []
    for line in out.splitlines():
        fields = split_nmcli(line)
        if len(fields) < 7 or fields[2] not in ("802-11-wireless", "wifi", "wireless"):
            continue
        name, connection_uuid, _type, timestamp_raw, autoconnect, active, device = fields[:7]
        details = connection_properties(connection_uuid)
        ssid = details.get("802-11-wireless.ssid", "") or name
        key_mgmt = details.get("802-11-wireless-security.key-mgmt", "")
        eap = details.get("802-1x.eap", "")
        lowered_key_mgmt = key_mgmt.lower()
        enterprise = bool(eap) or "eap" in lowered_key_mgmt
        secured = bool(key_mgmt)
        try:
            timestamp = int(timestamp_raw or 0)
        except ValueError:
            timestamp = 0
        profiles.append({
            "profile": name,
            "uuid": connection_uuid,
            "ssid": ssid,
            "autoconnect": autoconnect.lower() == "yes",
            "active": active.lower() == "yes",
            "device": device,
            "timestamp": timestamp,
            "security": "Enterprise" if enterprise else (key_mgmt.upper() if secured else "Open"),
            "secured": secured,
            "enterprise": enterprise,
            "eap": eap,
            "saved": True,
            "available": False,
        })

    profiles.sort(key=lambda row: (
        not row["active"],
        -int(row["timestamp"]),
        row["ssid"].casefold(),
        row["uuid"],
    ))
    return profiles


def preferred_profile_for_ssid(ssid: str, profiles=None):
    candidates = [
        row for row in (profiles if profiles is not None else saved_wifi_profiles())
        if row.get("ssid") == ssid
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda row: (
        not bool(row.get("active")),
        -int(row.get("timestamp") or 0),
        str(row.get("uuid") or ""),
    ))
    return candidates[0]


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

    properties = connection_properties(connection_uuid)
    key_mgmt = properties.get("802-11-wireless-security.key-mgmt", "")
    eap = properties.get("802-1x.eap", "")
    enterprise = bool(eap) or "eap" in key_mgmt.lower()
    current = {
        "profile": profile,
        "uuid": connection_uuid,
        "profileUuid": connection_uuid,
        "profileName": profile,
        "saved": True,
        "device": device,
        "ssid": ssid.splitlines()[0].strip(),
        "signal": -1,
        "quality": "",
        "frequency": 0,
        "band": "",
        "security": "Enterprise" if enterprise else (key_mgmt.upper() if key_mgmt else ""),
        "secured": bool(key_mgmt),
        "enterprise": enterprise,
        "state": "Connected",
    }
    current.update(ip_details(device))
    return current


def scan_networks(enabled: bool, *, rescan="auto", saved_profiles=None):
    if not enabled:
        return [], None
    profiles = saved_profiles if saved_profiles is not None else saved_wifi_profiles()
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
            "available": True,
            **security_info(security_raw),
        }
        saved = preferred_profile_for_ssid(ssid, profiles)
        entry["saved"] = saved is not None
        entry["profileUuid"] = str(saved.get("uuid") or "") if saved else ""
        entry["profileName"] = str(saved.get("profile") or "") if saved else ""
        if saved and saved.get("enterprise"):
            entry["enterprise"] = True
            entry["secured"] = True
        previous = strongest.get(ssid)
        if previous is None or signal > previous["signal"]:
            strongest[ssid] = entry
        if in_use.strip() == "*":
            current = entry.copy()

    # Keep every live scan row here, including the row NetworkManager marks
    # IN-USE. The authoritative active-connection query below decides what is
    # actually connected; a stale scan marker must never manufacture or erase
    # connection truth.
    networks = sorted(strongest.values(), key=lambda row: (-row["signal"], row["ssid"].lower()))

    present_ssids = {row["ssid"] for row in networks}
    for profile in profiles:
        ssid = str(profile.get("ssid") or "")
        if not ssid or ssid in present_ssids or profile.get("active"):
            continue
        networks.append({
            "ssid": ssid,
            "signal": -1,
            "quality": "Saved",
            "frequency": 0,
            "band": "",
            "available": False,
            "security": str(profile.get("security") or "Saved"),
            "secured": bool(profile.get("secured")),
            "enterprise": bool(profile.get("enterprise")),
            "saved": True,
            "profileUuid": str(profile.get("uuid") or ""),
            "profileName": str(profile.get("profile") or ""),
        })
        present_ssids.add(ssid)
    return networks, current


def ethernet_snapshot():
    code, out, _ = run([
        "nmcli", "-t", "-e", "yes", "-f",
        "DEVICE,TYPE,STATE,CONNECTION", "device", "status",
    ])
    if code != 0:
        return {"available": False, "connected": False, "device": "", "state": "Unavailable",
                "profile": "", "uuid": "", "ipv4": "", "gateway": ""}

    candidates = []
    for line in out.splitlines():
        fields = split_nmcli(line)
        if len(fields) < 4 or fields[1] != "ethernet":
            continue
        candidates.append({
            "device": fields[0],
            "stateRaw": fields[2],
            "profile": "" if fields[3] == "--" else fields[3],
        })
    if not candidates:
        return {"available": False, "connected": False, "device": "", "state": "Unavailable",
                "profile": "", "uuid": "", "ipv4": "", "gateway": ""}

    state_priority = {
        "connected": 0,
        "connecting": 1,
        "prepare": 1,
        "config": 1,
        "ip-config": 1,
        "ip-check": 1,
        "secondaries": 1,
        "disconnected": 2,
        "unavailable": 3,
        "unmanaged": 4,
    }
    candidates.sort(key=lambda row: state_priority.get(row["stateRaw"], 5))
    chosen = candidates[0]
    raw_state = chosen["stateRaw"]
    connected = raw_state == "connected"
    if connected:
        state_label = "Connected"
    elif raw_state in ("connecting", "prepare", "config", "ip-config", "ip-check", "secondaries"):
        state_label = "Connecting"
    elif raw_state == "disconnected":
        state_label = "Disconnected"
    elif raw_state == "unavailable":
        state_label = "Unavailable"
    elif raw_state == "unmanaged":
        state_label = "Unmanaged"
    else:
        state_label = raw_state.replace("-", " ").title() if raw_state else "Unknown"
    details = ip_details(chosen["device"]) if connected else {"ipv4": "", "gateway": ""}
    connection_uuid = ""
    if connected:
        code, active, _ = run([
            "nmcli", "-t", "-e", "yes", "-f", "NAME,UUID,TYPE,DEVICE",
            "connection", "show", "--active",
        ])
        if code == 0:
            for line in active.splitlines():
                fields = split_nmcli(line)
                if len(fields) >= 4 and fields[2] in ("802-3-ethernet", "ethernet") and fields[3] == chosen["device"]:
                    chosen["profile"] = fields[0]
                    connection_uuid = fields[1]
                    break
    return {
        "available": True,
        "connected": connected,
        "device": chosen["device"],
        "state": state_label,
        "profile": chosen["profile"],
        "uuid": connection_uuid,
        **details,
    }


def connectivity_snapshot():
    code, out, _ = run(["nmcli", "-t", "-f", "CONNECTIVITY", "general"])
    state = out.splitlines()[0].strip().lower() if code == 0 and out.strip() else "unknown"
    if state not in ("full", "portal", "limited", "none", "unknown"):
        state = "unknown"
    return {
        "state": state,
        "captivePortal": state == "portal",
        "limited": state == "limited",
        "online": state == "full",
        "loginAvailable": state in ("portal", "limited"),
    }


def unavailable_payload():
    return {
        "available": False,
        "enabled": False,
        "device": "",
        "current": None,
        "networks": [],
        "saved": [],
        "ethernet": {
            "available": False, "connected": False, "device": "", "state": "Unavailable",
            "profile": "", "uuid": "", "ipv4": "", "gateway": "",
        },
        "connectivity": {
            "state": "unknown", "captivePortal": False, "limited": False,
            "online": False, "loginAvailable": False,
        },
        "error": "NetworkManager nmcli is unavailable.",
    }


def merge_active_scan(
    active: dict | None,
    scan_current: dict | None,
    networks: list[dict],
) -> tuple[list[dict], dict | None, bool]:
    """Bind cached scan metadata to authoritative active-connection truth."""
    if active is None:
        # IN-USE in the scan cache is observational metadata only. If
        # NetworkManager no longer reports an active connection, stale cache
        # cannot keep a disconnected SSID visually connected.
        return networks, None, False

    active_ssid = str(active.get("ssid") or "")
    scan_match = None
    if scan_current and str(scan_current.get("ssid") or "") == active_ssid:
        scan_match = scan_current
    if scan_match is None:
        for row in networks:
            if str(row.get("ssid") or "") == active_ssid and bool(row.get("available")):
                scan_match = row
                break

    current = dict(active)
    if scan_match is not None:
        for field in (
            "signal", "quality", "frequency", "band", "available",
            "security", "secured", "enterprise",
        ):
            if field in scan_match:
                current[field] = scan_match[field]
        # Active profile identity remains authoritative even if a cached scan
        # row was associated with a different saved profile.
        current["saved"] = True
        current["profileUuid"] = str(active.get("profileUuid") or active.get("uuid") or "")
        current["profileName"] = str(active.get("profileName") or active.get("profile") or "")

    filtered = [
        row for row in networks
        if str(row.get("ssid") or "") != active_ssid
    ]
    return filtered, current, scan_match is not None


def coherent_wifi_observation(*, include_system: bool) -> dict:
    observed_at_ms = int(time.time() * 1000)
    if not shutil.which("nmcli"):
        payload = unavailable_payload()
        payload["observedAtMs"] = observed_at_ms
        payload["scanState"] = "unavailable"
        payload["scanSource"] = "none"
        return payload

    enabled = wifi_enabled()
    device = wifi_device()
    profiles = saved_wifi_profiles()
    active = active_connection(device) if enabled else None
    networks, scan_current = scan_networks(
        enabled, rescan="no", saved_profiles=profiles
    )
    networks, current, scan_has_current = merge_active_scan(
        active, scan_current, networks
    )

    live_rows = [row for row in networks if bool(row.get("available"))]
    if not enabled:
        scan_state = "disabled"
    elif scan_has_current or live_rows:
        scan_state = "cached"
    else:
        # Empty NetworkManager scan cache is not proof that no networks exist.
        # Render the authoritative current connection immediately and let the
        # asynchronous scan path converge nearby-network metadata.
        scan_state = "warming"

    payload = {
        "available": True,
        "enabled": enabled,
        "device": device,
        "current": current,
        "networks": networks,
        "saved": profiles,
        "observedAtMs": observed_at_ms,
        "scanState": scan_state,
        "scanSource": "networkmanager-cache",
        "error": "" if device or not enabled else "No Wi-Fi adapter is available.",
    }
    if include_system:
        payload["ethernet"] = ethernet_snapshot()
        payload["connectivity"] = connectivity_snapshot()
    return payload


def status_snapshot():
    if not shutil.which("nmcli"):
        payload = unavailable_payload()
        payload["observedAtMs"] = int(time.time() * 1000)
        payload["scanState"] = "unavailable"
        payload["scanSource"] = "none"
        emit(payload)
        return 0

    enabled = wifi_enabled()
    device = wifi_device()
    current = active_connection(device) if enabled else None
    emit({
        "available": True,
        "enabled": enabled,
        "device": device,
        "current": current,
        "observedAtMs": int(time.time() * 1000),
        "scanState": "status-only",
        "scanSource": "none",
        "ethernet": ethernet_snapshot(),
        "connectivity": connectivity_snapshot(),
        "error": "" if device or not enabled else "No Wi-Fi adapter is available.",
    })
    return 0


def networks_snapshot():
    emit(coherent_wifi_observation(include_system=False))
    return 0


def snapshot():
    emit(coherent_wifi_observation(include_system=True))
    return 0


def rescan_and_converge() -> int:
    device = wifi_device()
    if not device:
        emit({"ok": False, "message": "No Wi-Fi adapter is available."})
        return 1

    code, _, err = run(["nmcli", "device", "wifi", "rescan"], timeout=8.0)
    if code != 0:
        emit({
            "ok": False,
            "message": friendly_wifi_error(err, "Wi-Fi scan failed."),
        })
        return 1

    # The request is asynchronous inside NetworkManager. Keep this helper
    # asynchronous from QML too, and wait only for a bounded cache convergence
    # window. A genuinely empty RF environment may remain "warming"; that is
    # truthful and does not erase the current active connection.
    deadline = time.monotonic() + 2.2
    while time.monotonic() < deadline:
        time.sleep(0.18)
        observation = coherent_wifi_observation(include_system=False)
        if observation.get("scanState") != "warming":
            break

    emit({"ok": True, "message": "Scan refreshed."})
    return 0


def matching_security(ssid: str):
    networks, current = scan_networks(True)
    candidates = ([current] if current else []) + networks
    for row in candidates:
        if row and row.get("ssid") == ssid:
            return row
    return None


def replace_saved_psk(ssid: str, password: str):
    """Persist a replacement PSK without putting it in a process argument."""
    try:
        import gi

        gi.require_version("NM", "1.0")
        from gi.repository import NM
    except (ImportError, ValueError):
        # The optional libnm Python bindings are not required for ordinary
        # connection attempts. Fall back to nmcli --ask, which still receives
        # the password on stdin and never places it in process arguments.
        return "", ""

    try:
        client = NM.Client.new(None)
        matches = []
        for connection in client.get_connections():
            wireless = connection.get_setting_wireless()
            metadata = connection.get_setting_connection()
            if wireless is None or metadata is None:
                continue
            raw_ssid = wireless.get_ssid()
            if raw_ssid is None:
                continue
            candidate = bytes(raw_ssid.get_data()).decode("utf-8", errors="replace")
            if candidate != ssid:
                continue
            security = connection.get_setting_wireless_security()
            if security is None or security.get_key_mgmt() not in ("wpa-psk", "sae"):
                continue
            matches.append((int(metadata.get_timestamp() or 0), connection, security))

        if not matches:
            return "", ""

        _, connection, security = max(matches, key=lambda row: row[0])
        metadata = connection.get_setting_connection()
        security.set_property("psk", password)
        security.set_secret_flags("psk", 0)
        if not connection.commit_changes(True, None):
            return "", "NetworkManager did not save the updated Wi-Fi password."
        return str(metadata.get_uuid() or ""), ""
    except Exception as exc:
        return "", "NetworkManager could not securely update the saved Wi-Fi password: " + str(exc)


def validate_enterprise_file(value: str, label: str):
    if not value:
        return "", label + " is required."
    path = Path(value).expanduser()
    if not path.is_absolute():
        return "", label + " must use an absolute file path."
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return "", label + " could not be found."
    if not resolved.is_file():
        return "", label + " must point to a regular file."
    if not os.access(resolved, os.R_OK):
        return "", label + " is not readable."
    return str(resolved), ""


def persist_enterprise_secrets(connection_uuid: str, options: dict):
    """Persist 802.1X secrets through libnm so they never appear on argv."""
    password = str(options.get("password") or "")
    private_key_password = str(options.get("privateKeyPassword") or "")
    if not password and not private_key_password:
        return True, ""

    try:
        import gi

        gi.require_version("NM", "1.0")
        from gi.repository import NM
    except (ImportError, ValueError):
        return False, (
            "Secure enterprise credential storage is unavailable. "
            "Install the MahoOS python-gobject dependency and try again."
        )

    try:
        client = NM.Client.new(None)
        connection = client.get_connection_by_uuid(connection_uuid)
        if connection is None:
            return False, "NetworkManager could not find the new enterprise profile."
        setting = connection.get_setting_802_1x()
        if setting is None:
            return False, "NetworkManager did not create the 802.1X settings."
        if password:
            setting.set_property("password", password)
            setting.set_secret_flags("password", 0)
        if private_key_password:
            setting.set_property("private-key-password", private_key_password)
            setting.set_secret_flags("private-key-password", 0)
        if not connection.commit_changes(True, None):
            return False, "NetworkManager did not save the enterprise credentials."
        return True, ""
    except Exception:
        return False, "NetworkManager could not securely save the enterprise credentials."


def activate_saved_profile(connection_uuid: str):
    try:
        uuid.UUID(connection_uuid)
    except (ValueError, AttributeError):
        emit({"ok": False, "message": "Saved Wi-Fi profile identity is invalid."})
        return 2

    device = wifi_device()
    args = ["nmcli", "--wait", "25", "connection", "up", "uuid", connection_uuid]
    if device:
        args.extend(["ifname", device])
    code, _, err = run(args, timeout=30.0)
    if code != 0:
        emit({"ok": False, "message": friendly_wifi_error(err, "Could not connect using the saved Wi-Fi profile.")})
        return 1

    restored = active_connection(device)
    if restored is None or restored.get("uuid") != connection_uuid:
        emit({"ok": False, "message": "NetworkManager did not confirm the saved Wi-Fi connection."})
        return 1
    emit({"ok": True, "message": "Connected to " + str(restored.get("ssid") or restored.get("profile") or "Wi-Fi") + "."})
    return 0


def forget_saved_profile(connection_uuid: str):
    try:
        uuid.UUID(connection_uuid)
    except (ValueError, AttributeError):
        emit({"ok": False, "message": "Saved Wi-Fi profile identity is invalid."})
        return 2

    active = active_connection(wifi_device())
    if active and active.get("uuid") == connection_uuid:
        emit({"ok": False, "message": "Disconnect this Wi-Fi network before forgetting it."})
        return 1

    code, _, err = run(["nmcli", "connection", "delete", "uuid", connection_uuid], timeout=10.0)
    ok = code == 0
    emit({"ok": ok, "message": "Network forgotten." if ok else friendly_wifi_error(err, "Could not forget this Wi-Fi network.")})
    return 0 if ok else 1


def cleanup_enterprise_profile(connection_uuid: str) -> None:
    if not connection_uuid:
        return
    run(["nmcli", "connection", "delete", "uuid", connection_uuid], timeout=8.0)


def finalize_enterprise_profile(connection_uuid: str):
    code, _, err = run([
        "nmcli", "connection", "modify", "uuid", connection_uuid,
        "connection.autoconnect", "yes",
    ], timeout=8.0)
    if code != 0:
        return False, friendly_wifi_error(err, "NetworkManager could not finalize the enterprise profile.")

    code, value, err = run([
        "nmcli", "-g", "connection.autoconnect", "connection", "show", "uuid", connection_uuid,
    ], timeout=8.0)
    if code != 0 or value.strip().lower() != "yes":
        return False, friendly_wifi_error(err, "NetworkManager did not confirm the finalized enterprise profile.")
    return True, ""


def create_enterprise_profile(ssid: str, options: dict):
    identity = str(options.get("identity") or "").strip()
    eap = str(options.get("eap") or "peap").strip().lower()
    phase2 = str(options.get("phase2") or ("mschapv2" if eap == "peap" else "pap")).strip().lower()
    anonymous = str(options.get("anonymousIdentity") or "").strip()
    domain_suffix = str(options.get("domainSuffix") or "").strip()
    domain_match = str(options.get("domainMatch") or "").strip()
    ca_cert_input = str(options.get("caCert") or "").strip()
    client_cert_input = str(options.get("clientCert") or "").strip()
    private_key_input = str(options.get("privateKey") or "").strip()

    if not ssid or not identity:
        return "", "Enterprise Wi-Fi requires a network name and identity."
    if eap not in ("peap", "ttls", "tls"):
        return "", "Maho Link supports PEAP, TTLS, and EAP-TLS enterprise Wi-Fi."
    if eap != "tls" and phase2 not in ("mschapv2", "pap", "mschap", "chap"):
        return "", "Unsupported enterprise inner authentication method."
    if not domain_suffix and not domain_match:
        return "", "Enterprise Wi-Fi requires a server domain or domain suffix for certificate validation."

    ca_cert = ""
    client_cert = ""
    private_key = ""
    if ca_cert_input:
        ca_cert, error = validate_enterprise_file(ca_cert_input, "CA certificate")
        if error:
            return "", error

    if eap == "tls":
        if not ca_cert:
            return "", "EAP-TLS requires a CA certificate."
        client_cert, error = validate_enterprise_file(client_cert_input, "Client certificate")
        if error:
            return "", error
        private_key, error = validate_enterprise_file(private_key_input, "Private key")
        if error:
            return "", error

    profile_name = "Maho Link · " + ssid + " · " + uuid.uuid4().hex[:8]
    device = wifi_device()
    args = [
        "nmcli", "connection", "add", "type", "wifi",
        "ifname", device or "*", "con-name", profile_name, "ssid", ssid,
        "connection.autoconnect", "no",
        "802-11-wireless-security.key-mgmt", "wpa-eap",
        "802-1x.eap", eap,
        "802-1x.identity", identity,
    ]
    if eap != "tls":
        args.extend(["802-1x.phase2-auth", phase2])
    if anonymous:
        args.extend(["802-1x.anonymous-identity", anonymous])
    if domain_suffix:
        args.extend(["802-1x.domain-suffix-match", domain_suffix])
    if domain_match:
        args.extend(["802-1x.domain-match", domain_match])
    if ca_cert:
        args.extend(["802-1x.ca-cert", ca_cert])
    elif eap != "tls":
        args.extend(["802-1x.system-ca-certs", "yes"])
    if eap == "tls":
        args.extend([
            "802-1x.client-cert", client_cert,
            "802-1x.private-key", private_key,
        ])

    code, _, err = run(args, timeout=12.0)
    if code != 0:
        # The random profile name belongs only to this attempt. If nmcli was
        # interrupted after NetworkManager accepted the add, remove it by name.
        run(["nmcli", "connection", "delete", "id", profile_name], timeout=8.0)
        return "", friendly_wifi_error(err, "NetworkManager could not create the enterprise profile.")

    code, profile_uuid, err = run([
        "nmcli", "-g", "connection.uuid", "connection", "show", "id", profile_name,
    ])
    if code != 0 or not profile_uuid.strip():
        run(["nmcli", "connection", "delete", "id", profile_name], timeout=8.0)
        return "", err or "NetworkManager did not return the enterprise profile identity."
    return profile_uuid.splitlines()[0].strip(), ""


def connect_enterprise(ssid: str, options: dict):
    global _ENTERPRISE_CANCEL_REQUESTED
    _ENTERPRISE_CANCEL_REQUESTED = False
    eap = str(options.get("eap") or "peap").strip().lower()
    password = str(options.get("password") or "")
    if eap != "tls" and not password:
        emit({"ok": False, "message": "Enterprise Wi-Fi password is required."})
        return 1

    profile_uuid = ""
    finalized = False
    previous_handlers = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            previous_handlers[sig] = signal.signal(sig, _enterprise_cancel_handler)
        except (ValueError, OSError):
            pass

    try:
        profile_uuid, error = create_enterprise_profile(ssid, options)
        if not profile_uuid:
            emit({"ok": False, "message": error})
            return 1

        persisted, persist_error = persist_enterprise_secrets(profile_uuid, options)
        if not persisted:
            emit({"ok": False, "message": persist_error or "NetworkManager could not securely save the enterprise credentials."})
            return 1

        device = wifi_device()
        args = ["nmcli", "--wait", "25", "connection", "up", "uuid", profile_uuid]
        if device:
            args.extend(["ifname", device])

        code, _, err = run(args, timeout=30.0)
        if code != 0:
            message = "Enterprise Wi-Fi connection was cancelled." if _ENTERPRISE_CANCEL_REQUESTED else friendly_wifi_error(
                err, "Could not connect to enterprise Wi-Fi.")
            emit({"ok": False, "message": message})
            return 1

        restored = active_connection(device)
        if restored is None or restored.get("uuid") != profile_uuid:
            message = "Enterprise Wi-Fi connection was cancelled." if _ENTERPRISE_CANCEL_REQUESTED else (
                "NetworkManager did not confirm the enterprise Wi-Fi connection.")
            emit({"ok": False, "message": message})
            return 1

        finalized, final_error = finalize_enterprise_profile(profile_uuid)
        if not finalized:
            emit({"ok": False, "message": final_error})
            return 1

        emit({"ok": True, "message": "Connected to " + ssid + "."})
        return 0
    except EnterpriseConnectionCancelled:
        emit({"ok": False, "message": "Enterprise Wi-Fi connection was cancelled."})
        return 1
    except Exception:
        emit({"ok": False, "message": "Enterprise Wi-Fi connection helper failed."})
        return 1
    finally:
        for sig, handler in previous_handlers.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass
        if profile_uuid and not finalized:
            cleanup_enterprise_profile(profile_uuid)
        _ENTERPRISE_CANCEL_REQUESTED = False


def open_captive_portal():
    if not shutil.which("xdg-open"):
        emit({"ok": False, "message": "No browser opener is available for captive portal login."})
        return 1
    code, _, err = run(["xdg-open", "http://neverssl.com/"], timeout=8.0)
    emit({"ok": code == 0, "message": "Opened captive portal login." if code == 0 else (err or "Could not open captive portal login.")})
    return 0 if code == 0 else 1


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
        emit({"ok": False, "message": friendly_wifi_error(err, "Could not disconnect the current Wi-Fi connection.")})
        return 1
    if active_connection(device) is not None:
        emit({"ok": False, "message": "NetworkManager did not confirm the Wi-Fi disconnect."})
        return 1

    code, _, err = run(
        ["nmcli", "--wait", "20", "connection", "up", "uuid", connection_uuid, "ifname", device],
        timeout=25.0,
    )
    if code != 0:
        emit({"ok": False, "message": friendly_wifi_error(err, "Could not reconnect the Wi-Fi connection.")})
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

    if command == "connect-saved" and len(argv) == 2:
        return activate_saved_profile(argv[1])

    if command == "forget" and len(argv) == 2:
        return forget_saved_profile(argv[1])

    if command == "connect-enterprise" and len(argv) == 2:
        try:
            options = json.loads(sys.stdin.readline())
        except (json.JSONDecodeError, TypeError):
            emit({"ok": False, "message": "Enterprise Wi-Fi fields were invalid."})
            return 2
        if not isinstance(options, dict):
            emit({"ok": False, "message": "Enterprise Wi-Fi fields were invalid."})
            return 2
        return connect_enterprise(argv[1], options)

    if command == "portal-login" and len(argv) == 1:
        return open_captive_portal()

    if command == "toggle" and len(argv) == 2 and argv[1] in ("on", "off"):
        code, _, err = run(["nmcli", "radio", "wifi", argv[1]], timeout=5.0)
        emit({"ok": code == 0, "message": "Wi-Fi enabled." if argv[1] == "on" and code == 0 else "Wi-Fi disabled." if code == 0 else friendly_wifi_error(err, "Could not change Wi-Fi state.")})
        return 0 if code == 0 else 1

    if command == "rescan":
        return rescan_and_converge()

    if command == "disconnect":
        device = argv[1] if len(argv) > 1 else wifi_device()
        if not device:
            emit({"ok": False, "message": "No Wi-Fi adapter is available."})
            return 1
        code, _, err = run(["nmcli", "device", "disconnect", device], timeout=8.0)
        emit({"ok": code == 0, "message": "Disconnected." if code == 0 else friendly_wifi_error(err, "Disconnect failed.")})
        return 0 if code == 0 else 1

    if command == "connect" and len(argv) >= 2:
        ssid = argv[1]
        hidden = len(argv) >= 3 and argv[2] == "hidden"
        network = matching_security(ssid) if not hidden else None
        if network and network.get("enterprise"):
            emit({"ok": False, "message": "Enterprise Wi-Fi requires identity fields or a saved NetworkManager profile."})
            return 1

        password = sys.stdin.readline().rstrip("\n")
        device = wifi_device()

        if password:
            profile_uuid, profile_error = replace_saved_psk(ssid, password)
            if profile_error:
                emit({"ok": False, "message": profile_error})
                return 1
            if profile_uuid:
                args = ["nmcli", "--wait", "20", "connection", "up", "uuid", profile_uuid]
                if device:
                    args.extend(["ifname", device])
                code, _, err = run(args, timeout=25.0)
                message = "Connected to " + ssid + "." if code == 0 else friendly_wifi_error(err, "Could not connect to " + ssid + ".")
                emit({"ok": code == 0, "message": message})
                return 0 if code == 0 else 1

        args = ["nmcli", "--wait", "20"]
        if password:
            args.append("--ask")
        args.extend(["device", "wifi", "connect", ssid])
        if device:
            args.extend(["ifname", device])
        if hidden:
            args.extend(["hidden", "yes"])

        code, _, err = run(args, timeout=25.0, stdin_text=(password + "\n") if password else None)
        message = "Connected to " + ssid + "." if code == 0 else friendly_wifi_error(err, "Could not connect to " + ssid + ".")
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
