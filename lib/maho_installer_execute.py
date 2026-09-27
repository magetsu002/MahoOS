#!/usr/bin/env python3
"""Fail-closed storage executor for disposable MahoOS test media."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any, Iterator, Mapping, Protocol, Sequence

from maho_installer_plan import (
    build_install_plan,
    normalize_install_attempt_id,
    normalize_disk,
    probe_disk,
    same_disk_identity,
    validate_destructive_confirmation,
    validate_plan_integrity,
)

PHASES = (
    "OBSERVED", "CONFIRMED", "GPT_CREATED", "ESP_FORMATTED", "LUKS_CREATED",
    "LUKS_OPENED", "BTRFS_CREATED", "SUBVOLUMES_CREATED", "MOUNTED",
)
MUTATING_PHASES = PHASES[2:]


class SimulatedInterruption(RuntimeError):
    """Test-only interruption after a durable phase checkpoint."""


class StorageOps(Protocol):
    def observe(self, device: str) -> Mapping[str, Any]: ...
    def is_disposable(self, disk: Mapping[str, Any]) -> bool: ...
    def phase_complete(self, phase: str, plan: Mapping[str, Any], mount_root: Path) -> bool: ...
    def phase_started(self, phase: str, plan: Mapping[str, Any], mount_root: Path) -> bool: ...
    def apply_phase(
        self, phase: str, plan: Mapping[str, Any], mount_root: Path, key_file: Path,
    ) -> None: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json_durable(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_journal(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("installer journal is unreadable") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("installer journal is invalid")
    if payload.get("schema_version") != 2 or payload.get("kind") != "maho-installer-storage-journal":
        raise RuntimeError("installer journal schema is incompatible; start a new install attempt")
    try:
        normalize_install_attempt_id(payload.get("install_attempt_id"))
    except ValueError as exc:
        raise RuntimeError("installer journal lacks a valid install attempt identity") from exc
    phase = payload.get("phase")
    history = payload.get("history")
    if phase not in PHASES or not isinstance(history, list) or not history:
        raise RuntimeError("installer journal is invalid")
    names = [event.get("phase") for event in history if isinstance(event, Mapping)]
    expected = list(PHASES[:PHASES.index(phase) + 1])
    if names != expected:
        raise RuntimeError("installer journal phase history is incoherent")
    return payload


def _checkpoint(path: Path, journal: Mapping[str, Any], phase: str) -> dict[str, Any]:
    previous = str(journal["phase"])
    if PHASES.index(phase) != PHASES.index(previous) + 1:
        raise RuntimeError(f"illegal installer phase transition: {previous} -> {phase}")
    updated = dict(journal)
    updated["phase"] = phase
    updated.pop("in_progress_phase", None)
    updated["history"] = list(journal["history"]) + [{"phase": phase, "recorded_at": _now()}]
    _write_json_durable(path, updated)
    return updated


@contextmanager
def _mutation_lock(journal_path: Path) -> Iterator[None]:
    lock_path = journal_path.with_suffix(journal_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another installer mutation owner is active") from exc
        yield
    finally:
        os.close(descriptor)


def _validate_key_file(path: Path) -> None:
    try:
        metadata = path.stat()
    except OSError as exc:
        raise ValueError("encryption key file is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0:
        raise ValueError("encryption key file must be a non-empty regular file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("encryption key file must not be accessible by group or others")


def execute_storage_plan(
    plan: Mapping[str, Any], *, plan_id: str, confirmation: str,
    journal_path: Path, mount_root: Path, key_file: Path,
    source_revision: str, ops: StorageOps | None = None,
    fail_after: str | None = None, require_root: bool = True,
) -> dict[str, Any]:
    """Apply one exact plan. Only this function owns storage mutation."""
    validated = validate_plan_integrity(plan)
    if require_root and os.geteuid() != 0:
        raise PermissionError("storage execution requires root or an explicit PolicyKit transition")
    if fail_after is not None and fail_after not in MUTATING_PHASES:
        raise ValueError("failure injection phase is invalid")
    if plan_id != validated["plan_id"]:
        raise ValueError("exact plan ID is required")
    if source_revision != validated["source_revision"]:
        raise ValueError("installer source revision drifted")
    if confirmation != validated["destructive_confirmation"]:
        raise ValueError("exact destructive confirmation is required")
    if not validated["ready_for_destructive_confirmation"]:
        raise ValueError("install plan is blocked")
    if validated["execution_scope"] != "disposable-test-media-only":
        raise ValueError("install plan does not authorize disposable test execution")
    mount_root = mount_root.resolve()
    if mount_root == Path("/"):
        raise ValueError("the live root cannot be an installer mount target")
    _validate_key_file(key_file)
    owner = ops or SystemStorageOps()
    device = str(validated["target"]["path"])

    with _mutation_lock(journal_path):
        if journal_path.exists():
            journal = _read_journal(journal_path)
            if journal.get("install_attempt_id") != validated["install_attempt_id"]:
                raise RuntimeError("journal belongs to another install attempt")
            if journal.get("plan_id") != plan_id:
                raise RuntimeError("journal belongs to another install plan")
            if journal.get("target_identity_sha256") != validated["target"]["identity_sha256"]:
                raise RuntimeError("journal belongs to another target identity")
            observed = owner.observe(device)
            normalized = normalize_disk(observed)
            if not same_disk_identity(validated["target"], observed):
                raise RuntimeError("target identity changed; refusing journal resume")
            if normalized["read_only"] or normalized["removable"] or normalized["mountpoints"] and journal["phase"] != "MOUNTED":
                raise RuntimeError("target safety state changed; refusing journal resume")
            if not owner.is_disposable(normalized):
                raise RuntimeError("target is not provably disposable test media")
            completed_index = PHASES.index(journal["phase"])
            for completed in MUTATING_PHASES:
                if PHASES.index(completed) <= completed_index and not owner.phase_complete(completed, validated, mount_root):
                    raise RuntimeError(f"journaled phase no longer verifies: {completed}")
            in_progress = journal.get("in_progress_phase")
            if in_progress is not None:
                expected_next = PHASES[completed_index + 1] if completed_index + 1 < len(PHASES) else None
                if in_progress != expected_next:
                    raise RuntimeError("installer journal in-progress phase is incoherent")
                raise RuntimeError(f"execution was interrupted during {in_progress}; manual inspection required")
        else:
            observed = owner.observe(device)
            normalized = normalize_disk(observed)
            if not owner.is_disposable(normalized):
                raise RuntimeError("target is not provably disposable test media")
            validate_destructive_confirmation(
                validated, observed, source_revision=source_revision, confirmation=confirmation,
            )
            journal = {
                "schema_version": 2,
                "kind": "maho-installer-storage-journal",
                "install_attempt_id": validated["install_attempt_id"],
                "plan_id": plan_id,
                "plan_sha256": validated["plan_sha256"],
                "target_identity_sha256": validated["target"]["identity_sha256"],
                "installation_uuid": validated["installation_identity"]["installation_uuid"],
                "phase": "OBSERVED",
                "history": [{"phase": "OBSERVED", "recorded_at": _now()}],
            }
            _write_json_durable(journal_path, journal)

        if journal["phase"] == "OBSERVED":
            observed = owner.observe(device)
            validate_destructive_confirmation(
                validated, observed, source_revision=source_revision, confirmation=confirmation,
            )
            journal = _checkpoint(journal_path, journal, "CONFIRMED")

        start_index = PHASES.index(journal["phase"])
        for phase in PHASES[start_index + 1:]:
            if phase == "GPT_CREATED":
                # This is deliberately adjacent to the first write.
                observed = owner.observe(device)
                if not owner.is_disposable(normalize_disk(observed)):
                    raise RuntimeError("target stopped being disposable before first mutation")
                validate_destructive_confirmation(
                    validated, observed, source_revision=source_revision, confirmation=confirmation,
                )
            if owner.phase_complete(phase, validated, mount_root):
                raise RuntimeError(f"unjournaled mutation detected at phase {phase}; manual inspection required")
            if owner.phase_started(phase, validated, mount_root):
                raise RuntimeError(f"partial mutation detected at phase {phase}; manual inspection required")
            journal = dict(journal)
            journal["in_progress_phase"] = phase
            _write_json_durable(journal_path, journal)
            owner.apply_phase(phase, validated, mount_root, key_file)
            if not owner.phase_complete(phase, validated, mount_root):
                raise RuntimeError(f"phase did not reach its postcondition: {phase}")
            journal = _checkpoint(journal_path, journal, phase)
            if fail_after == phase:
                raise SimulatedInterruption(f"simulated interruption after {phase}")
        return journal


class SystemStorageOps:
    """The sole subprocess-backed mutation provider."""

    def _run(
        self, command: Sequence[str], *, input_text: str | None = None, check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(command, input=input_text, text=True, capture_output=True, check=False)
        if check and result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or str(result.returncode)
            raise RuntimeError(f"storage command failed ({command[0]}): {detail}")
        return result

    def observe(self, device: str) -> Mapping[str, Any]:
        return probe_disk(device)

    def is_disposable(self, disk: Mapping[str, Any]) -> bool:
        normalized = normalize_disk(disk)
        if normalized["path"].startswith("/dev/loop") and normalized["backing_file"]:
            return True
        virtual_path = re.fullmatch(r"/dev/vd[a-z]+", normalized["path"]) is not None
        return virtual_path and normalized["serial"].startswith("MAHO-DISPOSABLE-")

    def _blkid(self, device: str) -> dict[str, str]:
        result = self._run(("blkid", "-o", "export", device), check=False)
        if result.returncode != 0:
            return {}
        return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)

    def _gpt_complete(self, plan: Mapping[str, Any]) -> bool:
        result = self._run(("sfdisk", "--json", str(plan["target"]["path"])), check=False)
        if result.returncode != 0:
            return False
        try:
            table = json.loads(result.stdout)["partitiontable"]
            partitions = table["partitions"]
        except (KeyError, TypeError, json.JSONDecodeError):
            return False
        expected = plan["layout_contract"]["partitions"]
        if table.get("label") != "gpt" or str(table.get("id", "")).lower() != plan["installation_identity"]["gpt_disk_guid"]:
            return False
        gpt = plan["geometry"]["gpt"]
        if int(table.get("firstlba", -1)) != gpt["first_usable_lba"] or int(table.get("lastlba", -1)) != gpt["last_usable_lba"]:
            return False
        if int(table.get("sectorsize", -1)) != plan["geometry"]["logical_sector_size_bytes"]:
            return False
        if not isinstance(partitions, list) or len(partitions) != 2:
            return False
        for actual, wanted in zip(partitions, expected):
            if int(actual.get("start", -1)) != wanted["first_lba"] or int(actual.get("size", -1)) != wanted["sector_count"]:
                return False
            if str(actual.get("uuid", "")).lower() != wanted["partition_uuid"]:
                return False
            if str(actual.get("type", "")).lower() != wanted["type_guid"]:
                return False
            if str(actual.get("name", "")) != wanted["name"]:
                return False
        return True

    def _luks_complete(self, plan: Mapping[str, Any]) -> bool:
        partition = plan["layout_contract"]["partitions"][1]["path"]
        uuid_result = self._run(("cryptsetup", "luksUUID", partition), check=False)
        if uuid_result.returncode != 0 or uuid_result.stdout.strip() != plan["installation_identity"]["luks_uuid"]:
            return False
        metadata_result = self._run(("cryptsetup", "luksDump", "--dump-json-metadata", partition), check=False)
        if metadata_result.returncode != 0:
            return False
        try:
            metadata = json.loads(metadata_result.stdout)
            segments = metadata["segments"].values()
            keyslots = metadata["keyslots"].values()
        except (KeyError, AttributeError, json.JSONDecodeError):
            return False
        contract = plan["encryption_contract"]
        segment_ok = any(
            segment.get("encryption") == contract["cipher"]
            and int(segment.get("sector_size", -1)) == contract["sector_size_bytes"]
            for segment in segments
        )
        keyslot_ok = any(
            int(keyslot.get("key_size", -1)) * 8 == contract["key_size_bits"]
            and isinstance(keyslot.get("kdf"), Mapping)
            and keyslot["kdf"].get("type") == contract["pbkdf"]
            for keyslot in keyslots
        )
        return segment_ok and keyslot_ok

    def _subvolume_names(self, plan: Mapping[str, Any], mount_root: Path) -> set[str]:
        mapper = Path("/dev/mapper") / plan["encryption_contract"]["mapper_name"]
        if not mapper.exists():
            return set()
        mount_root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="maho-subvolume-check-", dir=mount_root.parent) as raw:
            check_root = Path(raw)
            mounted = False
            try:
                result = self._run(("mount", "-o", "ro,subvolid=5", str(mapper), str(check_root)), check=False)
                mounted = result.returncode == 0
                if not mounted:
                    return set()
                return {
                    name
                    for name in plan["layout_contract"]["btrfs"]["subvolumes"]
                    if self._run(("btrfs", "subvolume", "show", str(check_root / name)), check=False).returncode == 0
                }
            finally:
                if mounted:
                    self._run(("umount", str(check_root)), check=False)

    def phase_complete(self, phase: str, plan: Mapping[str, Any], mount_root: Path) -> bool:
        partitions = plan["layout_contract"]["partitions"]
        mapper = Path("/dev/mapper") / plan["encryption_contract"]["mapper_name"]
        if phase == "GPT_CREATED":
            return self._gpt_complete(plan)
        if phase == "ESP_FORMATTED":
            info = self._blkid(partitions[0]["path"])
            expected_id = plan["installation_identity"]["fat_volume_id"]
            return (
                info.get("TYPE") == "vfat"
                and info.get("LABEL") == "MAHO_ESP"
                and info.get("UUID", "").replace("-", "").upper() == expected_id
            )
        if phase == "LUKS_CREATED":
            return self._luks_complete(plan)
        if phase == "LUKS_OPENED":
            return mapper.exists() and self._run(("cryptsetup", "status", plan["encryption_contract"]["mapper_name"]), check=False).returncode == 0
        if phase == "BTRFS_CREATED":
            info = self._blkid(str(mapper))
            return info.get("TYPE") == "btrfs" and info.get("UUID") == plan["installation_identity"]["btrfs_uuid"]
        if phase == "SUBVOLUMES_CREATED":
            return self._subvolume_names(plan, mount_root) == set(plan["layout_contract"]["btrfs"]["subvolumes"])
        if phase == "MOUNTED":
            targets = [mount_root, mount_root / "home", mount_root / ".snapshots", mount_root / "var/log", mount_root / "boot"]
            for target in targets:
                result = self._run(("findmnt", "--noheadings", "--output", "TARGET", "--target", str(target)), check=False)
                if result.returncode != 0 or result.stdout.strip() != str(target):
                    return False
            return self._run(("findmnt", "--noheadings", "--types", "vfat", "--target", str(mount_root / "boot")), check=False).returncode == 0
        raise ValueError("unknown execution phase")

    def phase_started(self, phase: str, plan: Mapping[str, Any], mount_root: Path) -> bool:
        partitions = plan["layout_contract"]["partitions"]
        mapper = Path("/dev/mapper") / plan["encryption_contract"]["mapper_name"]
        if phase == "GPT_CREATED":
            return self._run(("sfdisk", "--json", str(plan["target"]["path"])), check=False).returncode == 0
        if phase == "ESP_FORMATTED":
            return bool(self._blkid(partitions[0]["path"]).get("TYPE"))
        if phase == "LUKS_CREATED":
            return bool(self._blkid(partitions[1]["path"]).get("TYPE"))
        if phase == "LUKS_OPENED":
            return mapper.exists()
        if phase == "BTRFS_CREATED":
            return bool(self._blkid(str(mapper)).get("TYPE"))
        if phase == "SUBVOLUMES_CREATED":
            return bool(self._subvolume_names(plan, mount_root))
        if phase == "MOUNTED":
            targets = [mount_root, mount_root / "home", mount_root / ".snapshots", mount_root / "var/log", mount_root / "boot"]
            return any(
                (result := self._run(("findmnt", "--noheadings", "--output", "TARGET", "--target", str(target)), check=False)).returncode == 0
                and result.stdout.strip() == str(target)
                for target in targets
            )
        raise ValueError("unknown execution phase")

    def apply_phase(
        self, phase: str, plan: Mapping[str, Any], mount_root: Path, key_file: Path,
    ) -> None:
        device = str(plan["target"]["path"])
        partitions = plan["layout_contract"]["partitions"]
        identifiers = plan["installation_identity"]
        encryption = plan["encryption_contract"]
        mapper = Path("/dev/mapper") / encryption["mapper_name"]
        if phase == "GPT_CREATED":
            lines = [
                "label: gpt", f"label-id: {identifiers['gpt_disk_guid']}", "unit: sectors",
                f"first-lba: {plan['geometry']['gpt']['first_usable_lba']}",
                f"last-lba: {plan['geometry']['gpt']['last_usable_lba']}",
                f"sector-size: {plan['geometry']['logical_sector_size_bytes']}", "",
                f"{partitions[0]['path']} : start={partitions[0]['first_lba']}, size={partitions[0]['sector_count']}, type={partitions[0]['type_guid']}, uuid={partitions[0]['partition_uuid']}, name=\"Maho ESP\"",
                f"{partitions[1]['path']} : start={partitions[1]['first_lba']}, size={partitions[1]['sector_count']}, type={partitions[1]['type_guid']}, uuid={partitions[1]['partition_uuid']}, name=\"Maho Crypt\"",
                "",
            ]
            self._run(("sfdisk", "--wipe", "always", "--wipe-partitions", "always", device), input_text="\n".join(lines))
            self._run(("partx", "--update", device))
            self._run(("udevadm", "settle"))
        elif phase == "ESP_FORMATTED":
            self._run(("mkfs.fat", "-F", "32", "-n", "MAHO_ESP", "-i", identifiers["fat_volume_id"], partitions[0]["path"]))
        elif phase == "LUKS_CREATED":
            self._run((
                "cryptsetup", "luksFormat", "--batch-mode", "--type", "luks2",
                "--cipher", encryption["cipher"], "--key-size", str(encryption["key_size_bits"]),
                "--pbkdf", encryption["pbkdf"], "--sector-size", str(encryption["sector_size_bytes"]),
                "--uuid", identifiers["luks_uuid"], "--key-file", str(key_file), partitions[1]["path"],
            ))
        elif phase == "LUKS_OPENED":
            self._run(("cryptsetup", "open", "--type", "luks", "--key-file", str(key_file), partitions[1]["path"], encryption["mapper_name"]))
        elif phase == "BTRFS_CREATED":
            self._run(("mkfs.btrfs", "-f", "-L", "MAHO_ROOT", "-U", identifiers["btrfs_uuid"], str(mapper)))
        elif phase == "SUBVOLUMES_CREATED":
            top = mount_root.with_name(mount_root.name + ".top")
            top.mkdir(parents=True, exist_ok=True)
            self._run(("mount", "-o", "subvolid=5", str(mapper), str(top)))
            try:
                for name in plan["layout_contract"]["btrfs"]["subvolumes"]:
                    self._run(("btrfs", "subvolume", "create", str(top / name)))
            finally:
                self._run(("umount", str(top)))
                top.rmdir()
        elif phase == "MOUNTED":
            mount_root.mkdir(parents=True, exist_ok=True)
            self._run(("mount", "-o", "subvol=@", str(mapper), str(mount_root)))
            for relative in ("home", ".snapshots", "var/log", "boot"):
                (mount_root / relative).mkdir(parents=True, exist_ok=True)
            self._run(("mount", "-o", "subvol=@home", str(mapper), str(mount_root / "home")))
            self._run(("mount", "-o", "subvol=@snapshots", str(mapper), str(mount_root / ".snapshots")))
            self._run(("mount", "-o", "subvol=@var_log", str(mapper), str(mount_root / "var/log")))
            self._run(("mount", partitions[0]["path"], str(mount_root / "boot")))
        else:
            raise ValueError("unknown execution phase")
