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
PROFILE_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
DEVICE_PATH = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


WIFI = load("maho_link_wifi_reviewed", LINK / "wifi.py")
BT = load("maho_link_bluetooth_reviewed", LINK / "bluetooth.py")


def invoke(function, *args):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = function(*args)
    lines = [line for line in output.getvalue().splitlines() if line.strip()]
    assert lines, f"{function.__name__} emitted no response"
    return code, json.loads(lines[-1])


def profile_runner(calls, profile_uuid=PROFILE_UUID):
    def run(args, **kwargs):
        command = list(args)
        calls.append((command, kwargs.get("stdin_text")))
        if command[1:3] == ["connection", "add"]:
            return 0, "", ""
        if command[1:4] == ["-g", "connection.uuid", "connection"]:
            return 0, profile_uuid, ""
        raise AssertionError(f"unexpected NetworkManager call: {command}")
    return run


# BLOCKER 1: new enterprise profiles require a trusted CA or server-name
# constraint; a custom CA alone is valid for networks without name matching.
for eap, phase2 in (("peap", "mschapv2"), ("ttls", "pap")):
    with mock.patch.object(WIFI, "run") as run_mock:
        profile_uuid, error = WIFI.create_enterprise_profile(
            "Corp",
            {"identity": "user@example.com", "eap": eap, "phase2": phase2},
        )
    assert profile_uuid == ""
    assert "trusted CA certificate or server domain constraint" in error
    run_mock.assert_not_called()

with tempfile.TemporaryDirectory() as temporary:
    temp = Path(temporary)
    ca = temp / "ca.pem"
    ca.write_text("test ca\n", encoding="utf-8")

    peap_calls = []
    with mock.patch.object(WIFI, "wifi_device", return_value="wlan0"), mock.patch.object(
        WIFI, "run", side_effect=profile_runner(peap_calls)
    ):
        profile_uuid, error = WIFI.create_enterprise_profile(
            "Corp PEAP",
            {
                "identity": "user@example.com",
                "eap": "peap",
                "phase2": "mschapv2",
                "domainSuffix": "auth.example.com",
            },
        )
    assert profile_uuid == PROFILE_UUID and error == ""
    peap_argv = peap_calls[0][0]
    assert peap_argv[peap_argv.index("802-1x.domain-suffix-match") + 1] == "auth.example.com"
    assert peap_argv[peap_argv.index("802-1x.system-ca-certs") + 1] == "yes"
    assert peap_argv[peap_argv.index("connection.autoconnect") + 1] == "no"

    ttls_calls = []
    with mock.patch.object(WIFI, "wifi_device", return_value="wlan0"), mock.patch.object(
        WIFI, "run", side_effect=profile_runner(ttls_calls)
    ):
        profile_uuid, error = WIFI.create_enterprise_profile(
            "Corp TTLS",
            {
                "identity": "user@example.com",
                "eap": "ttls",
                "phase2": "pap",
                "caCert": str(ca),
                "domainMatch": "radius.example.com",
            },
        )
    assert profile_uuid == PROFILE_UUID and error == ""
    ttls_argv = ttls_calls[0][0]
    assert ttls_argv[ttls_argv.index("802-1x.domain-match") + 1] == "radius.example.com"
    assert ttls_argv[ttls_argv.index("802-1x.ca-cert") + 1] == str(ca.resolve())
    assert "802-1x.system-ca-certs" not in ttls_argv

    # A private, explicitly supplied CA can authenticate an enterprise RADIUS
    # server even when the deployment supplies no server DNS-name constraint.
    for eap, phase2 in (("peap", "mschapv2"), ("ttls", "pap")):
        ca_only_calls = []
        with mock.patch.object(WIFI, "wifi_device", return_value="wlan0"), mock.patch.object(
            WIFI, "run", side_effect=profile_runner(ca_only_calls)
        ):
            profile_uuid, error = WIFI.create_enterprise_profile(
                "EnterpriseNetwork",
                {
                    "identity": "user@example.test",
                    "eap": eap,
                    "phase2": phase2,
                    "caCert": str(ca),
                },
            )
        assert (profile_uuid, error) == (PROFILE_UUID, "")
        argv = ca_only_calls[0][0]
        assert argv[argv.index("802-1x.ca-cert") + 1] == str(ca.resolve())
        assert "802-1x.domain-match" not in argv
        assert "802-1x.domain-suffix-match" not in argv
        assert "802-1x.system-ca-certs" not in argv

    with mock.patch.object(WIFI, "run") as run_mock:
        profile_uuid, error = WIFI.create_enterprise_profile(
            "Corp PEAP",
            {
                "identity": "user@example.com",
                "eap": "peap",
                "phase2": "mschapv2",
                "caCert": str(temp / "missing.pem"),
                "domainSuffix": "example.com",
            },
        )
    assert profile_uuid == ""
    assert error == "CA certificate could not be found."
    run_mock.assert_not_called()


# BLOCKER 2: provisional profile transaction boundaries.
options = {
    "identity": "user@example.com",
    "password": "enterprise-secret",
    "eap": "peap",
    "phase2": "mschapv2",
    "domainSuffix": "example.com",
}


def transactional_case(*, persist=(True, ""), activation=(0, "", ""),
                       active=None, finalize=(True, ""), raises=False,
                       cancelled=False):
    if active is None:
        active = {"uuid": PROFILE_UUID, "ssid": "Corp", "profile": "Corp"}

    def run(args, **kwargs):
        if raises:
            raise RuntimeError("helper failed")
        if cancelled:
            WIFI._ENTERPRISE_CANCEL_REQUESTED = True
        return activation

    with mock.patch.object(
        WIFI, "create_enterprise_profile", return_value=(PROFILE_UUID, "")
    ), mock.patch.object(
        WIFI, "persist_enterprise_secrets", return_value=persist
    ), mock.patch.object(
        WIFI, "wifi_device", return_value="wlan0"
    ), mock.patch.object(
        WIFI, "active_connection", return_value=active
    ), mock.patch.object(
        WIFI, "finalize_enterprise_profile", return_value=finalize
    ), mock.patch.object(
        WIFI, "cleanup_enterprise_profile"
    ) as cleanup, mock.patch.object(
        WIFI, "run", side_effect=run
    ):
        result, response = invoke(WIFI.connect_enterprise, "Corp", options)
    return result, response, cleanup


result, response, cleanup = transactional_case()
assert result == 0 and response["ok"] is True
cleanup.assert_not_called()

result, response, cleanup = transactional_case(persist=(False, "secure store unavailable"))
assert result == 1 and response["ok"] is False
cleanup.assert_called_once_with(PROFILE_UUID)

result, response, cleanup = transactional_case(activation=(10, "", "NetworkManager unavailable"))
assert result == 1 and response["ok"] is False
cleanup.assert_called_once_with(PROFILE_UUID)

result, response, cleanup = transactional_case(active={})
assert result == 1 and response["ok"] is False
cleanup.assert_called_once_with(PROFILE_UUID)

result, response, cleanup = transactional_case(finalize=(False, "finalize failed"))
assert result == 1 and response["ok"] is False
cleanup.assert_called_once_with(PROFILE_UUID)

result, response, cleanup = transactional_case(raises=True)
assert result == 1 and response["ok"] is False
cleanup.assert_called_once_with(PROFILE_UUID)

result, response, cleanup = transactional_case(
    activation=(127, "", "cancelled"), cancelled=True
)
assert result == 1 and response["ok"] is False
assert "cancel" in response["message"].lower()
cleanup.assert_called_once_with(PROFILE_UUID)

# The actual signal-handler exception path also lands in the same cleanup.
def signal_cancel_run(args, **kwargs):
    raise WIFI.EnterpriseConnectionCancelled("cancelled by SIGTERM")


with mock.patch.object(
    WIFI, "create_enterprise_profile", return_value=(PROFILE_UUID, "")
), mock.patch.object(
    WIFI, "persist_enterprise_secrets", return_value=(True, "")
), mock.patch.object(
    WIFI, "wifi_device", return_value="wlan0"
), mock.patch.object(
    WIFI, "run", side_effect=signal_cancel_run
), mock.patch.object(
    WIFI, "cleanup_enterprise_profile"
) as cleanup:
    result, response = invoke(WIFI.connect_enterprise, "Corp", options)
assert result == 1 and response["ok"] is False
assert "cancel" in response["message"].lower()
cleanup.assert_called_once_with(PROFILE_UUID)

# If NetworkManager accepts add but UUID readback fails, cleanup by the unique
# provisional profile name still runs before returning.
creation_calls = []


def readback_failure_run(args, **kwargs):
    command = list(args)
    creation_calls.append(command)
    if command[1:3] == ["connection", "add"]:
        return 0, "", ""
    if command[1:4] == ["-g", "connection.uuid", "connection"]:
        return 10, "", "NetworkManager disappeared"
    if command[1:3] == ["connection", "delete"]:
        return 0, "", ""
    raise AssertionError(command)


with mock.patch.object(WIFI, "wifi_device", return_value="wlan0"), mock.patch.object(
    WIFI, "run", side_effect=readback_failure_run
):
    profile_uuid, error = WIFI.create_enterprise_profile("Corp", options)
assert profile_uuid == ""
assert any(call[1:3] == ["connection", "delete"] and "id" in call for call in creation_calls)

finalize_calls = []


def finalize_run(args, **kwargs):
    command = list(args)
    finalize_calls.append(command)
    if command[1:3] == ["connection", "modify"]:
        return 0, "", ""
    if command[1:4] == ["-g", "connection.autoconnect", "connection"]:
        return 0, "yes", ""
    raise AssertionError(command)


with mock.patch.object(WIFI, "run", side_effect=finalize_run):
    ok, error = WIFI.finalize_enterprise_profile(PROFILE_UUID)
assert ok is True and error == ""
assert finalize_calls[0][-2:] == ["connection.autoconnect", "yes"]

# Existing exact saved profiles never enter provisional cleanup.
with mock.patch.object(WIFI, "wifi_device", return_value="wlan0"), mock.patch.object(
    WIFI, "run", return_value=(0, "", "")
), mock.patch.object(
    WIFI, "active_connection", return_value={"uuid": PROFILE_UUID, "ssid": "Existing Corp"}
), mock.patch.object(WIFI, "cleanup_enterprise_profile") as cleanup:
    result, response = invoke(WIFI.activate_saved_profile, PROFILE_UUID)
assert result == 0 and response["ok"] is True
cleanup.assert_not_called()


# BLOCKER 3 + Wi-Fi cancellation: form state is explicitly cleared on network
# identity changes, back/hide, completion and backend disappearance.
enterprise_source = (LINK / "MahoLinkEnterprise.qml").read_text(encoding="utf-8")
link_source = (LINK / "MahoLink.qml").read_text(encoding="utf-8")
state_source = (LINK / "MahoLinkState.qml").read_text(encoding="utf-8")
shell_source = (LINK / "shell.qml").read_text(encoding="utf-8")
reset_start = enterprise_source.index("function clearInteraction()")
reset_end = enterprise_source.index("function resetForNetwork()", reset_start)
reset_body = enterprise_source[reset_start:reset_end]
for field in (
    "identityInput.text = \"\"",
    "anonymousInput.text = \"\"",
    "passwordInput.text = \"\"",
    "caCertInput.text = \"\"",
    "clientCertInput.text = \"\"",
    "privateKeyInput.text = \"\"",
    "privateKeyPasswordInput.text = \"\"",
    "domainSuffixInput.text = \"\"",
    "domainMatchInput.text = \"\"",
):
    assert field in reset_body
assert "onNetworkChanged: Qt.callLater(root.resetForNetwork)" in enterprise_source
assert "enterpriseView.clearInteraction()" in link_source
assert "onShownChanged:" in link_source
assert "function onActionFinished(action, succeeded)" in link_source
assert "function onAvailableChanged()" in link_source
assert "function cancelPendingConnection()" in state_source
assert "actionProcess.running = false" in state_source
assert "wifi.cancelPendingConnection()" in shell_source


# BLOCKER 4: every exposed pairing entry point requires fresh BlueZ Paired=true.
with mock.patch.object(BT.shutil, "which", return_value="/usr/bin/busctl"), mock.patch.object(
    BT, "busctl_call", return_value=(0, "", "")
), mock.patch.object(
    BT, "confirm_paired", return_value=(False, "BlueZ did not confirm the paired state.")
):
    result, response = invoke(BT.action, ["pair", DEVICE_PATH])
assert result == 1 and response["ok"] is False

with mock.patch.object(BT.shutil, "which", return_value="/usr/bin/busctl"), mock.patch.object(
    BT, "busctl_call", return_value=(0, "", "")
), mock.patch.object(
    BT, "confirm_paired", return_value=(True, "")
):
    result, response = invoke(BT.action, ["pair", DEVICE_PATH])
assert result == 0 and response["ok"] is True


class PairDoneConnection:
    @staticmethod
    def call_finish(result):
        return None


session = BT.PairingAgentSession(DEVICE_PATH)
events = []
session.emit_event = events.append
with mock.patch.object(
    BT, "confirm_paired", return_value=(False, "BlueZ did not confirm the paired state.")
):
    session.pair_done(PairDoneConnection(), object(), None)
assert session.finished is True
assert session.exit_code == 1
assert events[-1]["ok"] is False


# BLOCKER 5: opening/refreshing Link cannot own Bluetooth connection policy.
bluetooth_state = (LINK / "BluetoothState.qml").read_text(encoding="utf-8")
session_policy = (ROOT / "config/quickshell/maho-shell/BluetoothAutoConnect.qml").read_text(encoding="utf-8")
assert '"auto-connect"' not in bluetooth_state
assert "maybeAutoConnect" not in bluetooth_state
assert "autoConnectProcess" not in bluetooth_state
refresh_start = bluetooth_state.index("function refresh()")
refresh_end = bluetooth_state.index("\n    function runAction", refresh_start)
refresh_body = bluetooth_state[refresh_start:refresh_end]
assert 'snapshotProcess.exec(["python", backendPath(), "snapshot"])' in refresh_body
assert '"connect"' not in refresh_body.lower()
show_start = shell_source.index("function showMode(")
show_end = shell_source.index("\n    function showOverlay", show_start)
show_body = shell_source[show_start:show_end]
assert "bluetooth.refresh()" in show_body
assert "connectDevice" not in show_body
close_start = shell_source.index("function closeOverlay()")
close_end = shell_source.index("\n    Connections {", close_start)
close_body = shell_source[close_start:close_end]
assert "connectDevice" not in close_body
assert '"auto-connect-policy"' in session_policy

# Secure enterprise secret transport is an explicit package capability.
wifi_source = (LINK / "wifi.py").read_text(encoding="utf-8")
package_source = (ROOT / "packaging/arch/PKGBUILD.in").read_text(encoding="utf-8")
enterprise_start = wifi_source.index("def connect_enterprise(")
enterprise_end = wifi_source.index("\ndef open_captive_portal(", enterprise_start)
assert '"--ask"' not in wifi_source[enterprise_start:enterprise_end]
assert "'python-gobject'" in package_source


# SHOULD FIX: Agent1 Release terminates the helper and cancels pending prompts.
class ReleaseInvocation:
    def __init__(self):
        self.returned = None
        self.error = None

    def return_value(self, value):
        self.returned = value

    def return_dbus_error(self, name, message):
        self.error = (name, message)


class ReleaseParameters:
    @staticmethod
    def unpack():
        return ()


class ReleaseLoop:
    def __init__(self):
        self.quit_called = False

    def quit(self):
        self.quit_called = True


release_session = BT.PairingAgentSession(DEVICE_PATH)
release_events = []
release_session.emit_event = release_events.append
release_session.loop = ReleaseLoop()
pending = ReleaseInvocation()
release_session.pending[1] = {"kind": "confirm", "invocation": pending}
release_call = ReleaseInvocation()
release_session.method_call(
    None, "org.bluez", BT.AGENT_PATH, BT.AGENT, "Release",
    ReleaseParameters(), release_call,
)
assert release_call.returned is None
assert pending.error[0] == "org.bluez.Error.Canceled"
assert release_session.finished is True
assert release_session.loop.quit_called is True
assert release_events[-1]["type"] == "result"
assert "released" in release_events[-1]["message"].lower()

print("PASS  reviewed Maho Link blocker regressions")
