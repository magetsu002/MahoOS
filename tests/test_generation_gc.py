#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import replace
import errno
import json
from pathlib import Path
import sys
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import maho_generation_gc as gc  # noqa: E402
from maho_generation_gc import (  # noqa: E402
    GCExecutor, GCObject, GenerationInventory, IdentityMismatchError,
    InventoryError, ObjectKind, SimulatedCrash, StaleAuthorityError,
    inventory_status, plan_retention, read_inventory, write_inventory,
)


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def rejects(name: str, operation, errors=(ValueError, RuntimeError)) -> None:
    try:
        operation()
    except errors:
        print("PASS", name)
        return
    raise AssertionError(name)


def obj(
    object_id: str, kind: ObjectKind, sequence: int, *, refs=(), size=10,
    eligible=False, root=False, allowed=True, path=None, digest=None,
) -> GCObject:
    return GCObject(
        object_id, kind, sequence, size, tuple(sorted(refs)), path, digest,
        eligible, root, allowed,
    )


def policy_inventory() -> GenerationInventory:
    rows: list[GCObject] = []
    shared_kernel = obj("kernel-shared", ObjectKind.KERNEL_GENERATION, 30, refs=("boot-shared",))
    rows.extend((shared_kernel, obj("boot-shared", ObjectKind.BOOT_ARTIFACT, 30)))
    for sequence in range(1, 6):
        sid = f"system-{sequence}"
        kid = "kernel-shared" if sequence >= 4 else f"kernel-{sequence}"
        rid = f"root-{sequence}"
        pid = f"package-{sequence}"
        eid = f"evidence-{sequence}"
        refs = (kid, rid, pid, eid)
        rows.append(obj(sid, ObjectKind.SYSTEM_GENERATION, sequence * 10, refs=refs, eligible=True, root=True))
        if sequence < 4:
            rows.append(obj(kid, ObjectKind.KERNEL_GENERATION, sequence * 10, refs=(f"boot-{sequence}",)))
            rows.append(obj(f"boot-{sequence}", ObjectKind.BOOT_ARTIFACT, sequence * 10))
        rows.extend((
            obj(rid, ObjectKind.ROOT, sequence * 10),
            obj(pid, ObjectKind.PACKAGE_GENERATION, sequence * 10),
            obj(eid, ObjectKind.EVIDENCE, sequence * 10),
        ))
    rows.extend((
        obj("runtime-current", ObjectKind.RUNTIME, 50),
        obj("recovery-current", ObjectKind.RECOVERY, 50, refs=("recovery-evidence",)),
        obj("recovery-last", ObjectKind.RECOVERY, 40),
        obj("recovery-evidence", ObjectKind.EVIDENCE, 50),
        obj("candidate-active", ObjectKind.ABANDONED_CANDIDATE, 60, root=True),
        obj("update-active", ObjectKind.TRANSACTION, 60),
        obj("recovery-active", ObjectKind.TRANSACTION, 60),
        obj("incident-open", ObjectKind.EVIDENCE, 2),
        obj("rotation-rollback", ObjectKind.ROTATION_ROLLBACK, 3),
        obj("audit-history", ObjectKind.EVIDENCE, 1),
        obj("candidate-abandoned", ObjectKind.ABANDONED_CANDIDATE, 1, size=7, root=True),
        obj("staging-expired", ObjectKind.EXPIRED_STAGING, 1, size=8, root=True),
        obj("cache-old", ObjectKind.PACKAGE_CACHE, 1, size=9, root=True),
    ))
    return GenerationInventory(
        objects=tuple(sorted(rows, key=lambda item: item.object_id)),
        current_system_generation_id="system-5", running_kernel_generation_id="kernel-shared",
        current_root_id="root-5", current_runtime_id="runtime-current",
        current_recovery_ids=("recovery-current",), last_verified_recovery_id="recovery-last",
        active_candidate_ids=("candidate-active",), active_update_ids=("update-active",),
        active_recovery_ids=("recovery-active",),
        unresolved_incident_evidence_ids=("incident-open",),
        rotation_rollback_ids=("rotation-rollback",), audit_evidence_ids=("audit-history",),
    )


inventory = policy_inventory()
plan = plan_retention(inventory, free_bytes=0, safe_reserve_bytes=10_000)
protected = set(plan.protected_object_ids)
removed = set(plan.removal_object_ids)
check("normal retention keeps current plus two previous eligible SystemGenerations", set(plan.retained_system_generation_ids) == {"system-3", "system-4", "system-5"})
check(">3 SystemGenerations makes the two oldest eligible", {"system-1", "system-2"} <= removed)
check("dependency sharing protects a kernel referenced by retained generations", {"kernel-shared", "boot-shared"} <= protected)
check("current generation cannot become GC eligible", "system-5" in protected and "system-5" not in removed)
check("current root cannot become GC eligible", "root-5" in protected and "root-5" not in removed)
check("active candidate is protected", "candidate-active" in protected)
check("active update is protected", "update-active" in protected)
check("active recovery is protected", "recovery-active" in protected)
check("current and last independently verified recovery routes are protected", {"recovery-current", "recovery-last", "recovery-evidence"} <= protected)
only_recovery = replace(inventory, current_recovery_ids=("recovery-current",), last_verified_recovery_id=None)
check("the only recovery generation is never reclaimed", "recovery-current" in plan_retention(only_recovery, free_bytes=0, safe_reserve_bytes=10_000).protected_object_ids)
check("unresolved incident evidence is protected", "incident-open" in protected)
check("key rotation rollback material is protected", "rotation-rollback" in protected)
check("audit history is protected", "audit-history" in protected)
ordered = [inventory.by_id[item].kind for item in plan.removal_object_ids]
check("storage policy exposes deterministic reclaimable and protected bytes", inventory_status(inventory, free_bytes=0, safe_reserve_bytes=10_000)["reclaimable_bytes"] == plan.reclaimable_bytes)
check("unsafe reserve blocks update mutation after all safe reclamation", plan.reserve_restored is False and inventory_status(inventory, free_bytes=0, safe_reserve_bytes=10_000)["update_mutation_allowed"] is False)

enough = plan_retention(inventory, free_bytes=9_999, safe_reserve_bytes=10_000)
check("pressure ordering reclaims abandoned candidate first", enough.removal_object_ids == ("candidate-abandoned",))
none = plan_retention(inventory, free_bytes=10_000, safe_reserve_bytes=10_000)
check("no-pressure planning is non-mutating", not none.removal_object_ids and none.reserve_restored)

broken_ref = replace(inventory.objects[0], references=("missing-object",))
rejects(
    "corrupt metadata with a missing dependency fails closed",
    lambda: GenerationInventory(
        objects=tuple(sorted((broken_ref, *inventory.objects[1:]), key=lambda item: item.object_id)),
        current_system_generation_id=inventory.current_system_generation_id,
        running_kernel_generation_id=inventory.running_kernel_generation_id,
        current_root_id=inventory.current_root_id,
    ),
    (InventoryError,),
)


def executor_fixture(base: Path) -> tuple[GenerationInventory, Path, Path, GCExecutor]:
    data = base / "data"
    state = base / "state"
    data.mkdir()
    rows: list[GCObject] = []
    specs = (
        ("system-current", ObjectKind.SYSTEM_GENERATION, 20, ("root-current", "kernel-current"), True, True),
        ("root-current", ObjectKind.ROOT, 20, (), False, False),
        ("kernel-current", ObjectKind.KERNEL_GENERATION, 20, (), False, False),
        ("system-old", ObjectKind.SYSTEM_GENERATION, 10, ("root-old", "kernel-old"), False, True),
        ("root-old", ObjectKind.ROOT, 10, (), False, False),
        ("kernel-old", ObjectKind.KERNEL_GENERATION, 10, (), False, False),
    )
    for object_id, kind, sequence, refs, eligible, gc_root in specs:
        path = data / object_id
        path.write_text(f"content:{object_id}\n", encoding="utf-8")
        rows.append(obj(
            object_id, kind, sequence, refs=refs, eligible=eligible, root=gc_root,
            path=object_id, digest=gc._tree_sha256(path),
        ))
    inv = GenerationInventory(
        objects=tuple(sorted(rows, key=lambda item: item.object_id)),
        current_system_generation_id="system-current",
        running_kernel_generation_id="kernel-current", current_root_id="root-current",
    )
    inventory_path = base / "inventory.json"
    write_inventory(inventory_path, inv)
    return inv, inventory_path, data, GCExecutor(inventory_path=inventory_path, data_root=data, state_root=state)


def execution_plan(inv: GenerationInventory):
    return plan_retention(inv, free_bytes=0, safe_reserve_bytes=1)


with tempfile.TemporaryDirectory() as raw:
    base = Path(raw)
    inv, inventory_path, data, executor = executor_fixture(base)
    receipt = executor.execute(execution_plan(inv))
    check("normal GC commits exact target inventory", read_inventory(inventory_path).inventory_sha256 == execution_plan(inv).target_inventory.inventory_sha256)
    check("normal GC removes only superseded generation closure", not (data / "system-old").exists() and (data / "system-current").exists())
    check("GC publishes a content-bound receipt", receipt["receipt_sha256"] == gc.digest_payload({key: value for key, value in receipt.items() if key != "receipt_sha256"}))
    check("repeated GC resume is idempotent", executor.resume() == receipt)


for fault in ("after_prepare", "before_catalog_commit", "after_catalog_commit", "after_first_delete", "before_receipt"):
    with tempfile.TemporaryDirectory() as raw:
        base = Path(raw)
        inv, inventory_path, data, executor = executor_fixture(base)
        fault_plan = execution_plan(inv)
        rejects(f"{fault} interruption is surfaced", lambda f=fault: executor.execute(fault_plan, fault_at=f), (SimulatedCrash,))
        receipt = executor.resume()
        check(f"{fault} resumes idempotently to the exact target", read_inventory(inventory_path).inventory_sha256 == fault_plan.target_inventory.inventory_sha256 and receipt["target_inventory_sha256"] == fault_plan.target_inventory.inventory_sha256)
        check(f"{fault} never deletes current authority", (data / "system-current").exists())


with tempfile.TemporaryDirectory() as raw:
    base = Path(raw)
    inv, inventory_path, data, executor = executor_fixture(base)
    stale_plan = execution_plan(inv)
    changed = replace(inv, audit_evidence_ids=("root-current",))
    write_inventory(inventory_path, changed)
    rejects("stale inventory authority rejects execution", lambda: executor.execute(stale_plan), (StaleAuthorityError,))

with tempfile.TemporaryDirectory() as raw:
    base = Path(raw)
    inv, inventory_path, data, executor = executor_fixture(base)
    wrong_plan = execution_plan(inv)
    (data / "system-old").write_text("wrong identity\n", encoding="utf-8")
    rejects("wrong object identity rejects deletion", lambda: executor.execute(wrong_plan), (IdentityMismatchError,))
    check("wrong identity preserves authoritative inventory", read_inventory(inventory_path).inventory_sha256 == inv.inventory_sha256)

with tempfile.TemporaryDirectory() as raw:
    base = Path(raw)
    inv, inventory_path, data, executor = executor_fixture(base)
    missing_plan = execution_plan(inv)
    (data / "root-old").unlink()
    rejects("partially missing target rejects pre-commit mutation", lambda: executor.execute(missing_plan), (IdentityMismatchError,))
    check("partially missing target preserves authoritative inventory", read_inventory(inventory_path).inventory_sha256 == inv.inventory_sha256)

with tempfile.TemporaryDirectory() as raw:
    base = Path(raw)
    inv, inventory_path, data, executor = executor_fixture(base)
    inventory_path.write_text("{corrupt", encoding="utf-8")
    rejects("corrupted authoritative metadata fails closed", lambda: executor.execute(execution_plan(inv)), (InventoryError,))

for label, code in (("ENOSPC", errno.ENOSPC), ("read-only filesystem", errno.EROFS)):
    with tempfile.TemporaryDirectory() as raw:
        base = Path(raw)
        inv, inventory_path, data, executor = executor_fixture(base)
        capacity_plan = execution_plan(inv)
        real_atomic = gc._atomic_json

        def fail_first(path, value, mode=0o600):
            if path == executor.journal_path:
                raise OSError(code, label)
            return real_atomic(path, value, mode)

        with mock.patch.object(gc, "_atomic_json", side_effect=fail_first):
            rejects(f"{label} during journal publication blocks mutation", lambda: executor.execute(capacity_plan), (OSError,))
        check(f"{label} leaves authority and object bytes unchanged", read_inventory(inventory_path).inventory_sha256 == inv.inventory_sha256 and (data / "system-old").exists())

with tempfile.TemporaryDirectory() as raw:
    base = Path(raw)
    inv, inventory_path, data, executor = executor_fixture(base)
    receipt_plan = execution_plan(inv)
    real_atomic = gc._atomic_json
    failed = False

    def fail_receipt(path, value, mode=0o600):
        global failed
        if path.parent == executor.receipt_dir and not failed:
            failed = True
            raise OSError(errno.ENOSPC, "receipt ENOSPC")
        return real_atomic(path, value, mode)

    with mock.patch.object(gc, "_atomic_json", side_effect=fail_receipt):
        rejects("ENOSPC during receipt publication is resumable", lambda: executor.execute(receipt_plan), (OSError,))
    check("receipt ENOSPC keeps the committed target unambiguous", read_inventory(inventory_path).inventory_sha256 == receipt_plan.target_inventory.inventory_sha256)
    check("receipt publication resumes after capacity returns", executor.resume()["target_inventory_sha256"] == receipt_plan.target_inventory.inventory_sha256)

with tempfile.TemporaryDirectory() as raw:
    base = Path(raw)
    inv, inventory_path, data, executor = executor_fixture(base)
    power_plan = execution_plan(inv)
    rejects("simulated sudden power loss after metadata commit is recoverable", lambda: executor.execute(power_plan, fault_at="after_catalog_commit"), (SimulatedCrash,))
    check("power loss cannot leave authority referencing deleted content", read_inventory(inventory_path).inventory_sha256 == power_plan.target_inventory.inventory_sha256 and (data / "system-old").exists())
    executor.resume()
    check("power-loss resume completes deferred deletion", not (data / "system-old").exists())

print("ALL GENERATION RETENTION AND GC TESTS PASS")
