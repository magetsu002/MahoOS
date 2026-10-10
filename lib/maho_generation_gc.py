#!/usr/bin/env python3
"""Identity-aware generation retention and crash-safe garbage collection.

The inventory is the deletion authority.  A plan binds its exact digest and
contains only inventory object identities; paths are bounded below data_root.
The executor first commits an inventory without the selected objects and only
then removes their bytes.  Therefore interruption can leave excess bytes, but
can never leave authoritative metadata referencing deleted content.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import stat
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
PLAN_SCHEMA_VERSION = 1
JOURNAL_SCHEMA_VERSION = 1


class InventoryError(ValueError):
    """The supplied authority is incomplete, corrupt, or internally stale."""


class StaleAuthorityError(RuntimeError):
    """The inventory no longer matches the authority used to create a plan."""


class IdentityMismatchError(RuntimeError):
    """An on-disk object is not the exact object authorized for deletion."""


class SimulatedCrash(RuntimeError):
    """Test-only interruption at a durable transaction boundary."""


class ObjectKind(str, Enum):
    SYSTEM_GENERATION = "system_generation"
    KERNEL_GENERATION = "kernel_generation"
    PACKAGE_GENERATION = "package_generation"
    ROOT = "root"
    BOOT_ARTIFACT = "boot_artifact"
    RECOVERY = "recovery"
    RUNTIME = "runtime"
    MANIFEST = "manifest"
    EVIDENCE = "evidence"
    TRANSACTION = "transaction"
    ROTATION_ROLLBACK = "rotation_rollback"
    ABANDONED_CANDIDATE = "abandoned_candidate"
    EXPIRED_STAGING = "expired_staging"
    PACKAGE_CACHE = "package_cache"
    OTHER = "other"


_ROOT_PRIORITY = {
    ObjectKind.ABANDONED_CANDIDATE: 0,
    ObjectKind.EXPIRED_STAGING: 1,
    ObjectKind.PACKAGE_CACHE: 2,
    ObjectKind.SYSTEM_GENERATION: 3,
    ObjectKind.OTHER: 4,
}


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest_payload(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _bounded_relative_path(value: str | None) -> str | None:
    if value is None:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or value in {"", "."} or ".." in path.parts:
        raise InventoryError("object paths must be non-empty bounded relative paths")
    return str(path)


@dataclass(frozen=True)
class GCObject:
    object_id: str
    kind: ObjectKind
    created_sequence: int
    size_bytes: int
    references: tuple[str, ...] = ()
    relative_path: str | None = None
    content_sha256: str | None = None
    retention_eligible: bool = False
    gc_root: bool = False
    gc_allowed: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.object_id or any(ch.isspace() for ch in self.object_id):
            raise InventoryError("object identity must be non-empty and contain no whitespace")
        if isinstance(self.created_sequence, bool) or self.created_sequence < 0:
            raise InventoryError("created_sequence must be a non-negative integer")
        if isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise InventoryError("size_bytes must be a non-negative integer")
        if len(set(self.references)) != len(self.references) or tuple(sorted(self.references)) != self.references:
            raise InventoryError("object references must be unique and canonical")
        object.__setattr__(self, "relative_path", _bounded_relative_path(self.relative_path))
        if self.content_sha256 is not None and (
            len(self.content_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in self.content_sha256)
        ):
            raise InventoryError("content_sha256 must be lowercase SHA-256")
        if not isinstance(self.metadata, Mapping):
            raise InventoryError("object metadata must be an object")

    def as_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "kind": self.kind.value,
            "created_sequence": self.created_sequence,
            "size_bytes": self.size_bytes,
            "references": list(self.references),
            "relative_path": self.relative_path,
            "content_sha256": self.content_sha256,
            "retention_eligible": self.retention_eligible,
            "gc_root": self.gc_root,
            "gc_allowed": self.gc_allowed,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "GCObject":
        expected = {
            "object_id", "kind", "created_sequence", "size_bytes", "references",
            "relative_path", "content_sha256", "retention_eligible", "gc_root",
            "gc_allowed", "metadata",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise InventoryError("GC object fields are invalid")
        if not isinstance(value["references"], list):
            raise InventoryError("object references must be a list")
        try:
            kind = ObjectKind(value["kind"])
        except (TypeError, ValueError) as exc:
            raise InventoryError("unknown GC object kind") from exc
        return cls(
            object_id=value["object_id"], kind=kind,
            created_sequence=value["created_sequence"], size_bytes=value["size_bytes"],
            references=tuple(value["references"]), relative_path=value["relative_path"],
            content_sha256=value["content_sha256"],
            retention_eligible=value["retention_eligible"] is True,
            gc_root=value["gc_root"] is True, gc_allowed=value["gc_allowed"] is True,
            metadata=value["metadata"],
        )


@dataclass(frozen=True)
class GenerationInventory:
    objects: tuple[GCObject, ...]
    current_system_generation_id: str
    running_kernel_generation_id: str
    current_root_id: str
    current_runtime_id: str | None = None
    current_recovery_ids: tuple[str, ...] = ()
    last_verified_recovery_id: str | None = None
    active_candidate_ids: tuple[str, ...] = ()
    active_update_ids: tuple[str, ...] = ()
    active_recovery_ids: tuple[str, ...] = ()
    unresolved_incident_evidence_ids: tuple[str, ...] = ()
    rotation_rollback_ids: tuple[str, ...] = ()
    audit_evidence_ids: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise InventoryError("unsupported generation inventory schema")
        ids = [item.object_id for item in self.objects]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise InventoryError("inventory objects must be unique and canonical")
        known = set(ids)
        required = {
            self.current_system_generation_id,
            self.running_kernel_generation_id,
            self.current_root_id,
        }
        if self.current_runtime_id:
            required.add(self.current_runtime_id)
        for values in (
            self.current_recovery_ids, self.active_candidate_ids, self.active_update_ids,
            self.active_recovery_ids, self.unresolved_incident_evidence_ids,
            self.rotation_rollback_ids, self.audit_evidence_ids,
        ):
            if tuple(sorted(set(values))) != values:
                raise InventoryError("protected identity lists must be unique and canonical")
            required.update(values)
        if self.last_verified_recovery_id:
            required.add(self.last_verified_recovery_id)
        missing = required - known
        if missing:
            raise InventoryError(f"protected object identities are absent: {sorted(missing)}")
        for item in self.objects:
            missing_refs = set(item.references) - known
            if missing_refs:
                raise InventoryError(f"object {item.object_id} has missing references: {sorted(missing_refs)}")
        kinds = {item.object_id: item.kind for item in self.objects}
        if kinds[self.current_system_generation_id] is not ObjectKind.SYSTEM_GENERATION:
            raise InventoryError("current SystemGeneration identity has the wrong kind")
        if kinds[self.running_kernel_generation_id] is not ObjectKind.KERNEL_GENERATION:
            raise InventoryError("running KernelGeneration identity has the wrong kind")
        if kinds[self.current_root_id] is not ObjectKind.ROOT:
            raise InventoryError("current root identity has the wrong kind")

    @property
    def by_id(self) -> dict[str, GCObject]:
        return {item.object_id: item for item in self.objects}

    def material(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "objects": [item.as_dict() for item in self.objects],
            "current_system_generation_id": self.current_system_generation_id,
            "running_kernel_generation_id": self.running_kernel_generation_id,
            "current_root_id": self.current_root_id,
            "current_runtime_id": self.current_runtime_id,
            "current_recovery_ids": list(self.current_recovery_ids),
            "last_verified_recovery_id": self.last_verified_recovery_id,
            "active_candidate_ids": list(self.active_candidate_ids),
            "active_update_ids": list(self.active_update_ids),
            "active_recovery_ids": list(self.active_recovery_ids),
            "unresolved_incident_evidence_ids": list(self.unresolved_incident_evidence_ids),
            "rotation_rollback_ids": list(self.rotation_rollback_ids),
            "audit_evidence_ids": list(self.audit_evidence_ids),
        }

    @property
    def inventory_sha256(self) -> str:
        return digest_payload(self.material())

    def as_dict(self) -> dict[str, Any]:
        material = self.material()
        return material | {"inventory_sha256": digest_payload(material)}

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "GenerationInventory":
        if not isinstance(value, Mapping):
            raise InventoryError("generation inventory must be an object")
        material = dict(value)
        claimed = material.pop("inventory_sha256", None)
        expected = {
            "schema_version", "objects", "current_system_generation_id",
            "running_kernel_generation_id", "current_root_id", "current_runtime_id",
            "current_recovery_ids", "last_verified_recovery_id", "active_candidate_ids",
            "active_update_ids", "active_recovery_ids", "unresolved_incident_evidence_ids",
            "rotation_rollback_ids", "audit_evidence_ids",
        }
        if set(material) != expected or claimed != digest_payload(material):
            raise InventoryError("generation inventory digest or fields are invalid")
        if not isinstance(material["objects"], list):
            raise InventoryError("inventory objects must be a list")
        list_fields = (
            "current_recovery_ids", "active_candidate_ids", "active_update_ids",
            "active_recovery_ids", "unresolved_incident_evidence_ids",
            "rotation_rollback_ids", "audit_evidence_ids",
        )
        if any(not isinstance(material[name], list) for name in list_fields):
            raise InventoryError("protected identity fields must be lists")
        return cls(
            objects=tuple(GCObject.parse(item) for item in material["objects"]),
            current_system_generation_id=material["current_system_generation_id"],
            running_kernel_generation_id=material["running_kernel_generation_id"],
            current_root_id=material["current_root_id"],
            current_runtime_id=material["current_runtime_id"],
            current_recovery_ids=tuple(material["current_recovery_ids"]),
            last_verified_recovery_id=material["last_verified_recovery_id"],
            active_candidate_ids=tuple(material["active_candidate_ids"]),
            active_update_ids=tuple(material["active_update_ids"]),
            active_recovery_ids=tuple(material["active_recovery_ids"]),
            unresolved_incident_evidence_ids=tuple(material["unresolved_incident_evidence_ids"]),
            rotation_rollback_ids=tuple(material["rotation_rollback_ids"]),
            audit_evidence_ids=tuple(material["audit_evidence_ids"]),
        )


@dataclass(frozen=True)
class RetentionPlan:
    source_inventory_sha256: str
    target_inventory: GenerationInventory
    retained_system_generation_ids: tuple[str, ...]
    protected_object_ids: tuple[str, ...]
    removal_object_ids: tuple[str, ...]
    protection_reasons: Mapping[str, tuple[str, ...]]
    free_bytes: int
    safe_reserve_bytes: int
    reclaimable_bytes: int
    planned_reclaim_bytes: int
    reserve_after_plan_bytes: int
    reserve_restored: bool
    schema_version: int = PLAN_SCHEMA_VERSION

    def material(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_inventory_sha256": self.source_inventory_sha256,
            "target_inventory": self.target_inventory.as_dict(),
            "retained_system_generation_ids": list(self.retained_system_generation_ids),
            "protected_object_ids": list(self.protected_object_ids),
            "removal_object_ids": list(self.removal_object_ids),
            "protection_reasons": {key: list(value) for key, value in sorted(self.protection_reasons.items())},
            "free_bytes": self.free_bytes,
            "safe_reserve_bytes": self.safe_reserve_bytes,
            "reclaimable_bytes": self.reclaimable_bytes,
            "planned_reclaim_bytes": self.planned_reclaim_bytes,
            "reserve_after_plan_bytes": self.reserve_after_plan_bytes,
            "reserve_restored": self.reserve_restored,
        }

    @property
    def plan_sha256(self) -> str:
        return digest_payload(self.material())

    def as_dict(self) -> dict[str, Any]:
        material = self.material()
        return material | {"plan_sha256": digest_payload(material)}

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "RetentionPlan":
        if not isinstance(value, Mapping):
            raise InventoryError("retention plan must be an object")
        material = dict(value)
        claimed = material.pop("plan_sha256", None)
        if claimed != digest_payload(material) or material.get("schema_version") != PLAN_SCHEMA_VERSION:
            raise InventoryError("retention plan digest or schema is invalid")
        target = GenerationInventory.parse(material["target_inventory"])
        reasons = material["protection_reasons"]
        if not isinstance(reasons, Mapping):
            raise InventoryError("plan protection reasons are invalid")
        return cls(
            source_inventory_sha256=material["source_inventory_sha256"],
            target_inventory=target,
            retained_system_generation_ids=tuple(material["retained_system_generation_ids"]),
            protected_object_ids=tuple(material["protected_object_ids"]),
            removal_object_ids=tuple(material["removal_object_ids"]),
            protection_reasons={str(k): tuple(v) for k, v in reasons.items()},
            free_bytes=material["free_bytes"], safe_reserve_bytes=material["safe_reserve_bytes"],
            reclaimable_bytes=material["reclaimable_bytes"],
            planned_reclaim_bytes=material["planned_reclaim_bytes"],
            reserve_after_plan_bytes=material["reserve_after_plan_bytes"],
            reserve_restored=material["reserve_restored"] is True,
        )


def _add_reason(reasons: dict[str, set[str]], object_id: str, reason: str) -> None:
    reasons.setdefault(object_id, set()).add(reason)


def _dependency_closure(objects: Mapping[str, GCObject], seeds: Iterable[str]) -> set[str]:
    closure: set[str] = set()
    pending = list(seeds)
    while pending:
        object_id = pending.pop()
        if object_id in closure:
            continue
        closure.add(object_id)
        pending.extend(objects[object_id].references)
    return closure


def plan_retention(
    inventory: GenerationInventory, *, free_bytes: int, safe_reserve_bytes: int,
) -> RetentionPlan:
    if isinstance(free_bytes, bool) or isinstance(safe_reserve_bytes, bool) or min(free_bytes, safe_reserve_bytes) < 0:
        raise ValueError("storage byte counts must be non-negative integers")
    objects = inventory.by_id
    systems = [item for item in inventory.objects if item.kind is ObjectKind.SYSTEM_GENERATION]
    current = objects[inventory.current_system_generation_id]
    eligible_previous = sorted(
        (
            item for item in systems
            if item.object_id != current.object_id and item.retention_eligible
        ),
        key=lambda item: (item.created_sequence, item.object_id), reverse=True,
    )[:2]
    retained_systems = {current.object_id, *(item.object_id for item in eligible_previous)}

    reasons: dict[str, set[str]] = {}
    for object_id in retained_systems:
        _add_reason(reasons, object_id, "system-retention-current" if object_id == current.object_id else "system-retention-previous")
    explicit: tuple[tuple[str, Iterable[str]], ...] = (
        ("running-kernel", (inventory.running_kernel_generation_id,)),
        ("current-root", (inventory.current_root_id,)),
        ("current-runtime", (inventory.current_runtime_id,) if inventory.current_runtime_id else ()),
        ("current-recovery", inventory.current_recovery_ids),
        ("last-verified-recovery", (inventory.last_verified_recovery_id,) if inventory.last_verified_recovery_id else ()),
        ("active-candidate", inventory.active_candidate_ids),
        ("active-update", inventory.active_update_ids),
        ("active-recovery", inventory.active_recovery_ids),
        ("unresolved-incident-evidence", inventory.unresolved_incident_evidence_ids),
        ("rotation-rollback", inventory.rotation_rollback_ids),
        ("audit-retention", inventory.audit_evidence_ids),
    )
    for reason, values in explicit:
        for object_id in values:
            _add_reason(reasons, object_id, reason)

    seeds = set(reasons)
    protected = _dependency_closure(objects, seeds)
    for seed in seeds:
        for object_id in _dependency_closure(objects, (seed,)) - {seed}:
            _add_reason(reasons, object_id, f"referenced-by:{seed}")

    # A removable dependency must have no surviving referrer. Recompute the
    # collectible closure as disposal roots are added in deterministic order.
    roots = sorted(
        (
            item for item in inventory.objects
            if item.object_id not in protected and item.gc_allowed
            and (item.gc_root or item.kind is ObjectKind.SYSTEM_GENERATION)
        ),
        key=lambda item: (_ROOT_PRIORITY.get(item.kind, 4), item.created_sequence, item.object_id),
    )
    reverse: dict[str, set[str]] = {object_id: set() for object_id in objects}
    for item in inventory.objects:
        for dependency in item.references:
            reverse[dependency].add(item.object_id)

    selected_roots: set[str] = set()

    def collectible() -> set[str]:
        removed = set(selected_roots)
        changed = True
        while changed:
            changed = False
            for item in inventory.objects:
                if item.object_id in removed or item.object_id in protected or not item.gc_allowed:
                    continue
                if not reverse[item.object_id] - removed and (
                    item.object_id in selected_roots
                    or any(parent in removed for parent in reverse[item.object_id])
                ):
                    removed.add(item.object_id)
                    changed = True
        return removed

    all_roots = {item.object_id for item in roots}
    selected_roots.update(all_roots)
    reclaimable_ids = collectible()
    reclaimable_bytes = sum(objects[object_id].size_bytes for object_id in reclaimable_ids)
    selected_roots.clear()
    target = max(0, safe_reserve_bytes - free_bytes)
    removal_ids: set[str] = set()
    if target:
        for root in roots:
            selected_roots.add(root.object_id)
            removal_ids = collectible()
            if sum(objects[object_id].size_bytes for object_id in removal_ids) >= target:
                break
    planned = sum(objects[object_id].size_bytes for object_id in removal_ids)
    target_objects = tuple(item for item in inventory.objects if item.object_id not in removal_ids)
    target_inventory = GenerationInventory(
        objects=target_objects,
        current_system_generation_id=inventory.current_system_generation_id,
        running_kernel_generation_id=inventory.running_kernel_generation_id,
        current_root_id=inventory.current_root_id,
        current_runtime_id=inventory.current_runtime_id,
        current_recovery_ids=inventory.current_recovery_ids,
        last_verified_recovery_id=inventory.last_verified_recovery_id,
        active_candidate_ids=inventory.active_candidate_ids,
        active_update_ids=inventory.active_update_ids,
        active_recovery_ids=inventory.active_recovery_ids,
        unresolved_incident_evidence_ids=inventory.unresolved_incident_evidence_ids,
        rotation_rollback_ids=inventory.rotation_rollback_ids,
        audit_evidence_ids=inventory.audit_evidence_ids,
    )
    return RetentionPlan(
        source_inventory_sha256=inventory.inventory_sha256,
        target_inventory=target_inventory,
        retained_system_generation_ids=tuple(sorted(retained_systems)),
        protected_object_ids=tuple(sorted(protected)),
        removal_object_ids=tuple(sorted(removal_ids)),
        protection_reasons={key: tuple(sorted(value)) for key, value in sorted(reasons.items())},
        free_bytes=free_bytes, safe_reserve_bytes=safe_reserve_bytes,
        reclaimable_bytes=reclaimable_bytes, planned_reclaim_bytes=planned,
        reserve_after_plan_bytes=free_bytes + planned,
        reserve_restored=free_bytes + planned >= safe_reserve_bytes,
    )


def inventory_status(inventory: GenerationInventory, *, free_bytes: int, safe_reserve_bytes: int) -> dict[str, Any]:
    plan = plan_retention(inventory, free_bytes=free_bytes, safe_reserve_bytes=safe_reserve_bytes)
    objects = inventory.by_id
    protected_bytes = sum(objects[item].size_bytes for item in plan.protected_object_ids)
    return {
        "schema_version": 1,
        "kind": "maho-generation-retention-status",
        "inventory_sha256": inventory.inventory_sha256,
        "current_system_generation_id": inventory.current_system_generation_id,
        "retained_system_generation_ids": list(plan.retained_system_generation_ids),
        "free_bytes": free_bytes,
        "safe_reserve_bytes": safe_reserve_bytes,
        "protected_bytes": protected_bytes,
        "reclaimable_bytes": plan.reclaimable_bytes,
        "gc_eligible_object_ids": list(sorted(
            item.object_id for item in inventory.objects
            if item.gc_allowed and item.object_id not in plan.protected_object_ids
        )),
        "planned_removal_object_ids": list(plan.removal_object_ids),
        "reserve_restored": plan.reserve_restored,
        "update_mutation_allowed": plan.reserve_restored,
        "protection_reasons": {key: list(value) for key, value in plan.protection_reasons.items()},
    }


def inventory_from_generation_store(root: Path) -> GenerationInventory:
    """Build a fail-closed read-only inventory from published generation data.

    This adapter deliberately marks roots and package state non-deletable: the
    generation store does not contain the separate Btrfs/package deletion
    authorities needed to mutate them.  A future updater may persist a richer
    inventory, but status remains truthful on installations predating GC.
    """
    from maho_generation_v2 import SystemGeneration
    from maho_kernel_generation import KernelGeneration
    from maho_live_generation import read_live_publication
    from maho_trust_identity import TrustState

    publication = read_live_publication(root)
    if publication is None:
        raise InventoryError("live generation publication is missing or invalid")
    try:
        current_system_id = str(publication["system_generation_id"])
        running_kernel_id = str(publication["kernel_generation_id"])
        runtime_revision = str(publication["source_revision"])
        recovery_generation_id = str(publication["recovery_generation_id"])
    except (KeyError, TypeError) as exc:
        raise InventoryError("live generation publication lacks retention identities") from exc

    systems: dict[str, SystemGeneration] = {}
    for path in sorted((root / "manifests/system").glob("gen-*.json")):
        try:
            value = SystemGeneration.parse(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise InventoryError(f"invalid SystemGeneration manifest: {path.name}") from exc
        systems[str(value.generation_id)] = value
    kernels: dict[str, KernelGeneration] = {}
    for path in sorted((root / "manifests/kernel").glob("kgen-*.json")):
        try:
            value = KernelGeneration.parse(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise InventoryError(f"invalid KernelGeneration manifest: {path.name}") from exc
        kernels[str(value.kernel_generation_id)] = value
    if current_system_id not in systems or running_kernel_id not in kernels:
        raise InventoryError("live generation manifests are incomplete")

    sequence: dict[str, int] = {}
    cursor: str | None = current_system_id
    rank = len(systems)
    while cursor is not None:
        if cursor in sequence or cursor not in systems:
            raise InventoryError("current SystemGeneration lineage is missing or cyclic")
        sequence[cursor] = rank
        rank -= 1
        parent = systems[cursor].parent_generation_id
        cursor = str(parent) if parent else None

    rows: dict[str, GCObject] = {}

    def add(item: GCObject) -> None:
        previous = rows.get(item.object_id)
        if previous is not None and previous != item:
            raise InventoryError(f"conflicting discovered GC identity: {item.object_id}")
        rows[item.object_id] = item

    def file_object(object_id: str, kind: ObjectKind, relative: Path, created: int) -> GCObject:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise InventoryError(f"generation object is missing or not a regular file: {relative}")
        return GCObject(
            object_id=object_id, kind=kind, created_sequence=max(0, created),
            size_bytes=path.stat().st_size, relative_path=str(relative),
            content_sha256=_tree_sha256(path), gc_allowed=True,
        )

    def artifact_object(object_id: str, kind: ObjectKind, created: int) -> GCObject:
        digest = object_id.removeprefix("art-")
        relative = Path("artifacts/sha256") / digest[:2] / digest[2:]
        path = root / relative
        if path.is_file() and not path.is_symlink():
            return file_object(object_id, kind, relative, created)
        # Kernel module/DKMS artifact identities may describe live external
        # trees rather than generation-store blobs. They remain dependencies,
        # but this adapter has no authority to delete those external bytes.
        return GCObject(object_id, kind, created, 0, gc_allowed=False)

    for kernel_id, kernel in kernels.items():
        created = max(
            (sequence.get(system_id, 0) for system_id, system in systems.items() if str(system.kernel_generation_id) == kernel_id),
            default=0,
        )
        artifact_refs: list[str] = []
        for artifact_id in kernel.artifact_ids:
            identity = str(artifact_id)
            add(artifact_object(identity, ObjectKind.BOOT_ARTIFACT, created))
            artifact_refs.append(identity)
        manifest = file_object(
            kernel_id, ObjectKind.KERNEL_GENERATION,
            Path("manifests/kernel") / f"{kernel_id}.json", created,
        )
        add(replace_gc_object(manifest, references=tuple(sorted(artifact_refs))))

    runtime_id = f"runtime:{runtime_revision}"
    add(GCObject(runtime_id, ObjectKind.RUNTIME, len(systems), 0, gc_allowed=False))
    recovery_id = f"recovery:{recovery_generation_id}"
    add(GCObject(recovery_id, ObjectKind.RECOVERY, len(systems), 0, gc_allowed=False))
    current_root_id = ""
    for system_id, system in systems.items():
        created = sequence.get(system_id, 0)
        if system.root_identity is None or system.kernel_generation_id is None or system.package_set_identity is None:
            raise InventoryError("partial legacy SystemGeneration is not a GC authority")
        root_id = f"root:{system.root_identity.snapshot_identity}"
        package_id = str(system.package_set_identity)
        add(GCObject(root_id, ObjectKind.ROOT, created, 0, gc_allowed=False))
        add(GCObject(package_id, ObjectKind.PACKAGE_GENERATION, created, 0, gc_allowed=False))
        references = {root_id, package_id, str(system.kernel_generation_id), *(str(item) for item in system.artifact_ids)}
        for artifact_id in system.artifact_ids:
            identity = str(artifact_id)
            if identity in rows:
                continue
            add(artifact_object(identity, ObjectKind.EVIDENCE, created))
        compatibility = Path("evidence/compatibility") / f"{system_id}--{system.kernel_generation_id}.json"
        compatibility_id = f"compatibility:{system_id}:{system.kernel_generation_id}"
        add(file_object(compatibility_id, ObjectKind.EVIDENCE, compatibility, created))
        references.add(compatibility_id)
        if system_id == current_system_id:
            references.update((runtime_id, recovery_id))
            current_root_id = root_id
        manifest = file_object(
            system_id, ObjectKind.SYSTEM_GENERATION,
            Path("manifests/system") / f"{system_id}.json", created,
        )
        add(replace_gc_object(
            manifest, references=tuple(sorted(references)),
            retention_eligible=(
                system_id in sequence
                and system.trust_state in {TrustState.VERIFIED, TrustState.REVALIDATED}
            ),
            gc_root=True,
        ))
    if not current_root_id:
        raise InventoryError("current root identity is unavailable")
    return GenerationInventory(
        objects=tuple(sorted(rows.values(), key=lambda item: item.object_id)),
        current_system_generation_id=current_system_id,
        running_kernel_generation_id=running_kernel_id,
        current_root_id=current_root_id,
        current_runtime_id=runtime_id,
        current_recovery_ids=(recovery_id,),
        last_verified_recovery_id=recovery_id,
    )


def replace_gc_object(item: GCObject, **changes: Any) -> GCObject:
    """Local dataclass replacement without exposing mutable object state."""
    values = item.as_dict()
    values.update(changes)
    if isinstance(values.get("kind"), ObjectKind):
        values["kind"] = values["kind"].value
    if isinstance(values.get("references"), tuple):
        values["references"] = list(values["references"])
    return GCObject.parse(values)


def _atomic_json(path: Path, value: Mapping[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def read_inventory(path: Path) -> GenerationInventory:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InventoryError(f"cannot read generation inventory: {exc}") from exc
    return GenerationInventory.parse(value)


def write_inventory(path: Path, inventory: GenerationInventory) -> None:
    _atomic_json(path, inventory.as_dict(), 0o600)


def _tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_symlink():
        digest.update(b"L\0" + os.readlink(path).encode())
        return digest.hexdigest()
    if path.is_file():
        digest.update(b"F\0" + path.read_bytes())
        return digest.hexdigest()
    if not path.is_dir():
        raise IdentityMismatchError(f"unsupported GC object type: {path}")
    digest.update(b"D\0")
    for child in sorted(path.rglob("*"), key=lambda item: str(item.relative_to(path))):
        relative = str(child.relative_to(path)).encode()
        if child.is_symlink():
            digest.update(b"L\0" + relative + b"\0" + os.readlink(child).encode())
        elif child.is_file():
            digest.update(b"F\0" + relative + b"\0" + child.read_bytes())
        elif child.is_dir():
            digest.update(b"D\0" + relative + b"\0")
    return digest.hexdigest()


class GCExecutor:
    def __init__(self, *, inventory_path: Path, data_root: Path, state_root: Path) -> None:
        self.inventory_path = inventory_path
        self.data_root = data_root.resolve()
        self.state_root = state_root
        self.journal_path = state_root / "active.json"
        self.receipt_dir = state_root / "receipts"

    def _lock(self):
        self.state_root.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.state_root / "gc.lock", os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return descriptor

    def _path_for(self, item: GCObject) -> Path:
        if item.relative_path is None:
            raise IdentityMismatchError(f"object has no bounded deletion path: {item.object_id}")
        candidate = self.data_root / item.relative_path
        parent = candidate.parent.resolve()
        try:
            parent.relative_to(self.data_root)
        except ValueError as exc:
            raise IdentityMismatchError(f"object path escapes data root: {item.object_id}") from exc
        return candidate

    def _verify_objects(self, inventory: GenerationInventory, object_ids: Iterable[str]) -> None:
        for object_id in object_ids:
            item = inventory.by_id[object_id]
            path = self._path_for(item)
            if not path.exists() and not path.is_symlink():
                raise IdentityMismatchError(f"authorized GC object is missing: {object_id}")
            if item.content_sha256 is None:
                raise IdentityMismatchError(f"authorized GC object has no content identity: {object_id}")
            if _tree_sha256(path) != item.content_sha256:
                raise IdentityMismatchError(f"authorized GC object identity changed: {object_id}")

    def _journal(
        self, plan: RetentionPlan, phase: str, deleted: Iterable[str] = (),
        removed: Iterable[GCObject] = (),
    ) -> dict[str, Any]:
        value = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "kind": "maho-generation-gc-journal",
            "plan": plan.as_dict(),
            "phase": phase,
            "deleted_object_ids": sorted(set(deleted)),
            "removed_objects": [item.as_dict() for item in sorted(removed, key=lambda row: row.object_id)],
        }
        value["journal_sha256"] = digest_payload(value)
        return value

    def _read_journal(self) -> tuple[RetentionPlan, str, set[str], tuple[GCObject, ...]]:
        try:
            value = json.loads(self.journal_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise InventoryError(f"cannot read active GC journal: {exc}") from exc
        claimed = value.pop("journal_sha256", None)
        if claimed != digest_payload(value) or value.get("schema_version") != JOURNAL_SCHEMA_VERSION:
            raise InventoryError("active GC journal is corrupt")
        removed_values = value.get("removed_objects")
        if not isinstance(removed_values, list):
            raise InventoryError("active GC journal lacks removed-object identities")
        removed = tuple(GCObject.parse(item) for item in removed_values)
        return RetentionPlan.parse(value["plan"]), str(value["phase"]), set(value["deleted_object_ids"]), removed

    def execute(self, plan: RetentionPlan, *, fault_at: str | None = None) -> dict[str, Any]:
        lock = self._lock()
        try:
            return self._execute_locked(plan, fault_at=fault_at)
        finally:
            os.close(lock)

    def _execute_locked(self, plan: RetentionPlan, *, fault_at: str | None = None) -> dict[str, Any]:
        if self.journal_path.exists():
            _, phase, _, _ = self._read_journal()
            if phase != "COMMITTED":
                raise StaleAuthorityError("an interrupted GC transaction must be resumed first")
        current = read_inventory(self.inventory_path)
        if current.inventory_sha256 != plan.source_inventory_sha256:
            raise StaleAuthorityError("GC plan does not match current inventory authority")
        if set(plan.removal_object_ids) & set(plan.protected_object_ids):
            raise InventoryError("GC plan attempts to remove a protected object")
        expected_target = tuple(item for item in current.objects if item.object_id not in set(plan.removal_object_ids))
        if expected_target != plan.target_inventory.objects:
            raise InventoryError("GC plan target is not the exact source-minus-removals inventory")
        removed = tuple(current.by_id[object_id] for object_id in plan.removal_object_ids)
        if any(item.relative_path is None or item.content_sha256 is None for item in removed):
            raise IdentityMismatchError("every removal requires a bounded path and content identity")
        self._verify_objects(current, plan.removal_object_ids)
        _atomic_json(self.journal_path, self._journal(plan, "PREPARED", removed=removed), 0o600)
        if fault_at == "after_prepare":
            raise SimulatedCrash(fault_at)
        if fault_at == "before_catalog_commit":
            raise SimulatedCrash(fault_at)
        write_inventory(self.inventory_path, plan.target_inventory)
        _atomic_json(self.journal_path, self._journal(plan, "METADATA_COMMITTED", removed=removed), 0o600)
        if fault_at == "after_catalog_commit":
            raise SimulatedCrash(fault_at)
        return self._finish(plan, set(), removed, fault_at=fault_at)

    def _finish(
        self, plan: RetentionPlan, deleted: set[str], removed_objects: Iterable[GCObject],
        *, fault_at: str | None = None,
    ) -> dict[str, Any]:
        removed = {item.object_id: item for item in removed_objects}
        if set(removed) != set(plan.removal_object_ids):
            raise InventoryError("GC journal removed-object identities do not match the plan")
        first = True
        for object_id in plan.removal_object_ids:
            if object_id in deleted:
                continue
            item = removed[object_id]
            path = self._path_for(item)
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                raise IdentityMismatchError(f"unsupported GC object type: {object_id}")
            deleted.add(object_id)
            _atomic_json(self.journal_path, self._journal(plan, "DELETING", deleted, removed.values()), 0o600)
            if first and fault_at == "after_first_delete":
                raise SimulatedCrash(fault_at)
            first = False
        receipt = {
            "schema_version": 1,
            "kind": "maho-generation-gc-receipt",
            "plan_sha256": plan.plan_sha256,
            "source_inventory_sha256": plan.source_inventory_sha256,
            "target_inventory_sha256": plan.target_inventory.inventory_sha256,
            "removed_object_ids": list(plan.removal_object_ids),
            "reclaimed_bytes": plan.planned_reclaim_bytes,
            "reserve_restored": plan.reserve_restored,
        }
        receipt["receipt_sha256"] = digest_payload(receipt)
        if fault_at == "before_receipt":
            raise SimulatedCrash(fault_at)
        _atomic_json(self.receipt_dir / f"gc-{plan.plan_sha256}.json", receipt, 0o600)
        _atomic_json(self.journal_path, self._journal(plan, "COMMITTED", deleted, removed.values()), 0o600)
        return receipt

    def resume(self, *, fault_at: str | None = None) -> dict[str, Any]:
        lock = self._lock()
        try:
            return self._resume_locked(fault_at=fault_at)
        finally:
            os.close(lock)

    def _resume_locked(self, *, fault_at: str | None = None) -> dict[str, Any]:
        plan, phase, deleted, removed = self._read_journal()
        current = read_inventory(self.inventory_path)
        if phase == "COMMITTED":
            receipt_path = self.receipt_dir / f"gc-{plan.plan_sha256}.json"
            return json.loads(receipt_path.read_text(encoding="utf-8"))
        if current.inventory_sha256 == plan.source_inventory_sha256:
            self._verify_objects(current, plan.removal_object_ids)
            write_inventory(self.inventory_path, plan.target_inventory)
            _atomic_json(self.journal_path, self._journal(plan, "METADATA_COMMITTED", removed=removed), 0o600)
            if fault_at == "after_catalog_commit":
                raise SimulatedCrash(fault_at)
        elif current.inventory_sha256 != plan.target_inventory.inventory_sha256:
            raise StaleAuthorityError("neither GC source nor target inventory is authoritative")
        return self._finish(plan, deleted, removed, fault_at=fault_at)


def errno_is_capacity_or_readonly(exc: OSError) -> bool:
    return exc.errno in {errno.ENOSPC, errno.EROFS, errno.EDQUOT}


class CertifiedFileGC:
    """Narrow GC executor for Update-owned, sealed disposable archive files.

    The Update owner supplies a fresh independent protection validator. This
    executor never traverses a directory recursively or removes a snapshot.
    All cache/state ancestors are opened without following links. The caller
    must hold the shared update campaign lock throughout planning and execution.
    """

    def __init__(self, *, roots: Mapping[str, Path], state_root: Path,
                 owner_uid: int = 0) -> None:
        self.roots = {name: Path(path) for name, path in roots.items()}
        self.state_root = Path(state_root)
        self.owner_uid = owner_uid
        self.journal_path = self.state_root / "archive-retirement.json"
        if not self.roots or any(not p.is_absolute() for p in self.roots.values()):
            raise InventoryError("file GC requires exact absolute cache roots")

    def _directory(self, path: Path, *, final_uid: int | None = None) -> int:
        if not path.is_absolute() or ".." in path.parts:
            raise IdentityMismatchError("unbounded GC directory")
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for index, part in enumerate(path.parts[1:], 1):
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=fd)
                os.close(fd)
                fd = child
                info = os.fstat(fd)
                # Disposable fixture roots may live under sticky /tmp. The
                # production executor accepts only owner-controlled ancestors.
                fixture_tmp = (self.owner_uid != 0 and index == 1 and part == "tmp"
                               and info.st_uid == 0 and info.st_mode & stat.S_ISVTX)
                allowed = {0, self.owner_uid}
                if index == len(path.parts) - 1 and final_uid is not None:
                    allowed.add(final_uid)
                if (info.st_uid not in allowed or info.st_mode & 0o022) and not fixture_tmp:
                    raise IdentityMismatchError("untrusted archive path ancestor")
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _trusted_directory(self, path: Path) -> int:
        fd = self._directory(path)
        info = os.fstat(fd)
        if info.st_uid != self.owner_uid or info.st_mode & 0o022:
            os.close(fd)
            raise IdentityMismatchError("archive directory is not sealed to its lifecycle owner")
        return fd

    def _parent(self, row: Mapping[str, Any], *, adoption_uid: int | None = None) -> int:
        import re
        if row.get("root") not in self.roots:
            raise IdentityMismatchError("unknown archive cache root")
        txid, name = row.get("transaction_id"), row.get("name")
        if not isinstance(txid, str) or re.fullmatch(r"upd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}", txid) is None:
            raise IdentityMismatchError("invalid archive transaction path")
        if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9@._+:-]+\.pkg\.tar\.(zst|xz|gz)(\.sig)?", name) is None:
            raise IdentityMismatchError("target is not a bounded package archive file")
        base = self.roots[row["root"]]
        descriptors = []
        try:
            for path in (base, base / txid):
                descriptors.append(self._trusted_directory(path))
            if adoption_uid is None:
                descriptors.append(self._trusted_directory(base / txid / "staging"))
            else:
                descriptors.append(self._directory(base / txid / "staging", final_uid=adoption_uid))
            fd = descriptors.pop()
            info = os.fstat(fd)
            root_device = os.fstat(descriptors[0]).st_dev
            if info.st_dev != root_device or any(os.fstat(d).st_dev != root_device for d in descriptors):
                os.close(fd)
                raise IdentityMismatchError("archive path crosses a mount boundary")
            if row.get("parent_identity") not in (None, [info.st_dev, info.st_ino]):
                os.close(fd)
                raise IdentityMismatchError("archive parent directory changed")
            return fd
        finally:
            for descriptor in descriptors:
                os.close(descriptor)

    def inspect(self, root: str, transaction_id: str, name: str, *,
                adoption_uid: int | None = None) -> dict[str, Any]:
        row = {"root": root, "transaction_id": transaction_id, "name": name}
        parent = self._parent(row, adoption_uid=adoption_uid)
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                         dir_fd=parent)
            try:
                before = os.fstat(fd)
                if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                        or before.st_uid != self.owner_uid or before.st_mode & 0o022):
                    raise IdentityMismatchError("archive file is not an exact owner-controlled regular file")
                digest = hashlib.sha256()
                while chunk := os.read(fd, 1024 * 1024):
                    digest.update(chunk)
                after = os.fstat(fd)
                identity = lambda s: [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]
                if identity(before) != identity(after):
                    raise IdentityMismatchError("archive changed while hashing")
                row.update({"identity": identity(after), "sha256": digest.hexdigest(),
                            "allocated_bytes": after.st_blocks * 512,
                            "parent_identity": [os.fstat(parent).st_dev, os.fstat(parent).st_ino]})
                return row
            finally:
                os.close(fd)
        finally:
            os.close(parent)

    def plan(self, objects: Iterable[Mapping[str, Any]], *, source_revision: str,
             evidence: Mapping[str, Any], now: datetime | None = None) -> dict[str, Any]:
        import re
        if re.fullmatch(r"[0-9a-f]{40}", source_revision) is None:
            raise InventoryError("archive retirement requires exact source identity")
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        rows = sorted((dict(row) for row in objects),
                      key=lambda row: (row["root"], row["transaction_id"], row["name"]))
        if len({(r["root"], r["transaction_id"], r["name"]) for r in rows}) != len(rows):
            raise InventoryError("archive retirement has duplicate targets")
        for row in rows:
            if row != self.inspect(row["root"], row["transaction_id"], row["name"]):
                raise IdentityMismatchError("archive identity changed before retirement planning")
        value = {"schema_version": 1, "kind": "maho-certified-archive-retirement",
                 "source_revision": source_revision, "roots": {k: str(v) for k, v in self.roots.items()},
                 "created_at": current.isoformat(), "expires_at": (current + timedelta(minutes=5)).isoformat(),
                 "objects": rows, "evidence": dict(evidence)}
        value["plan_sha256"] = digest_payload(value)
        return value

    def _validate_plan(self, plan: Mapping[str, Any], *, completed_history: bool = False) -> dict[str, Any]:
        material = dict(plan)
        claimed = material.pop("plan_sha256", None)
        observed_roots = material.get("roots")
        current_roots = {k: str(v) for k, v in self.roots.items()}
        # A completed/cancelled journal is immutable evidence, not authority
        # to execute against newly added cache lanes. Only unchanged prior
        # bindings may be read after an independently verified root expansion.
        roots_match = observed_roots == current_roots
        if completed_history and isinstance(observed_roots, dict) and observed_roots:
            roots_match = all(current_roots.get(k) == v for k, v in observed_roots.items())
        if (claimed != digest_payload(material)
                or material.get("kind") != "maho-certified-archive-retirement"
                or material.get("schema_version") != 1
                or not roots_match
                or not isinstance(material.get("objects"), list)):
            raise InventoryError("archive retirement authority is corrupt or cross-bound")
        if any(not isinstance(r, Mapping) or r.get("root") not in observed_roots
               for r in material["objects"]):
            raise InventoryError("archive target is outside its plan roots")
        keys = [(r["root"], r["transaction_id"], r["name"]) for r in material["objects"]]
        if keys != sorted(set(keys)):
            raise InventoryError("archive targets are not unique and canonical")
        return dict(plan)

    def _write(self, path: Path, value: Mapping[str, Any]) -> None:
        # State root is created by the root-owned deployment, never from an
        # untrusted plan. Validate the containing directory before each write.
        parent = self._trusted_directory(path.parent)
        os.close(parent)
        _atomic_json(path, value, 0o600)

    def _read(self) -> dict[str, Any]:
        parent = self._trusted_directory(self.state_root)
        try:
            fd = os.open(self.journal_path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=parent)
            with os.fdopen(fd, "r") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid or info.st_mode & 0o077:
                    raise InventoryError("archive retirement journal is untrusted")
                value = json.load(stream)
        finally:
            os.close(parent)
        material = dict(value)
        claimed = material.pop("journal_sha256", None)
        if claimed != digest_payload(material):
            raise InventoryError("archive retirement journal is corrupt")
        self._validate_plan(value["plan"], completed_history=value.get("phase") in {"COMMITTED", "CANCELLED"})
        if value.get("phase") not in {"PREPARED", "RETIRED", "DELETING", "COMMITTED", "CANCELLED"}:
            raise InventoryError("archive retirement journal has an unknown phase")
        if not isinstance(value.get("deleted"), list) or value["deleted"] != sorted(set(value["deleted"])):
            raise InventoryError("archive retirement completion identities are corrupt")
        if any(not isinstance(i, int) or isinstance(i, bool) or i < 0 or i >= len(value["plan"]["objects"]) for i in value["deleted"]):
            raise InventoryError("archive retirement completion identity is out of scope")
        if value["phase"] in {"PREPARED", "RETIRED", "CANCELLED"} and value["deleted"]:
            raise InventoryError("archive retirement phase contradicts deletion evidence")
        if value["phase"] == "COMMITTED" and len(value["deleted"]) != len(value["plan"]["objects"]):
            raise InventoryError("committed archive retirement lacks completion evidence")
        reclaimed = value.get("reclaimed_bytes")
        if (not isinstance(reclaimed, int) or isinstance(reclaimed, bool) or reclaimed < 0
                or reclaimed > sum(r["allocated_bytes"] for r in value["plan"]["objects"])):
            raise InventoryError("archive retirement allocation evidence is corrupt")
        return value

    def _journal(self, plan, phase, deleted=(), reclaimed=0):
        value = {"plan": plan, "phase": phase, "deleted": sorted(deleted), "reclaimed_bytes": reclaimed}
        value["journal_sha256"] = digest_payload(value)
        self._write(self.journal_path, value)
        return value

    def execute(self, plan: Mapping[str, Any], *, validate_protections,
                now: datetime | None = None, fault_at: str | None = None) -> dict[str, Any]:
        plan = self._validate_plan(plan)
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        created, expiry = (datetime.fromisoformat(plan[k]) for k in ("created_at", "expires_at"))
        if not created.tzinfo or not expiry.tzinfo or not created <= current <= expiry or expiry - created != timedelta(minutes=5):
            raise StaleAuthorityError("archive retirement authority expired or future-dated")
        if self.journal_path.exists() or self.journal_path.is_symlink():
            prior = self._read()
            if prior["phase"] not in {"COMMITTED", "CANCELLED"}:
                raise StaleAuthorityError("interrupted archive retirement must resume first")
            if prior["plan"]["plan_sha256"] == plan["plan_sha256"]:
                raise StaleAuthorityError("archive retirement authority is single-use")
            # Preserve the full historical proof before replacing the active
            # journal with a different exact plan.
            self._write(self.state_root / ("archive-history-" + prior["plan"]["plan_sha256"] + ".json"), prior)
        validate_protections(plan)
        for row in plan["objects"]:
            if row != self.inspect(row["root"], row["transaction_id"], row["name"]):
                raise IdentityMismatchError("archive drift before retirement")
        journal = self._journal(plan, "PREPARED")
        if fault_at == "after_prepare":
            raise SimulatedCrash(fault_at)
        # This is the authoritative retirement record. Only after it is fsynced
        # can bytes disappear; transaction/manifest/incident evidence stays.
        journal = self._journal(plan, "RETIRED")
        if fault_at == "after_retire":
            raise SimulatedCrash(fault_at)
        return self._finish_files(journal, validate_protections, fault_at=fault_at)

    def resume_files(self, *, validate_protections, now: datetime | None = None,
                     fault_at: str | None = None) -> dict[str, Any]:
        journal = self._read()
        if journal["phase"] in {"COMMITTED", "CANCELLED"}:
            return {"plan_sha256": journal["plan"]["plan_sha256"],
                    "reclaimed_bytes": journal["reclaimed_bytes"], "phase": journal["phase"]}
        if journal["phase"] == "PREPARED":
            # No retirement committed: expiry still applies and no missing file
            # is accepted as an interrupted deletion at this boundary.
            current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
            expiry = datetime.fromisoformat(journal["plan"]["expires_at"])
            created = datetime.fromisoformat(journal["plan"]["created_at"])
            if not expiry.tzinfo or not created.tzinfo or not created <= current <= expiry:
                raise StaleAuthorityError("uncommitted archive retirement expired")
            validate_protections(journal["plan"])
            for row in journal["plan"]["objects"]:
                if row != self.inspect(row["root"], row["transaction_id"], row["name"]):
                    raise IdentityMismatchError("archive drift before resumed retirement")
            journal = self._journal(journal["plan"], "RETIRED")
        return self._finish_files(journal, validate_protections, fault_at=fault_at)

    def _finish_files(self, journal, validate_protections, *, fault_at=None):
        plan, deleted, reclaimed = journal["plan"], set(journal["deleted"]), journal["reclaimed_bytes"]
        for index, row in enumerate(plan["objects"]):
            if index in deleted:
                continue
            validate_protections(plan, target=row)
            parent = self._parent(row)
            try:
                try:
                    observed = self.inspect(row["root"], row["transaction_id"], row["name"])
                except FileNotFoundError:
                    # Covers the unlink->journal crash gap. No replacement is
                    # removed, and attribution remains explicitly bounded.
                    observed = None
                if observed is not None:
                    if observed != row:
                        raise IdentityMismatchError("archive drift during retirement")
                    info = os.stat(row["name"], dir_fd=parent, follow_symlinks=False)
                    if [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns] != row["identity"]:
                        raise IdentityMismatchError("archive replaced before unlink")
                    os.unlink(row["name"], dir_fd=parent)
                    os.fsync(parent)
                    reclaimed += row["allocated_bytes"]
                if fault_at == "after_unlink":
                    raise SimulatedCrash(fault_at)
            finally:
                os.close(parent)
            deleted.add(index)
            journal = self._journal(plan, "DELETING", deleted, reclaimed)
            if fault_at == "after_first_delete":
                raise SimulatedCrash(fault_at)
        receipt = {"plan_sha256": plan["plan_sha256"], "reclaimed_bytes": reclaimed,
                   "removed_file_count": len(deleted), "phase": "COMMITTED"}
        self._write(self.state_root / ("archive-receipt-" + plan["plan_sha256"] + ".json"), receipt)
        self._journal(plan, "COMMITTED", deleted, reclaimed)
        return receipt
