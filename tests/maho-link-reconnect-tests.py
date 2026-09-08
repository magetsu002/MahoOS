#!/usr/bin/env python3

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest import mock

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
PROFILE_UUID = "11111111-2222-3333-4444-555555555555"
OTHER_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


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
        "uuid": PROFILE_UUID,
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
        ["nmcli", "--wait", "15", "connection", "down", "uuid", PROFILE_UUID],
        ["nmcli", "--wait", "20", "connection", "up", "uuid", PROFILE_UUID, "ifname", "wlan0"],
    ]

    # NetworkManager must confirm the down transition before the exact saved
    # profile is reactivated; credentials are never rebuilt or passed on argv.
    wifi_calls.clear()
    wifi_states = iter([active_profile, active_profile])
    WIFI.active_connection = lambda _device: next(wifi_states)
    result, response = invoke(WIFI.reconnect_current)
    assert result == 1
    assert response["message"] == "NetworkManager did not confirm the Wi-Fi disconnect."
    assert len(wifi_calls) == 1 and "down" in wifi_calls[0]

    # Profile names are not unique NetworkManager identities. A different UUID
    # with the same human-readable name must not satisfy reconnect verification.
    wifi_calls.clear()
    wrong_profile = dict(active_profile)
    wrong_profile["uuid"] = OTHER_UUID
    wifi_states = iter([active_profile, None, wrong_profile])
    WIFI.active_connection = lambda _device: next(wifi_states)
    result, response = invoke(WIFI.reconnect_current)
    assert result == 1
    assert response["message"] == "NetworkManager did not confirm the Wi-Fi reconnection."
    assert wifi_calls == [
        ["nmcli", "--wait", "15", "connection", "down", "uuid", PROFILE_UUID],
        ["nmcli", "--wait", "20", "connection", "up", "uuid", PROFILE_UUID, "ifname", "wlan0"],
    ]

    # A password typed for an already-saved network must replace the stored
    # secret before activation. Otherwise nmcli --ask silently reuses it.
    wifi_calls.clear()
    replaced = []
    WIFI.matching_security = lambda _ssid: {
        "ssid": "School Wi-Fi", "enterprise": False
    }
    with mock.patch.object(
        WIFI,
        "replace_saved_psk",
        side_effect=lambda ssid, password: (
            replaced.append((ssid, password)) or (PROFILE_UUID, "")
        ),
    ):
        with mock.patch.object(sys, "stdin", io.StringIO("new-password\n")):
            result, response = invoke(WIFI.action, ["connect", "School Wi-Fi"])
    assert result == 0
    assert response == {"ok": True, "message": "Connected to School Wi-Fi."}
    assert replaced == [("School Wi-Fi", "new-password")]
    assert wifi_calls == [[
        "nmcli", "--wait", "20", "connection", "up", "uuid", PROFILE_UUID,
        "ifname", "wlan0",
    ]]
    assert all("new-password" not in argument for call in wifi_calls for argument in call)

    # libnm Python bindings are optional. Their absence must preserve the
    # existing stdin-only nmcli connection path instead of making Wi-Fi fail.
    real_import = __import__

    def import_without_gi(name, *args, **kwargs):
        if name == "gi" or name.startswith("gi."):
            raise ImportError("gi unavailable for test")
        return real_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=import_without_gi):
        assert WIFI.replace_saved_psk("Unsaved Wi-Fi", "secret") == ("", "")

print("PASS  Bluetooth confirmation and Wi-Fi reconnect use exact confirmed state")
