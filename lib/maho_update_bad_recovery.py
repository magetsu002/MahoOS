#!/usr/bin/env python3
"""Transaction-bound recovery for a failed S2.2 normal update candidate."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
from typing import Any, Callable, Mapping

from guardian_bad_update_recovery import select_exact_previous_generation
from maho_update_candidate_generation import load_current_verified_generations
from maho_update_execution_authority import (
    parse_activation_handoff, read_activation_handoff_consumption,
)
from maho_update_native import NativeBtrfsOps
from maho_update_state import (
    UpdateState, publish_transaction, read_transaction, transaction_path,
    transition_transaction,
)


AUTHORITY_TTL = timedelta(minutes=5)
MAX_CLOCK_SKEW = timedelta(minutes=2)
_SHA40 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GEN = re.compile(r"gen-[0-9a-f]{64}")
_KGEN = re.compile(r"kgen-[0-9a-f]{64}")
_TXID = re.compile(r"upd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")
_UUID = re.compile(r"[0-9a-fA-F-]{36}")
_ARTIFACT = re.compile(r"art-[0-9a-f]{64}")
_EVIDENCE_DIRECTORIES = {
    "automatic-executions", "recovery-authorities",
    "recovery-authority-consumptions",
}
_EXECUTION_FIELDS = {
    "failed_candidate_uuid", "previous_root_uuid", "filesystem_uuid",
    "failed_root_name", "root_exchange_completed", "failed_root_read_only",
    "selected_root_writable", "boot_sha256", "package_manager_invoked",
    "firmware_mutated", "home_mutated", "reboot_performed",
    "reboot_required",
}


class RecoveryTerminalCommitError(RuntimeError):
    """Terminal recovery verification succeeded, but durable commit did not."""


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_stamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} is invalid")
    return parsed.astimezone(timezone.utc)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode()


def _artifact_id(value: Mapping[str, Any]) -> str:
    return "art-" + hashlib.sha256(_canonical(value)).hexdigest()


def _open_evidence_directory(path: Path, *, create: bool) -> tuple[int, int, str]:
    directory = path.parent.name
    if directory not in _EVIDENCE_DIRECTORIES or path.name in {"", ".", ".."}:
        raise ValueError("recovery evidence path is outside the bounded state root")
    state_root = path.parent.parent
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    root_fd = os.open(state_root, flags)
    try:
        if create:
            try:
                os.mkdir(directory, 0o755, dir_fd=root_fd)
                os.fsync(root_fd)
            except FileExistsError:
                pass
        directory_fd = os.open(directory, flags, dir_fd=root_fd)
        if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
            raise ValueError("recovery evidence parent is not a directory")
        if create:
            os.fchmod(directory_fd, 0o755)
        return root_fd, directory_fd, path.name
    except Exception:
        os.close(root_fd)
        raise


def _atomic_json(path: Path, payload: Mapping[str, Any], *, exclusive: bool = False) -> None:
    root_fd, directory_fd, name = _open_evidence_directory(path, create=True)
    data = _canonical(payload) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    temporary = f".{name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    try:
        target = name if exclusive else temporary
        descriptor = os.open(target, flags, 0o600, dir_fd=directory_fd)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if not exclusive:
            os.rename(
                temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
            )
        os.chmod(name, 0o644, dir_fd=directory_fd, follow_symlinks=False)
        os.fsync(directory_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)
        os.close(root_fd)


def _read_evidence_json(path: Path, unavailable: str) -> dict[str, Any]:
    root_fd: int | None = None
    directory_fd: int | None = None
    descriptor: int | None = None
    try:
        root_fd, directory_fd, name = _open_evidence_directory(path, create=False)
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("recovery evidence is not a regular file")
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as stream:
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(unavailable) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory_fd is not None:
            os.close(directory_fd)
        if root_fd is not None:
            os.close(root_fd)
    if not isinstance(value, Mapping):
        raise ValueError("recovery evidence is invalid")
    return dict(value)


def _evidence_exists(path: Path) -> bool:
    try:
        root_fd, directory_fd, name = _open_evidence_directory(path, create=False)
    except FileNotFoundError:
        return False
    try:
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(name, flags, dir_fd=directory_fd)
        except FileNotFoundError:
            return False
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("recovery evidence is not a regular file")
            return True
        finally:
            os.close(descriptor)
    finally:
        os.close(directory_fd)
        os.close(root_fd)


def recovery_record_path(state_root: Path, transaction_id: str) -> Path:
    if _TXID.fullmatch(transaction_id) is None:
        raise ValueError("invalid update transaction identity")
    return state_root / "automatic-executions" / f"{transaction_id}.json"


def authority_path(state_root: Path, transaction_id: str) -> Path:
    if _TXID.fullmatch(transaction_id) is None:
        raise ValueError("invalid update transaction identity")
    return state_root / "recovery-authorities" / f"{transaction_id}.json"


def consumption_path(state_root: Path, authority_id: str) -> Path:
    if not isinstance(authority_id, str) or _ARTIFACT.fullmatch(authority_id) is None:
        raise ValueError("invalid recovery authority identity")
    return state_root / "recovery-authority-consumptions" / f"{authority_id}.json"


def _read_record(state_root: Path, transaction_id: str) -> dict[str, Any]:
    return _read_evidence_json(
        recovery_record_path(state_root, transaction_id),
        "normal update execution record is unavailable",
    )


def executor_identity(campaign_root: Path) -> dict[str, Any]:
    modules = (
        "guardian_bad_update_recovery.py", "maho_generation_v2.py",
        "maho_kernel_generation.py", "maho_live_generation.py",
        "maho_trust_identity.py", "maho_update_bad_recovery.py",
        "maho_update_candidate_generation.py", "maho_update_effects.py",
        "maho_update_execution_authority.py", "maho_update_native.py",
        "maho_update_state.py",
    )
    identities: dict[str, str] = {}
    for name in modules:
        path = campaign_root / "lib" / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"recovery executor module unavailable:{name}")
        identities[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    value = {
        "campaign_root": str(campaign_root.resolve(strict=True)),
        "modules": identities,
        "interpreter": str(Path("/proc/self/exe").resolve(strict=True)),
    }
    value["executor_id"] = _artifact_id(value)
    return value


@dataclass(frozen=True)
class BadUpdateRecoveryAuthority:
    authority_id: str
    transaction_id: str
    source_revision: str
    filesystem_uuid: str
    failed_candidate_uuid: str
    failed_system_generation_id: str
    previous_root_uuid: str
    previous_system_generation_id: str
    kernel_generation_id: str
    guardian_decision_id: str
    executor: Mapping[str, Any]
    issued_at: str
    expires_at: str
    nonce: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "maho-bad-update-recovery-authority",
            "authority_id": self.authority_id,
            "authority_scope": "exchange-exact-failed-root-with-exact-previous-once",
            "transaction_id": self.transaction_id,
            "source_revision": self.source_revision,
            "filesystem_uuid": self.filesystem_uuid,
            "failed_candidate_uuid": self.failed_candidate_uuid,
            "failed_system_generation_id": self.failed_system_generation_id,
            "previous_root_uuid": self.previous_root_uuid,
            "previous_system_generation_id": self.previous_system_generation_id,
            "kernel_generation_id": self.kernel_generation_id,
            "guardian_decision_id": self.guardian_decision_id,
            "executor": dict(self.executor),
            "effects": ["btrfs-root-entry-exchange", "recovery-evidence-publication"],
            "excluded_effects": ["home", "packages", "firmware", "boot-artifacts", "arbitrary-paths"],
            "maximum_attempts": 1,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
        }


def _authority_material(value: Mapping[str, Any]) -> dict[str, Any]:
    material = dict(value)
    material.pop("authority_id", None)
    return material


def issue_recovery_authority(
    *, transaction: Mapping[str, Any], provider_evidence: Mapping[str, Any],
    guardian_decision: Mapping[str, Any], executor: Mapping[str, Any],
    now: datetime | None = None,
) -> BadUpdateRecoveryAuthority:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    txid = transaction.get("transaction_id")
    if transaction.get("state") != UpdateState.RECOVERING.value:
        raise ValueError("recovery authority requires RECOVERING transaction")
    if guardian_decision.get("outcome") != "RECOVER_EXACT_PREVIOUS":
        raise ValueError("Guardian did not authorize exact previous generation recovery")
    bindings = (
        ("transaction_id", txid),
        ("failed_candidate_uuid", provider_evidence.get("failed_candidate_uuid")),
        ("failed_system_generation_id", provider_evidence.get("failed_system_generation_id")),
        ("selected_root_uuid", provider_evidence.get("previous_root_uuid")),
        ("selected_system_generation_id", provider_evidence.get("previous_system_generation_id")),
        ("selected_kernel_generation_id", provider_evidence.get("current_kernel_generation_id")),
    )
    if any(guardian_decision.get(key) != expected for key, expected in bindings):
        raise ValueError("Guardian recovery decision binding mismatch")
    issued = _stamp(current)
    expires = _stamp(current + AUTHORITY_TTL)
    material = {
        "schema_version": 1,
        "kind": "maho-bad-update-recovery-authority",
        "authority_scope": "exchange-exact-failed-root-with-exact-previous-once",
        "transaction_id": txid,
        "source_revision": transaction.get("source_revision"),
        "filesystem_uuid": provider_evidence.get("filesystem_uuid"),
        "failed_candidate_uuid": provider_evidence.get("failed_candidate_uuid"),
        "failed_system_generation_id": provider_evidence.get("failed_system_generation_id"),
        "previous_root_uuid": provider_evidence.get("previous_root_uuid"),
        "previous_system_generation_id": provider_evidence.get("previous_system_generation_id"),
        "kernel_generation_id": provider_evidence.get("current_kernel_generation_id"),
        "guardian_decision_id": guardian_decision.get("decision_id"),
        "executor": dict(executor),
        "effects": ["btrfs-root-entry-exchange", "recovery-evidence-publication"],
        "excluded_effects": ["home", "packages", "firmware", "boot-artifacts", "arbitrary-paths"],
        "maximum_attempts": 1,
        "issued_at": issued,
        "expires_at": expires,
        "nonce": secrets.token_hex(16),
    }
    authority_id = _artifact_id(material)
    return parse_recovery_authority({**material, "authority_id": authority_id})


def parse_recovery_authority(value: Mapping[str, Any]) -> BadUpdateRecoveryAuthority:
    data = dict(value)
    required = {
        "schema_version", "kind", "authority_id", "authority_scope",
        "transaction_id", "source_revision", "filesystem_uuid",
        "failed_candidate_uuid", "failed_system_generation_id",
        "previous_root_uuid", "previous_system_generation_id",
        "kernel_generation_id", "guardian_decision_id", "executor",
        "effects", "excluded_effects", "maximum_attempts", "issued_at",
        "expires_at", "nonce",
    }
    if set(data) != required or data.get("schema_version") != 1:
        raise ValueError("recovery authority fields are invalid")
    if data.get("kind") != "maho-bad-update-recovery-authority" or data.get("authority_scope") != "exchange-exact-failed-root-with-exact-previous-once":
        raise ValueError("recovery authority kind is invalid")
    if data.get("effects") != ["btrfs-root-entry-exchange", "recovery-evidence-publication"]:
        raise ValueError("recovery authority effects are invalid")
    if data.get("excluded_effects") != ["home", "packages", "firmware", "boot-artifacts", "arbitrary-paths"]:
        raise ValueError("recovery authority exclusions are invalid")
    if data.get("maximum_attempts") != 1:
        raise ValueError("recovery authority attempt bound is invalid")
    if _artifact_id(_authority_material(data)) != data.get("authority_id"):
        raise ValueError("recovery authority identity mismatch")
    if not isinstance(data.get("transaction_id"), str) or _TXID.fullmatch(data["transaction_id"]) is None:
        raise ValueError("recovery authority transaction identity is invalid")
    if not isinstance(data.get("source_revision"), str) or _SHA40.fullmatch(data["source_revision"]) is None:
        raise ValueError("recovery authority source revision is invalid")
    for key in ("filesystem_uuid", "failed_candidate_uuid", "previous_root_uuid"):
        if not isinstance(data.get(key), str) or _UUID.fullmatch(data[key]) is None:
            raise ValueError(f"recovery authority {key} is invalid")
    for key, pattern in (
        ("failed_system_generation_id", _GEN),
        ("previous_system_generation_id", _GEN),
        ("kernel_generation_id", _KGEN),
    ):
        if not isinstance(data.get(key), str) or pattern.fullmatch(data[key]) is None:
            raise ValueError(f"recovery authority {key} is invalid")
    if not isinstance(data.get("guardian_decision_id"), str) or _ARTIFACT.fullmatch(data["guardian_decision_id"]) is None:
        raise ValueError("recovery authority Guardian decision is invalid")
    if not isinstance(data.get("executor"), Mapping) or not data["executor"].get("executor_id"):
        raise ValueError("recovery executor identity is invalid")
    issued = _parse_stamp(data.get("issued_at"), "recovery authority issue time")
    expires = _parse_stamp(data.get("expires_at"), "recovery authority expiry")
    if expires - issued != AUTHORITY_TTL:
        raise ValueError("recovery authority lifetime is invalid")
    if not isinstance(data.get("nonce"), str) or re.fullmatch(r"[0-9a-f]{32}", data["nonce"]) is None:
        raise ValueError("recovery authority nonce is invalid")
    return BadUpdateRecoveryAuthority(
        authority_id=data["authority_id"], transaction_id=data["transaction_id"],
        source_revision=data["source_revision"], filesystem_uuid=data["filesystem_uuid"],
        failed_candidate_uuid=data["failed_candidate_uuid"],
        failed_system_generation_id=data["failed_system_generation_id"],
        previous_root_uuid=data["previous_root_uuid"],
        previous_system_generation_id=data["previous_system_generation_id"],
        kernel_generation_id=data["kernel_generation_id"],
        guardian_decision_id=data["guardian_decision_id"], executor=dict(data["executor"]),
        issued_at=data["issued_at"], expires_at=data["expires_at"], nonce=data["nonce"],
    )


def verify_recovery_authority(
    value: Mapping[str, Any], *, transaction: Mapping[str, Any],
    provider_evidence: Mapping[str, Any], guardian_decision: Mapping[str, Any],
    executor: Mapping[str, Any], state_root: Path, now: datetime | None = None,
    allow_started_reconciliation: bool = False,
    allow_consumed: bool = False,
) -> BadUpdateRecoveryAuthority:
    authority = parse_recovery_authority(value)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    issued = _parse_stamp(authority.issued_at, "recovery authority issue time")
    expires = _parse_stamp(authority.expires_at, "recovery authority expiry")
    if current < issued - MAX_CLOCK_SKEW or (
        current > expires and not allow_started_reconciliation
    ):
        raise ValueError("recovery authority is expired or not yet valid")
    expected = {
        "transaction_id": transaction.get("transaction_id"),
        "source_revision": transaction.get("source_revision"),
        "filesystem_uuid": provider_evidence.get("filesystem_uuid"),
        "failed_candidate_uuid": provider_evidence.get("failed_candidate_uuid"),
        "failed_system_generation_id": provider_evidence.get("failed_system_generation_id"),
        "previous_root_uuid": provider_evidence.get("previous_root_uuid"),
        "previous_system_generation_id": provider_evidence.get("previous_system_generation_id"),
        "kernel_generation_id": provider_evidence.get("current_kernel_generation_id"),
        "guardian_decision_id": guardian_decision.get("decision_id"),
    }
    if any(getattr(authority, key) != value for key, value in expected.items()):
        raise ValueError("recovery authority binding mismatch")
    if dict(authority.executor) != dict(executor):
        raise ValueError("recovery authority executor identity mismatch")
    if _evidence_exists(consumption_path(state_root, authority.authority_id)) and not allow_consumed:
        raise ValueError("recovery authority was already consumed")
    return authority


def _validate_execution(
    execution: Mapping[str, Any], authority: BadUpdateRecoveryAuthority,
) -> None:
    if set(execution) != _EXECUTION_FIELDS:
        raise ValueError("recovery execution scope is not closed")
    required = {
        "failed_candidate_uuid": authority.failed_candidate_uuid,
        "previous_root_uuid": authority.previous_root_uuid,
        "filesystem_uuid": authority.filesystem_uuid,
        "failed_root_name": "@maho-update-backup-" + authority.transaction_id.rsplit("-", 1)[1],
        "root_exchange_completed": True,
        "failed_root_read_only": True,
        "selected_root_writable": True,
        "package_manager_invoked": False,
        "firmware_mutated": False,
        "home_mutated": False,
        "reboot_performed": False,
        "reboot_required": True,
    }
    if any(execution.get(key) != expected for key, expected in required.items()):
        raise ValueError("recovery execution exceeded exact authority")
    boot = execution.get("boot_sha256")
    if (
        not isinstance(boot, Mapping)
        or set(boot) == set()
        or any(not isinstance(key, str) or not isinstance(value, str) or _SHA256.fullmatch(value) is None
               for key, value in boot.items())
    ):
        raise ValueError("recovery execution boot identity is invalid")


def consume_recovery_authority(
    state_root: Path, authority: BadUpdateRecoveryAuthority,
    execution: Mapping[str, Any], *, now: datetime | None = None,
) -> dict[str, Any]:
    _validate_execution(execution, authority)
    receipt = {
        "schema_version": 1,
        "kind": "maho-bad-update-recovery-authority-consumption",
        "authority_id": authority.authority_id,
        "transaction_id": authority.transaction_id,
        "consumed_at": _stamp((now or datetime.now(timezone.utc)).astimezone(timezone.utc)),
        "attempt": 1,
        "execution": dict(execution),
    }
    receipt["consumption_id"] = _artifact_id(receipt)
    _atomic_json(consumption_path(state_root, authority.authority_id), receipt, exclusive=True)
    return receipt


def read_recovery_consumption(
    state_root: Path, authority: BadUpdateRecoveryAuthority,
) -> dict[str, Any]:
    value = _read_evidence_json(
        consumption_path(state_root, authority.authority_id),
        "recovery authority consumption is unavailable",
    )
    data = dict(value)
    identity = data.pop("consumption_id", None)
    if identity != _artifact_id(data):
        raise ValueError("recovery authority consumption identity mismatch")
    execution = data.get("execution")
    if (
        data.get("schema_version") != 1
        or data.get("kind") != "maho-bad-update-recovery-authority-consumption"
        or data.get("authority_id") != authority.authority_id
        or data.get("transaction_id") != authority.transaction_id
        or data.get("attempt") != 1
        or not isinstance(execution, Mapping)
    ):
        raise ValueError("recovery authority consumption binding is invalid")
    _validate_execution(execution, authority)
    return dict(value)


def _recovering_evidence(transaction: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    for event in reversed(transaction.get("history", [])):
        evidence = event.get("evidence")
        if event.get("state") == UpdateState.RECOVERING.value and isinstance(evidence, Mapping):
            provider = evidence.get("provider")
            decision = evidence.get("guardian_decision")
            if isinstance(provider, Mapping) and isinstance(decision, Mapping):
                return dict(provider), dict(decision)
    raise ValueError("RECOVERING transaction lacks exact provider and Guardian evidence")


def _reconstructed_execution(
    authority: BadUpdateRecoveryAuthority, boot_sha256: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "failed_candidate_uuid": authority.failed_candidate_uuid,
        "previous_root_uuid": authority.previous_root_uuid,
        "filesystem_uuid": authority.filesystem_uuid,
        "failed_root_name": "@maho-update-backup-" + authority.transaction_id.rsplit("-", 1)[1],
        "root_exchange_completed": True,
        "failed_root_read_only": True,
        "selected_root_writable": True,
        "boot_sha256": dict(boot_sha256),
        "package_manager_invoked": False,
        "firmware_mutated": False,
        "home_mutated": False,
        "reboot_performed": False,
        "reboot_required": True,
    }


def _package_versions(
    transaction: Mapping[str, Any], *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, str]:
    names = [item["name"] for item in transaction["package_generation"]["packages"]]
    completed = runner(["pacman", "-Q", "--", *names], text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError("recovered package generation query failed")
    observed: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        name, separator, version = line.partition(" ")
        if separator:
            observed[name] = version.strip()
    expected = {
        item["name"]: item["installed_version"]
        for item in transaction["package_generation"]["packages"]
    }
    if observed != expected:
        raise RuntimeError("recovered package generation does not match previous known-good root")
    return observed


def _verified_root_identity_binding(
    live: Mapping[str, Any], identity: Any, *, previous_root_uuid: str,
    filesystem_uuid: str,
) -> bool:
    """Require an exact root UUID proof, including for legacy @ manifests."""
    if identity is None:
        return False
    filesystem_matches = (
        str(live.get("filesystem_uuid", "")).lower() == filesystem_uuid.lower()
        and str(getattr(identity, "filesystem_identity", "")).lower()
        == f"uuid:{filesystem_uuid.lower()}"
    )
    if not filesystem_matches or live.get("root_subvolume_uuid") != previous_root_uuid:
        return False
    snapshot_identity = getattr(identity, "snapshot_identity", "")
    if snapshot_identity == f"btrfs-uuid:{previous_root_uuid}":
        return True
    # Older verified manifests named the canonical live root instead of recording
    # its UUID. Accept that one legacy spelling only when the signed live
    # publication supplies the exact UUID and filesystem binding above.
    return snapshot_identity == "btrfs-subvolume:@"


def _validate_target_recovery_artifacts(
    generation_root: Path, *, previous_root_uuid: str, filesystem_uuid: str,
    system_generation_id: str, kernel_generation_id: str,
) -> tuple[dict[str, Any], Any, Any]:
    live, system, kernel = load_current_verified_generations(generation_root)
    identity = getattr(system, "root_identity", None)
    if (
        live.get("system_generation_id") != system_generation_id
        or live.get("kernel_generation_id") != kernel_generation_id
        or live.get("root_subvolume_uuid") != previous_root_uuid
        or str(live.get("filesystem_uuid", "")).lower() != filesystem_uuid.lower()
        or str(system.generation_id) != system_generation_id
        or str(kernel.kernel_generation_id) != kernel_generation_id
        or not _verified_root_identity_binding(
            live, identity, previous_root_uuid=previous_root_uuid,
            filesystem_uuid=filesystem_uuid,
        )
    ):
        raise ValueError("retained previous generation artifacts do not bind the selected root")
    path = generation_root / "evidence/compatibility" / (
        f"{system_generation_id}--{kernel_generation_id}.json"
    )
    try:
        compatibility = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("retained previous generation compatibility artifact is unavailable") from exc
    if (
        not isinstance(compatibility, Mapping)
        or compatibility.get("system_generation_id") != system_generation_id
        or compatibility.get("kernel_generation_id") != kernel_generation_id
        or compatibility.get("root_manifest_sha256") != identity.root_manifest_sha256
        or str(compatibility.get("filesystem_identity", "")).lower()
        != identity.filesystem_identity.lower()
        or compatibility.get("kernel_abi") != kernel.kernel_abi
        or compatibility.get("modules_abi") != kernel.modules_abi
        or compatibility.get("independently_verified") is not True
    ):
        raise ValueError("retained previous generation compatibility proof is invalid")
    return live, system, kernel


def _publish_recovery_seed(
    state_root: Path, transaction_id: str, transaction: Mapping[str, Any],
    record: Mapping[str, Any], authority: BadUpdateRecoveryAuthority,
) -> None:
    publish_transaction(state_root, transaction)
    _atomic_json(recovery_record_path(state_root, transaction_id), record)
    _atomic_json(authority_path(state_root, transaction_id), authority.as_dict())


def _attention(
    transaction_id: str, *, state_root: Path, reason: str, blocker: str,
    detail: str = "", now: datetime | None = None,
) -> dict[str, Any]:
    transaction = read_transaction(transaction_path(state_root, transaction_id))
    if transaction["state"] == UpdateState.ATTENTION_REQUIRED.value:
        return {"phase": transaction["state"], "transaction": transaction}
    if transaction["state"] in {
        UpdateState.INSTALLED_PENDING_ACTIVATION.value,
        UpdateState.ACTIVE_VERIFYING.value,
        UpdateState.RECOVERING.value,
    }:
        transaction = transition_transaction(
            transaction, UpdateState.ATTENTION_REQUIRED, reason=reason,
            blockers=[blocker], evidence={"detail": detail[:4000]}, now=now,
        )
        publish_transaction(state_root, transaction)
    try:
        record = _read_record(state_root, transaction_id)
        record.update({
            "phase": UpdateState.ATTENTION_REQUIRED.value,
            "transaction_state": transaction["state"],
            "recovery_blocker": blocker,
            "recovery_error": detail[:4000],
            "reboot_required": False,
        })
        _atomic_json(recovery_record_path(state_root, transaction_id), record)
    except ValueError:
        pass
    return {"phase": transaction["state"], "transaction": transaction}


def begin_bad_update_recovery(
    transaction_id: str, *, failure_code: str, failure_detail: str,
    state_root: Path, generation_root: Path,
    campaign_root: Path | None = None, executor: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Identify, authorize, and execute the exact previous-root exchange."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    transaction = read_transaction(transaction_path(state_root, transaction_id))
    if transaction["state"] not in {
        UpdateState.INSTALLED_PENDING_ACTIVATION.value,
        UpdateState.ACTIVE_VERIFYING.value,
    }:
        raise ValueError("bad-update recovery requires one failed postboot verification")
    record = _read_record(state_root, transaction_id)
    if record.get("phase") != "ACTIVATION_ARMED":
        raise ValueError("bad-update recovery requires current activation evidence")
    candidate = record.get("candidate")
    candidate_generation = record.get("candidate_generation")
    handoff_value = record.get("activation_handoff")
    activation = record.get("activation")
    recorded_consumption = record.get("handoff_consumption")
    if not all(isinstance(item, Mapping) for item in (
        candidate, candidate_generation, handoff_value, activation,
        recorded_consumption,
    )):
        raise ValueError("bad-update recovery evidence is incomplete")
    assert isinstance(candidate, Mapping) and isinstance(candidate_generation, Mapping)
    handoff = parse_activation_handoff(handoff_value)
    live, system, kernel = load_current_verified_generations(generation_root)
    expected = {
        "transaction_id": transaction_id,
        "source_revision": transaction["source_revision"],
        "current_system_generation_id": str(system.generation_id),
        "candidate_uuid": candidate.get("uuid"),
        "previous_root_uuid": candidate.get("parent_root_uuid"),
        "candidate_system_generation_id": candidate_generation.get("system_generation_id"),
        "candidate_kernel_generation_id": candidate_generation.get("kernel_generation_id"),
    }
    if any(getattr(handoff, key) != value for key, value in expected.items()):
        raise ValueError("bad-update activation binding mismatch")
    durable_consumption = read_activation_handoff_consumption(state_root, handoff)
    if dict(recorded_consumption) != durable_consumption:
        raise ValueError("bad-update activation consumption artifact mismatch")
    if dict(activation) != dict(durable_consumption["activation_evidence"]):
        raise ValueError("bad-update activation execution evidence mismatch")
    if (
        live.get("root_subvolume_uuid") != handoff.previous_root_uuid
        or live.get("filesystem_uuid", "").lower() != str(candidate.get("filesystem_uuid", "")).lower()
        or live.get("system_generation_id") != str(system.generation_id)
        or live.get("kernel_generation_id") != str(kernel.kernel_generation_id)
        or str(kernel.kernel_generation_id) != handoff.candidate_kernel_generation_id
        or candidate_generation.get("parent_system_generation_id") != str(system.generation_id)
        or not _verified_root_identity_binding(
            live, getattr(system, "root_identity", None),
            previous_root_uuid=handoff.previous_root_uuid,
            filesystem_uuid=str(candidate.get("filesystem_uuid", "")),
        )
    ):
        raise ValueError("previous known-good generation binding mismatch")

    btrfs = NativeBtrfsOps(transaction_id)
    try:
        topology = btrfs.normal_recovery_topology(
            expected_failed_uuid=handoff.candidate_uuid,
            expected_previous_uuid=handoff.previous_root_uuid,
            expected_filesystem_uuid=str(candidate.get("filesystem_uuid", "")),
        )
        identity = btrfs.recovery_root_identity(
            expected_failed_uuid=handoff.candidate_uuid,
            expected_previous_uuid=handoff.previous_root_uuid,
            expected_filesystem_uuid=str(candidate.get("filesystem_uuid", "")),
        )
        if (
            topology != "ARMED" or identity.subvolume_uuid != handoff.candidate_uuid
            or identity.filesystem_uuid.lower() != str(candidate.get("filesystem_uuid", "")).lower()
        ):
            raise RuntimeError("current failed-root recovery topology is not exact")
        target_generation_root = btrfs.previous_generation_root_for_recovery(
            expected_failed_uuid=handoff.candidate_uuid,
            expected_previous_uuid=handoff.previous_root_uuid,
            expected_filesystem_uuid=str(candidate["filesystem_uuid"]),
        )
        _validate_target_recovery_artifacts(
            target_generation_root,
            previous_root_uuid=handoff.previous_root_uuid,
            filesystem_uuid=str(candidate["filesystem_uuid"]),
            system_generation_id=str(system.generation_id),
            kernel_generation_id=str(kernel.kernel_generation_id),
        )
        provider = {
            "schema_version": 1,
            "kind": "maho-update-postboot-failure",
            "observed_at": _stamp(current),
            "current": True,
            "transaction_id": transaction_id,
            "source_revision": transaction["source_revision"],
            "filesystem_uuid": str(candidate["filesystem_uuid"]),
            "failed_candidate_uuid": handoff.candidate_uuid,
            "failed_system_generation_id": handoff.candidate_system_generation_id,
            "previous_root_uuid": handoff.previous_root_uuid,
            "previous_system_generation_id": str(system.generation_id),
            "current_kernel_generation_id": str(kernel.kernel_generation_id),
            "candidate_kernel_generation_id": handoff.candidate_kernel_generation_id,
            "root_topology": topology,
            "recovery_artifacts_intact": True,
            "failure_code": failure_code,
            "postboot_verification_succeeded": False,
        }
        decision = select_exact_previous_generation(provider, now=current)
        if decision["outcome"] != "RECOVER_EXACT_PREVIOUS":
            raise ValueError("Guardian refused bad-update recovery: " + ",".join(decision["reasons"]))
        if transaction["state"] == UpdateState.INSTALLED_PENDING_ACTIVATION.value:
            transaction = transition_transaction(
                transaction, UpdateState.ACTIVE_VERIFYING,
                reason="exact activated candidate failed postboot verification",
                evidence={
                    "failure_code": failure_code,
                    "failed_candidate_uuid": handoff.candidate_uuid,
                    "failed_system_generation_id": handoff.candidate_system_generation_id,
                }, now=current,
            )
        transaction = transition_transaction(
            transaction, UpdateState.RECOVERING,
            reason="Guardian selected exact previous known-good SystemGeneration",
            evidence={"provider": provider, "guardian_decision": decision}, now=current,
        )
        publish_transaction(state_root, transaction)
        actual_executor = dict(executor) if executor is not None else executor_identity(
            campaign_root or Path(__file__).resolve().parents[1]
        )
        authority = issue_recovery_authority(
            transaction=transaction, provider_evidence=provider,
            guardian_decision=decision, executor=actual_executor, now=current,
        )
        _atomic_json(authority_path(state_root, transaction_id), authority.as_dict(), exclusive=True)
        record.update({
            "phase": "RECOVERY_AUTHORIZED",
            "transaction_state": UpdateState.RECOVERING.value,
            "postboot_failure": {
                "code": failure_code, "detail": failure_detail[:4000],
                "failed_candidate_uuid": authority.failed_candidate_uuid,
                "failed_system_generation_id": authority.failed_system_generation_id,
            },
            "recovery_provider_evidence": provider,
            "guardian_recovery_decision": decision,
            "recovery_authority": authority.as_dict(),
            "recovery_attempts": 1,
            "reboot_required": True,
            "reboot_performed": False,
        })
        _atomic_json(recovery_record_path(state_root, transaction_id), record)
        verified = verify_recovery_authority(
            authority.as_dict(), transaction=transaction, provider_evidence=provider,
            guardian_decision=decision, executor=actual_executor,
            state_root=state_root, now=current,
        )
        target_state_root = btrfs.make_recovery_target_writable(
            expected_failed_uuid=authority.failed_candidate_uuid,
            expected_previous_uuid=authority.previous_root_uuid,
            expected_filesystem_uuid=authority.filesystem_uuid,
        )
        _publish_recovery_seed(
            target_state_root, transaction_id, transaction, record, verified,
        )
        execution = btrfs.arm_root_recovery(
            expected_failed_uuid=verified.failed_candidate_uuid,
            expected_previous_uuid=verified.previous_root_uuid,
            expected_filesystem_uuid=verified.filesystem_uuid,
            expected_boot_hashes=dict(handoff.candidate_boot_identity.get("sha256", {})),
        )
        recovered_state_root = btrfs.recovered_state_root(
            expected_failed_uuid=verified.failed_candidate_uuid,
            expected_previous_uuid=verified.previous_root_uuid,
            expected_filesystem_uuid=verified.filesystem_uuid,
        )
        receipt = consume_recovery_authority(
            recovered_state_root, verified, execution, now=current,
        )
        record.update({
            "phase": "RECOVERY_ARMED",
            "transaction_state": UpdateState.RECOVERING.value,
            "postboot_failure": {
                "code": failure_code, "detail": failure_detail[:4000],
                "failed_candidate_uuid": verified.failed_candidate_uuid,
                "failed_system_generation_id": verified.failed_system_generation_id,
            },
            "recovery_provider_evidence": provider,
            "guardian_recovery_decision": decision,
            "recovery_authority": verified.as_dict(),
            "recovery_authority_consumption": receipt,
            "recovery_execution": execution,
            "recovery_attempts": 1,
            "reboot_required": True,
            "reboot_performed": False,
        })
        _publish_recovery_seed(
            recovered_state_root, transaction_id, transaction, record, verified,
        )
        return {
            "transaction_id": transaction_id,
            "phase": UpdateState.RECOVERING.value,
            "failed_candidate_uuid": verified.failed_candidate_uuid,
            "failed_system_generation_id": verified.failed_system_generation_id,
            "selected_root_uuid": verified.previous_root_uuid,
            "selected_system_generation_id": verified.previous_system_generation_id,
            "filesystem_uuid": verified.filesystem_uuid,
            "authority_id": verified.authority_id,
            "reboot_required": True,
            "reboot_performed": False,
            "recovery_attempts": 1,
        }
    finally:
        btrfs.close()


def resume_bad_update_recovery(
    transaction_id: str, *, state_root: Path,
    campaign_root: Path | None = None, executor: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resume only an already-authorized exact recovery after interruption."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    transaction = read_transaction(transaction_path(state_root, transaction_id))
    if transaction["state"] != UpdateState.RECOVERING.value:
        raise ValueError("interrupted recovery resume requires RECOVERING transaction")
    provider, decision = _recovering_evidence(transaction)
    record = _read_record(state_root, transaction_id)
    authority_value = record.get("recovery_authority")
    if not isinstance(authority_value, Mapping):
        authority_value = _read_evidence_json(
            authority_path(state_root, transaction_id),
            "interrupted recovery authority is unavailable",
        )
    authority = parse_recovery_authority(authority_value)
    actual_executor = dict(executor) if executor is not None else executor_identity(
        campaign_root or Path(__file__).resolve().parents[1]
    )
    handoff_value = record.get("activation_handoff")
    if not isinstance(handoff_value, Mapping):
        raise ValueError("interrupted recovery activation handoff is unavailable")
    handoff = parse_activation_handoff(handoff_value)
    if (
        handoff.candidate_uuid != authority.failed_candidate_uuid
        or handoff.previous_root_uuid != authority.previous_root_uuid
        or handoff.candidate_system_generation_id != authority.failed_system_generation_id
        or handoff.candidate_kernel_generation_id != authority.kernel_generation_id
    ):
        raise ValueError("interrupted recovery handoff binding mismatch")
    expected_boot = dict(handoff.candidate_boot_identity.get("sha256", {}))
    btrfs = NativeBtrfsOps(transaction_id)
    try:
        topology = btrfs.normal_recovery_topology(
            expected_failed_uuid=authority.failed_candidate_uuid,
            expected_previous_uuid=authority.previous_root_uuid,
            expected_filesystem_uuid=authority.filesystem_uuid,
        )
        if topology not in {
            "ARMED", "TARGET_MUTABLE", "RECOVERY_EXCHANGED_PENDING_FREEZE",
            "RECOVERY_ARMED",
        }:
            raise RuntimeError("interrupted recovery topology is unsafe")
        if topology in {"ARMED", "TARGET_MUTABLE"}:
            target_generation_root = btrfs.previous_generation_root_for_recovery(
                expected_failed_uuid=authority.failed_candidate_uuid,
                expected_previous_uuid=authority.previous_root_uuid,
                expected_filesystem_uuid=authority.filesystem_uuid,
            )
        else:
            target_generation_root = btrfs.selected_generation_root_for_recovery(
                expected_failed_uuid=authority.failed_candidate_uuid,
                expected_previous_uuid=authority.previous_root_uuid,
                expected_filesystem_uuid=authority.filesystem_uuid,
            )
        _validate_target_recovery_artifacts(
            target_generation_root,
            previous_root_uuid=authority.previous_root_uuid,
            filesystem_uuid=authority.filesystem_uuid,
            system_generation_id=authority.previous_system_generation_id,
            kernel_generation_id=authority.kernel_generation_id,
        )
        original_topology = topology
        if topology in {"ARMED", "TARGET_MUTABLE"}:
            target_state_root = btrfs.previous_state_root_for_recovery(
                expected_failed_uuid=authority.failed_candidate_uuid,
                expected_previous_uuid=authority.previous_root_uuid,
                expected_filesystem_uuid=authority.filesystem_uuid,
            )
        else:
            target_state_root = btrfs.selected_state_root_for_recovery(
                expected_failed_uuid=authority.failed_candidate_uuid,
                expected_previous_uuid=authority.previous_root_uuid,
                expected_filesystem_uuid=authority.filesystem_uuid,
            )
        consumed = _evidence_exists(
            consumption_path(target_state_root, authority.authority_id),
        )
        verified = verify_recovery_authority(
            authority.as_dict(), transaction=transaction,
            provider_evidence=provider, guardian_decision=decision,
            executor=actual_executor, state_root=state_root, now=current,
            allow_started_reconciliation=original_topology != "ARMED",
            allow_consumed=consumed,
        )
        if original_topology == "ARMED":
            target_state_root = btrfs.make_recovery_target_writable(
                expected_failed_uuid=authority.failed_candidate_uuid,
                expected_previous_uuid=authority.previous_root_uuid,
                expected_filesystem_uuid=authority.filesystem_uuid,
            )
            topology = "TARGET_MUTABLE"
        identity = btrfs.recovery_root_identity(
            expected_failed_uuid=authority.failed_candidate_uuid,
            expected_previous_uuid=authority.previous_root_uuid,
            expected_filesystem_uuid=authority.filesystem_uuid,
        )
        if topology == "TARGET_MUTABLE":
            _publish_recovery_seed(
                target_state_root, transaction_id, transaction, record, verified,
            )
        if topology == "RECOVERY_ARMED":
            boot = btrfs.live_boot_hashes()
            if boot != expected_boot:
                raise RuntimeError("interrupted recovery boot identity drifted")
            execution = _reconstructed_execution(verified, boot)
        else:
            execution = btrfs.arm_root_recovery(
                expected_failed_uuid=verified.failed_candidate_uuid,
                expected_previous_uuid=verified.previous_root_uuid,
                expected_filesystem_uuid=verified.filesystem_uuid,
                expected_boot_hashes=expected_boot,
            )
        target_state_root = btrfs.recovered_state_root(
            expected_failed_uuid=verified.failed_candidate_uuid,
            expected_previous_uuid=verified.previous_root_uuid,
            expected_filesystem_uuid=verified.filesystem_uuid,
        )
        consumed = _evidence_exists(
            consumption_path(target_state_root, verified.authority_id),
        )
        if consumed:
            receipt = read_recovery_consumption(target_state_root, verified)
        else:
            receipt = consume_recovery_authority(
                target_state_root, verified, execution, now=current,
            )
        record.update({
            "phase": "RECOVERY_ARMED",
            "transaction_state": UpdateState.RECOVERING.value,
            "recovery_authority": verified.as_dict(),
            "recovery_authority_consumption": receipt,
            "recovery_execution": execution,
            "recovery_attempts": 1,
            "reboot_required": True,
            "reboot_performed": identity.subvolume_uuid == verified.previous_root_uuid,
            "reconciled_after_interruption": True,
        })
        _publish_recovery_seed(
            target_state_root, transaction_id, transaction, record, verified,
        )
        return {
            "transaction_id": transaction_id,
            "phase": UpdateState.RECOVERING.value,
            "failed_candidate_uuid": verified.failed_candidate_uuid,
            "selected_root_uuid": verified.previous_root_uuid,
            "selected_system_generation_id": verified.previous_system_generation_id,
            "filesystem_uuid": verified.filesystem_uuid,
            "authority_id": verified.authority_id,
            "recovery_attempts": 1,
            "reboot_required": identity.subvolume_uuid != verified.previous_root_uuid,
            "reboot_performed": identity.subvolume_uuid == verified.previous_root_uuid,
            "reconciled_after_interruption": True,
        }
    finally:
        btrfs.close()


def _observe_recovered_normal(
    transaction_id: str, *, state_root: Path, generation_root: Path,
    package_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    running_kernel: Callable[[], str] = lambda: os.uname().release,
    cmdline_path: Path = Path("/proc/cmdline"),
) -> tuple[dict[str, Any], dict[str, Any], BadUpdateRecoveryAuthority] | dict[str, Any]:
    """Observe the exact selected generation from current live state.

    The durable recovery record is historical input only.  Root, generation,
    kernel, package, and boot identities are read again on every invocation.
    """
    transaction = read_transaction(transaction_path(state_root, transaction_id))
    if transaction["state"] not in {
        UpdateState.RECOVERING.value, UpdateState.RECOVERED.value,
    }:
        raise ValueError("recovered generation observation requires recovery transaction")
    record = _read_record(state_root, transaction_id)
    allowed_record_phases = (
        {"RECOVERY_ARMED", "RECOVERED_VERIFIED_PENDING_TRANSACTION"}
        if transaction["state"] == UpdateState.RECOVERING.value
        else {"RECOVERED_VERIFIED_PENDING_TRANSACTION", "RECOVERED_VERIFIED"}
    )
    if record.get("phase") not in allowed_record_phases or record.get("recovery_attempts") != 1:
        raise ValueError("current recovery evidence is unavailable")
    authority_value = record.get("recovery_authority")
    receipt = record.get("recovery_authority_consumption")
    if not isinstance(authority_value, Mapping) or not isinstance(receipt, Mapping):
        raise ValueError("recovery authority evidence is incomplete")
    authority = parse_recovery_authority(authority_value)
    receipt = read_recovery_consumption(state_root, authority)
    cmdline = cmdline_path.read_text(encoding="utf-8").split()
    if "maho.recovery_snapshot=1" in cmdline:
        raise RuntimeError("recovered generation verification observed recovery boot")
    btrfs = NativeBtrfsOps(transaction_id)
    try:
        topology = btrfs.normal_recovery_topology(
            expected_failed_uuid=authority.failed_candidate_uuid,
            expected_previous_uuid=authority.previous_root_uuid,
            expected_filesystem_uuid=authority.filesystem_uuid,
        )
        identity = btrfs.recovery_root_identity(
            expected_failed_uuid=authority.failed_candidate_uuid,
            expected_previous_uuid=authority.previous_root_uuid,
            expected_filesystem_uuid=authority.filesystem_uuid,
        )
        if (
            topology == "RECOVERY_ARMED"
            and identity.subvolume_uuid == authority.failed_candidate_uuid
            and identity.filesystem_uuid.lower() == authority.filesystem_uuid.lower()
        ):
            return {
                "transaction_id": transaction_id,
                "phase": UpdateState.RECOVERING.value,
                "failed_candidate_uuid": authority.failed_candidate_uuid,
                "selected_root_uuid": authority.previous_root_uuid,
                "selected_system_generation_id": authority.previous_system_generation_id,
                "recovery_attempts": 1,
                "reboot_required": True,
                "reboot_performed": False,
                "next_action": "explicit reboot required to enter selected previous root",
            }
        if (
            topology != "RECOVERY_ARMED"
            or identity.subvolume_uuid != authority.previous_root_uuid
            or identity.filesystem_uuid.lower() != authority.filesystem_uuid.lower()
            or identity.fsroot != "/@"
        ):
            raise RuntimeError("recovered live root identity mismatch")
        observed_boot = btrfs.live_boot_hashes()
    finally:
        btrfs.close()
    execution = receipt["execution"]
    if observed_boot != dict(execution.get("boot_sha256", {})):
        raise RuntimeError("post-recovery boot identity drifted")
    live, system, kernel = _validate_target_recovery_artifacts(
        generation_root,
        previous_root_uuid=authority.previous_root_uuid,
        filesystem_uuid=authority.filesystem_uuid,
        system_generation_id=authority.previous_system_generation_id,
        kernel_generation_id=authority.kernel_generation_id,
    )
    if (
        live.get("system_generation_id") != authority.previous_system_generation_id
        or live.get("root_subvolume_uuid") != authority.previous_root_uuid
        or live.get("filesystem_uuid", "").lower() != authority.filesystem_uuid.lower()
        or str(system.generation_id) != authority.previous_system_generation_id
        or str(kernel.kernel_generation_id) != authority.kernel_generation_id
        or running_kernel() != kernel.kernel_abi
    ):
        raise RuntimeError("recovered SystemGeneration or KernelGeneration binding mismatch")
    packages = _package_versions(transaction, runner=package_runner)
    verification = {
        "authority_id": authority.authority_id,
        "failed_candidate_uuid": authority.failed_candidate_uuid,
        "failed_system_generation_id": authority.failed_system_generation_id,
        "recovered_root_uuid": authority.previous_root_uuid,
        "recovered_system_generation_id": authority.previous_system_generation_id,
        "kernel_generation_id": authority.kernel_generation_id,
        "package_versions": packages,
        "boot_sha256": observed_boot,
        "compatibility_currently_observed": True,
        "recovery_attempts": 1,
        "home_mutated": False,
    }
    return verification, record, authority


def verify_recovered_normal(
    transaction_id: str, *, state_root: Path, generation_root: Path,
    now: datetime | None = None,
    package_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    running_kernel: Callable[[], str] = lambda: os.uname().release,
    cmdline_path: Path = Path("/proc/cmdline"),
) -> dict[str, Any]:
    """Independently verify and restart-safely commit recovered state."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    transaction = read_transaction(transaction_path(state_root, transaction_id))
    if transaction["state"] != UpdateState.RECOVERING.value:
        raise ValueError("post-recovery verification requires RECOVERING transaction")
    observed = _observe_recovered_normal(
        transaction_id, state_root=state_root, generation_root=generation_root,
        package_runner=package_runner, running_kernel=running_kernel,
        cmdline_path=cmdline_path,
    )
    if isinstance(observed, dict):
        return observed
    verification, record, authority = observed

    # Publish a reconcilable receipt before the irreversible terminal
    # transaction.  A crash before or after either write can resume the same
    # exact observation without inventing another recovery attempt.
    pending_record = dict(record)
    pending_record.update({
        "phase": "RECOVERED_VERIFIED_PENDING_TRANSACTION",
        "transaction_state": UpdateState.RECOVERING.value,
        "post_recovery_verification": verification,
        "reboot_required": False,
        "reboot_performed": True,
    })
    try:
        _atomic_json(recovery_record_path(state_root, transaction_id), pending_record)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RecoveryTerminalCommitError(
            "could not persist pending recovered verification",
        ) from exc
    transaction = transition_transaction(
        transaction, UpdateState.RECOVERED,
        reason="exact previous known-good SystemGeneration passed independent verification",
        evidence=verification, now=current,
    )
    try:
        publish_transaction(state_root, transaction)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RecoveryTerminalCommitError(
            "could not publish terminal recovered transaction",
        ) from exc
    pending_record.update({
        "phase": "RECOVERED_VERIFIED",
        "transaction_state": UpdateState.RECOVERED.value,
        "reboot_required": False,
        "reboot_performed": True,
    })
    try:
        _atomic_json(recovery_record_path(state_root, transaction_id), pending_record)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RecoveryTerminalCommitError(
            "could not persist final recovered verification",
        ) from exc
    return {
        "transaction_id": transaction_id,
        "phase": UpdateState.RECOVERED.value,
        "failed_candidate_uuid": authority.failed_candidate_uuid,
        "failed_system_generation_id": authority.failed_system_generation_id,
        "root_uuid": authority.previous_root_uuid,
        "system_generation_id": authority.previous_system_generation_id,
        "kernel_generation_id": authority.kernel_generation_id,
        "package_versions": verification["package_versions"],
        "recovery_attempts": 1,
        "reboot_required": False,
        "reboot_performed": True,
    }


def reverify_recovered_normal(
    transaction_id: str, *, state_root: Path, generation_root: Path,
    package_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    running_kernel: Callable[[], str] = lambda: os.uname().release,
    cmdline_path: Path = Path("/proc/cmdline"),
) -> dict[str, Any]:
    """Re-observe a terminal recovery and reconcile its final record."""
    transaction = read_transaction(transaction_path(state_root, transaction_id))
    if transaction["state"] != UpdateState.RECOVERED.value:
        raise ValueError("terminal recovery revalidation requires RECOVERED transaction")
    observed = _observe_recovered_normal(
        transaction_id, state_root=state_root, generation_root=generation_root,
        package_runner=package_runner, running_kernel=running_kernel,
        cmdline_path=cmdline_path,
    )
    if isinstance(observed, dict):
        raise RuntimeError("terminal recovered root is not currently active")
    verification, record, authority = observed
    terminal = transaction["history"][-1].get("evidence")
    recorded = record.get("post_recovery_verification")
    if not isinstance(terminal, Mapping) or dict(terminal) != verification:
        raise ValueError("terminal transaction recovery evidence is not current")
    if not isinstance(recorded, Mapping) or dict(recorded) != verification:
        raise ValueError("terminal recovery record evidence is not current")
    if record.get("phase") == "RECOVERED_VERIFIED_PENDING_TRANSACTION":
        reconciled = dict(record)
        reconciled.update({
            "phase": "RECOVERED_VERIFIED",
            "transaction_state": UpdateState.RECOVERED.value,
            "reboot_required": False,
            "reboot_performed": True,
        })
        _atomic_json(recovery_record_path(state_root, transaction_id), reconciled)
    return {
        "transaction_id": transaction_id,
        "phase": UpdateState.RECOVERED.value,
        "failed_candidate_uuid": authority.failed_candidate_uuid,
        "failed_system_generation_id": authority.failed_system_generation_id,
        "root_uuid": authority.previous_root_uuid,
        "system_generation_id": authority.previous_system_generation_id,
        "kernel_generation_id": authority.kernel_generation_id,
        "package_versions": verification["package_versions"],
        "recovery_attempts": 1,
        "reboot_required": False,
        "reboot_performed": True,
    }


def attention_after_recovery_failure(
    transaction_id: str, *, state_root: Path, detail: str,
    blocker: str = "bad_update_recovery_failed", now: datetime | None = None,
) -> dict[str, Any]:
    return _attention(
        transaction_id, state_root=state_root,
        reason="bad-update recovery could not be proven safe",
        blocker=blocker, detail=detail, now=now,
    )
