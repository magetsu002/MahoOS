#!/usr/bin/env python3

"""Thin BlueZ D-Bus adapter for Maho Link Bluetooth.

BlueZ remains authoritative. This module intentionally has no device database and
never invokes bluetoothctl. Structured ObjectManager snapshots are read through
busctl JSON and actions are sent directly to org.bluez D-Bus interfaces.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from typing import Any, Iterable, Iterator

BLUEZ = "org.bluez"
OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
BATTERY = "org.bluez.Battery1"
AGENT_MANAGER = "org.bluez.AgentManager1"
AGENT = "org.bluez.Agent1"
AGENT_PATH = "/org/maho/LinkPairingAgent"

ADAPTER_PATH_RE = re.compile(r"^/org/bluez/hci[0-9]+$")
DEVICE_PATH_RE = re.compile(r"^/org/bluez/hci[0-9]+/dev_[0-9A-Fa-f_]+$")
AUTOCONNECT_BACKOFF_SECONDS = (5, 15, 45, 120)
MAX_AUTOCONNECT_ATTEMPTS = len(AUTOCONNECT_BACKOFF_SECONDS)
RFKILL_CLASS = Path("/sys/class/rfkill")


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), flush=True)


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


def _read_rfkill_value(path: Path, fallback: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return fallback


def rfkill_devices(root: Path = RFKILL_CLASS) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        candidates = sorted(
            root.glob("rfkill*"),
            key=lambda item: int(item.name.removeprefix("rfkill"))
            if item.name.removeprefix("rfkill").isdigit() else 1_000_000,
        )
    except OSError:
        return rows

    for path in candidates:
        kind = _read_rfkill_value(path / "type").lower()
        if not kind:
            continue
        raw_id = path.name.removeprefix("rfkill")
        try:
            rfkill_id = int(raw_id)
        except ValueError:
            continue
        rows.append({
            "id": rfkill_id,
            "type": kind,
            "name": _read_rfkill_value(path / "name"),
            "softBlocked": _read_rfkill_value(path / "soft", "0") == "1",
            "hardBlocked": _read_rfkill_value(path / "hard", "0") == "1",
        })
    return rows


def rfkill_type_signature(kind: str, root: Path = RFKILL_CLASS) -> tuple[tuple[Any, ...], ...]:
    normalized = str(kind or "").strip().lower()
    return tuple(
        (row["id"], row["name"], row["softBlocked"], row["hardBlocked"])
        for row in rfkill_devices(root)
        if row["type"] == normalized
    )


def bluetooth_rfkill_state(root: Path = RFKILL_CLASS) -> dict[str, Any]:
    devices = [row for row in rfkill_devices(root) if row["type"] == "bluetooth"]
    if not devices:
        return {
            "available": False,
            "state": "unavailable",
            "softBlocked": False,
            "hardBlocked": False,
            "devices": [],
        }

    hard_blocked = any(bool(row["hardBlocked"]) for row in devices)
    soft_blocked = any(bool(row["softBlocked"]) for row in devices)
    state = "hard-blocked" if hard_blocked else "soft-blocked" if soft_blocked else "unblocked"
    return {
        "available": True,
        "state": state,
        "softBlocked": soft_blocked,
        "hardBlocked": hard_blocked,
        "devices": devices,
    }


def bluetooth_power_state(enabled: bool, rfkill: dict[str, Any]) -> str:
    if rfkill.get("hardBlocked"):
        return "hard-blocked"
    if rfkill.get("softBlocked"):
        return "soft-blocked"
    return "powered" if enabled else "powered-off"


def unavailable_snapshot(error: str) -> dict[str, Any]:
    return {
        "available": False,
        "enabled": False,
        "discovering": False,
        "adapterPath": "",
        "powerState": "unavailable",
        "powerActionable": False,
        "rfkillState": "unavailable",
        "softBlocked": False,
        "hardBlocked": False,
        "rfkillDevices": [],
        "paired": [],
        "availableDevices": [],
        "connected": [],
        "autoConnectEligible": [],
        "error": error,
    }


def merge_device_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate BlueZ objects by stable adapter/address identity."""
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = safe_string(row.get("address")).upper() or safe_string(row.get("path"))
        current = merged.get(identity)
        if current is None:
            merged[identity] = dict(row)
            continue

        def priority(candidate: dict[str, Any]) -> tuple[bool, bool, bool, bool]:
            return (
                bool(candidate.get("paired")),
                bool(candidate.get("bonded")),
                bool(candidate.get("connected")),
                bool(candidate.get("discovered")),
            )

        preferred, other = (row, current) if priority(row) > priority(current) else (current, row)
        combined = dict(preferred)
        for field in ("paired", "bonded", "trusted", "connected", "discovered"):
            combined[field] = bool(current.get(field)) or bool(row.get(field))
        if combined.get("rssi") is None and other.get("rssi") is not None:
            combined["rssi"] = other["rssi"]
            combined["quality"] = other.get("quality", "")
        combined["available"] = combined["connected"] or combined["discovered"]
        merged[identity] = combined
    return list(merged.values())


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
    rfkill = bluetooth_rfkill_state()
    power_state = bluetooth_power_state(enabled, rfkill)

    device_rows: list[dict[str, Any]] = []
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
        address = safe_string(property_value(props, "Address")).upper()
        paired_flag = bool(property_value(props, "Paired", False))
        bonded_flag = bool(property_value(props, "Bonded", False))
        connected_flag = bool(property_value(props, "Connected", False))
        trusted_flag = bool(property_value(props, "Trusted", False))
        rssi = property_value(props, "RSSI")
        discovered_flag = isinstance(rssi, (int, float))
        battery_props = interfaces.get(BATTERY)
        battery = None
        if isinstance(battery_props, dict):
            percentage = property_value(battery_props, "Percentage")
            try:
                battery = max(0, min(100, int(percentage)))
            except (TypeError, ValueError):
                battery = None

        reachable = connected_flag or discovered_flag
        row = {
            "path": path,
            "address": address,
            "name": name,
            "paired": paired_flag,
            "bonded": bonded_flag,
            "connected": connected_flag,
            "trusted": trusted_flag,
            "discovered": discovered_flag,
            "available": reachable,
            "type": type_label,
            "kind": kind,
            "icon": icon,
            "battery": battery,
            "rssi": int(rssi) if isinstance(rssi, (int, float)) else None,
            "quality": quality_from_rssi(rssi),
        }
        device_rows.append(row)

    paired: list[dict[str, Any]] = []
    nearby: list[dict[str, Any]] = []
    connected: list[dict[str, Any]] = []
    for row in merge_device_rows(device_rows):
        if row["paired"]:
            paired.append(row)
        elif enabled and row["discovered"]:
            nearby.append(row)
        if row["connected"]:
            connected.append(row)
        if (enabled and row["paired"] and row["trusted"] and not row["connected"]
                and row["available"] and row["kind"] in ("headphones", "speaker")):
            auto_connect_eligible.append(row["path"])

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
        "powerState": power_state,
        "powerActionable": not bool(rfkill.get("hardBlocked")),
        "rfkillState": str(rfkill.get("state") or "unavailable"),
        "softBlocked": bool(rfkill.get("softBlocked")),
        "hardBlocked": bool(rfkill.get("hardBlocked")),
        "rfkillDevices": rfkill.get("devices", []),
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
        (("service unknown", "name has no owner", "org.bluez was not provided",
          "the name org.bluez was not provided"),
         "Bluetooth service became unavailable."),
        (("unknown object", "does not exist", "unknownobject"),
         "Device is no longer available for pairing."),
        (("br-connection-unknown", "host is down", "no matching connection"),
         "Device is not reachable or not accepting a connection."),
        (("connectionattemptfailed", "connection attempt failed"), "Couldn’t connect to this device."),
        (("failed",), fallback),
    )
    for needles, message in mappings:
        if any(needle in lowered for needle in needles):
            return message
    return fallback



AGENT_XML = """<node>
  <interface name="org.bluez.Agent1">
    <method name="Release"/>
    <method name="RequestPinCode">
      <arg type="o" direction="in"/>
      <arg type="s" direction="out"/>
    </method>
    <method name="DisplayPinCode">
      <arg type="o" direction="in"/>
      <arg type="s" direction="in"/>
    </method>
    <method name="RequestPasskey">
      <arg type="o" direction="in"/>
      <arg type="u" direction="out"/>
    </method>
    <method name="DisplayPasskey">
      <arg type="o" direction="in"/>
      <arg type="u" direction="in"/>
      <arg type="q" direction="in"/>
    </method>
    <method name="RequestConfirmation">
      <arg type="o" direction="in"/>
      <arg type="u" direction="in"/>
    </method>
    <method name="RequestAuthorization">
      <arg type="o" direction="in"/>
    </method>
    <method name="AuthorizeService">
      <arg type="o" direction="in"/>
      <arg type="s" direction="in"/>
    </method>
    <method name="Cancel"/>
  </interface>
</node>"""


def normalize_pairing_response(kind: str, value: Any):
    if kind == "pin":
        pin = str(value or "").strip()
        if not pin or len(pin) > 16 or any(ord(char) < 32 for char in pin):
            return None, "PIN must contain 1 to 16 printable characters."
        return pin, ""
    if kind == "passkey":
        raw = str(value or "").strip()
        if not raw.isdigit() or len(raw) > 6:
            return None, "Passkey must be a number from 000000 to 999999."
        passkey = int(raw)
        if passkey < 0 or passkey > 999999:
            return None, "Passkey must be a number from 000000 to 999999."
        return passkey, ""
    if kind in ("confirm", "authorize", "authorize-service"):
        return None, ""
    return None, "Unsupported Bluetooth pairing response."


def confirm_paired(device_path: str, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while True:
        payload = snapshot_payload()
        if not payload.get("available"):
            return False, str(payload.get("error") or "Bluetooth service became unavailable.")
        for row in payload.get("paired", []):
            if row.get("path") == device_path and row.get("paired"):
                return True, ""
        if time.monotonic() >= deadline:
            return False, "BlueZ did not confirm the paired state."
        time.sleep(0.15)


class PairingAgentSession:
    def __init__(self, device_path: str):
        self.device_path = device_path
        self.connection = None
        self.loop = None
        self.Gio = None
        self.GLib = None
        self.registration_id = 0
        self.owner_subscription = 0
        self.agent_registered = False
        self.pending: dict[int, dict[str, Any]] = {}
        self.next_request_id = 1
        self.finished = False
        self.cancel_requested = False
        self.exit_code = 1

    def emit_event(self, payload: dict[str, Any]) -> None:
        emit(payload)

    def reject_pending(self, error_name: str, message: str) -> None:
        pending = list(self.pending.values())
        self.pending.clear()
        for request in pending:
            try:
                request["invocation"].return_dbus_error(error_name, message)
            except Exception:
                pass

    def prompt(self, kind: str, invocation: Any, device_path: str,
               *, value: str = "", service_uuid: str = "") -> None:
        if device_path != self.device_path:
            invocation.return_dbus_error(
                "org.bluez.Error.Rejected",
                "Maho Link only authorizes the device currently being paired.",
            )
            return
        request_id = self.next_request_id
        self.next_request_id += 1
        self.pending[request_id] = {
            "kind": kind,
            "invocation": invocation,
        }
        self.emit_event({
            "type": "prompt",
            "requestId": request_id,
            "kind": kind,
            "devicePath": device_path,
            "value": value,
            "serviceUuid": service_uuid,
        })

    def method_call(self, connection: Any, sender: str, object_path: str,
                    interface_name: str, method_name: str, parameters: Any,
                    invocation: Any) -> None:
        values = parameters.unpack() if parameters is not None else ()
        if method_name == "Release":
            self.reject_pending("org.bluez.Error.Canceled", "Pairing agent was released.")
            self.emit_event({"type": "agent-release"})
            invocation.return_value(None)
            self.finish(False, "Bluetooth pairing agent was released.")
            return

        if method_name == "RequestPinCode":
            self.prompt("pin", invocation, str(values[0]))
            return
        if method_name == "RequestPasskey":
            self.prompt("passkey", invocation, str(values[0]))
            return
        if method_name == "RequestConfirmation":
            self.prompt("confirm", invocation, str(values[0]),
                        value=f"{int(values[1]):06d}")
            return
        if method_name == "RequestAuthorization":
            self.prompt("authorize", invocation, str(values[0]))
            return
        if method_name == "AuthorizeService":
            self.prompt("authorize-service", invocation, str(values[0]),
                        service_uuid=str(values[1]))
            return

        if method_name == "DisplayPinCode":
            self.emit_event({
                "type": "display",
                "kind": "pin",
                "devicePath": str(values[0]),
                "value": str(values[1]),
            })
            invocation.return_value(None)
            return
        if method_name == "DisplayPasskey":
            self.emit_event({
                "type": "display",
                "kind": "passkey",
                "devicePath": str(values[0]),
                "value": f"{int(values[1]):06d}",
                "entered": int(values[2]),
            })
            invocation.return_value(None)
            return
        if method_name == "Cancel":
            self.reject_pending("org.bluez.Error.Canceled", "Pairing was cancelled.")
            self.emit_event({"type": "cancelled", "message": "Pairing was cancelled."})
            invocation.return_value(None)
            return

        invocation.return_dbus_error("org.bluez.Error.Rejected", "Unsupported pairing request.")

    def respond(self, payload: dict[str, Any]) -> bool:
        try:
            request_id = int(payload.get("requestId"))
        except (TypeError, ValueError):
            self.emit_event({"type": "input-error", "message": "Pairing response identity is invalid."})
            return False
        request = self.pending.get(request_id)
        if request is None:
            self.emit_event({"type": "input-error", "message": "That pairing request is no longer active."})
            return False

        action = str(payload.get("action") or "").lower()
        if action in ("reject", "cancel"):
            self.pending.pop(request_id, None)
            error_name = "org.bluez.Error.Canceled" if action == "cancel" else "org.bluez.Error.Rejected"
            request["invocation"].return_dbus_error(
                error_name,
                "Pairing was cancelled." if action == "cancel" else "Pairing was rejected.",
            )
            return True
        if action != "accept":
            self.emit_event({"type": "input-error", "message": "Pairing response action is invalid."})
            return False

        kind = str(request["kind"])
        normalized, error = normalize_pairing_response(kind, payload.get("value"))
        if error:
            self.emit_event({
                "type": "input-error",
                "requestId": request_id,
                "kind": kind,
                "message": error,
            })
            return False

        self.pending.pop(request_id, None)
        if kind == "pin":
            result = self.GLib.Variant("(s)", (normalized,))
        elif kind == "passkey":
            result = self.GLib.Variant("(u)", (normalized,))
        else:
            result = None
        request["invocation"].return_value(result)
        self.emit_event({"type": "accepted", "requestId": request_id, "kind": kind})
        return True

    def cancel_pairing_done(self, connection: Any, result: Any, user_data: Any) -> None:
        try:
            connection.call_finish(result)
        except Exception:
            pass

    def request_cancel(self) -> bool:
        if self.finished:
            return False
        self.cancel_requested = True
        self.reject_pending("org.bluez.Error.Canceled", "Pairing was cancelled.")
        self.emit_event({"type": "status", "message": "Cancelling pairing…"})
        try:
            self.connection.call(
                BLUEZ,
                self.device_path,
                DEVICE,
                "CancelPairing",
                None,
                None,
                self.Gio.DBusCallFlags.NONE,
                5000,
                None,
                self.cancel_pairing_done,
                None,
            )
        except Exception:
            pass
        return False

    def handle_control(self, payload: dict[str, Any]) -> bool:
        action = str(payload.get("action") or "").lower()
        if action == "cancel-session":
            return self.request_cancel()
        self.respond(payload)
        return False

    def stdin_reader(self) -> None:
        for line in sys.stdin:
            try:
                payload = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                self.emit_event({"type": "input-error", "message": "Pairing response was invalid."})
                continue
            if not isinstance(payload, dict):
                self.emit_event({"type": "input-error", "message": "Pairing response was invalid."})
                continue
            self.GLib.idle_add(self.handle_control, payload)
        if not self.finished:
            self.GLib.idle_add(self.request_cancel)

    def owner_changed(self, connection: Any, sender_name: str, object_path: str,
                      interface_name: str, signal_name: str, parameters: Any,
                      user_data: Any) -> None:
        name, old_owner, new_owner = parameters.unpack()
        if name == BLUEZ and old_owner and not new_owner:
            self.reject_pending("org.bluez.Error.Canceled", "Bluetooth service became unavailable.")
            self.finish(False, "Bluetooth service became unavailable.")

    def finish(self, ok: bool, message: str) -> None:
        if self.finished:
            return
        self.finished = True
        if not ok:
            self.reject_pending("org.bluez.Error.Canceled", message)
        self.exit_code = 0 if ok else 1
        self.emit_event({"type": "result", "ok": ok, "message": message})
        if self.loop is not None:
            self.loop.quit()

    def pair_done(self, connection: Any, result: Any, user_data: Any) -> None:
        try:
            connection.call_finish(result)
        except Exception as exc:
            message = "Pairing was cancelled." if self.cancel_requested else friendly_error(
                str(exc), "Pairing failed.")
            self.finish(False, message)
            return

        if self.cancel_requested:
            self.finish(False, "Pairing was cancelled.")
            return
        paired, error = confirm_paired(self.device_path)
        self.finish(paired, "Paired." if paired else error)

    def run(self) -> int:
        try:
            import gi

            gi.require_version("Gio", "2.0")
            gi.require_version("GLib", "2.0")
            from gi.repository import Gio, GLib
        except (ImportError, ValueError) as exc:
            self.emit_event({
                "type": "result",
                "ok": False,
                "message": "Bluetooth pairing support is unavailable: " + str(exc),
            })
            return 1

        self.Gio = Gio
        self.GLib = GLib
        self.loop = GLib.MainLoop()

        try:
            self.connection = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            node = Gio.DBusNodeInfo.new_for_xml(AGENT_XML)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                self.registration_id = self.connection.register_object(
                    AGENT_PATH, node.interfaces[0], self.method_call, None, None)
            if not self.registration_id:
                raise RuntimeError("Could not export the Bluetooth pairing agent.")

            self.connection.call_sync(
                BLUEZ,
                "/org/bluez",
                AGENT_MANAGER,
                "RegisterAgent",
                GLib.Variant("(os)", (AGENT_PATH, "KeyboardDisplay")),
                None,
                Gio.DBusCallFlags.NONE,
                5000,
                None,
            )
            self.agent_registered = True
            self.owner_subscription = self.connection.signal_subscribe(
                "org.freedesktop.DBus",
                "org.freedesktop.DBus",
                "NameOwnerChanged",
                "/org/freedesktop/DBus",
                BLUEZ,
                Gio.DBusSignalFlags.NONE,
                self.owner_changed,
                None,
            )
            self.emit_event({
                "type": "ready",
                "devicePath": self.device_path,
                "capability": "KeyboardDisplay",
            })

            threading.Thread(target=self.stdin_reader, daemon=True).start()
            self.connection.call(
                BLUEZ,
                self.device_path,
                DEVICE,
                "Pair",
                None,
                None,
                Gio.DBusCallFlags.NONE,
                60000,
                None,
                self.pair_done,
                None,
            )
            self.loop.run()
        except Exception as exc:
            if not self.finished:
                self.finish(False, friendly_error(str(exc), "Pairing could not start."))
        finally:
            if self.connection is not None and self.owner_subscription:
                try:
                    self.connection.signal_unsubscribe(self.owner_subscription)
                except Exception:
                    pass
            if self.connection is not None and self.agent_registered:
                try:
                    self.connection.call_sync(
                        BLUEZ,
                        "/org/bluez",
                        AGENT_MANAGER,
                        "UnregisterAgent",
                        GLib.Variant("(o)", (AGENT_PATH,)),
                        None,
                        Gio.DBusCallFlags.NONE,
                        3000,
                        None,
                    )
                except Exception:
                    pass
            if self.connection is not None and self.registration_id:
                try:
                    self.connection.unregister_object(self.registration_id)
                except Exception:
                    pass
        return self.exit_code


def pair_session(device_path: str) -> int:
    if not valid_device(device_path):
        emit({"type": "result", "ok": False, "message": "Bluetooth device path is invalid."})
        return 2
    return PairingAgentSession(device_path).run()


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


def auto_connect_lock_path() -> Path:
    return session_state_path().with_name("link-bluetooth-auto-connect.lock")


@contextmanager
def connection_operation(*, blocking: bool) -> Iterator[bool]:
    """Serialize every connect/disconnect sequence across Maho processes."""
    lock_path = auto_connect_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path.parent.chmod(0o700)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(descriptor, flags)
            acquired = True
        except BlockingIOError:
            acquired = False
        yield acquired
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


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


def device_from_snapshot(device_path: str) -> dict[str, Any] | None:
    payload = snapshot_payload()
    for row in payload.get("paired", []):
        if row.get("path") == device_path:
            return row
    return None


def wait_for_connected(device_path: str, expected: bool, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        device = device_from_snapshot(device_path)
        if device is None:
            return False
        if bool(device.get("connected")) is expected:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


def auto_connect_locked() -> int:
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
    if code == 0 and wait_for_connected(path, True, 15.0):
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
    message = (
        "Bluetooth did not confirm the connection state."
        if code == 0
        else friendly_error(err or out, "Couldn’t connect to this device.")
    )
    emit({
        "ok": False,
        "status": "backoff",
        "devicePath": path,
        "message": message,
        "retryAfter": delay,
        "attempt": failures,
    })
    return 1


def auto_connect() -> int:
    """Run one policy evaluation without racing another Maho surface."""
    with connection_operation(blocking=False) as acquired:
        if not acquired:
            emit({"ok": True, "status": "busy", "devicePath": "", "message": ""})
            return 0
        return auto_connect_locked()


def wait_for_adapter_power(adapter_path: str, expected: bool, timeout: float = 4.0) -> tuple[bool, dict[str, Any]]:
    deadline = time.monotonic() + timeout
    last = snapshot_payload()
    while True:
        if not last.get("available") or last.get("adapterPath") != adapter_path:
            return False, last
        if bool(last.get("enabled")) is expected:
            return True, last
        if time.monotonic() >= deadline:
            return False, last
        time.sleep(0.15)
        last = snapshot_payload()


def wait_for_bluetooth_unblocked(timeout: float = 2.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last = bluetooth_rfkill_state()
    while last.get("softBlocked") and not last.get("hardBlocked"):
        if time.monotonic() >= deadline:
            break
        time.sleep(0.10)
        last = bluetooth_rfkill_state()
    return last


def power_state_message(payload: dict[str, Any], fallback: str) -> str:
    state = str(payload.get("powerState") or "")
    if state == "hard-blocked":
        return "Bluetooth is blocked by a hardware switch or firmware."
    if state == "soft-blocked":
        return "Bluetooth remains software-blocked."
    if state == "unavailable":
        return str(payload.get("error") or "Bluetooth adapter is unavailable.")
    return fallback


def set_adapter_power(adapter_path: str, enabled: bool) -> int:
    if not valid_adapter(adapter_path):
        emit({"ok": False, "message": "Bluetooth adapter path is invalid.", "powerState": "unavailable"})
        return 2

    before = snapshot_payload()
    if not before.get("available") or before.get("adapterPath") != adapter_path:
        emit({
            "ok": False,
            "message": str(before.get("error") or "Bluetooth adapter is unavailable."),
            "powerState": str(before.get("powerState") or "unavailable"),
        })
        return 1

    if enabled and bool(before.get("hardBlocked")):
        emit({
            "ok": False,
            "message": "Bluetooth is blocked by a hardware switch or firmware.",
            "powerState": "hard-blocked",
            "rfkillState": str(before.get("rfkillState") or "hard-blocked"),
        })
        return 1

    if bool(before.get("enabled")) is enabled and not (enabled and bool(before.get("softBlocked"))):
        emit({
            "ok": True,
            "message": "Bluetooth enabled." if enabled else "Bluetooth disabled.",
            "powerState": str(before.get("powerState") or ("powered" if enabled else "powered-off")),
            "rfkillState": str(before.get("rfkillState") or "unavailable"),
        })
        return 0

    if enabled and bool(before.get("softBlocked")):
        if not shutil.which("rfkill"):
            emit({
                "ok": False,
                "message": "Bluetooth is software-blocked and rfkill is unavailable.",
                "powerState": "soft-blocked",
                "rfkillState": "soft-blocked",
            })
            return 1

        wifi_before = rfkill_type_signature("wlan")
        code, out, err = run(["rfkill", "unblock", "bluetooth"], timeout=5.0)
        after_rfkill = (
            wait_for_bluetooth_unblocked()
            if code == 0 else bluetooth_rfkill_state()
        )
        wifi_after = rfkill_type_signature("wlan")

        if wifi_after != wifi_before:
            emit({
                "ok": False,
                "message": "Bluetooth unblock did not preserve Wi-Fi rfkill state.",
                "powerState": bluetooth_power_state(False, after_rfkill),
                "rfkillState": str(after_rfkill.get("state") or "unavailable"),
            })
            return 1
        if code != 0:
            emit({
                "ok": False,
                "message": friendly_error(err or out, "Couldn’t clear the Bluetooth software block."),
                "powerState": bluetooth_power_state(False, after_rfkill),
                "rfkillState": str(after_rfkill.get("state") or "unavailable"),
            })
            return 1
        if after_rfkill.get("hardBlocked"):
            emit({
                "ok": False,
                "message": "Bluetooth is blocked by a hardware switch or firmware.",
                "powerState": "hard-blocked",
                "rfkillState": "hard-blocked",
            })
            return 1
        if after_rfkill.get("softBlocked"):
            emit({
                "ok": False,
                "message": "Bluetooth remains software-blocked.",
                "powerState": "soft-blocked",
                "rfkillState": "soft-blocked",
            })
            return 1

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
            "true" if enabled else "false",
        ],
        timeout=8.0,
    )
    if code != 0:
        observed = snapshot_payload()
        emit({
            "ok": False,
            "message": power_state_message(observed, friendly_error(
                err or out, "Couldn’t change Bluetooth state.")),
            "powerState": str(observed.get("powerState") or "unavailable"),
            "rfkillState": str(observed.get("rfkillState") or "unavailable"),
        })
        return 1

    confirmed, observed = wait_for_adapter_power(adapter_path, enabled)
    if not confirmed:
        emit({
            "ok": False,
            "message": power_state_message(
                observed,
                "BlueZ did not confirm the Bluetooth power state.",
            ),
            "powerState": str(observed.get("powerState") or "unavailable"),
            "rfkillState": str(observed.get("rfkillState") or "unavailable"),
        })
        return 1

    emit({
        "ok": True,
        "message": "Bluetooth enabled." if enabled else "Bluetooth disabled.",
        "powerState": str(observed.get("powerState") or ("powered" if enabled else "powered-off")),
        "rfkillState": str(observed.get("rfkillState") or "unavailable"),
    })
    return 0


def reconnect_device(device_path: str) -> int:
    if not valid_device(device_path):
        emit({"ok": False, "message": "Bluetooth device path is invalid."})
        return 2

    device = device_from_snapshot(device_path)
    if device is None or not device.get("paired") or not device.get("connected"):
        emit({"ok": False, "message": "This Bluetooth device is not currently connected."})
        return 1

    code, out, err = busctl_call(device_path, DEVICE, "Disconnect", timeout=12.0)
    if code != 0:
        emit({"ok": False, "message": friendly_error(err or out, "Couldn’t disconnect this device.")})
        return 1
    if not wait_for_connected(device_path, False, 8.0):
        emit({"ok": False, "message": "Bluetooth did not confirm the disconnect."})
        return 1

    code, out, err = busctl_call(device_path, DEVICE, "Connect", timeout=18.0)
    if code != 0:
        emit({"ok": False, "message": friendly_error(err or out, "Couldn’t reconnect this device.")})
        return 1
    if not wait_for_connected(device_path, True, 15.0):
        emit({"ok": False, "message": "Bluetooth did not confirm the reconnection."})
        return 1

    remember_manual_connection(device_path, True)
    emit({"ok": True, "message": "Reconnected."})
    return 0


def action(argv: list[str]) -> int:
    if not shutil.which("busctl"):
        emit({"ok": False, "message": "systemd busctl is unavailable."})
        return 1
    if not argv:
        emit({"ok": False, "message": "No Bluetooth action was supplied."})
        return 2

    command = argv[0]

    if command == "reconnect" and len(argv) == 2:
        with connection_operation(blocking=True):
            return reconnect_device(argv[1])

    if command == "toggle" and len(argv) == 3 and argv[2] in ("on", "off"):
        return set_adapter_power(argv[1], argv[2] == "on")

    if command in ("scan-start", "scan-stop") and len(argv) == 2:
        adapter_path = argv[1]
        if not valid_adapter(adapter_path):
            emit({"ok": False, "message": "Bluetooth adapter path is invalid."})
            return 2
        method = "StartDiscovery" if command == "scan-start" else "StopDiscovery"
        code, out, err = busctl_call(adapter_path, ADAPTER, method, timeout=10.0)
        ok = code == 0
        emit({
            "ok": ok,
            "message": ("Looking for nearby devices…" if command == "scan-start" else "Discovery stopped.")
            if ok else friendly_error(err or out, "Couldn’t change Bluetooth discovery."),
        })
        return 0 if ok else 1

    if command in ("connect", "disconnect") and len(argv) == 2:
        device_path = argv[1]
        if not valid_device(device_path):
            emit({"ok": False, "message": "Bluetooth device path is invalid."})
            return 2
        method = {"connect": "Connect", "disconnect": "Disconnect"}[command]
        expected_connected = command == "connect"
        with connection_operation(blocking=True):
            code, out, err = busctl_call(device_path, DEVICE, method, timeout=18.0)
            ok = code == 0 and wait_for_connected(device_path, expected_connected, 15.0)
            if ok:
                remember_manual_connection(device_path, expected_connected)
        success = {"connect": "Connected.", "disconnect": "Disconnected."}[command]
        failure = {
            "connect": "Couldn’t connect to this device.",
            "disconnect": "Couldn’t disconnect this device.",
        }[command]
        if ok:
            message = success
        elif code == 0:
            message = "Bluetooth did not confirm the connection state."
        else:
            message = friendly_error(err or out, failure)
        emit({"ok": ok, "message": message})
        return 0 if ok else 1

    if command == "pair" and len(argv) == 2:
        device_path = argv[1]
        if not valid_device(device_path):
            emit({"ok": False, "message": "Bluetooth device path is invalid."})
            return 2
        code, out, err = busctl_call(device_path, DEVICE, "Pair", timeout=45.0)
        if code != 0:
            emit({"ok": False, "message": friendly_error(err or out, "Pairing failed.")})
            return 1
        paired, confirm_error = confirm_paired(device_path)
        emit({
            "ok": paired,
            "message": "Paired." if paired else (confirm_error or "BlueZ did not confirm the paired state."),
        })
        return 0 if paired else 1

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
        emit({
            "ok": ok,
            "message": "Device forgotten." if ok else friendly_error(err or out, "Couldn’t forget this device."),
        })
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
    if sys.argv[1] == "pair-session" and len(sys.argv) == 3:
        return pair_session(sys.argv[2])
    if sys.argv[1] == "action":
        return action(sys.argv[2:])
    emit({"ok": False, "message": "Unknown Bluetooth command."})
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
