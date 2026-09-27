#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_installer_execute import (  # noqa: E402
    MUTATING_PHASES,
    PHASES,
    STORAGE_PHASES,
    SimulatedInterruption,
    execute_storage_plan,
)
from maho_installer_plan import MINIMUM_DISK_BYTES, build_install_plan  # noqa: E402

REV = "a" * 40
ATTEMPT_A = "11111111-1111-4111-8111-111111111111"
ATTEMPT_B = "22222222-2222-4222-8222-222222222222"


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def rejected(label: str, function, expected=(ValueError, RuntimeError, PermissionError)) -> None:
    try:
        function()
    except expected:
        print("PASS", label)
        return
    raise AssertionError(label)


def disk() -> dict:
    return {
        "path": "/dev/vdz", "type": "disk", "size": MINIMUM_DISK_BYTES,
        "ro": 0, "rm": 0, "model": "QEMU HARDDISK",
        "serial": "MAHO-DISPOSABLE-EXEC", "wwn": "", "tran": "virtio",
        "back-file": "", "log-sec": 512, "phy-sec": 4096,
        "maj:min": "252:99", "mountpoints": [None], "pttype": None, "fstype": None,
    }


class FakeOps:
    def __init__(self, observed: dict | None = None) -> None:
        self.disk = copy.deepcopy(observed or disk())
        self.completed: set[str] = set()
        self.partial: set[str] = set()
        self.applied: list[str] = []
        self.observations = 0
        self.raise_during: str | None = None

    def observe(self, device: str) -> dict:
        assert device == self.disk["path"]
        self.observations += 1
        result = copy.deepcopy(self.disk)
        if "GPT_CREATED" in self.completed:
            result["pttype"] = "gpt"
            result["children"] = [
                {"path": device + "1", "type": "part", "mountpoints": [None]},
                {"path": device + "2", "type": "part", "mountpoints": [None]},
            ]
        if "MOUNTED" in self.completed:
            result["children"][0]["mountpoints"] = ["/mnt/maho/boot"]
            result["children"][1]["mountpoints"] = ["/mnt/maho"]
        return result

    def is_disposable(self, observed) -> bool:
        return str(observed.get("serial", "")).startswith("MAHO-DISPOSABLE-")

    def phase_complete(self, phase, plan, mount_root) -> bool:
        return phase in self.completed

    def phase_started(self, phase, plan, mount_root) -> bool:
        return phase in self.partial

    def apply_phase(self, phase, plan, mount_root, key_file) -> None:
        expected = MUTATING_PHASES[len(self.applied)]
        if phase != expected:
            raise AssertionError(f"out-of-order mutation: {phase}, expected {expected}")
        self.applied.append(phase)
        if self.raise_during == phase:
            raise RuntimeError(f"simulated mid-phase failure: {phase}")
        self.completed.add(phase)


def invoke(plan, tmp: Path, ops: FakeOps, *, confirmation: str | None = None, plan_id: str | None = None, fail_after: str | None = None):
    key = tmp / "key"
    if not key.exists():
        key.write_bytes(b"disposable-test-key\n")
        key.chmod(0o600)
    return execute_storage_plan(
        plan,
        plan_id=plan_id or plan["plan_id"],
        confirmation=confirmation or plan["destructive_confirmation"],
        journal_path=tmp / "journal.json",
        mount_root=tmp / "mnt/maho",
        key_file=key,
        source_revision=REV,
        ops=ops,
        fail_after=fail_after,
        require_root=False,
    )


def main() -> None:
    plan = build_install_plan(disk(), source_revision=REV, install_attempt_id=ATTEMPT_A)

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ops = FakeOps()
        rejected("wrong confirmation performs no mutation", lambda: invoke(plan, tmp, ops, confirmation="ERASE-MAHO:" + "0" * 64))
        check("wrong confirmation creates no journal", not (tmp / "journal.json").exists() and not ops.applied)

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ops = FakeOps()
        rejected("wrong exact plan ID performs no mutation", lambda: invoke(plan, tmp, ops, plan_id="install-plan-" + "0" * 64))
        check("wrong plan ID creates no journal", not (tmp / "journal.json").exists() and not ops.applied)

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        physical = disk()
        physical["serial"] = "PHYSICAL-SYSTEM-DISK"
        physical_plan = build_install_plan(
            physical, source_revision=REV, install_attempt_id=ATTEMPT_A,
        )
        ops = FakeOps(physical)
        rejected("non-disposable target is rejected", lambda: invoke(physical_plan, tmp, ops))
        check("physical rejection occurs before journal and writes", not (tmp / "journal.json").exists() and not ops.applied)

    for injected_phase in MUTATING_PHASES:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            ops = FakeOps()
            try:
                invoke(plan, tmp, ops, fail_after=injected_phase)
            except SimulatedInterruption:
                pass
            else:
                raise AssertionError(f"missing interruption after {injected_phase}")
            journal = json.loads((tmp / "journal.json").read_text(encoding="utf-8"))
            check(f"journal is durable after {injected_phase}", journal["phase"] == injected_phase)
            check(f"journal preserves attempt identity after {injected_phase}", journal["install_attempt_id"] == ATTEMPT_A)
            expected_history = list(PHASES[:PHASES.index(injected_phase) + 1])
            check(f"journal history is coherent after {injected_phase}", [row["phase"] for row in journal["history"]] == expected_history)
            resumed = invoke(plan, tmp, ops)
            check(f"resume reaches MOUNTED after {injected_phase}", resumed["phase"] == "MOUNTED")
            check(f"resume never duplicates mutation after {injected_phase}", ops.applied == list(MUTATING_PHASES))

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ops = FakeOps()
        try:
            invoke(plan, tmp, ops, fail_after="GPT_CREATED")
        except SimulatedInterruption:
            pass
        ops.disk["serial"] = "MAHO-DISPOSABLE-WRONG"
        ops.disk["maj:min"] = "252:100"
        before = list(ops.applied)
        rejected("wrong disk cannot resume old journal", lambda: invoke(plan, tmp, ops))
        check("wrong-disk resume performs no further mutation", ops.applied == before)

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ops = FakeOps()
        try:
            invoke(plan, tmp, ops, fail_after="GPT_CREATED")
        except SimulatedInterruption:
            pass
        different_attempt = build_install_plan(
            disk(), source_revision=REV, install_attempt_id=ATTEMPT_B,
        )
        before = list(ops.applied)
        rejected("resume cannot switch persisted install attempt", lambda: invoke(different_attempt, tmp, ops))
        check("attempt mismatch performs no further mutation", ops.applied == before)

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ops = FakeOps()
        try:
            invoke(plan, tmp, ops, fail_after="GPT_CREATED")
        except SimulatedInterruption:
            pass
        journal_path = tmp / "journal.json"
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        journal.pop("install_attempt_id")
        journal_path.write_text(json.dumps(journal) + "\n", encoding="utf-8")
        before = list(ops.applied)
        rejected("journal missing install attempt identity fails closed", lambda: invoke(plan, tmp, ops))
        check("missing attempt identity performs no further mutation", ops.applied == before)

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ops = FakeOps()
        try:
            invoke(plan, tmp, ops, fail_after="GPT_CREATED")
        except SimulatedInterruption:
            pass
        journal_path = tmp / "journal.json"
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        journal["schema_version"] = 1
        journal_path.write_text(json.dumps(journal) + "\n", encoding="utf-8")
        before = list(ops.applied)
        rejected("incompatible old journal fails closed", lambda: invoke(plan, tmp, ops))
        check("incompatible journal performs no further mutation", ops.applied == before)

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ops = FakeOps()
        ops.completed.add("GPT_CREATED")
        rejected("unjournaled mutation aborts instead of duplicating", lambda: invoke(plan, tmp, ops))
        check("unjournaled mutation is not repeated", not ops.applied)

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ops = FakeOps()
        try:
            invoke(plan, tmp, ops, fail_after="GPT_CREATED")
        except SimulatedInterruption:
            pass
        ops.partial.add("ESP_FORMATTED")
        before = list(ops.applied)
        rejected("partially started phase aborts for inspection", lambda: invoke(plan, tmp, ops))
        check("partial phase is never blindly retried", ops.applied == before)

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ops = FakeOps()
        ops.raise_during = "ESP_FORMATTED"
        rejected("mid-phase interruption is surfaced", lambda: invoke(plan, tmp, ops))
        journal = json.loads((tmp / "journal.json").read_text(encoding="utf-8"))
        check("journal records the in-progress crash window", journal["phase"] == "GPT_CREATED" and journal["in_progress_phase"] == "ESP_FORMATTED")
        ops.raise_during = None
        before = list(ops.applied)
        rejected("mid-phase journal cannot auto-resume", lambda: invoke(plan, tmp, ops))
        check("mid-phase command is not duplicated", ops.applied == before)

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ops = FakeOps()
        journal = invoke(plan, tmp, ops)
        check("clean storage run records every required phase", [row["phase"] for row in journal["history"]] == list(STORAGE_PHASES))
        check("target is observed at planning gate, confirmation gate, and immediately pre-write", ops.observations >= 3)

    print("ALL MAHO INSTALLER EXECUTION CONTRACTS PASS")


if __name__ == "__main__":
    main()
