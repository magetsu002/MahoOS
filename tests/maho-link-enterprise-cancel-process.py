#!/usr/bin/env python3

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "config/quickshell/maho-link/wifi.py"
PROFILE_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

with tempfile.TemporaryDirectory() as temporary:
    temp = Path(temporary)
    bindir = temp / "bin"
    bindir.mkdir()
    log = temp / "nmcli.log"
    up_started = temp / "up-started"

    nmcli = bindir / "nmcli"
    nmcli.write_text(
        """#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$FAKE_NMCLI_LOG"
case "$*" in
  "-t -e yes -f DEVICE,TYPE,STATE device status")
    printf '%s\n' 'wlan0:wifi:disconnected'
    ;;
  "connection add "*)
    ;;
  "-g connection.uuid connection show id "*)
    printf '%s\n' "$FAKE_PROFILE_UUID"
    ;;
  "--wait 25 connection up uuid "*)
    : > "$FAKE_UP_STARTED"
    sleep 30
    ;;
  "connection delete uuid "*)
    ;;
  "connection delete id "*)
    ;;
  *)
    printf 'unexpected fake nmcli invocation: %s\n' "$*" >&2
    exit 64
    ;;
esac
""",
        encoding="utf-8",
    )
    nmcli.chmod(0o755)

    ca = temp / "ca.pem"
    client = temp / "client.pem"
    key = temp / "client.key"
    for path in (ca, client, key):
        path.write_text("test material\n", encoding="utf-8")

    options = {
        "identity": "device@example.com",
        "eap": "tls",
        "caCert": str(ca),
        "clientCert": str(client),
        "privateKey": str(key),
        "domainSuffix": "auth.example.com",
    }

    env = os.environ.copy()
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    env["FAKE_NMCLI_LOG"] = str(log)
    env["FAKE_PROFILE_UUID"] = PROFILE_UUID
    env["FAKE_UP_STARTED"] = str(up_started)

    process = subprocess.Popen(
        [sys.executable, str(BACKEND), "action", "connect-enterprise", "Corp TLS"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert process.stdin is not None
    process.stdin.write(json.dumps(options) + "\n")
    process.stdin.flush()

    deadline = time.monotonic() + 8
    while not up_started.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert up_started.exists(), "enterprise activation never reached provisional connection up"

    process.send_signal(signal.SIGTERM)
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode != 0, (process.returncode, stdout, stderr)

    responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    assert responses
    assert responses[-1]["ok"] is False
    assert "cancel" in responses[-1]["message"].lower()

    calls = log.read_text(encoding="utf-8").splitlines()
    delete = f"connection delete uuid {PROFILE_UUID}"
    assert delete in calls, calls
    assert any("connection.autoconnect no" in call for call in calls)
    assert not any("connection.autoconnect yes" in call for call in calls)
    assert not any("--ask" in call for call in calls)

print("PASS  enterprise SIGTERM cancellation cleans provisional profile")
