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
import guardian_service_watcher as watcher  # noqa: E402
from guardian_service_watcher import _decode_chunk, _journal_argv  # noqa: E402

BOOT_A = "a" * 32
BOOT_B = "b" * 32
FAILED_A = "1" * 32
FAILED_B = "2" * 32
REPLACEMENT = "3" * 32
LATER = "4" * 32
LATER_2 = "5" * 32


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


def snap(invocation=REPLACEMENT, *, boot=BOOT_A, active="active", sub="running", restart="on-failure", health_ok=True):
    return ServiceSnapshot(
        "maho-notify.service", "loaded", active, sub, "success", invocation, restart,
        "quickshell-notify-runtime", health_ok,
        ("quickshell -p /config/maho-notify/shell.qml",), boot,
    )


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
    check("always-on reconciliation can retire stale active latches only through bounded verification", "_reconcile_service_state(" in watcher_source and "store.arm_supersession(" in watcher_source)
    check("service reconciliation has a bounded periodic wake even under journal load", "SERVICE_RECONCILE_SECONDS = 30.0" in watcher_source and "next_service_reconcile" in watcher_source)
    burst = b"prefix" + b' suffix"}\n{"one":1}\n{"two":2}\npartial'
    remainder, rows = _decode_chunk(b'{"zero":0,"text":"', burst)
    check("one readable journal burst drains every complete event", rows == [{"zero": 0, "text": "prefix suffix"}, {"one": 1}, {"two": 2}] and remainder == b"partial")
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
        check("active/running exact replacement and service health verifies", store.verify(due[0], snap(), timestamp="2027-01-15T08:00:03+00:00"))
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
        store.process(event(UNIT_FAILED), now=250.0)
        store.process(event(RESTART_SCHEDULED), now=251.0)
        verifying = store.process(event(UNIT_STARTED, REPLACEMENT), now=252.0)
        check("service-specific failed postcondition cannot pass", not store.verify(verifying, snap(health_ok=False)))

    with tempfile.TemporaryDirectory() as tmp:
        store = ServiceIncidentStore(Path(tmp))
        failed = store.process(event(UNIT_FAILED), now=300.0)
        recovering = store.process(event(RESTART_SCHEDULED), now=301.0)
        repeated = store.process(event(RESTART_SCHEDULED), now=304.0)
        check("provider receives a bounded replacement window", recovering["recover_by_epoch"] == 306.0 and store.due_verifications(305.99) == [])
        check("duplicate recovery observation cannot extend provider deadline", repeated["recover_by_epoch"] == 306.0)
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

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = ServiceIncidentStore(root)
        failed = store.process(event(UNIT_FAILED), now=500.0)
        store.process(event(RESTART_SCHEDULED), now=501.0)
        verifying = store.process(event(UNIT_STARTED, REPLACEMENT), now=502.0)
        check("bounded provider miss creates unresolved recovery truth", not store.verify(verifying, snap(invocation=REPLACEMENT, active="activating", sub="auto-restart")))
        iid = failed["incident_id"]
        history_path = root / "guardian/recovery-history" / f"{iid}.json"
        check("failed delegated recovery is recorded before supersession", json.loads(history_path.read_text())["status"] == "unresolved")

        store.process(event(UNIT_STARTED, FAILED_A), now=510.0)
        stale_state = json.loads((root / "guardian/service-state" / f"{iid}.json").read_text())
        check("failed invocation cannot supersede its own incident", stale_state.get("supersession") is None)

        store.process(event(UNIT_STARTED, LATER), now=511.0)
        armed = json.loads((root / "guardian/service-state" / f"{iid}.json").read_text())
        check("later invocation arms independent stability verification", armed["supersession"]["candidate_invocation_id"] == LATER and armed["supersession"]["verify_after_epoch"] == 514.0)
        rearmed = store.arm_supersession(
            unit="maho-notify.service", boot_id=BOOT_A, invocation_id=LATER, now=512.0,
        )
        stable_deadline = json.loads((root / "guardian/service-state" / f"{iid}.json").read_text())
        check("same healthy candidate cannot reset supersession deadline", rearmed == [] and stable_deadline["supersession"]["verify_after_epoch"] == 514.0)
        check("supersession is not due before the stability window", store.due_verifications(513.99) == [])
        due = store.due_verifications(514.0)
        check("supersession becomes due after the normal stability window", len(due) == 1 and due[0]["incident_id"] == iid)
        check("unhealthy later invocation cannot retire stale incident", not store.verify(due[0], snap(invocation=LATER, health_ok=False)))
        still_active = json.loads((root / "guardian/active" / f"{iid}.json").read_text())
        check("failed supersession verification keeps original L2 active", still_active["decision"]["severity"]["level"] == 2)

        store.process(event(UNIT_STARTED, LATER_2), now=520.0)
        due = store.due_verifications(523.0)
        check("verified later service does not rewrite original recovery as successful", not store.verify(due[0], snap(invocation=LATER_2), timestamp="2027-01-15T08:10:00+00:00"))
        history = json.loads(history_path.read_text())
        check("superseded history preserves failed recovery truth", history["status"] == "superseded" and history["verified"] is False and history["guardian_severity"]["level"] == 2 and history["terminal_guardian_severity"]["level"] == 0)
        check("supersession records independently verified current service", history["superseded_by_service"]["invocation_id"] == LATER_2 and history["superseded_by_service"]["health_ok"] is True)
        check("superseded incident no longer latches Guardian active state", not (root / "guardian/active" / f"{iid}.json").exists())
        archived = json.loads(next((root / "guardian/archive").glob(f"{iid}-superseded.json")).read_text())
        check("archive explains supersession instead of fake recovery success", archived["resolution"]["kind"] == "superseded-by-verified-service-invocation" and archived["decision"]["severity"]["level"] == 0)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = ServiceIncidentStore(root)
        failed = store.process(event(UNIT_FAILED, boot=BOOT_A), now=600.0)
        store.process(event(RESTART_SCHEDULED, boot=BOOT_A), now=601.0)
        verifying = store.process(event(UNIT_STARTED, REPLACEMENT, boot=BOOT_A), now=602.0)
        check("old boot failed recovery becomes unresolved", not store.verify(verifying, snap(active="activating", sub="auto-restart")))
        iid = failed["incident_id"]

        store.process(event(UNIT_STARTED, LATER, boot=BOOT_B), now=610.0)
        armed = json.loads((root / "guardian/service-state" / f"{iid}.json").read_text())
        supersession = armed["supersession"]
        check("healthy start on a later boot arms stale incident retirement", supersession["candidate_boot_id"] == BOOT_B and supersession["candidate_invocation_id"] == LATER and supersession["verify_after_epoch"] == 613.0)
        due = store.due_verifications(613.0)
        check("later-boot retirement still waits for stability window", len(due) == 1 and due[0]["incident_id"] == iid)
        check("wrong boot cannot retire stale incident", not store.verify(due[0], snap(invocation=LATER, boot=BOOT_A)))
        check("wrong-boot verification leaves original incident active", (root / "guardian/active" / f"{iid}.json").exists())

        store.process(event(UNIT_STARTED, LATER_2, boot=BOOT_B), now=620.0)
        due = store.due_verifications(623.0)
        check("verified current boot retires stale prior-boot L2", not store.verify(due[0], snap(invocation=LATER_2, boot=BOOT_B), timestamp="2027-01-15T08:20:00+00:00"))
        history = json.loads((root / "guardian/recovery-history" / f"{iid}.json").read_text())
        check("cross-boot supersession preserves original failed recovery truth", history["status"] == "superseded" and history["verified"] is False and history["superseded_by_service"]["boot_id"] == BOOT_B)
        check("cross-boot supersession clears only active latch", not (root / "guardian/active" / f"{iid}.json").exists())

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = ServiceIncidentStore(root)
        failed = store.process(event(UNIT_FAILED), now=700.0)
        due = store.due_verifications(705.0)
        check("fixture reaches unresolved state before periodic convergence", len(due) == 1 and not store.verify(due[0], snap(invocation=FAILED_A, active="failed", sub="failed")))
        iid = failed["incident_id"]

        original_units = watcher.certified_service_units
        original_snapshot = watcher.snapshot
        watcher.certified_service_units = lambda: ("maho-notify.service",)
        watcher.snapshot = lambda unit: snap(invocation=LATER, boot=BOOT_A)
        try:
            watcher._reconcile_service_state(store, BOOT_A, now=710.0)
            first = json.loads((root / "guardian/service-state" / f"{iid}.json").read_text())
            watcher._reconcile_service_state(store, BOOT_A, now=711.0)
            second = json.loads((root / "guardian/service-state" / f"{iid}.json").read_text())
        finally:
            watcher.certified_service_units = original_units
            watcher.snapshot = original_snapshot

        check("periodic healthy observation arms stale incident retirement", first["supersession"]["candidate_invocation_id"] == LATER)
        check("periodic re-observation preserves the original stability deadline", first["supersession"]["verify_after_epoch"] == 713.0 and second["supersession"]["verify_after_epoch"] == 713.0)
        due = store.due_verifications(713.0)
        check("periodically armed supersession becomes due", len(due) == 1 and due[0]["incident_id"] == iid)
        check("verified periodic convergence preserves failed recovery truth", not store.verify(due[0], snap(invocation=LATER, boot=BOOT_A), timestamp="2027-01-15T08:30:00+00:00"))
        history = json.loads((root / "guardian/recovery-history" / f"{iid}.json").read_text())
        check("periodic convergence retires stale active latch as superseded", history["status"] == "superseded" and not (root / "guardian/active" / f"{iid}.json").exists())

    print("ALL GUARDIAN SERVICE INCIDENT TESTS PASS")


if __name__ == "__main__":
    main()
