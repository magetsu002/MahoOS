#!/usr/bin/env python3

"""Thin BlueZ D-Bus adapter for Maho Link Bluetooth.

BlueZ remains authoritative. This module intentionally has no device database and
never invokes bluetoothctl. Structured ObjectManager snapshots are read through
busctl JSON and actions are sent directly to org.bluez D-Bus interfaces.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable

BLUEZ = "org.bluez"
OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
BATTERY = "org.bluez.Battery1"

ADAPTER_PATH_RE = re.compile(r"^/org/bluez/hci[0-9]+$")
DEVICE_PATH_RE = re.compile(r"^/org/bluez/hci[0-9]+/dev_[0-9A-Fa-f_]+$")
AUTOCONNECT_BACKOFF_SECONDS = (5, 15, 45, 120)
MAX_AUTOCONNECT_ATTEMPTS = len(AUTOCONNECT_BACKOFF_SECONDS)


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))


def run(args: Iterable[str], *, timeout: float = 6.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            list(args),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "The Bluetooth operation timed out."
    except Exception as exc:  # pragma: no cover - defensive system boundary
        return 127, "", str(exc)


def unwrap(value: Any) -> Any:
    """Unwrap busctl --json=short typed values without assuming one layout."""
    if isinstance(value, list):
        return [unwrap(item) for item in value]
    if not isinstance(value, dict):
        return value

    if "data" in value and set(value).issubset({"type", "data"}):
        return unwrap(value["data"])

    return {key: unwrap(item) for key, item in value.items()}


def managed_objects() -> tuple[dict[str, Any] | None, str]:
    if not shutil.which("busctl"):
        return None, "systemd busctl is unavailable."

    code, out, err = run(
        [
            "busctl",
            "--system",
            "--json=short",
            "call",
            BLUEZ,
            "/",
            OBJECT_MANAGER,
            "GetManagedObjects",
        ],
        timeout=8.0,
    )
    if code != 0:
        lowered = (err or out).lower()
        if "service unknown" in lowered or "name has no owner" in lowered:
            return None, "Bluetooth service is unavailable."
        return None, "Bluetooth status could not be read."

    try:
        payload = unwrap(json.loads(out))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, "Bluetooth returned an invalid status response."

    # busctl wraps method return values in the top-level data array.
    if isinstance(payload, dict) and "data" in payload:
        payload = unwrap(payload["data"])
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        payload = payload[0]

    if not isinstance(payload, dict):
        return None, "Bluetooth returned an unsupported status response."
    return payload, ""


def safe_string(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).replace("\x00", "").strip()
    return text[:160]


def device_kind(icon: str, klass: int | None) -> tuple[str, str]:
    normalized = icon.lower()
    mappings = (
        (("audio-headphones", "audio-headset"), ("Headphones", "headphones")),
        (("audio-speakers", "audio-card"), ("Speaker", "speaker")),
        (("input-keyboard",), ("Keyboard", "keyboard")),
        (("input-mouse",), ("Mouse", "mouse")),
        (("input-gaming", "input-joystick"), ("Controller", "controller")),
        (("phone",), ("Phone", "phone")),
        (("computer",), ("Computer", "computer")),
    )
    for needles, result in mappings:
        if any(needle in normalized for needle in needles):
            return result

    # Bluetooth major device class is encoded in bits 8..12.
    if isinstance(klass, int):
        major = (klass >> 8) & 0x1F
        if major == 0x04:
            return "Audio Device", "speaker"
        if major == 0x05:
            return "Input Device", "generic"
        if major == 0x02:
            return "Phone", "phone"
        if major == 0x01:
            return "Computer", "computer"

    return "Bluetooth Device", "generic"


def quality_from_rssi(rssi: Any) -> str:
    try:
        value = int(rssi)
    except (TypeError, ValueError):
        return ""
    if value >= -50:
        return "Excellent"
    if value >= -60:
        return "Very Good"
    if value >= -70:
        return "Good"
    if value >= -80:
        return "Fair"
    return "Weak"


def property_value(props: dict[str, Any], name: str, default: Any = None) -> Any:
    value = props.get(name, default)
    return unwrap(value)


def unavailable_snapshot(error: str) -> dict[str, Any]:
    return {
        "available": False,
        "enabled": False,
        "discovering": False,
        "adapterPath": "",
        "paired": [],
        "availableDevices": [],
        "connected": [],
        "autoConnectEligible": [],
        "error": error,
    }


def snapshot_payload() -> dict[str, Any]:
    objects, error = managed_objects()
    if objects is None:
        return unavailable_snapshot(error)

    adapters: list[tuple[str, dict[str, Any]]] = []
    for path, interfaces in objects.items():
        if not isinstance(interfaces, dict):
            continue
        adapter_props = interfaces.get(ADAPTER)
        if isinstance(adapter_props, dict) and ADAPTER_PATH_RE.fullmatch(path):
            adapters.append((path, adapter_props))

    if not adapters:
        return unavailable_snapshot("No Bluetooth adapter is available.")

    adapters.sort(key=lambda row: row[0])
    adapter_path, adapter_props = adapters[0]
    enabled = bool(property_value(adapter_props, "Powered", False))
    discovering = bool(property_value(adapter_props, "Discovering", False))

    paired: list[dict[str, Any]] = []
    nearby: list[dict[str, Any]] = []
    connected: list[dict[str, Any]] = []
    auto_connect_eligible: list[str] = []

    for path, interfaces in objects.items():
        if not isinstance(interfaces, dict) or not DEVICE_PATH_RE.fullmatch(path):
            continue
        props = interfaces.get(DEVICE)
        if not isinstance(props, dict):
            continue
        if safe_string(property_value(props, "Adapter")) != adapter_path:
            continue

        alias = safe_string(property_value(props, "Alias"))
        name = alias or safe_string(property_value(props, "Name")) or "Bluetooth Device"
        icon = safe_string(property_value(props, "Icon"))
        klass_raw = property_value(props, "Class")
        try:
            klass = int(klass_raw) if klass_raw is not None else None
        except (TypeError, ValueError):
            klass = None
        type_label, kind = device_kind(icon, klass)
        paired_flag = bool(property_value(props, "Paired", False))
        connected_flag = bool(property_value(props, "Connected", False))
        trusted_flag = bool(property_value(props, "Trusted", False))
        rssi = property_value(props, "RSSI")
        battery_props = interfaces.get(BATTERY)
        battery = None
        if isinstance(battery_props, dict):
            percentage = property_value(battery_props, "Percentage")
            try:
                battery = max(0, min(100, int(percentage)))
            except (TypeError, ValueError):
                battery = None

        reachable = connected_flag or isinstance(rssi, (int, float))
        row = {
            "path": path,
            "name": name,
            "paired": paired_flag,
            "connected": connected_flag,
            "trusted": trusted_flag,
            "available": reachable,
            "type": type_label,
            "kind": kind,
            "icon": icon,
            "battery": battery,
            "rssi": int(rssi) if isinstance(rssi, (int, float)) else None,
            "quality": quality_from_rssi(rssi),
        }

        if paired_flag:
            paired.append(row)
        elif enabled:
            nearby.append(row)
        if connected_flag:
            connected.append(row)
        if (enabled and paired_flag and trusted_flag and not connected_flag
                and reachable and kind in ("headphones", "speaker")):
            auto_connect_eligible.append(path)

    paired.sort(key=lambda row: (not row["connected"], row["name"].casefold(), row["path"]))
    nearby.sort(
        key=lambda row: (
            -(row["rssi"] if isinstance(row["rssi"], int) else -200),
            row["name"].casefold(),
            row["path"],
        )
    )
    connected.sort(key=lambda row: (row["name"].casefold(), row["path"]))

    auto_connect_eligible.sort()
    return {
        "available": True,
        "enabled": enabled,
        "discovering": discovering,
        "adapterPath": adapter_path,
        "paired": paired,
        "availableDevices": nearby,
        "connected": connected,
        "autoConnectEligible": auto_connect_eligible,
        "error": "",
    }


def snapshot() -> int:
    emit(snapshot_payload())
    return 0


def valid_adapter(path: Any) -> bool:
    return isinstance(path, str) and bool(ADAPTER_PATH_RE.fullmatch(path))


def valid_device(path: Any) -> bool:
    return isinstance(path, str) and bool(DEVICE_PATH_RE.fullmatch(path))


def friendly_error(raw: str, fallback: str) -> str:
    lowered = raw.lower()
    mappings = (
        (("authenticationcanceled", "authentication canceled", "authentication rejected"), "Pairing was cancelled."),
        (("authenticationfailed", "authentication failed"), "Authentication failed."),
        (("authenticationrejected", "rejected"), "Pairing was rejected."),
        (("alreadyconnected", "already connected"), "Device is already connected."),
        (("notconnected", "not connected"), "Device is not connected."),
        (("inprogress", "in progress"), "Another Bluetooth operation is already in progress."),
        (("notready", "not ready"), "Bluetooth is not ready."),
        (("connectionattemptfailed", "connection attempt failed"), "Couldn’t connect to this device."),
        (("failed",), fallback),
    )
    for needles, message in mappings:
        if any(needle in lowered for needle in needles):
            return message
    return fallback


def busctl_call(path: str, interface: str, method: str, *signature_and_args: str, timeout: float = 12.0):
    return run(
        ["busctl", "--system", "call", BLUEZ, path, interface, method, *signature_and_args],
        timeout=timeout,
    )


def session_state_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "maho" / "link-bluetooth-session.json"
    return Path(tempfile.gettempdir()) / f"maho-{os.getuid()}" / "link-bluetooth-session.json"


def empty_session_state() -> dict[str, Any]:
    return {"version": 1, "suppressed": [], "attempts": {}, "reachable": []}


def load_session_state() -> dict[str, Any]:
    try:
        raw = json.loads(session_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return empty_session_state()
    if not isinstance(raw, dict):
        return empty_session_state()

    suppressed = sorted({path for path in raw.get("suppressed", []) if valid_device(path)})
    reachable = sorted({path for path in raw.get("reachable", []) if valid_device(path)})
    attempts: dict[str, dict[str, Any]] = {}
    source_attempts = raw.get("attempts", {})
    if isinstance(source_attempts, dict):
        for path, value in source_attempts.items():
            if not valid_device(path) or not isinstance(value, dict):
                continue
            try:
                failures = max(0, min(MAX_AUTOCONNECT_ATTEMPTS, int(value.get("failures", 0))))
                next_attempt = max(0.0, float(value.get("nextAttempt", 0)))
            except (TypeError, ValueError):
                continue
            attempts[path] = {"failures": failures, "nextAttempt": next_attempt}
    return {
        "version": 1,
        "suppressed": suppressed,
        "attempts": attempts,
        "reachable": reachable,
    }


def save_session_state(state: dict[str, Any]) -> None:
    target = session_state_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.parent.chmod(0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".link-bluetooth.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def remember_manual_connection(device_path: str, connected: bool) -> None:
    state = load_session_state()
    suppressed = set(state["suppressed"])
    if connected:
        suppressed.discard(device_path)
        state["attempts"][device_path] = {
            "failures": 0,
            "nextAttempt": time.time() + AUTOCONNECT_BACKOFF_SECONDS[1],
        }
    else:
        suppressed.add(device_path)
    state["suppressed"] = sorted(suppressed)
    save_session_state(state)


def auto_connect() -> int:
    payload = snapshot_payload()
    if not payload["available"] or not payload["enabled"]:
        state = load_session_state()
        state["attempts"] = {}
        state["reachable"] = []
        save_session_state(state)
        emit({"ok": True, "status": "idle", "devicePath": "", "message": ""})
        return 0

    candidates = {
        row["path"]: row
        for row in payload["paired"]
        if row["path"] in payload["autoConnectEligible"]
    }
    reachable_now = set(candidates)
    state = load_session_state()
    previously_reachable = set(state["reachable"])

    # A disappearance ends the old bounded retry epoch. A later real
    # reachability transition may receive a fresh, still-bounded attempt set.
    for path in set(state["attempts"]) - reachable_now:
        state["attempts"].pop(path, None)
    for path in reachable_now - previously_reachable:
        state["attempts"].pop(path, None)
    state["reachable"] = sorted(reachable_now)

    now = time.time()
    selected: dict[str, Any] | None = None
    for path in sorted(candidates, key=lambda candidate: (
            candidates[candidate]["kind"] != "headphones",
            candidates[candidate]["name"].casefold(),
            candidate)):
        if path in state["suppressed"]:
            continue
        attempt = state["attempts"].get(path, {"failures": 0, "nextAttempt": 0})
        if attempt["failures"] >= MAX_AUTOCONNECT_ATTEMPTS:
            continue
        if now < attempt["nextAttempt"]:
            continue
        selected = candidates[path]
        break

    if selected is None:
        save_session_state(state)
        emit({"ok": True, "status": "idle", "devicePath": "", "message": ""})
        return 0

    path = selected["path"]
    code, out, err = busctl_call(path, DEVICE, "Connect", timeout=18.0)
    if code == 0:
        # BlueZ method success means the request was accepted; the following
        # ObjectManager snapshot remains the authority for Connected=true.
        # Hold a short grace window so a slow property signal cannot duplicate
        # the successful request.
        state["attempts"][path] = {
            "failures": 0,
            "nextAttempt": now + AUTOCONNECT_BACKOFF_SECONDS[1],
        }
        save_session_state(state)
        emit({"ok": True, "status": "connected", "devicePath": path, "message": "Connected."})
        return 0

    previous = state["attempts"].get(path, {"failures": 0, "nextAttempt": 0})
    failures = min(MAX_AUTOCONNECT_ATTEMPTS, int(previous["failures"]) + 1)
    delay = AUTOCONNECT_BACKOFF_SECONDS[failures - 1]
    state["attempts"][path] = {"failures": failures, "nextAttempt": now + delay}
    save_session_state(state)
    emit({
        "ok": False,
        "status": "backoff",
        "devicePath": path,
        "message": friendly_error(err or out, "Couldn’t connect to this device."),
        "retryAfter": delay,
        "attempt": failures,
    })
    return 1


def action(argv: list[str]) -> int:
    if not shutil.which("busctl"):
        emit({"ok": False, "message": "systemd busctl is unavailable."})
        return 1
    if not argv:
        emit({"ok": False, "message": "No Bluetooth action was supplied."})
        return 2

    command = argv[0]

    if command == "toggle" and len(argv) == 3 and argv[2] in ("on", "off"):
        adapter_path = argv[1]
        if not valid_adapter(adapter_path):
            emit({"ok": False, "message": "Bluetooth adapter path is invalid."})
            return 2
        code, out, err = run(
            [
                "busctl",
                "--system",
                "set-property",
                BLUEZ,
                adapter_path,
                ADAPTER,
                "Powered",
                "b",
                "true" if argv[2] == "on" else "false",
            ],
            timeout=8.0,
        )
        ok = code == 0
        emit(
            {
                "ok": ok,
                "message": ("Bluetooth enabled." if argv[2] == "on" else "Bluetooth disabled.")
                if ok
                else friendly_error(err or out, "Couldn’t change Bluetooth state."),
            }
        )
        return 0 if ok else 1

    if command in ("scan-start", "scan-stop") and len(argv) == 2:
        adapter_path = argv[1]
        if not valid_adapter(adapter_path):
            emit({"ok": False, "message": "Bluetooth adapter path is invalid."})
            return 2
        method = "StartDiscovery" if command == "scan-start" else "StopDiscovery"
        code, out, err = busctl_call(adapter_path, ADAPTER, method, timeout=10.0)
        ok = code == 0
        emit(
            {
                "ok": ok,
                "message": ("Looking for nearby devices…" if command == "scan-start" else "Discovery stopped.")
                if ok
                else friendly_error(err or out, "Couldn’t change Bluetooth discovery."),
            }
        )
        return 0 if ok else 1

    if command in ("connect", "disconnect", "pair") and len(argv) == 2:
        device_path = argv[1]
        if not valid_device(device_path):
            emit({"ok": False, "message": "Bluetooth device path is invalid."})
            return 2
        method = {"connect": "Connect", "disconnect": "Disconnect", "pair": "Pair"}[command]
        timeout = 45.0 if command == "pair" else 18.0
        code, out, err = busctl_call(device_path, DEVICE, method, timeout=timeout)
        ok = code == 0
        if ok and command in ("connect", "disconnect"):
            remember_manual_connection(device_path, command == "connect")
        success = {"connect": "Connected.", "disconnect": "Disconnected.", "pair": "Paired."}[command]
        failure = {
            "connect": "Couldn’t connect to this device.",
            "disconnect": "Couldn’t disconnect this device.",
            "pair": "Pairing failed.",
        }[command]
        emit({"ok": ok, "message": success if ok else friendly_error(err or out, failure)})
        return 0 if ok else 1

    if command == "forget" and len(argv) == 3:
        adapter_path, device_path = argv[1], argv[2]
        if not valid_adapter(adapter_path) or not valid_device(device_path):
            emit({"ok": False, "message": "Bluetooth device path is invalid."})
            return 2
        if not device_path.startswith(adapter_path + "/dev_"):
            emit({"ok": False, "message": "Bluetooth device does not belong to this adapter."})
            return 2
        code, out, err = busctl_call(adapter_path, ADAPTER, "RemoveDevice", "o", device_path, timeout=12.0)
        ok = code == 0
        emit(
            {
                "ok": ok,
                "message": "Device forgotten." if ok else friendly_error(err or out, "Couldn’t forget this device."),
            }
        )
        return 0 if ok else 1

    emit({"ok": False, "message": "Unsupported Bluetooth action."})
    return 2


def main() -> int:
    if len(sys.argv) < 2:
        emit({"ok": False, "message": "Bluetooth command is required."})
        return 2
    if sys.argv[1] == "snapshot":
        return snapshot()
    if sys.argv[1] == "auto-connect":
        return auto_connect()
    if sys.argv[1] == "action":
        return action(sys.argv[2:])
    emit({"ok": False, "message": "Unknown Bluetooth command."})
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
