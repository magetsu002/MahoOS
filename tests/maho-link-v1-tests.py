#!/usr/bin/env python3

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LINK = ROOT / "config/quickshell/maho-link"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


WIFI = load("maho_link_wifi_v1", LINK / "wifi.py")
BLUETOOTH = load("maho_link_bluetooth_v1", LINK / "bluetooth.py")

HOME_UUID = "11111111-2222-3333-4444-555555555555"
CORP_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ADAPTER = "/org/bluez/hci0"
DEVICE = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01"


def invoke(function, *args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = function(*args)
    return result, json.loads(output.getvalue())


# Missing authorities must be explicit UNKNOWN/unavailable state, never cached
# healthy-looking state.
with mock.patch.object(WIFI.shutil, "which", return_value=None):
    result, payload = invoke(WIFI.snapshot)
assert result == 0
assert payload["available"] is False
assert payload["current"] is None
assert payload["networks"] == []
assert payload["saved"] == []
assert payload["ethernet"]["available"] is False
assert payload["connectivity"]["state"] == "unknown"

with mock.patch.object(BLUETOOTH.shutil, "which", return_value=None):
    payload = BLUETOOTH.snapshot_payload()
assert payload["available"] is False
assert payload["paired"] == []
assert payload["connected"] == []


# WPA/WPA2/WPA3 remain NetworkManager-owned. Link only classifies the scan
# security string and does not implement a parallel supplicant policy.
assert WIFI.security_info("WPA2") == {
    "security": "WPA2", "secured": True, "enterprise": False
}
assert WIFI.security_info("WPA3 SAE") == {
    "security": "WPA3 SAE", "secured": True, "enterprise": False
}
assert WIFI.security_info("WPA2 802.1X")["enterprise"] is True
assert WIFI.security_info("--")["secured"] is False


def saved_profile_run(args, **_kwargs):
    command = list(args)
    if command[-2:] == ["connection", "show"]:
        return 0, (
            f"Home:{HOME_UUID}:802-11-wireless:10:yes:no:\n"
            f"Corp:{CORP_UUID}:802-11-wireless:20:yes:no:"
        ), ""
    if command[-2:] == ["uuid", HOME_UUID]:
        return 0, (
            "connection.id:Home\n"
            f"connection.uuid:{HOME_UUID}\n"
            "connection.autoconnect:yes\n"
            "802-11-wireless.ssid:Home\n"
            "802-11-wireless-security.key-mgmt:wpa-psk"
        ), ""
    if command[-2:] == ["uuid", CORP_UUID]:
        return 0, (
            "connection.id:Corp\n"
            f"connection.uuid:{CORP_UUID}\n"
            "connection.autoconnect:yes\n"
            "802-11-wireless.ssid:Corp\n"
            "802-11-wireless-security.key-mgmt:wpa-eap\n"
            "802-1x.eap:peap"
        ), ""
    raise AssertionError(f"unexpected nmcli call: {command}")


with mock.patch.object(WIFI, "run", side_effect=saved_profile_run):
    profiles = WIFI.saved_wifi_profiles()
assert [row["ssid"] for row in profiles] == ["Corp", "Home"]
assert profiles[0]["enterprise"] is True
assert profiles[0]["eap"] == "peap"
assert profiles[1]["security"] == "WPA-PSK"


# A saved profile remains visible even when it is not in the current scan.
scan_profiles = [dict(profiles[0])]
with mock.patch.object(
    WIFI,
    "run",
    return_value=(0, ":Cafe:70:WPA2:5180", ""),
):
    networks, current = WIFI.scan_networks(
        True, rescan="no", saved_profiles=scan_profiles
    )
assert current is None
assert [row["ssid"] for row in networks] == ["Cafe", "Corp"]
assert networks[0]["available"] is True
assert networks[1]["saved"] is True
assert networks[1]["available"] is False
assert networks[1]["profileUuid"] == CORP_UUID


def wired_run(args, **_kwargs):
    command = list(args)
    joined = " ".join(command)
    if "DEVICE,TYPE,STATE,CONNECTION" in joined:
        return 0, "wlan0:wifi:connected:Home\nenp3s0:ethernet:connected:Wired", ""
    if command[-3:] == ["connection", "show", "--active"]:
        return 0, (
            f"Home:{HOME_UUID}:802-11-wireless:wlan0\n"
            f"Wired:{CORP_UUID}:802-3-ethernet:enp3s0"
        ), ""
    if command[-3:] == ["device", "show", "enp3s0"]:
        return 0, "IP4.ADDRESS[1]:10.10.0.5/24\nIP4.GATEWAY:10.10.0.1", ""
    if command == ["nmcli", "-t", "-f", "CONNECTIVITY", "general"]:
        return 0, "portal", ""
    raise AssertionError(f"unexpected nmcli call: {command}")


with mock.patch.object(WIFI, "run", side_effect=wired_run):
    wired = WIFI.ethernet_snapshot()
    connectivity = WIFI.connectivity_snapshot()
assert wired["available"] is True
assert wired["connected"] is True
assert wired["device"] == "enp3s0"
assert wired["uuid"] == CORP_UUID
assert wired["ipv4"] == "10.10.0.5/24"
assert connectivity["captivePortal"] is True
assert connectivity["loginAvailable"] is True

with mock.patch.object(
    WIFI,
    "run",
    return_value=(0, "enp3s0:ethernet:unavailable:--", ""),
):
    wired_unavailable = WIFI.ethernet_snapshot()
assert wired_unavailable["available"] is True
assert wired_unavailable["connected"] is False
assert wired_unavailable["state"] == "Unavailable"


# Enterprise profile creation carries only non-secret fields on argv.
enterprise_calls = []


def enterprise_profile_run(args, **kwargs):
    enterprise_calls.append((list(args), kwargs.get("stdin_text")))
    command = list(args)
    if command[1:3] == ["connection", "add"]:
        return 0, "", ""
    if command[1:4] == ["-g", "connection.uuid", "connection"]:
        return 0, CORP_UUID, ""
    raise AssertionError(f"unexpected enterprise profile call: {command}")


with mock.patch.object(WIFI, "wifi_device", return_value="wlan0"), mock.patch.object(
    WIFI, "run", side_effect=enterprise_profile_run
):
    profile_uuid, error = WIFI.create_enterprise_profile(
        "Corp",
        {
            "identity": "student@example.com",
            "eap": "peap",
            "phase2": "mschapv2",
            "domainSuffix": "example.com",
        },
    )
assert error == ""
assert profile_uuid == CORP_UUID
create_argv = enterprise_calls[0][0]
assert "wpa-eap" in create_argv
assert "peap" in create_argv
assert "student@example.com" in create_argv
assert "example.com" in create_argv


# When libnm can persist the secret, enterprise activation contains no secret
# in argv or stdin and exact NetworkManager UUID confirmation is required.
activation_calls = []


def enterprise_activation_run(args, **kwargs):
    activation_calls.append((list(args), kwargs.get("stdin_text")))
    return 0, "", ""


with mock.patch.object(
    WIFI, "create_enterprise_profile", return_value=(CORP_UUID, "")
), mock.patch.object(
    WIFI, "persist_enterprise_secrets", return_value=(True, "")
), mock.patch.object(
    WIFI, "wifi_device", return_value="wlan0"
), mock.patch.object(
    WIFI,
    "active_connection",
    return_value={"uuid": CORP_UUID, "ssid": "Corp", "profile": "Corp"},
), mock.patch.object(
    WIFI, "finalize_enterprise_profile", return_value=(True, "")
), mock.patch.object(
    WIFI, "cleanup_enterprise_profile"
) as enterprise_cleanup, mock.patch.object(
    WIFI, "run", side_effect=enterprise_activation_run
):
    result, response = invoke(
        WIFI.connect_enterprise,
        "Corp",
        {
            "identity": "student@example.com",
            "password": "super-secret",
            "eap": "peap",
            "phase2": "mschapv2",
        },
    )
assert result == 0
assert response["ok"] is True
enterprise_cleanup.assert_not_called()
assert all(
    "super-secret" not in argument
    for argv, _stdin in activation_calls
    for argument in argv
)
assert all(stdin is None for _argv, stdin in activation_calls)


# Without secure libnm secret persistence, newly authored enterprise
# profiles fail closed and the provisional UUID is removed before activation.
activation_calls.clear()
with mock.patch.object(
    WIFI, "create_enterprise_profile", return_value=(CORP_UUID, "")
), mock.patch.object(
    WIFI, "persist_enterprise_secrets", return_value=(False, "secure store unavailable")
), mock.patch.object(
    WIFI, "cleanup_enterprise_profile"
) as enterprise_cleanup, mock.patch.object(
    WIFI, "run", side_effect=enterprise_activation_run
):
    result, response = invoke(
        WIFI.connect_enterprise,
        "Corp",
        {
            "identity": "student@example.com",
            "password": "fallback-secret",
            "eap": "ttls",
            "phase2": "pap",
            "domainSuffix": "example.com",
        },
    )
assert result == 1
assert response["ok"] is False
enterprise_cleanup.assert_called_once_with(CORP_UUID)
assert activation_calls == []


# Saved-profile mutation is exact-UUID bounded. Active profiles cannot be
# forgotten behind NetworkManager's back.
with mock.patch.object(WIFI, "wifi_device", return_value="wlan0"), mock.patch.object(
    WIFI,
    "active_connection",
    return_value={"uuid": HOME_UUID, "ssid": "Home", "profile": "Home"},
):
    result, response = invoke(WIFI.forget_saved_profile, HOME_UUID)
assert result == 1
assert response["message"] == "Disconnect this Wi-Fi network before forgetting it."


portal_calls = []
with mock.patch.object(WIFI.shutil, "which", return_value="/usr/bin/xdg-open"), mock.patch.object(
    WIFI,
    "run",
    side_effect=lambda args, **kwargs: (
        portal_calls.append(list(args)) or (0, "", "")
    ),
):
    result, response = invoke(WIFI.open_captive_portal)
assert result == 0 and response["ok"] is True
assert portal_calls == [["xdg-open", "http://neverssl.com/"]]


# BlueZ remains the device database and exposes paired/trusted/connected truth,
# device class/name, RSSI and battery when present.
objects = {
    ADAPTER: {
        BLUETOOTH.ADAPTER: {
            "Powered": True,
            "Discovering": False,
        }
    },
    DEVICE: {
        BLUETOOTH.DEVICE: {
            "Adapter": ADAPTER,
            "Alias": "Headset",
            "Address": "AA:BB:CC:DD:EE:01",
            "Icon": "audio-headset",
            "Paired": True,
            "Bonded": True,
            "Trusted": True,
            "Connected": True,
            "RSSI": -52,
        },
        BLUETOOTH.BATTERY: {"Percentage": 77},
    },
}
with mock.patch.object(BLUETOOTH, "managed_objects", return_value=(objects, "")):
    bluetooth = BLUETOOTH.snapshot_payload()
assert bluetooth["available"] is True
assert bluetooth["enabled"] is True
assert len(bluetooth["paired"]) == 1
device = bluetooth["paired"][0]
assert device["name"] == "Headset"
assert device["kind"] == "headphones"
assert device["trusted"] is True
assert device["connected"] is True
assert device["battery"] == 77


# Link observes the authorities; it must never supervise or restart them.
state_source = (LINK / "MahoLinkState.qml").read_text(encoding="utf-8")
bt_state_source = (LINK / "BluetoothState.qml").read_text(encoding="utf-8")
launcher_source = (ROOT / "bin/maho-link").read_text(encoding="utf-8")
wifi_source = (LINK / "wifi.py").read_text(encoding="utf-8")
shell_sources = "\n".join((state_source, bt_state_source, launcher_source, wifi_source))
assert 'command: ["nmcli", "monitor"]' in state_source
assert "state.networks = []" in state_source
assert "state.savedNetworks = []" in state_source
for forbidden in (
    "systemctl restart NetworkManager",
    "systemctl restart bluetooth",
    "systemctl stop NetworkManager",
    "systemctl stop bluetooth",
    "nmcli networking off",
):
    assert forbidden not in shell_sources

link_source = (LINK / "MahoLink.qml").read_text(encoding="utf-8")
enterprise_source = (LINK / "MahoLinkEnterprise.qml").read_text(encoding="utf-8")
enterprise_field_source = (LINK / "MahoLinkEnterpriseField.qml").read_text(encoding="utf-8")
assert 'page = "enterprise"' in link_source
assert "connectSaved" in link_source
assert "connectEnterprise" in enterprise_source
assert '"privateKeyPassword"' in enterprise_source
assert 'echoMode: root.secret ? TextInput.Password : TextInput.Normal' in enterprise_field_source
assert "activeFocusOnTab: true" in enterprise_source

# Authentication errors should become actionable user feedback instead of raw
# NetworkManager wording.
assert WIFI.friendly_wifi_error(
    "Connection activation failed: Secrets were required, but not provided.",
    "fallback",
) == "Authentication failed. Check the Wi-Fi password or enterprise credentials."
assert WIFI.friendly_wifi_error(
    "Error: No network with SSID 'Gone' found.", "fallback"
) == "This Wi-Fi network is no longer in range."

# Keyboard operation is a V1 input contract, not just text-entry support.
for relative in (
    "MahoLinkButton.qml",
    "MahoLinkNetworkRow.qml",
    "MahoLinkMain.qml",
    "MahoLinkDetails.qml",
    "BluetoothDeviceRow.qml",
    "BluetoothMain.qml",
    "BluetoothDetails.qml",
    "BluetoothPairing.qml",
    "BluetoothForgetConfirmation.qml",
    "MahoLinkEnterprise.qml",
    "MahoLinkEnterpriseField.qml",
):
    source = (LINK / relative).read_text(encoding="utf-8")
    assert "activeFocusOnTab: true" in source, relative
    assert "Keys.onReturnPressed" in source, relative

print("PASS  Maho Link V1 NetworkManager/BlueZ truth and failure contracts")
