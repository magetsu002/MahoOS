#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_reliability import (
    FailureOccurrence,
    ReliabilityObservation,
    ReliabilityState,
    RemediationDisposition,
    assess_observation,
    assess_recurrence,
    load_live_reliability,
)
from guardian_reliability_provider import memory_facts, refresh_once, service_facts


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def fake_systemctl(argv, **kwargs):
    unit = argv[3]
    output = "LoadState=loaded\nActiveState=active\nSubState=running\nNRestarts=0\n"
    if unit == "maho-notify.service":
        output = "LoadState=loaded\nActiveState=failed\nSubState=failed\nNRestarts=4\n"
    return subprocess.CompletedProcess(argv, 0, output, "")


def main() -> None:
    stale = assess_observation(ReliabilityObservation("x", "memory", "host", "stale", "healthy", {"available_percent": 90}))
    check("stale clean evidence is unknown, never healthy", stale.state is ReliabilityState.UNKNOWN)

    unknown_service = assess_observation(ReliabilityObservation("svc", "service", "third-party.service", "current", "healthy", {"active_state": "failed", "restart_count": 8}))
    check("unknown service failure does not invent remediation", unknown_service.remediation is RemediationDisposition.OBSERVE_ONLY and not unknown_service.authority_granted)

    certified = assess_observation(ReliabilityObservation("svc", "service", "maho-notify.service", "current", "healthy", {"active_state": "failed", "restart_count": 4}))
    check("certified service churn maps only to delegated provider", certified.remediation is RemediationDisposition.DELEGATED_CERTIFIED and certified.provider == "systemd-user")
    check("reliability finding never grants authority", not certified.authority_granted)

    memory = assess_observation(ReliabilityObservation("mem", "memory", "host", "current", "healthy", {"available_percent": 5.0}))
    check("memory pressure is degraded", memory.state is ReliabilityState.DEGRADED)
    disk = assess_observation(ReliabilityObservation("disk", "storage", "/", "current", "healthy", {"used_percent": 95.0}))
    check("disk pressure is degraded", disk.state is ReliabilityState.DEGRADED)
    journal = assess_observation(ReliabilityObservation("journal", "journal", "user-journal", "current", "healthy", {"continuity": "continuous", "dropped_events": 2}))
    check("journal drops are degraded", journal.state is ReliabilityState.DEGRADED)

    transaction = assess_observation(ReliabilityObservation("tx", "transaction", "maho-runtime", "current", "healthy", {"age_seconds": 4000, "max_age_seconds": 1800}))
    check("stuck runtime transaction references existing recovery but still requires authority", transaction.remediation is RemediationDisposition.AUTHORIZATION_REQUIRED and not transaction.authority_granted)

    occurrences = [
        FailureOccurrence("same-failure", "2026-09-15T11:30:00Z", "history"),
        FailureOccurrence("same-failure", "2026-09-15T11:40:00Z", "history"),
        FailureOccurrence("same-failure", "2026-09-15T11:50:00Z", "history"),
        FailureOccurrence("other", "2026-09-15T11:55:00Z", "history"),
    ]
    recurrence = assess_recurrence("same-failure", occurrences, now="2026-09-15T12:00:00Z")
    check("bounded recurrence detects repeated stable failure identity", recurrence.repeated and recurrence.count == 3)
    check("recurrence cannot fabricate causal proof or recovery authority", not recurrence.causal_proof_granted and not recurrence.recovery_authority_granted)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        proc = root / "proc"
        proc.mkdir()
        (proc / "meminfo").write_text("MemTotal:       100000 kB\nMemAvailable:    8000 kB\n", encoding="utf-8")
        facts = memory_facts(proc)
        check("procfs memory observer reports normalized availability", round(facts["available_percent"], 1) == 8.0)
        services = service_facts(runner=fake_systemctl)
        notify = next(row for row in services["services"] if row["unit"] == "maho-notify.service")
        check("service observer records restart count and active state", notify["restart_count"] == 4 and notify["active_state"] == "failed")
        refresh_once(root, boot_id="boot-test", proc_root=proc, storage_path=root, runner=fake_systemctl)
        check("always-on sampler persisted memory evidence", (root / "guardian/reliability/memory.json").is_file())
        check("always-on sampler persisted storage evidence", (root / "guardian/reliability/storage.json").is_file())
        check("always-on sampler persisted service evidence", (root / "guardian/reliability/services.json").is_file())
        reliability, freshness = load_live_reliability(root, now=datetime.now(timezone.utc))
        check("fresh reliability heartbeats are current", all(row["freshness"] == "current" for row in freshness.values()))
        check("live projection sees certified service degradation", reliability["state"] == "degraded")
        check("live reliability projection exposes no automatic authority", reliability["automatic_authority"] is False)

    print("ALL GUARDIAN RELIABILITY TESTS PASS")


if __name__ == "__main__":
    main()
