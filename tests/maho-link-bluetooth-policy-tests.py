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


def device(path, name, *, paired, trusted, connected=False, icon="audio-headphones", rssi=-52):
    properties = {
        "Adapter": ADAPTER,
        "Alias": name,
        "Paired": paired,
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

    def fake_call(path, interface, method, *arguments, timeout=12.0):
        calls.append((path, interface, method, arguments, timeout))
        if method == "Connect" and connect_results:
            return connect_results.pop(0)
        return 0, "", ""

    MODULE.busctl_call = fake_call

    # Maho Link and the persistent Maho Shell may observe the same BlueZ
    # transition. Only one of them may evaluate/connect at a time.
    policy_lock = MODULE.auto_connect_lock_path()
    policy_lock.parent.mkdir(parents=True, exist_ok=True)
    with policy_lock.open("a+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, response = invoke(MODULE.auto_connect)
        assert result == 0 and response["status"] == "busy"
    assert calls == []

    # Snapshot truth is entirely derived from BlueZ properties. Only a
    # reachable, paired, trusted audio device is auto-connect eligible.
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

    # Retries are bounded to four for the same reachability epoch.
    for expected_attempt, advance in ((2, 5), (3, 15), (4, 45)):
        now[0] += advance
        connect_results.append((1, "", "org.bluez.Error.Failed"))
        result, response = invoke(MODULE.auto_connect)
        assert result == 1 and response["attempt"] == expected_attempt
    now[0] += 120
    result, response = invoke(MODULE.auto_connect)
    assert result == 0 and response["status"] == "idle"
    assert len([call for call in calls if call[2] == "Connect"]) == 4

    # Becoming unavailable resets that bounded epoch; becoming reachable later
    # permits one new attempt and a successful method call receives a grace
    # window while Connected=true is still awaiting confirmation.
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

    # A successful explicit disconnect is remembered for this login session.
    # It suppresses all later automatic attempts but never changes pairing or
    # trust and can be cleared by an explicit manual Connect.
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

print("PASS  BlueZ truth, eligible audio policy, bounded backoff, and session disconnect suppression")
