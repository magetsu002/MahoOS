#!/usr/bin/env python3

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LINK = ROOT / "config/quickshell/maho-link"
ADAPTER = "/org/bluez/hci0"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BT = load("maho_link_bt_rfkill", LINK / "bluetooth.py")
WIFI = load("maho_link_wifi_convergence", LINK / "wifi.py")


def invoke(function, *args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = function(*args)
    lines = [line for line in output.getvalue().splitlines() if line.strip()]
    assert lines, function.__name__
    return result, json.loads(lines[-1])


def bt_state(*, enabled=False, soft=False, hard=False, power_state=None):
    if power_state is None:
        power_state = "hard-blocked" if hard else "soft-blocked" if soft else "powered" if enabled else "powered-off"
    return {
        "available": True,
        "enabled": enabled,
        "adapterPath": ADAPTER,
        "powerState": power_state,
        "powerActionable": not hard,
        "rfkillState": "hard-blocked" if hard else "soft-blocked" if soft else "unblocked",
        "softBlocked": soft,
        "hardBlocked": hard,
        "error": "",
    }


# Physical rfkill observation is type-bounded: a blocked WLAN entry must never
# make Bluetooth itself look blocked.
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    for index, kind, name, soft, hard in (
        (0, "wlan", "phy0", "1", "0"),
        (1, "bluetooth", "hci0", "0", "0"),
    ):
        d = root / f"rfkill{index}"
        d.mkdir()
        (d / "type").write_text(kind)
        (d / "name").write_text(name)
        (d / "soft").write_text(soft)
        (d / "hard").write_text(hard)
    rf = BT.bluetooth_rfkill_state(root)
assert rf["state"] == "unblocked"
assert rf["softBlocked"] is False
assert [row["name"] for row in rf["devices"]] == ["hci0"]


# soft-blocked -> Bluetooth-only unblock -> BlueZ power -> confirmed readback.
calls = []


def successful_power_run(args, **_kwargs):
    command = list(args)
    calls.append(command)
    if command == ["rfkill", "unblock", "bluetooth"]:
        return 0, "", ""
    assert command[:4] == ["busctl", "--system", "set-property", BT.BLUEZ]
    assert command[-2:] == ["b", "true"]
    return 0, "", ""


with mock.patch.object(BT.shutil, "which", return_value="/usr/bin/tool"), \
     mock.patch.object(BT, "snapshot_payload", return_value=bt_state(soft=True)), \
     mock.patch.object(BT, "bluetooth_rfkill_state", return_value={
         "available": True, "state": "unblocked", "softBlocked": False,
         "hardBlocked": False, "devices": [],
     }), \
     mock.patch.object(BT, "rfkill_type_signature", side_effect=[
         ((0, "phy0", False, False),),
         ((0, "phy0", False, False),),
     ]), \
     mock.patch.object(BT, "run", side_effect=successful_power_run), \
     mock.patch.object(BT, "wait_for_adapter_power", return_value=(
         True, bt_state(enabled=True)
     )):
    result, payload = invoke(BT.action, ["toggle", ADAPTER, "on"])
assert result == 0 and payload["ok"] is True
assert payload["powerState"] == "powered"
assert calls[0] == ["rfkill", "unblock", "bluetooth"]
assert all("wlan" not in part and "wifi" not in part for call in calls for part in call)


# Hard-blocked Bluetooth is truthful and non-actionable; no mutation is tried.
with mock.patch.object(BT.shutil, "which", return_value="/usr/bin/busctl"), \
     mock.patch.object(BT, "snapshot_payload", return_value=bt_state(hard=True)), \
     mock.patch.object(BT, "run") as run_mock:
    result, payload = invoke(BT.action, ["toggle", ADAPTER, "on"])
assert result == 1 and payload["powerState"] == "hard-blocked"
assert "hardware" in payload["message"].lower()
run_mock.assert_not_called()


# If BlueZ power fails after a successful unblock, report the exact observed
# powered-off state rather than pretending Bluetooth is enabled.
calls = []


def bluez_failure_run(args, **_kwargs):
    command = list(args)
    calls.append(command)
    if command == ["rfkill", "unblock", "bluetooth"]:
        return 0, "", ""
    return 1, "", "org.bluez.Error.Failed: power failed"


with mock.patch.object(BT.shutil, "which", return_value="/usr/bin/tool"), \
     mock.patch.object(BT, "snapshot_payload", side_effect=[
         bt_state(soft=True),
         bt_state(enabled=False),
     ]), \
     mock.patch.object(BT, "bluetooth_rfkill_state", return_value={
         "available": True, "state": "unblocked", "softBlocked": False,
         "hardBlocked": False, "devices": [],
     }), \
     mock.patch.object(BT, "rfkill_type_signature", side_effect=[
         ((0, "phy0", False, False),),
         ((0, "phy0", False, False),),
     ]), \
     mock.patch.object(BT, "run", side_effect=bluez_failure_run):
    result, payload = invoke(BT.action, ["toggle", ADAPTER, "on"])
assert result == 1 and payload["powerState"] == "powered-off"
assert calls[0] == ["rfkill", "unblock", "bluetooth"]


# A successful D-Bus write without readback confirmation is still a failure.
with mock.patch.object(BT.shutil, "which", return_value="/usr/bin/busctl"), \
     mock.patch.object(BT, "snapshot_payload", return_value=bt_state(enabled=False)), \
     mock.patch.object(BT, "run", return_value=(0, "", "")), \
     mock.patch.object(BT, "wait_for_adapter_power", return_value=(
         False, bt_state(enabled=False)
     )):
    result, payload = invoke(BT.action, ["toggle", ADAPTER, "on"])
assert result == 1 and payload["powerState"] == "powered-off"
assert "confirm" in payload["message"].lower()


# Wi-Fi rfkill drift is a fail-closed safety violation and BlueZ is not powered.
calls = []
with mock.patch.object(BT.shutil, "which", return_value="/usr/bin/tool"), \
     mock.patch.object(BT, "snapshot_payload", return_value=bt_state(soft=True)), \
     mock.patch.object(BT, "bluetooth_rfkill_state", return_value={
         "available": True, "state": "unblocked", "softBlocked": False,
         "hardBlocked": False, "devices": [],
     }), \
     mock.patch.object(BT, "rfkill_type_signature", side_effect=[
         ((0, "phy0", False, False),),
         ((0, "phy0", True, False),),
     ]), \
     mock.patch.object(BT, "run", side_effect=lambda args, **_kwargs: (
         calls.append(list(args)) or (0, "", "")
     )):
    result, payload = invoke(BT.action, ["toggle", ADAPTER, "on"])
assert result == 1
assert "preserve Wi-Fi rfkill" in payload["message"]
assert calls == [["rfkill", "unblock", "bluetooth"]]


# Turning Bluetooth off is BlueZ-only; it must not invent a global rfkill block.
calls = []
with mock.patch.object(BT.shutil, "which", return_value="/usr/bin/busctl"), \
     mock.patch.object(BT, "snapshot_payload", return_value=bt_state(enabled=True)), \
     mock.patch.object(BT, "run", side_effect=lambda args, **_kwargs: (
         calls.append(list(args)) or (0, "", "")
     )), \
     mock.patch.object(BT, "wait_for_adapter_power", return_value=(
         True, bt_state(enabled=False)
     )):
    result, payload = invoke(BT.action, ["toggle", ADAPTER, "off"])
assert result == 0 and payload["ok"] is True
assert len(calls) == 1
assert calls[0][-2:] == ["b", "false"]
assert all(call[0] != "rfkill" for call in calls)


ACTIVE = {
    "profile": "Home",
    "uuid": "11111111-2222-3333-4444-555555555555",
    "profileUuid": "11111111-2222-3333-4444-555555555555",
    "profileName": "Home",
    "saved": True,
    "device": "wlan0",
    "ssid": "Home",
    "signal": -1,
    "quality": "",
    "frequency": 0,
    "band": "",
    "security": "WPA2",
    "secured": True,
    "enterprise": False,
    "state": "Connected",
    "ipv4": "192.0.2.10/24",
    "gateway": "192.0.2.1",
}


def observe_with(scan_side_effect, active=ACTIVE):
    with mock.patch.object(WIFI.shutil, "which", return_value="/usr/bin/nmcli"), \
         mock.patch.object(WIFI, "wifi_enabled", return_value=True), \
         mock.patch.object(WIFI, "wifi_device", return_value="wlan0"), \
         mock.patch.object(WIFI, "saved_wifi_profiles", return_value=[]), \
         mock.patch.object(WIFI, "active_connection", return_value=active), \
         mock.patch.object(WIFI, "scan_networks", side_effect=scan_side_effect):
        return WIFI.coherent_wifi_observation(include_system=False)


# Connected truth is visible immediately even while the scan cache is warming.
warming = observe_with([([], None)])
assert warming["current"]["ssid"] == "Home"
assert warming["current"]["state"] == "Connected"
assert warming["current"]["signal"] == -1
assert warming["networks"] == []
assert warming["scanState"] == "warming"


# The same coherent observation converges signal + nearby networks when cache
# data appears, without changing active connection identity.
home_scan = {
    "ssid": "Home", "signal": 74, "quality": "Very Good", "frequency": 5180,
    "band": "5 GHz", "available": True, "security": "WPA2", "secured": True,
    "enterprise": False, "saved": True, "profileUuid": ACTIVE["uuid"],
    "profileName": "Home",
}
cafe_scan = {
    "ssid": "Cafe", "signal": 58, "quality": "Good", "frequency": 2412,
    "band": "2.4 GHz", "available": True, "security": "WPA2", "secured": True,
    "enterprise": False, "saved": False, "profileUuid": "", "profileName": "",
}
fresh = observe_with([([home_scan, cafe_scan], dict(home_scan))])
assert fresh["current"]["ssid"] == "Home"
assert fresh["current"]["uuid"] == ACTIVE["uuid"]
assert fresh["current"]["signal"] == 74
assert [row["ssid"] for row in fresh["networks"]] == ["Cafe"]
assert fresh["scanState"] == "cached"


# A stale cached IN-USE marker cannot override fresher NetworkManager truth that
# there is no active connection.
stale_scan = dict(home_scan)
with mock.patch.object(WIFI.shutil, "which", return_value="/usr/bin/nmcli"), \
     mock.patch.object(WIFI, "wifi_enabled", return_value=True), \
     mock.patch.object(WIFI, "wifi_device", return_value="wlan0"), \
     mock.patch.object(WIFI, "saved_wifi_profiles", return_value=[]), \
     mock.patch.object(WIFI, "active_connection", return_value=None), \
     mock.patch.object(WIFI, "scan_networks", return_value=([stale_scan], stale_scan)):
    disconnected = WIFI.coherent_wifi_observation(include_system=False)
assert disconnected["current"] is None
assert [row["ssid"] for row in disconnected["networks"]] == ["Home"]


# NetworkManager disappearance is explicit and clears authority.
with mock.patch.object(WIFI.shutil, "which", return_value=None):
    missing = WIFI.coherent_wifi_observation(include_system=False)
assert missing["available"] is False
assert missing["current"] is None
assert missing["networks"] == []
assert missing["scanState"] == "unavailable"


# Both public cached observation commands share the same model.
payload = {
    "available": True, "enabled": True, "device": "wlan0",
    "current": ACTIVE, "networks": [cafe_scan], "saved": [],
    "scanState": "cached", "scanSource": "networkmanager-cache",
    "observedAtMs": 1, "error": "",
}
with mock.patch.object(WIFI, "coherent_wifi_observation", return_value=payload) as observation:
    _, snapshot_payload = invoke(WIFI.snapshot)
    _, networks_payload = invoke(WIFI.networks_snapshot)
assert snapshot_payload["current"]["ssid"] == networks_payload["current"]["ssid"] == "Home"
assert observation.call_args_list == [mock.call(include_system=True), mock.call(include_system=False)]


# QML has one Wi-Fi state owner. Refresh queues a newer observation instead of
# allowing concurrent status/network results to overwrite each other.
state_source = (LINK / "MahoLinkState.qml").read_text(encoding="utf-8")
main_source = (LINK / "MahoLinkMain.qml").read_text(encoding="utf-8")
shell_source = (LINK / "shell.qml").read_text(encoding="utf-8")
assert "id: snapshotProcess" in state_source
assert "id: statusProcess" not in state_source
assert "id: networkProcess" not in state_source
assert "state.refreshPending = true" in state_source
assert "observedAt < state.lastObservationAtMs" in state_source
assert "state.statusReady = false" in state_source
refresh_start = state_source.index("function refresh()")
refresh_end = state_source.index("function maybeStartupScan()", refresh_start)
refresh_body = state_source[refresh_start:refresh_end]
assert "state.currentNetwork = null" not in refresh_body
assert "state.networks = []" not in refresh_body
assert 'scanState !== "warming"' in state_source
assert 'root.wifi.scanState === "warming" ? "Refreshing nearby networks…"' in main_source
assert "Your current connection is confirmed while NetworkManager refreshes nearby networks." in main_source
assert "if (activeMode === \"wifi\" && !wifi.statusReady)" in shell_source

print("PASS  Maho Link rfkill power and Wi-Fi freshness convergence blockers")
