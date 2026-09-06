#!/usr/bin/env python3

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BLUETOOTH = load("maho_link_bluetooth_reconnect", ROOT / "config/quickshell/maho-link/bluetooth.py")
WIFI = load("maho_link_wifi_reconnect", ROOT / "config/quickshell/maho-link/wifi.py")
DEVICE = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01"


def invoke(function, *args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = function(*args)
    return result, json.loads(output.getvalue())


with tempfile.TemporaryDirectory() as temporary:
    os.environ["XDG_RUNTIME_DIR"] = temporary
    bluetooth_calls = []
    device_states = iter([
        {"path": DEVICE, "paired": True, "connected": True},
        {"path": DEVICE, "paired": True, "connected": False},
        {"path": DEVICE, "paired": True, "connected": True},
    ])
    BLUETOOTH.device_from_snapshot = lambda path: next(device_states)
    BLUETOOTH.shutil.which = lambda _name: "/usr/bin/busctl"
    BLUETOOTH.busctl_call = lambda path, interface, method, *args, timeout=12.0: (
        bluetooth_calls.append((path, interface, method, timeout)) or (0, "", "")
    )
    BLUETOOTH.time.sleep = lambda _seconds: None

    result, response = invoke(BLUETOOTH.action, ["reconnect", DEVICE])
    assert result == 0 and response == {"ok": True, "message": "Reconnected."}
    assert [call[2] for call in bluetooth_calls] == ["Disconnect", "Connect"]
    assert DEVICE not in BLUETOOTH.load_session_state()["suppressed"]

    # A Connect request is never sent until authoritative state confirms the
    # disconnect. This is a failure, not optimistic success.
    bluetooth_calls.clear()
    BLUETOOTH.device_from_snapshot = lambda path: {
        "path": DEVICE, "paired": True, "connected": True
    }
    BLUETOOTH.wait_for_connected = lambda path, expected, timeout: False
    result, response = invoke(BLUETOOTH.action, ["reconnect", DEVICE])
    assert result == 1
    assert response["message"] == "Bluetooth did not confirm the disconnect."
    assert [call[2] for call in bluetooth_calls] == ["Disconnect"]
    assert DEVICE not in BLUETOOTH.load_session_state()["suppressed"]

    # Failure releases the shared operation lock and cannot poison a later
    # explicit Connect. Manual actions and the session auto-connect worker use
    # the same lock, so they serialize instead of sending duplicate requests.
    bluetooth_calls.clear()
    BLUETOOTH.wait_for_connected = lambda path, expected, timeout: True
    result, response = invoke(BLUETOOTH.action, ["connect", DEVICE])
    assert result == 0 and response == {"ok": True, "message": "Connected."}
    assert [call[2] for call in bluetooth_calls] == ["Connect"]
    assert DEVICE not in BLUETOOTH.load_session_state()["suppressed"]
    assert BLUETOOTH.friendly_error(
        "org.bluez.Error.Failed br-connection-unknown", "fallback"
    ) == "Device is not reachable or not accepting a connection."

    wifi_calls = []
    active_profile = {
        "profile": "Home profile",
        "device": "wlan0",
        "ssid": "Home Wi-Fi",
    }
    wifi_states = iter([active_profile, None, active_profile])
    WIFI.shutil.which = lambda _name: "/usr/bin/nmcli"
    WIFI.wifi_device = lambda: "wlan0"
    WIFI.active_connection = lambda _device: next(wifi_states)
    WIFI.run = lambda args, **kwargs: (wifi_calls.append(list(args)) or (0, "", ""))

    result, response = invoke(WIFI.reconnect_current)
    assert result == 0
    assert response == {"ok": True, "message": "Reconnected to Home Wi-Fi."}
    assert wifi_calls == [
        ["nmcli", "--wait", "15", "connection", "down", "id", "Home profile"],
        ["nmcli", "--wait", "20", "connection", "up", "id", "Home profile", "ifname", "wlan0"],
    ]

    # NetworkManager must confirm the down transition before the saved profile
    # is reactivated; credentials are never rebuilt or passed on argv.
    wifi_calls.clear()
    wifi_states = iter([active_profile, active_profile])
    WIFI.active_connection = lambda _device: next(wifi_states)
    result, response = invoke(WIFI.reconnect_current)
    assert result == 1
    assert response["message"] == "NetworkManager did not confirm the Wi-Fi disconnect."
    assert len(wifi_calls) == 1 and "down" in wifi_calls[0]

print("PASS  Bluetooth and Wi-Fi reconnect use confirmed disconnect/reconnect state")
