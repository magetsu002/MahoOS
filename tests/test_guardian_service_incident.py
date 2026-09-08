#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_service_incident import (  # noqa: E402
    RESTART_SCHEDULED,
    UNIT_FAILED,
    UNIT_STARTED,
    ServiceIncidentStore,
    ServiceSnapshot,
    incident_identity,
    normalize_journal_event,
)
from guardian_service_watcher import _journal_argv  # noqa: E402

BOOT_A = "a" * 32
BOOT_B = "b" * 32
FAILED_A = "1" * 32
FAILED_B = "2" * 32
REPLACEMENT = "3" * 32


def raw(message_id, invocation=FAILED_A, *, boot=BOOT_A, result="signal"):
    row = {
        "_COMM": "systemd",
        "USER_UNIT": "maho-notify.service",
        "_BOOT_ID": boot,
        "USER_INVOCATION_ID": invocation,
        "MESSAGE_ID": message_id,
        "__REALTIME_TIMESTAMP": "1800000000000000",
        "__CURSOR": "cursor-1",
    }
    if message_id == UNIT_FAILED:
        row["UNIT_RESULT"] = result
    elif message_id == RESTART_SCHEDULED:
        row["UNIT_RESULT"] = result
    elif message_id == UNIT_STARTED:
        row.update({"JOB_TYPE": "start", "JOB_RESULT": "done"})
    return row


def event(*args, **kwargs):
    value = normalize_journal_event(raw(*args, **kwargs))
    assert value is not None
    return value


def snap(invocation=REPLACEMENT, *, active="active", sub="running", restart="on-failure"):
    return ServiceSnapshot("maho-notify.service", "loaded", active, sub, "success", invocation, restart)


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def main():
    setup_source = (ROOT / "bin/maho-setup").read_text()
    check("transactional setup owns watcher command and core unit", "maho-guardian-watch" in setup_source and "maho-guardian.service" in setup_source)
    journal_argv = _journal_argv("cursor-before-failure")
    check("watcher uses structured continuous journal events", journal_argv[:5] == ["journalctl", "--user", "--follow", "--output=json", "--no-pager"] and "--unit" in journal_argv and "maho-notify.service" in journal_argv and journal_argv[-1] == "--after-cursor=cursor-before-failure")
    watcher_source = (ROOT / "lib/guardian_service_watcher.py").read_text()
    incident_source = (ROOT / "lib/guardian_service_incident.py").read_text()
    check("delegated watcher contains no direct restart command", '"restart"' not in watcher_source and '"restart"' not in incident_source)
    check("identity is deterministic", incident_identity(BOOT_A, "maho-notify.service", FAILED_A) == incident_identity(BOOT_A, "maho-notify.service", FAILED_A))
    check("different failed invocation is distinct", incident_identity(BOOT_A, "maho-notify.service", FAILED_A) != incident_identity(BOOT_A, "maho-notify.service", FAILED_B))
    check("new boot is a separate namespace", incident_identity(BOOT_A, "maho-notify.service", FAILED_A) != incident_identity(BOOT_B, "maho-notify.service", FAILED_A))
    check("intentional success is not a failure", normalize_journal_event(raw(UNIT_FAILED, result="success")) is None)
    malformed = raw(UNIT_FAILED); malformed["_BOOT_ID"] = "bad"
    check("malformed event fails closed", normalize_journal_event(malformed) is None)
    unknown = raw(UNIT_FAILED); unknown["USER_UNIT"] = "external.service"
    check("unknown service cannot self-certify", normalize_journal_event(unknown) is None)
    app_line = raw(UNIT_FAILED); app_line["_COMM"] = "quickshell"
    check("application logs cannot impersonate manager events", normalize_journal_event(app_line) is None)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = ServiceIncidentStore(root)
        detected = store.process(event(UNIT_FAILED), now=100.0)
        iid = detected["incident_id"]
        first_active = json.loads((root / "guardian/active" / f"{iid}.json").read_text())
        check("one failure event creates one active L1 incident", detected["lifecycle"] == "detected" and first_active["decision"]["severity"]["level"] == 1)
        store.process(event(UNIT_FAILED), now=101.0)
        check("duplicate observation does not duplicate state or history", len(list((root / "guardian/service-state").glob("*.json"))) == 1 and len(list((root / "guardian/recovery-history").glob("*.json"))) == 1)

        recovering = store.process(event(RESTART_SCHEDULED), now=102.0)
        active = json.loads((root / "guardian/active" / f"{iid}.json").read_text())
        decision = active["decision"]
        check("auto-restart is delegated recovery in progress", recovering["lifecycle"] == "recovering" and decision["execution_mode"] == "delegated")
        check("delegated recovery grants no Guardian mutation", decision["mutating_recovery_allowed"] is False)

        check("same invocation cannot masquerade as replacement", store.process(event(UNIT_STARTED, FAILED_A), now=103.0) is None)
        verifying = store.process(event(UNIT_STARTED, REPLACEMENT), now=103.0)
        check("replacement enters bounded verification", verifying["lifecycle"] == "verifying" and verifying["verify_after_epoch"] == 106.0)
        check("verification is not due early", store.due_verifications(105.99) == [])
        due = store.due_verifications(106.0)
        check("verification becomes due after stability interval", len(due) == 1 and due[0]["incident_id"] == iid)
        check("active/running exact replacement verifies", store.verify(due[0], snap(), timestamp="2027-01-15T08:00:03+00:00"))
        history_path = root / "guardian/recovery-history" / f"{iid}.json"
        history = json.loads(history_path.read_text())
        check("verified history attributes recovery to systemd", history["status"] == "succeeded" and history["verified"] is True and history["provider"] == "systemd-user" and history["guardian_mutation"] is False and history["guardian_severity"]["level"] == 1 and history["terminal_guardian_severity"]["level"] == 0)
        check("success resolves active incident and archives it", not (root / "guardian/active" / f"{iid}.json").exists() and len(list((root / "guardian/archive").glob(f"{iid}-*.json"))) == 1)
        before = history_path.read_bytes()
        check("terminal result is immutable to duplicate verification", store.verify(due[0], snap()) and history_path.read_bytes() == before)
        private = [root / "guardian", root / "guardian/active", history_path]
        check("Guardian state is private", all((os.stat(path).st_mode & 0o077) == 0 for path in private))
        check("atomic writer leaves no temporary files", not list((root / "guardian").rglob(".*.json.*")))

    with tempfile.TemporaryDirectory() as tmp:
        store = ServiceIncidentStore(Path(tmp))
        failed = store.process(event(UNIT_FAILED), now=200.0)
        store.process(event(RESTART_SCHEDULED), now=201.0)
        verifying = store.process(event(UNIT_STARTED, REPLACEMENT), now=202.0)
        check("same or unhealthy replacement cannot pass", not store.verify(verifying, snap(invocation=FAILED_A, active="activating", sub="auto-restart")))
        active_path = Path(tmp) / "guardian/active" / f"{failed['incident_id']}.json"
        unresolved = json.loads(active_path.read_text())
        history = json.loads((Path(tmp) / "guardian/recovery-history" / f"{failed['incident_id']}.json").read_text())
        check("unresolved recovery stays visible", unresolved["service_recovery"]["lifecycle"] == "unresolved" and history["status"] == "unresolved" and history["verified"] is False)
        check("exhausted provider becomes diagnosis-only L2", unresolved["decision"]["severity"]["level"] == 2 and unresolved["decision"]["execution_mode"] == "diagnose" and unresolved["decision"]["recovery"]["action"] == "diagnose-service-incident")
        check("no success record exists without verification", not list((Path(tmp) / "guardian/archive").glob("*.json")))

    with tempfile.TemporaryDirectory() as tmp:
        store = ServiceIncidentStore(Path(tmp))
        failed = store.process(event(UNIT_FAILED), now=300.0)
        recovering = store.process(event(RESTART_SCHEDULED), now=301.0)
        check("provider receives a bounded replacement window", recovering["recover_by_epoch"] == 306.0 and store.due_verifications(305.99) == [])
        due = store.due_verifications(306.0)
        check("missing replacement becomes due for failure verification", len(due) == 1)
        check("missing replacement cannot pass", not store.verify(due[0], snap(invocation=FAILED_A, active="failed", sub="failed")))
        history = json.loads((Path(tmp) / "guardian/recovery-history" / f"{failed['incident_id']}.json").read_text())
        check("provider timeout is recorded unresolved", history["status"] == "unresolved" and history["verified"] is False)

    with tempfile.TemporaryDirectory() as tmp:
        store = ServiceIncidentStore(Path(tmp))
        failed = store.process(event(UNIT_FAILED), now=400.0)
        due = store.due_verifications(405.0)
        check("failure without a restart schedule also expires safely", len(due) == 1 and due[0]["incident_id"] == failed["incident_id"] and not store.verify(due[0], snap(invocation=FAILED_A, active="failed", sub="failed")))

    print("ALL GUARDIAN SERVICE INCIDENT TESTS PASS")


if __name__ == "__main__":
    main()
