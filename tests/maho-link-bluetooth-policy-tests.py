#!/usr/bin/env python3

import contextlib
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "config/quickshell/maho-link/bluetooth.py"
SPEC = importlib.util.spec_from_file_location("maho_link_bluetooth", BACKEND)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

ADAPTER = "/org/bluez/hci0"
HEADPHONES = ADAPTER + "/dev_AA_BB_CC_DD_EE_01"
KEYBOARD = ADAPTER + "/dev_AA_BB_CC_DD_EE_02"
UNKNOWN = ADAPTER + "/dev_AA_BB_CC_DD_EE_03"
GALAXY = ADAPTER + "/dev_5C_5E_0A_18_45_BD"
GALAXY_SCAN_SHADOW = ADAPTER + "/dev_5C_5E_0A_18_45_BE"


def device(path, name, *, paired, trusted, bonded=None, connected=False,
           icon="audio-headphones", rssi=-52, address=None):
    if address is None:
        address = path.rsplit("/dev_", 1)[-1].replace("_", ":")
    properties = {
        "Adapter": ADAPTER,
        "Address": address,
        "Alias": name,
        "Paired": paired,
        "Bonded": paired if bonded is None else bonded,
        "Trusted": trusted,
        "Connected": connected,
        "Icon": icon,
    }
    if rssi is not None:
        properties["RSSI"] = rssi
    return path, {MODULE.DEVICE: properties}


def objects_with(*devices, powered=True):
    objects = {ADAPTER: {MODULE.ADAPTER: {"Powered": powered, "Discovering": True}}}
    objects.update(dict(devices))
    return objects


def invoke(function, *args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = function(*args)
    return result, json.loads(output.getvalue())


with tempfile.TemporaryDirectory() as temporary:
    os.environ["XDG_RUNTIME_DIR"] = temporary
    now = [1000.0]
    calls = []
    connect_results = []

    MODULE.time.time = lambda: now[0]
    MODULE.shutil.which = lambda name: "/usr/bin/" + name

    typed_payload = {
        "type": "a{oa{sa{sv}}}",
        "data": [{ADAPTER: {MODULE.ADAPTER: {
            "Powered": {"type": "b", "data": True},
            "Discovering": {"type": "b", "data": False},
        }}}],
    }
    original_run = MODULE.run
    MODULE.run = lambda *_args, **_kwargs: (0, json.dumps(typed_payload), "")
    parsed, parse_error = MODULE.managed_objects()
    assert parse_error == "" and parsed[ADAPTER][MODULE.ADAPTER]["Powered"] is True
    MODULE.run = original_run

    def fake_call(path, interface, method, *arguments, timeout=12.0):
        calls.append((path, interface, method, arguments, timeout))
        if method == "Connect" and connect_results:
            return connect_results.pop(0)
        return 0, "", ""

    MODULE.busctl_call = fake_call
    MODULE.wait_for_connected = lambda _path, _expected, _timeout: True

    policy_lock = MODULE.auto_connect_lock_path()
    policy_lock.parent.mkdir(parents=True, exist_ok=True)
    with policy_lock.open("a+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, response = invoke(MODULE.auto_connect)
        assert result == 0 and response["status"] == "busy"
    assert calls == []

    current_objects = objects_with(
        device(HEADPHONES, "Studio Headset", paired=True, trusted=True),
        device(KEYBOARD, "Keyboard", paired=True, trusted=True, icon="input-keyboard"),
        device(UNKNOWN, "Unknown Buds", paired=False, trusted=False),
    )
    MODULE.managed_objects = lambda: (current_objects, "")
    payload = MODULE.snapshot_payload()
    assert payload["paired"][0]["trusted"] is True
    assert payload["paired"][0]["available"] is True
    assert payload["autoConnectEligible"] == [HEADPHONES]

    current_objects = objects_with(
        device(GALAXY, "Galaxy Buds Core", paired=True, bonded=True,
               trusted=False, connected=False, rssi=-48),
        device(GALAXY_SCAN_SHADOW, "Galaxy Buds Core", paired=False,
               bonded=False, trusted=False, connected=False, rssi=-43,
               address="5C:5E:0A:18:45:BD"),
        device(UNKNOWN, "Stale unknown", paired=False, bonded=False,
               trusted=False, rssi=None),
    )
    payload = MODULE.snapshot_payload()
    assert len(payload["paired"]) == 1
    galaxy = payload["paired"][0]
    assert galaxy["address"] == "5C:5E:0A:18:45:BD"
    assert galaxy["paired"] is True and galaxy["bonded"] is True
    assert galaxy["trusted"] is False and galaxy["connected"] is False
    assert galaxy["discovered"] is True
    assert payload["availableDevices"] == []
    assert payload["autoConnectEligible"] == []

    current_objects = objects_with(
        device(HEADPHONES, "Studio Headset", paired=True, trusted=True),
        device(KEYBOARD, "Keyboard", paired=True, trusted=True, icon="input-keyboard"),
        device(UNKNOWN, "Unknown Buds", paired=False, trusted=False),
    )

    # A D-Bus Connect method success is not a connection success until BlueZ
    # exposes Connected=true. Lack of confirmation enters the same bounded
    # backoff path instead of emitting a false "connected" state.
    MODULE.wait_for_connected = lambda _path, _expected, _timeout: False
    connect_results.append((0, "", ""))
    result, response = invoke(MODULE.auto_connect)
    assert result == 1 and response["status"] == "backoff"
    assert response["message"] == "Bluetooth did not confirm the connection state."
    assert response["attempt"] == 1
    assert len(calls) == 1
    MODULE.save_session_state(MODULE.empty_session_state())
    calls.clear()
    MODULE.wait_for_connected = lambda _path, _expected, _timeout: True

    # One failed request enters backoff. Repeated policy evaluations cannot
    # spam BlueZ before the retry deadline.
    connect_results.append((1, "", "org.bluez.Error.Failed"))
    result, response = invoke(MODULE.auto_connect)
    assert result == 1 and response["status"] == "backoff"
    assert response["attempt"] == 1 and response["retryAfter"] == 5
    assert len(calls) == 1
    result, response = invoke(MODULE.auto_connect)
    assert result == 0 and response["status"] == "idle"
    assert len(calls) == 1

    for expected_attempt, advance in ((2, 5), (3, 15), (4, 45)):
        now[0] += advance
        connect_results.append((1, "", "org.bluez.Error.Failed"))
        result, response = invoke(MODULE.auto_connect)
        assert result == 1 and response["attempt"] == expected_attempt
    now[0] += 120
    result, response = invoke(MODULE.auto_connect)
    assert result == 0 and response["status"] == "idle"
    assert len([call for call in calls if call[2] == "Connect"]) == 4

    current_objects = objects_with(
        device(HEADPHONES, "Studio Headset", paired=True, trusted=True, rssi=None)
    )
    invoke(MODULE.auto_connect)
    current_objects = objects_with(
        device(HEADPHONES, "Studio Headset", paired=True, trusted=True)
    )
    connect_results.append((0, "", ""))
    result, response = invoke(MODULE.auto_connect)
    assert result == 0 and response["status"] == "connected"
    successful_call_count = len(calls)
    invoke(MODULE.auto_connect)
    assert len(calls) == successful_call_count

    result, response = invoke(MODULE.action, ["disconnect", HEADPHONES])
    assert result == 0 and response["ok"] is True
    persisted = MODULE.load_session_state()
    assert HEADPHONES in persisted["suppressed"]
    now[0] += 500
    call_count = len(calls)
    invoke(MODULE.auto_connect)
    assert len(calls) == call_count

    invoke(MODULE.action, ["connect", HEADPHONES])
    assert HEADPHONES not in MODULE.load_session_state()["suppressed"]
    state_file = MODULE.session_state_path()
    assert state_file.stat().st_mode & 0o777 == 0o600

print("PASS  BlueZ truth, confirmed auto-connect, bounded backoff, and session disconnect suppression")
