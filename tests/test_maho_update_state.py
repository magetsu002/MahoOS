#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_update_state import (  # noqa: E402
    UpdateState,
    create_transaction,
    new_transaction_id,
    package_generation_id,
    publish_transaction,
    read_transaction,
    transaction_path,
    transaction_receipt,
    transition_transaction,
    validate_transaction,
    write_transaction,
)

NOW = datetime(2026, 9, 12, 1, 2, 3, tzinfo=timezone.utc)
TXID = "upd-20260912T010203Z-abcdef123456"
SHA = "a" * 40


def packages() -> list[dict]:
    return [
        {"name": "maho-os", "installed_version": "1", "candidate_version": "2", "repository": "maho", "download_size": 10, "installed_size": 20, "roles": ["maho-runtime"]},
        {"name": "linux-cachyos", "installed_version": "7.1", "candidate_version": "7.2", "repository": "cachyos", "download_size": 30, "installed_size": 40, "roles": ["kernel"], "security_relevant": True},
    ]


def sample() -> dict:
    return create_transaction(
        transaction_id=TXID,
        source_revision=SHA,
        packages=packages(),
        activation_requirements=["restart", "initramfs", "boot-artifacts"],
        recovery_generation_id="g3-1234567890abcdef12345678",
        now=NOW,
    )


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def rejected(name: str, function) -> None:
    try:
        function()
    except (ValueError, TypeError):
        check(name, True)
        return
    check(name, False)


def at(minutes: int) -> datetime:
    return NOW + timedelta(minutes=minutes)


def main() -> None:
    check("transaction identity is deterministic with injected entropy", new_transaction_id(now=NOW, entropy="abcdef123456") == TXID)
    generation = package_generation_id(packages())
    check("package generation identity is exact and stable", generation == package_generation_id(reversed(packages())))
    discovered = sample()
    check("new transaction begins DISCOVERED", discovered["state"] == "DISCOVERED")
    check("native execution is explicitly uncertified", discovered["activation"]["native_execution_certified"] is False)
    check("native L3 relationship is explicitly uncertified", discovered["recovery"]["native_l3_certified"] is False)

    staged = transition_transaction(discovered, UpdateState.STAGED, evidence={"payloads": "complete"}, now=at(1))
    prepared = transition_transaction(staged, UpdateState.PREPARED, now=at(2))
    ready = transition_transaction(prepared, UpdateState.MAINTENANCE_READY, now=at(3))
    installing = transition_transaction(ready, UpdateState.INSTALLING, now=at(4))
    pending = transition_transaction(installing, UpdateState.INSTALLED_PENDING_ACTIVATION, reason="activation awaits explicit restart", now=at(5))
    verifying = transition_transaction(pending, UpdateState.ACTIVE_VERIFYING, now=at(6))
    healthy = transition_transaction(verifying, UpdateState.HEALTHY, reason="post-activation verification passed", now=at(7))
    check("complete healthy chain is explicit", [item["state"] for item in healthy["history"]] == [state.value for state in (
        UpdateState.DISCOVERED, UpdateState.STAGED, UpdateState.PREPARED, UpdateState.MAINTENANCE_READY,
        UpdateState.INSTALLING, UpdateState.INSTALLED_PENDING_ACTIVATION, UpdateState.ACTIVE_VERIFYING, UpdateState.HEALTHY,
    )])
    rejected("terminal healthy state cannot be rewritten", lambda: transition_transaction(healthy, UpdateState.ATTENTION_REQUIRED, reason="no"))
    rejected("phase skipping fails closed", lambda: transition_transaction(discovered, UpdateState.PREPARED))

    blocked = transition_transaction(staged, UpdateState.BLOCKED, blockers=["insufficient_disk"], now=at(2))
    resumed = transition_transaction(blocked, UpdateState.STAGED, reason="disk blocker cleared", now=at(3))
    check("blocked transaction resumes only at its exact checkpoint", resumed["state"] == "STAGED")
    rejected("blocked transaction cannot invent later progress", lambda: transition_transaction(blocked, UpdateState.MAINTENANCE_READY))
    failed = transition_transaction(staged, UpdateState.FAILED_RECOVERABLE, reason="download interrupted", now=at(2))
    recovering = transition_transaction(failed, UpdateState.RECOVERING, reason="cleaning bounded staging residue", now=at(3))
    recovered = transition_transaction(recovering, UpdateState.RECOVERED, reason="staging residue removed", now=at(4))
    check("recoverable failure has an unambiguous terminal recovery", recovered["state"] == "RECOVERED")

    tampered = json.loads(json.dumps(staged))
    tampered["package_generation"]["packages"][0]["candidate_version"] = "999"
    rejected("candidate tampering breaks immutable generation identity", lambda: validate_transaction(tampered))
    gate = json.loads(json.dumps(staged))
    gate["activation"]["native_execution_certified"] = True
    rejected("native update certification cannot be forged", lambda: validate_transaction(gate))
    l3 = json.loads(json.dumps(staged))
    l3["recovery"]["native_l3_certified"] = True
    rejected("native L3 certification cannot be forged", lambda: validate_transaction(l3))
    ambiguous = json.loads(json.dumps(staged))
    ambiguous["state"] = "UPDATED"
    rejected("vague boolean-like update state is rejected", lambda: validate_transaction(ambiguous))
    history = json.loads(json.dumps(staged))
    history["history"][1]["state"] = "PREPARED"
    rejected("tampered history is rejected", lambda: validate_transaction(history))

    receipt = transaction_receipt(pending)
    check("receipt exposes exact package and kernel changes", receipt["package_generation_id"] == generation and receipt["kernel_changes"] == ["linux-cachyos"])
    check("receipt exposes activation and recovery relationship", receipt["activation_required"] and receipt["recovery_generation"].startswith("g3-"))

    with tempfile.TemporaryDirectory(prefix="maho-update-state-") as temporary:
        path = transaction_path(temporary, TXID)
        write_transaction(path, pending)
        check("durable state roundtrip is exact", read_transaction(path) == pending)
        check("root-owned authority is readable by product consumers", path.stat().st_mode & 0o777 == 0o644)
        check("durable state leaves no temporary residue", not [item for item in path.parent.iterdir() if item.name.startswith(".")])
        rejected("durable path must bind transaction identity", lambda: write_transaction(path.with_name("upd-20260912T010203Z-000000000000.json"), pending))
        published = publish_transaction(Path(temporary) / "published", pending)
        check("published authority binds an exact current pointer", published.is_file() and (Path(temporary) / "published/current").read_text().strip() == TXID)
        check("current authority pointer is read-only to product consumers", (Path(temporary) / "published/current").stat().st_mode & 0o777 == 0o644)

    print("ALL MAHO UPDATE STATE CONTRACTS PASS")


if __name__ == "__main__":
    main()
