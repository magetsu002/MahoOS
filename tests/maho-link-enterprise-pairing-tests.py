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


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


WIFI = load("maho_link_wifi_enterprise", LINK / "wifi.py")
BT = load("maho_link_bluetooth_pairing", LINK / "bluetooth.py")

PROFILE_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
DEVICE_PATH = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01"


def invoke(function, *args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = function(*args)
    return result, json.loads(output.getvalue())


# EAP-TLS field construction is NetworkManager-owned. Certificate paths are
# referenced in place and only non-secret settings may appear on argv.
with tempfile.TemporaryDirectory() as temporary:
    temp = Path(temporary)
    ca = temp / "ca.pem"
    client = temp / "client.pem"
    key = temp / "client.key"
    for path in (ca, client, key):
        path.write_text("test material\n", encoding="utf-8")

    calls = []

    def profile_run(args, **kwargs):
        calls.append((list(args), kwargs.get("stdin_text")))
        command = list(args)
        if command[1:3] == ["connection", "add"]:
            return 0, "", ""
        if command[1:4] == ["-g", "connection.uuid", "connection"]:
            return 0, PROFILE_UUID, ""
        raise AssertionError(f"unexpected NetworkManager call: {command}")

    options = {
        "identity": "device@example.com",
        "anonymousIdentity": "anonymous@example.com",
        "eap": "tls",
        "caCert": str(ca),
        "clientCert": str(client),
        "privateKey": str(key),
        "privateKeyPassword": "key-secret",
        "domainSuffix": "auth.example.com",
        "domainMatch": "radius.auth.example.com",
    }
    with mock.patch.object(WIFI, "wifi_device", return_value="wlan0"), mock.patch.object(
        WIFI, "run", side_effect=profile_run
    ):
        profile_uuid, error = WIFI.create_enterprise_profile("Corp TLS", options)

    assert error == ""
    assert profile_uuid == PROFILE_UUID
    argv = calls[0][0]
    expected_pairs = {
        "802-1x.eap": "tls",
        "802-1x.identity": "device@example.com",
        "802-1x.anonymous-identity": "anonymous@example.com",
        "802-1x.ca-cert": str(ca.resolve()),
        "802-1x.client-cert": str(client.resolve()),
        "802-1x.private-key": str(key.resolve()),
        "802-1x.domain-suffix-match": "auth.example.com",
        "802-1x.domain-match": "radius.auth.example.com",
    }
    for field, value in expected_pairs.items():
        index = argv.index(field)
        assert argv[index + 1] == value, (field, argv)
    assert "802-1x.phase2-auth" not in argv
    assert "key-secret" not in argv
    assert all(stdin is None for _argv, stdin in calls)


# Invalid/missing TLS certificate material is rejected before NetworkManager is
# mutated, and server-name validation is mandatory for newly authored EAP-TLS.
with tempfile.TemporaryDirectory() as temporary:
    temp = Path(temporary)
    ca = temp / "ca.pem"
    client = temp / "client.pem"
    key = temp / "client.key"
    for path in (ca, client, key):
        path.write_text("test material\n", encoding="utf-8")

    with mock.patch.object(WIFI, "run") as run_mock:
        profile_uuid, error = WIFI.create_enterprise_profile(
            "Corp TLS",
            {
                "identity": "device@example.com",
                "eap": "tls",
                "caCert": str(temp / "missing-ca.pem"),
                "clientCert": str(client),
                "privateKey": str(key),
                "domainSuffix": "example.com",
            },
        )
    assert profile_uuid == ""
    assert error == "CA certificate could not be found."
    run_mock.assert_not_called()

    with mock.patch.object(WIFI, "run") as run_mock:
        profile_uuid, error = WIFI.create_enterprise_profile(
            "Corp TLS",
            {
                "identity": "device@example.com",
                "eap": "tls",
                "caCert": str(ca),
                "clientCert": str(client),
                "privateKey": str(key),
            },
        )
    assert profile_uuid == ""
    assert "server domain or domain suffix" in error
    run_mock.assert_not_called()


# Private-key passwords follow the same safe transport rule as PEAP/TTLS:
# never argv, and no prompt-order-dependent nmcli fallback.
activation_calls = []


def activation_run(args, **kwargs):
    activation_calls.append((list(args), kwargs.get("stdin_text")))
    return 0, "", ""


tls_options = {
    "identity": "device@example.com",
    "eap": "tls",
    "privateKeyPassword": "private-key-secret",
}
with mock.patch.object(
    WIFI, "create_enterprise_profile", return_value=(PROFILE_UUID, "")
), mock.patch.object(
    WIFI, "persist_enterprise_secrets", return_value=(False, "secure store unavailable")
), mock.patch.object(
    WIFI, "cleanup_enterprise_profile"
) as cleanup_mock, mock.patch.object(
    WIFI, "run", side_effect=activation_run
):
    result, response = invoke(WIFI.connect_enterprise, "Corp TLS", tls_options)

assert result == 1
assert response["ok"] is False
cleanup_mock.assert_called_once_with(PROFILE_UUID)
assert activation_calls == []

activation_calls.clear()
with mock.patch.object(
    WIFI, "create_enterprise_profile", return_value=(PROFILE_UUID, "")
), mock.patch.object(
    WIFI, "persist_enterprise_secrets", return_value=(True, "")
), mock.patch.object(
    WIFI, "wifi_device", return_value="wlan0"
), mock.patch.object(
    WIFI,
    "active_connection",
    return_value={"uuid": PROFILE_UUID, "ssid": "Corp TLS", "profile": "Corp TLS"},
), mock.patch.object(
    WIFI, "finalize_enterprise_profile", return_value=(True, "")
), mock.patch.object(
    WIFI, "cleanup_enterprise_profile"
) as cleanup_mock, mock.patch.object(
    WIFI, "run", side_effect=activation_run
):
    result, response = invoke(WIFI.connect_enterprise, "Corp TLS", tls_options)

assert result == 0
assert response["ok"] is True
cleanup_mock.assert_not_called()
assert all(stdin is None for _argv, stdin in activation_calls)


# Pairing request validation covers the BlueZ Agent1 input cases without
# inventing pairing state.
value, error = BT.normalize_pairing_response("pin", "1234")
assert value == "1234" and error == ""
value, error = BT.normalize_pairing_response("pin", "")
assert value is None and "1 to 16" in error
value, error = BT.normalize_pairing_response("passkey", "000042")
assert value == 42 and error == ""
value, error = BT.normalize_pairing_response("passkey", "12x")
assert value is None and "000000" in error
value, error = BT.normalize_pairing_response("confirm", "")
assert value is None and error == ""
value, error = BT.normalize_pairing_response("authorize", "")
assert value is None and error == ""


class FakeInvocation:
    def __init__(self):
        self.returned = None
        self.error = None

    def return_value(self, value):
        self.returned = value

    def return_dbus_error(self, name, message):
        self.error = (name, message)


class FakeGLib:
    @staticmethod
    def Variant(signature, values):
        return signature, values


class FakeParameters:
    def __init__(self, *values):
        self.values = values

    def unpack(self):
        return self.values


# BlueZ method dispatch creates truthful UI prompts for the device being paired.
dispatch_session = BT.PairingAgentSession(DEVICE_PATH)
dispatch_events = []
dispatch_session.emit_event = dispatch_events.append

request_pin = FakeInvocation()
dispatch_session.method_call(
    None, "org.bluez", BT.AGENT_PATH, BT.AGENT, "RequestPinCode",
    FakeParameters(DEVICE_PATH), request_pin,
)
assert dispatch_events[-1]["type"] == "prompt"
assert dispatch_events[-1]["kind"] == "pin"
assert request_pin.returned is None and request_pin.error is None

request_confirmation = FakeInvocation()
dispatch_session.method_call(
    None, "org.bluez", BT.AGENT_PATH, BT.AGENT, "RequestConfirmation",
    FakeParameters(DEVICE_PATH, 42), request_confirmation,
)
assert dispatch_events[-1]["kind"] == "confirm"
assert dispatch_events[-1]["value"] == "000042"

request_service = FakeInvocation()
dispatch_session.method_call(
    None, "org.bluez", BT.AGENT_PATH, BT.AGENT, "AuthorizeService",
    FakeParameters(DEVICE_PATH, "0000110b-0000-1000-8000-00805f9b34fb"),
    request_service,
)
assert dispatch_events[-1]["kind"] == "authorize-service"
assert dispatch_events[-1]["serviceUuid"] == "0000110b-0000-1000-8000-00805f9b34fb"

cancel_method = FakeInvocation()
dispatch_session.method_call(
    None, "org.bluez", BT.AGENT_PATH, BT.AGENT, "Cancel",
    FakeParameters(), cancel_method,
)
assert cancel_method.error is None
assert dispatch_events[-1]["type"] == "cancelled"
assert not dispatch_session.pending
assert request_pin.error[0] == "org.bluez.Error.Canceled"
assert request_confirmation.error[0] == "org.bluez.Error.Canceled"
assert request_service.error[0] == "org.bluez.Error.Canceled"


session = BT.PairingAgentSession(DEVICE_PATH)
session.GLib = FakeGLib
events = []
session.emit_event = events.append

pin_invocation = FakeInvocation()
session.pending[7] = {"kind": "pin", "invocation": pin_invocation}
assert session.respond({"action": "accept", "requestId": 7, "value": "9876"}) is True
assert pin_invocation.returned == ("(s)", ("9876",))
assert pin_invocation.error is None

passkey_invocation = FakeInvocation()
session.pending[8] = {"kind": "passkey", "invocation": passkey_invocation}
assert session.respond({"action": "accept", "requestId": 8, "value": "000123"}) is True
assert passkey_invocation.returned == ("(u)", (123,))

confirm_invocation = FakeInvocation()
session.pending[9] = {"kind": "confirm", "invocation": confirm_invocation}
assert session.respond({"action": "accept", "requestId": 9, "value": ""}) is True
assert confirm_invocation.returned is None

reject_invocation = FakeInvocation()
session.pending[10] = {"kind": "authorize", "invocation": reject_invocation}
assert session.respond({"action": "reject", "requestId": 10, "value": ""}) is True
assert reject_invocation.error[0] == "org.bluez.Error.Rejected"

cancel_invocation = FakeInvocation()
session.pending[11] = {"kind": "authorize-service", "invocation": cancel_invocation}
assert session.respond({"action": "cancel", "requestId": 11, "value": ""}) is True
assert cancel_invocation.error[0] == "org.bluez.Error.Canceled"


# The agent surface must cover the common BlueZ interactive methods and remain
# process-scoped; it must not promote itself to the system default agent.
for method in (
    "RequestPinCode",
    "RequestPasskey",
    "DisplayPinCode",
    "DisplayPasskey",
    "RequestConfirmation",
    "RequestAuthorization",
    "AuthorizeService",
    "Cancel",
):
    assert f'name="{method}"' in BT.AGENT_XML
bluetooth_source = (LINK / "bluetooth.py").read_text(encoding="utf-8")
assert '"RegisterAgent"' in bluetooth_source
assert '"RequestDefaultAgent"' not in bluetooth_source
assert '"Pair"' in bluetooth_source
assert "confirm_paired" in bluetooth_source


# Backend disappearance becomes explicit failure, and a live agent session
# terminates instead of leaving a stale request behind.
assert BT.friendly_error(
    "GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown: The name org.bluez was not provided",
    "Pairing failed.",
) == "Bluetooth service became unavailable."


class FakeLoop:
    def __init__(self):
        self.quit_called = False

    def quit(self):
        self.quit_called = True


lost_session = BT.PairingAgentSession(DEVICE_PATH)
lost_events = []
lost_session.emit_event = lost_events.append
lost_session.loop = FakeLoop()
lost_session.owner_changed(
    None, "org.freedesktop.DBus", "/org/freedesktop/DBus",
    "org.freedesktop.DBus", "NameOwnerChanged",
    FakeParameters(BT.BLUEZ, ":1.42", ""), None,
)
assert lost_session.finished is True
assert lost_session.exit_code == 1
assert lost_session.loop.quit_called is True
assert lost_events[-1] == {
    "type": "result",
    "ok": False,
    "message": "Bluetooth service became unavailable.",
}

state_source = (LINK / "BluetoothState.qml").read_text(encoding="utf-8")
pairing_source = (LINK / "BluetoothPairing.qml").read_text(encoding="utf-8")
link_source = (LINK / "MahoLink.qml").read_text(encoding="utf-8")
assert '"pair-session", String(device.path)' in state_source
assert '"action": "cancel-session"' in state_source
assert "id: pairingCancelFallback" in state_source
assert "state.clearPairingPrompt()" in state_source
assert 'type === "result"' in state_source
assert "pairingPromptKind" in pairing_source
assert "respondPairing" in pairing_source
assert 'promptKind === "confirm"' in pairing_source
assert 'promptKind === "authorize"' in pairing_source
assert 'page === "pairing"' in link_source
assert "bluetooth.cancelPairing(selectedBluetoothDevice)" in link_source

print("PASS  Maho Link EAP-TLS and interactive BlueZ pairing contracts")
