#!/usr/bin/env python3
"""Update-owned evidence adapter for the existing generation GC executor.

Only never-executed, durably invalidated archives are disposable in v1. Unknown
historical candidates, snapshots, receipts and logs have no deletion authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping

from maho_generation_gc import CertifiedFileGC, InventoryError, IdentityMismatchError, StaleAuthorityError, digest_payload
from maho_update_state import UpdateState, validate_transaction

PROFILE = "retire-sealed-unexecuted-invalidated-update-archives-v1"
ROOTS = {"auto": Path("/var/cache/maho/update-auto"), "m4b": Path("/var/cache/maho/update-m4b")}
ARCHIVE_BUDGET_BYTES = 12 * 1024**3
INVALIDATION = {"repository_generation_drifted", "coordinator_source_revision_changed", "stale_update_transaction"}
PRE_EXECUTION = {"DISCOVERED", "STAGED", "PREPARED", "MAINTENANCE_READY", "BLOCKED"}
TX_PATTERN = re.compile(r"upd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")


def reserve_bytes(total_bytes: int) -> int:
    return max(20 * 1024**3, (total_bytes * 15 + 99) // 100)


def _owned_json(path: Path, uid: int = 0) -> tuple[dict[str, Any], str]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != uid
                or before.st_mode & 0o022 or before.st_nlink != 1 or before.st_size > 8 * 1024**2):
            raise InventoryError(f"untrusted protection document: {path}")
        raw = stream.read()
        after = os.fstat(stream.fileno())
        if (before.st_mtime_ns, before.st_ctime_ns, before.st_size) != (after.st_mtime_ns, after.st_ctime_ns, after.st_size):
            raise InventoryError("protection document changed while reading")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise InventoryError("protection document is not an object")
    return value, hashlib.sha256(raw).hexdigest()


def _documents(root: Path, uid: int, *, excluded=()):
    # Enumerate evidence only. No recursive deletion or implicit adoption.
    if not root.is_dir() or root.is_symlink():
        raise InventoryError(f"protection evidence root unavailable: {root}")
    count = 0
    for directory, directories, names in os.walk(root, followlinks=False):
        directory = Path(directory)
        if directory == root:
            directories[:] = [name for name in directories if name not in excluded]
        if any((directory / name).is_symlink() for name in directories):
            raise InventoryError("symlink in protection evidence inventory")
        for name in sorted(names):
            if not name.endswith(".json") or (directory == root and name in excluded):
                continue
            count += 1
            if count > 10000:
                raise InventoryError("protection evidence inventory exceeds its bounded scan")
            path = directory / name
            value, digest = _owned_json(path, uid)
            yield path, value, digest


class UpdateArchiveLifecycle:
    def __init__(self, *, update_root: Path, generation_root: Path,
                 guardian_active: Path, guardian_uid: int, roots=ROOTS,
                 owner_uid: int = 0, recovery_roots=()) -> None:
        self.update_root = Path(update_root)
        self.generation_root = Path(generation_root)
        self.guardian_active = Path(guardian_active)
        self.guardian_uid = guardian_uid
        self.roots = {k: Path(v) for k, v in roots.items()}
        self.owner_uid = owner_uid
        self.recovery_roots = tuple(Path(p) for p in recovery_roots)
        self.executor = CertifiedFileGC(roots=self.roots,
            state_root=self.update_root / "artifact-gc", owner_uid=owner_uid)

    def protection_inventory(self) -> dict[str, Any]:
        documents, protected, protected_generations = {}, set(), set()
        heartbeat_path = self.guardian_active.parent / "providers/guardian.watch.json"
        heartbeat, heartbeat_digest = _owned_json(heartbeat_path, self.guardian_uid)
        observed = datetime.fromisoformat(str(heartbeat.get("last_success_at", "")).replace("Z", "+00:00"))
        current = datetime.now(timezone.utc)
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if (heartbeat.get("kind") != "guardian-provider-heartbeat" or heartbeat.get("schema_version") != 1
                or heartbeat.get("provider_id") != "guardian.watch" or heartbeat.get("health") != "healthy"
                or heartbeat.get("authority_boundary") != "read-only-observer"
                or heartbeat.get("boot_id") != boot_id or heartbeat.get("errors") != []
                or observed.tzinfo is None or not 0 <= (current - observed).total_seconds() <= 90):
            raise InventoryError("fresh Guardian incident protection observation is unavailable")
        documents[str(heartbeat_path)] = heartbeat_digest
        pointer_path = self.update_root / "current"
        # Pointer is required for adoption; no guessing from directory age.
        fd = os.open(pointer_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid or info.st_mode & 0o022:
                raise InventoryError("untrusted current update pointer")
            pointer = stream.read(100).strip()
        if TX_PATTERN.fullmatch(pointer) is None:
            raise InventoryError("missing exact current update protection")
        protected.add(pointer)
        coordinator_path = self.update_root / "coordinator.json"
        coordinator, coordinator_digest = _owned_json(coordinator_path, self.owner_uid)
        if coordinator.get("schema_version") != 1:
            raise InventoryError("unknown coordinator protection schema")
        active = coordinator.get("active_transaction_id")
        if active is not None:
            if not isinstance(active, str) or TX_PATTERN.fullmatch(active) is None:
                raise InventoryError("corrupt coordinator protection identity")
            protected.add(active)
        documents[str(coordinator_path)] = coordinator_digest
        documents[str(pointer_path)] = hashlib.sha256(pointer.encode()).hexdigest()
        inventories = [
            _documents(self.generation_root, self.owner_uid),
            _documents(self.update_root, self.owner_uid,
                       excluded=("transactions", "artifact-gc", "coordinator.json", "storage-retirement-authority.json")),
            _documents(self.guardian_active, self.guardian_uid),
        ]
        inventories.extend(_documents(p, self.owner_uid, excluded=("update", "generations"))
                           for p in self.recovery_roots)
        for inventory in inventories:
            for path, value, digest in inventory:
                if path.parent == self.guardian_active:
                    if value.get("kind") != "guardian-assessment" or value.get("version") != 1:
                        raise InventoryError("unknown active Guardian protection schema")
                    decision = value.get("decision", {})
                    catastrophic = decision.get("catastrophic", {})
                    if catastrophic.get("evidence_preservation_required") is not False:
                        raise InventoryError("unscoped Guardian forensic preservation requires review")
                encoded = json.dumps(value, sort_keys=True)
                protected.update(TX_PATTERN.findall(encoded))
                protected_generations.update(re.findall(r"pkg-[0-9a-f]{64}", encoded))
                documents[str(path)] = digest
        return {"documents": documents, "protected_transactions": sorted(protected),
                "protected_package_generations": sorted(protected_generations)}

    def seal_retired(self, *, download_uid: int) -> list[str]:
        """Explicit adoption of historical never-executed invalidated staging.

        Directory ownership is the only effect. This runs under the same
        certified retirement capability and campaign lock, never for an active
        transaction. It does not unlink, recurse, or chown package contents.
        """
        inventory = self.protection_inventory()
        sealed = []
        for tx, _ in self.transactions():
            if not self.eligible(tx, inventory):
                continue
            for key, root in self.roots.items():
                cache = root / tx["transaction_id"] / "staging"
                if not cache.exists() and not cache.is_symlink():
                    continue
                # Identify the durable owner manifest before accepting custody.
                self._manifest(root, tx)
                for ancestor in (root, root / tx["transaction_id"]):
                    fd = self.executor._trusted_directory(ancestor)
                    os.close(fd)
                fd = self.executor._directory(cache, final_uid=download_uid)
                try:
                    info = os.fstat(fd)
                    if info.st_uid not in {self.owner_uid, download_uid} or info.st_mode & 0o022:
                        raise IdentityMismatchError("historical staging has an unsupported owner or permissions")
                    if info.st_uid == self.owner_uid:
                        continue
                    # Reobserve protections immediately before custody transfer.
                    if not self.eligible(tx, self.protection_inventory()):
                        raise InventoryError("historical staging protection changed before sealing")
                    os.fchown(fd, self.owner_uid, self.owner_uid)
                    os.fchmod(fd, 0o755)
                    os.fsync(fd)
                    sealed.append(key + ":" + tx["transaction_id"])
                finally:
                    os.close(fd)
        return sealed

    def transactions(self):
        root = self.update_root / "transactions"
        if not root.is_dir() or root.is_symlink():
            raise InventoryError("transaction evidence unavailable")
        for path in sorted(root.glob("*.json")):
            tx, digest = _owned_json(path, self.owner_uid)
            tx = validate_transaction(tx)
            if path.name != tx["transaction_id"] + ".json":
                raise InventoryError("cross-bound transaction evidence")
            yield tx, digest

    def eligible(self, tx: Mapping[str, Any], inventory: Mapping[str, Any]) -> bool:
        return (tx["state"] == UpdateState.BLOCKED.value
                and bool(tx["blockers"]) and set(tx["blockers"]) <= INVALIDATION
                and all(event["state"] in PRE_EXECUTION for event in tx["history"])
                and tx["transaction_id"] not in inventory["protected_transactions"]
                and tx["package_generation"]["id"] not in inventory["protected_package_generations"])

    def _manifest(self, root: Path, tx: Mapping[str, Any]):
        cache = root / tx["transaction_id"] / "staging"
        path = cache / ("manifest-" + tx["package_generation"]["id"] + ".json")
        value, digest = _owned_json(path, self.owner_uid)
        if (value.get("schema_version") != 2 or value.get("transaction_id") != tx["transaction_id"]
                or value.get("package_generation_id") != tx["package_generation"]["id"]
                or not isinstance(value.get("payloads"), list)):
            raise InventoryError("retirement manifest identity is invalid")
        expected = {(p["name"], p["candidate_version"]) for p in tx["package_generation"]["packages"]}
        identities = [(p.get("name"), p.get("version")) for p in value["payloads"]]
        if len(set(identities)) != len(identities) or set(identities) != expected:
            raise InventoryError("retirement manifest does not bind the complete generation")
        return cache, value, digest

    def report(self, *, source_revision: str, now=None, adoption_uid: int | None = None) -> dict[str, Any]:
        inventory = self.protection_inventory()
        rows, proofs, protected, blockers = [], {}, [], []
        for tx, tx_digest in self.transactions():
            txid = tx["transaction_id"]
            if not self.eligible(tx, inventory):
                protected.append(txid)
                continue
            for key, root in self.roots.items():
                if not (root / txid / "staging").exists():
                    continue
                try:
                    cache, manifest, manifest_digest = self._manifest(root, tx)
                    group = []
                    for payload in manifest["payloads"]:
                        path = Path(payload.get("path", ""))
                        if path.parent != cache:
                            raise IdentityMismatchError("retirement manifest path is not exact")
                        # Completed retirement may leave receipts and a manifest
                        # after its disposable bytes are gone; never reconstruct.
                        if not path.exists() and not path.is_symlink():
                            continue
                        row = self.executor.inspect(key, txid, path.name, adoption_uid=adoption_uid)
                        if row["sha256"] != payload.get("sha256") or row["identity"][2] != payload.get("size"):
                            raise IdentityMismatchError("archive does not match its durable staging manifest")
                        group.append(row)
                        signature = path.with_name(path.name + ".sig")
                        if signature.exists() or signature.is_symlink():
                            group.append(self.executor.inspect(key, txid, signature.name, adoption_uid=adoption_uid))
                    rows.extend(group)
                    proofs[key + ":" + txid] = {"transaction_sha256": tx_digest,
                        "manifest_sha256": manifest_digest, "package_generation_id": tx["package_generation"]["id"]}
                except (OSError, ValueError, RuntimeError) as exc:
                    blockers.append({"transaction_id": txid, "root": key, "reason": str(exc)})
        evidence = {"inventory": inventory, "transactions": proofs}
        if adoption_uid is not None:
            proposal = {"kind": "maho-update-archive-adoption-proposal", "schema_version": 1,
                        "source_revision": source_revision, "objects": rows, "evidence": evidence,
                        "execution_authorized": False}
            proposal["proposal_sha256"] = digest_payload(proposal)
            plan = None
        else:
            proposal = None
            plan = self.executor.plan(rows, source_revision=source_revision, evidence=evidence, now=now)
        return {"plan": plan, "proposal": proposal, "protected_transactions": protected, "blockers": blockers,
                "planned_allocated_bytes": sum(r["allocated_bytes"] for r in rows),
                "file_count": len(rows)}

    def validate_protections(self, plan: Mapping[str, Any], *, target=None) -> None:
        inventory = self.protection_inventory()
        # The full plan is checked before retirement commits. Each unlink then
        # reobserves all live protection roots and the exact target's owner
        # documents, without reparsing every other retired transaction.
        rows = plan["objects"] if target is None else [target]
        if target is not None and target not in plan["objects"]:
            raise InventoryError("archive target is outside its committed retirement plan")
        by_id = {}
        for txid in {row["transaction_id"] for row in rows}:
            if TX_PATTERN.fullmatch(txid) is None:
                raise InventoryError("invalid archive owner identity")
            tx, digest = _owned_json(self.update_root / "transactions" / (txid + ".json"), self.owner_uid)
            tx = validate_transaction(tx)
            if tx["transaction_id"] != txid:
                raise InventoryError("cross-bound archive owner evidence")
            by_id[txid] = tx, digest
        for row in rows:
            key, txid = row["root"], row["transaction_id"]
            if txid not in by_id or not self.eligible(by_id[txid][0], inventory):
                raise InventoryError("archive retirement protection changed")
            tx, digest = by_id[txid]
            cache, manifest, manifest_digest = self._manifest(self.roots[key], tx)
            proof = plan["evidence"]["transactions"].get(key + ":" + txid)
            if proof != {"transaction_sha256": digest, "manifest_sha256": manifest_digest,
                         "package_generation_id": tx["package_generation"]["id"]}:
                raise InventoryError("archive retirement source evidence changed")
            payloads = {Path(p["path"]).name: p for p in manifest["payloads"]
                        if Path(p["path"]).parent == cache}
            name = row["name"][:-4] if row["name"].endswith(".sig") else row["name"]
            if name not in payloads:
                raise InventoryError("archive target is not declared by its staging owner")
            if not row["name"].endswith(".sig") and (
                row["sha256"] != payloads[name]["sha256"] or row["identity"][2] != payloads[name]["size"]
            ):
                raise InventoryError("archive target identity differs from the staging owner")

    def collect(self, *, source_revision: str, now=None) -> dict[str, Any]:
        parent = self.executor._trusted_directory(self.update_root)
        try:
            try:
                os.mkdir("artifact-gc", mode=0o700, dir_fd=parent)
            except FileExistsError:
                pass
            os.fsync(parent)
        finally:
            os.close(parent)
        if self.executor.journal_path.exists() or self.executor.journal_path.is_symlink():
            journal = self.executor._read()
            if journal["phase"] not in {"COMMITTED", "CANCELLED"}:
                if journal["plan"]["source_revision"] != source_revision:
                    raise InventoryError("interrupted retirement belongs to another source")
                try:
                    return self.executor.resume_files(validate_protections=self.validate_protections, now=now)
                except StaleAuthorityError:
                    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
                    expiry = datetime.fromisoformat(journal["plan"]["expires_at"])
                    if journal["phase"] != "PREPARED" or not expiry.tzinfo or current <= expiry:
                        raise
                    # No retirement or unlink began. Cancel the expired plan,
                    # preserve its evidence, and independently plan again.
                    self.executor._write(self.executor.state_root / (
                        "archive-cancelled-" + journal["plan"]["plan_sha256"] + ".json"), journal)
                    self.executor._journal(journal["plan"], "CANCELLED")
        report = self.report(source_revision=source_revision, now=now)
        if not report["file_count"]:
            return {"phase": "NO_DISPOSABLE_FILES", "reclaimed_bytes": 0,
                    "blockers": report["blockers"], "protected_transactions": report["protected_transactions"]}
        receipt = self.executor.execute(report["plan"], validate_protections=self.validate_protections, now=now)
        return {**receipt, "blockers": report["blockers"], "protected_transactions": report["protected_transactions"]}


CERTIFICATION_CHECKS = {"retirement", "active-protection", "recovery-protection", "incident-protection",
                        "interruption", "symlink", "replay", "budget", "coordinator", "guardian-freshness"}
PAYLOAD_FILES = ("lib/maho_generation_gc.py", "lib/maho_update_artifact_lifecycle.py",
                 "lib/maho_update_coordinator.py", "lib/maho_update_staging.py")


def profile_payload_sha256(campaign_root: Path) -> str:
    rows = {name: hashlib.sha256((campaign_root / name).read_bytes()).hexdigest() for name in PAYLOAD_FILES}
    return digest_payload(rows)


def load_retirement_authority(update_root: Path, *, source_revision: str,
                              campaign_root: Path, owner_uid: int = 0) -> dict[str, Any]:
    value, _ = _owned_json(update_root / "storage-retirement-authority.json", owner_uid)
    certificate = value.get("certificate")
    if (value.get("kind") != "maho-update-archive-retirement-authority" or value.get("schema_version") != 1
            or value.get("profile") != PROFILE or value.get("source_revision") != source_revision
            or not isinstance(certificate, dict)
            or value.get("certificate_sha256") != digest_payload(certificate)
            or certificate.get("evidence_kind") != "disposable-vm"
            or certificate.get("source_revision") != source_revision
            or certificate.get("source_payload_sha256") != profile_payload_sha256(campaign_root)
            or set(certificate.get("passed_checks", [])) != CERTIFICATION_CHECKS):
        raise InventoryError("certified archive retirement authority is missing, stale or incomplete")
    return value


def archive_usage(roots=ROOTS) -> int:
    allocated = 0
    for root in roots.values():
        if not root.exists():
            continue
        if root.is_symlink() or not root.is_dir():
            raise InventoryError("unsafe archive budget root")
        for transaction in root.iterdir():
            if TX_PATTERN.fullmatch(transaction.name) is None:
                continue
            if transaction.is_symlink() or not transaction.is_dir():
                raise InventoryError("unsafe transaction archive budget path")
            cache = transaction / "staging"
            if not cache.exists() and not cache.is_symlink():
                continue
            if cache.is_symlink() or not cache.is_dir():
                raise InventoryError("unsafe staging budget path")
            for path in cache.iterdir():
                if ".pkg.tar." not in path.name:
                    continue
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode):
                    raise InventoryError("unsafe staging budget object")
                allocated += info.st_blocks * 512
    return allocated


def staging_budget(transaction: Mapping[str, Any], *, allocated_bytes: int,
                   total_bytes: int, available_bytes: int) -> dict[str, Any]:
    downloads = sum(p["download_size"] for p in transaction["package_generation"]["packages"])
    worst_case = sum(p["download_size"] + p["installed_size"]
                     for p in transaction["package_generation"]["packages"]) + 512 * 1024**2
    reserve = reserve_bytes(total_bytes)
    blockers = []
    if allocated_bytes + downloads > ARCHIVE_BUDGET_BYTES:
        blockers.append("update_archive_storage_budget_exceeded")
    if available_bytes - worst_case < reserve:
        blockers.append("unsafe_post_update_disk_reserve")
    return {"blockers": blockers, "archive_allocated_bytes": allocated_bytes,
            "archive_budget_bytes": ARCHIVE_BUDGET_BYTES, "required_disk_bytes": worst_case,
            "available_disk_bytes": available_bytes, "safe_reserve_bytes": reserve}
