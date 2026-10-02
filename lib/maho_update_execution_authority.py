#!/usr/bin/env python3
"""Transaction-specific S2.2 execution and activation handoff authority.

This module grants no mutation capability by itself.  It produces and verifies
short-lived, content-addressed envelopes consumed by the existing root-owned
Maho Update executors.  Consumption is one-shot and durable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any, Mapping, Sequence

from maho_trust_identity import ArtifactID, canonical_bytes
from maho_update_state import UpdateState, validate_transaction

SCHEMA_VERSION = 1
EXECUTION_TTL = timedelta(minutes=5)
ACTIVATION_TTL = timedelta(hours=24)
MAX_CLOCK_SKEW = timedelta(seconds=5)
_TXID = re.compile(r"upd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")
_SHA40 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_UUID = re.compile(r"[0-9a-fA-F-]{36}")
_PKG = re.compile(r"pkg-[0-9a-f]{64}")
_GEN = re.compile(r"gen-[0-9a-f]{64}")
_KGEN = re.compile(r"kgen-[0-9a-f]{64}")
_ALLOWED_MODES = {"normal-candidate", "native-m4b"}


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_stamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return canonical_bytes(dict(value))


def _atomic_json(path: Path, payload: Mapping[str, Any], *, exclusive: bool = False) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    encoded = _canonical(payload) + b"\n"
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            raise
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _normalized_packages(
    transaction: Mapping[str, Any], manifest: Mapping[str, Any],
) -> tuple[dict[str, str], ...]:
    tx = validate_transaction(transaction)
    payloads = manifest.get("payloads")
    if not isinstance(payloads, list):
        raise ValueError("staging manifest payloads are unavailable")
    by_name: dict[str, Mapping[str, Any]] = {}
    for raw in payloads:
        if not isinstance(raw, Mapping):
            raise ValueError("staging manifest payload is invalid")
        name = raw.get("name")
        digest = raw.get("sha256")
        if not isinstance(name, str) or name in by_name or not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise ValueError("staging manifest payload identity is invalid")
        by_name[name] = raw
    result: list[dict[str, str]] = []
    for package in tx["package_generation"]["packages"]:
        name = package["name"]
        payload = by_name.get(name)
        if payload is None:
            raise ValueError(f"staged payload missing:{name}")
        result.append({
            "name": name,
            "installed_version": package["installed_version"],
            "candidate_version": package["candidate_version"],
            "repository": package["repository"],
            "sha256": str(payload["sha256"]),
        })
    if set(by_name) != {item["name"] for item in result}:
        raise ValueError("staging payload set exceeds exact package generation")
    return tuple(sorted(result, key=lambda item: item["name"]))


def package_set_sha256(packages: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(_canonical({"packages": [dict(item) for item in packages]})).hexdigest()


def executor_identity(campaign_root: Path, module_names: Sequence[str]) -> dict[str, Any]:
    root = campaign_root.resolve(strict=True)
    source = (root / "SOURCE_REVISION").read_text(encoding="utf-8").strip()
    if _SHA40.fullmatch(source) is None or root.name != source:
        raise ValueError("installed campaign identity is invalid")
    modules: dict[str, str] = {}
    for name in sorted(set(module_names)):
        if "/" in name or not name.endswith(".py"):
            raise ValueError("executor module name is invalid")
        path = root / "lib" / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"executor module unavailable:{name}")
        modules[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    interpreter = Path("/proc/self/exe").resolve(strict=True)
    return {
        "interpreter": str(interpreter),
        "campaign_root": str(root),
        "source_revision": source,
        "modules": modules,
    }


@dataclass(frozen=True)
class ExecutionAuthority:
    authority_id: str
    transaction_id: str
    source_revision: str
    package_generation_id: str
    source_provenance_id: str
    current_system_generation_id: str
    current_kernel_generation_id: str
    execution_mode: str
    packages: tuple[Mapping[str, str], ...]
    effects: tuple[str, ...]
    activation_requirements: tuple[str, ...]
    candidate_target: Mapping[str, str]
    recovery_evidence: Mapping[str, Any]
    maintenance_evidence: Mapping[str, Any]
    executor: Mapping[str, Any]
    issued_at: str
    expires_at: str
    nonce: str

    def identity_material(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "maho-update-execution-authority",
            "authority_scope": "execute-exact-prepared-candidate-once",
            "transaction_id": self.transaction_id,
            "source_revision": self.source_revision,
            "package_generation_id": self.package_generation_id,
            "source_provenance_id": self.source_provenance_id,
            "current_system_generation_id": self.current_system_generation_id,
            "current_kernel_generation_id": self.current_kernel_generation_id,
            "execution_mode": self.execution_mode,
            "packages": [dict(item) for item in self.packages],
            "package_set_sha256": package_set_sha256(self.packages),
            "effects": list(self.effects),
            "activation_requirements": list(self.activation_requirements),
            "candidate_target": dict(self.candidate_target),
            "recovery_evidence": dict(self.recovery_evidence),
            "maintenance_evidence": dict(self.maintenance_evidence),
            "executor": dict(self.executor),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
        }

    def as_dict(self) -> dict[str, Any]:
        return self.identity_material() | {"authority_id": self.authority_id}


def issue_execution_authority(
    transaction: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    current_system_generation_id: str,
    current_kernel_generation_id: str,
    execution_mode: str,
    effects: Sequence[str],
    activation_requirements: Sequence[str],
    candidate_target: Mapping[str, str],
    recovery_evidence: Mapping[str, Any],
    maintenance_evidence: Mapping[str, Any],
    executor: Mapping[str, Any],
    now: datetime | None = None,
) -> ExecutionAuthority:
    tx = validate_transaction(transaction)
    if tx["state"] != UpdateState.MAINTENANCE_READY.value:
        raise ValueError("execution authority requires MAINTENANCE_READY transaction")
    if _GEN.fullmatch(current_system_generation_id) is None or _KGEN.fullmatch(current_kernel_generation_id) is None:
        raise ValueError("current verified generation identity is unavailable")
    if execution_mode not in _ALLOWED_MODES:
        raise ValueError("execution mode is invalid")
    packages = _normalized_packages(tx, manifest)
    target = dict(candidate_target)
    required_target = {"name", "uuid", "filesystem_uuid", "parent_root_uuid"}
    if set(target) != required_target:
        raise ValueError("candidate target identity is incomplete")
    if not target["name"].startswith("@maho-update-candidate-"):
        raise ValueError("candidate target name is invalid")
    if (
        _UUID.fullmatch(target["uuid"]) is None
        or _UUID.fullmatch(target["parent_root_uuid"]) is None
        or not target["filesystem_uuid"]
    ):
        raise ValueError("candidate root identity is invalid")
    if not effects or any(not isinstance(item, str) or not item for item in effects):
        raise ValueError("execution effects are invalid")
    if any(not isinstance(item, str) or not item for item in activation_requirements):
        raise ValueError("activation requirements are invalid")
    recovery = dict(recovery_evidence)
    if recovery.get("ready") is not True:
        raise ValueError("execution authority requires exact recovery readiness")
    maintenance = dict(maintenance_evidence)
    if maintenance.get("safe") is not True or not maintenance.get("snapshot_id") or not maintenance.get("captured_at"):
        raise ValueError("execution authority requires exact fresh maintenance evidence")
    executor_value = dict(executor)
    if executor_value.get("source_revision") != tx["source_revision"]:
        raise ValueError("executor source revision does not match transaction")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    issued = _stamp(current)
    expires = _stamp(current + EXECUTION_TTL)
    provisional = ExecutionAuthority(
        authority_id="art-" + "0" * 64,
        transaction_id=tx["transaction_id"],
        source_revision=tx["source_revision"],
        package_generation_id=tx["package_generation"]["id"],
        source_provenance_id=tx["source_provenance"]["id"],
        current_system_generation_id=current_system_generation_id,
        current_kernel_generation_id=current_kernel_generation_id,
        execution_mode=execution_mode,
        packages=packages,
        effects=tuple(effects),
        activation_requirements=tuple(activation_requirements),
        candidate_target=target,
        recovery_evidence=recovery,
        maintenance_evidence=maintenance,
        executor=executor_value,
        issued_at=issued,
        expires_at=expires,
        nonce=secrets.token_hex(16),
    )
    material = provisional.identity_material()
    return ExecutionAuthority(
        authority_id=str(ArtifactID.from_content(_canonical(material))),
        **{
            name: getattr(provisional, name)
            for name in provisional.__dataclass_fields__
            if name != "authority_id"
        },
    )


def parse_execution_authority(value: Mapping[str, Any]) -> ExecutionAuthority:
    required = {
        "schema_version", "kind", "authority_scope", "transaction_id",
        "source_revision", "package_generation_id", "source_provenance_id",
        "current_system_generation_id", "current_kernel_generation_id",
        "execution_mode", "packages", "package_set_sha256", "effects",
        "activation_requirements", "candidate_target", "recovery_evidence",
        "maintenance_evidence", "executor", "issued_at", "expires_at", "nonce", "authority_id",
    }
    if set(value) != required:
        raise ValueError("execution authority fields are invalid")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != "maho-update-execution-authority"
        or value.get("authority_scope") != "execute-exact-prepared-candidate-once"
    ):
        raise ValueError("execution authority schema is invalid")
    packages = value.get("packages")
    effects = value.get("effects")
    activation = value.get("activation_requirements")
    if not isinstance(packages, list) or not isinstance(effects, list) or not isinstance(activation, list):
        raise ValueError("execution authority collections are invalid")
    authority = ExecutionAuthority(
        authority_id=str(value["authority_id"]),
        transaction_id=str(value["transaction_id"]),
        source_revision=str(value["source_revision"]),
        package_generation_id=str(value["package_generation_id"]),
        source_provenance_id=str(value["source_provenance_id"]),
        current_system_generation_id=str(value["current_system_generation_id"]),
        current_kernel_generation_id=str(value["current_kernel_generation_id"]),
        execution_mode=str(value["execution_mode"]),
        packages=tuple(dict(item) for item in packages if isinstance(item, Mapping)),
        effects=tuple(str(item) for item in effects),
        activation_requirements=tuple(str(item) for item in activation),
        candidate_target=dict(value["candidate_target"]) if isinstance(value["candidate_target"], Mapping) else {},
        recovery_evidence=dict(value["recovery_evidence"]) if isinstance(value["recovery_evidence"], Mapping) else {},
        maintenance_evidence=dict(value["maintenance_evidence"]) if isinstance(value["maintenance_evidence"], Mapping) else {},
        executor=dict(value["executor"]) if isinstance(value["executor"], Mapping) else {},
        issued_at=str(value["issued_at"]),
        expires_at=str(value["expires_at"]),
        nonce=str(value["nonce"]),
    )
    if len(authority.packages) != len(packages):
        raise ValueError("execution authority package set is invalid")
    if value.get("package_set_sha256") != package_set_sha256(authority.packages):
        raise ValueError("execution authority package set digest mismatch")
    if value != authority.as_dict():
        raise ValueError("execution authority closed schema mismatch")
    expected = str(ArtifactID.from_content(_canonical(authority.identity_material())))
    if authority.authority_id != expected:
        raise ValueError("execution authority identity mismatch")
    return authority


def verify_execution_authority(
    value: Mapping[str, Any],
    transaction: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    current_system_generation_id: str,
    current_kernel_generation_id: str,
    execution_mode: str,
    effects: Sequence[str],
    activation_requirements: Sequence[str],
    candidate_target: Mapping[str, str],
    recovery_evidence: Mapping[str, Any],
    maintenance_evidence: Mapping[str, Any],
    executor: Mapping[str, Any],
    now: datetime | None = None,
) -> ExecutionAuthority:
    authority = parse_execution_authority(value)
    tx = validate_transaction(transaction)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    issued = _parse_stamp(authority.issued_at, "execution authority issue time")
    expires = _parse_stamp(authority.expires_at, "execution authority expiry")
    if current < issued - MAX_CLOCK_SKEW or current > expires or expires - issued != EXECUTION_TTL:
        raise ValueError("execution authority is expired or temporally invalid")
    expected_packages = _normalized_packages(tx, manifest)
    if tx["state"] != UpdateState.MAINTENANCE_READY.value:
        raise ValueError("execution authority requires current MAINTENANCE_READY state")
    if (
        authority.transaction_id != tx["transaction_id"]
        or authority.source_revision != tx["source_revision"]
        or authority.package_generation_id != tx["package_generation"]["id"]
        or authority.source_provenance_id != tx["source_provenance"]["id"]
        or authority.current_system_generation_id != current_system_generation_id
        or authority.current_kernel_generation_id != current_kernel_generation_id
        or authority.execution_mode != execution_mode
        or authority.packages != expected_packages
        or authority.effects != tuple(effects)
        or authority.activation_requirements != tuple(activation_requirements)
        or dict(authority.candidate_target) != dict(candidate_target)
        or dict(authority.recovery_evidence) != dict(recovery_evidence)
        or dict(authority.maintenance_evidence) != dict(maintenance_evidence)
        or dict(authority.executor) != dict(executor)
    ):
        raise ValueError("execution authority exact binding mismatch")
    return authority


def authority_path(root: Path, transaction_id: str) -> Path:
    if _TXID.fullmatch(transaction_id) is None:
        raise ValueError("execution authority transaction identity is invalid")
    return root / "execution-authorities" / f"{transaction_id}.json"


def consumption_path(root: Path, authority_id: str) -> Path:
    if not isinstance(authority_id, str) or not authority_id.startswith("art-"):
        raise ValueError("execution authority identity is invalid")
    return root / "execution-authorities" / "consumed" / f"{authority_id}.json"


def publish_execution_authority(root: Path, authority: ExecutionAuthority) -> Path:
    path = authority_path(root, authority.transaction_id)
    _atomic_json(path, authority.as_dict())
    return path


def consume_execution_authority(
    root: Path,
    authority: ExecutionAuthority,
    *,
    candidate_uuid: str,
    candidate_root_identity: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    if _UUID.fullmatch(candidate_uuid) is None or not candidate_root_identity:
        raise ValueError("execution authority candidate consumption identity is invalid")
    path = consumption_path(root, authority.authority_id)
    receipt = {
        "schema_version": 1,
        "kind": "maho-update-execution-authority-consumption",
        "authority_id": authority.authority_id,
        "transaction_id": authority.transaction_id,
        "package_generation_id": authority.package_generation_id,
        "candidate_uuid": candidate_uuid,
        "candidate_root_identity": candidate_root_identity,
        "consumed_at": _stamp((now or datetime.now(timezone.utc)).astimezone(timezone.utc)),
    }
    try:
        _atomic_json(path, receipt, exclusive=True)
    except FileExistsError as exc:
        raise ValueError("execution authority already consumed") from exc
    return receipt


def execution_authority_consumed(root: Path, authority_id: str) -> bool:
    return consumption_path(root, authority_id).is_file()


@dataclass(frozen=True)
class ActivationHandoff:
    handoff_id: str
    transaction_id: str
    source_revision: str
    package_generation_id: str
    current_system_generation_id: str
    candidate_system_generation_id: str
    candidate_kernel_generation_id: str
    candidate_uuid: str
    previous_root_uuid: str
    reboot_required: bool
    reboot_reason: str
    activation_authority: Mapping[str, Any]
    recovery_evidence: Mapping[str, Any]
    candidate_boot_identity: Mapping[str, Any]
    issued_at: str
    expires_at: str

    def identity_material(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "maho-update-activation-handoff",
            "authority_scope": "activate-exact-installed-candidate-once",
            "transaction_id": self.transaction_id,
            "source_revision": self.source_revision,
            "package_generation_id": self.package_generation_id,
            "current_system_generation_id": self.current_system_generation_id,
            "candidate_system_generation_id": self.candidate_system_generation_id,
            "candidate_kernel_generation_id": self.candidate_kernel_generation_id,
            "candidate_uuid": self.candidate_uuid,
            "previous_root_uuid": self.previous_root_uuid,
            "reboot_required": self.reboot_required,
            "reboot_reason": self.reboot_reason,
            "activation_authority": dict(self.activation_authority),
            "recovery_evidence": dict(self.recovery_evidence),
            "candidate_boot_identity": dict(self.candidate_boot_identity),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def as_dict(self) -> dict[str, Any]:
        return self.identity_material() | {"handoff_id": self.handoff_id}


def issue_activation_handoff(
    transaction: Mapping[str, Any],
    *,
    current_system_generation_id: str,
    candidate_system_generation_id: str,
    candidate_kernel_generation_id: str,
    candidate_uuid: str,
    previous_root_uuid: str,
    activation_authority: Mapping[str, Any],
    recovery_evidence: Mapping[str, Any],
    candidate_boot_identity: Mapping[str, Any],
    reboot_required: bool,
    reboot_reason: str,
    now: datetime | None = None,
) -> ActivationHandoff:
    tx = validate_transaction(transaction)
    if tx["state"] != UpdateState.INSTALLED_PENDING_ACTIVATION.value:
        raise ValueError("activation handoff requires installed pending activation state")
    if (
        _GEN.fullmatch(current_system_generation_id) is None
        or _GEN.fullmatch(candidate_system_generation_id) is None
        or _KGEN.fullmatch(candidate_kernel_generation_id) is None
        or _UUID.fullmatch(candidate_uuid) is None
        or _UUID.fullmatch(previous_root_uuid) is None
    ):
        raise ValueError("activation handoff generation or root identity is invalid")
    if not isinstance(activation_authority, Mapping) or not activation_authority:
        raise ValueError("activation handoff requires exact activation authority")
    recovery = dict(recovery_evidence)
    if recovery.get("ready") is not True:
        raise ValueError("activation handoff requires exact recovery readiness")
    if not reboot_reason:
        raise ValueError("activation handoff reason is required")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    provisional = ActivationHandoff(
        handoff_id="art-" + "0" * 64,
        transaction_id=tx["transaction_id"],
        source_revision=tx["source_revision"],
        package_generation_id=tx["package_generation"]["id"],
        current_system_generation_id=current_system_generation_id,
        candidate_system_generation_id=candidate_system_generation_id,
        candidate_kernel_generation_id=candidate_kernel_generation_id,
        candidate_uuid=candidate_uuid,
        previous_root_uuid=previous_root_uuid,
        reboot_required=bool(reboot_required),
        reboot_reason=reboot_reason,
        activation_authority=dict(activation_authority),
        recovery_evidence=recovery,
        candidate_boot_identity=dict(candidate_boot_identity),
        issued_at=_stamp(current),
        expires_at=_stamp(current + ACTIVATION_TTL),
    )
    return ActivationHandoff(
        handoff_id=str(ArtifactID.from_content(_canonical(provisional.identity_material()))),
        **{
            name: getattr(provisional, name)
            for name in provisional.__dataclass_fields__
            if name != "handoff_id"
        },
    )


def parse_activation_handoff(value: Mapping[str, Any]) -> ActivationHandoff:
    required = {
        "schema_version", "kind", "authority_scope", "transaction_id",
        "source_revision", "package_generation_id", "current_system_generation_id",
        "candidate_system_generation_id", "candidate_kernel_generation_id",
        "candidate_uuid", "previous_root_uuid", "reboot_required", "reboot_reason",
        "activation_authority", "recovery_evidence", "candidate_boot_identity",
        "issued_at", "expires_at", "handoff_id",
    }
    if set(value) != required:
        raise ValueError("activation handoff fields are invalid")
    if (
        value.get("schema_version") != 1
        or value.get("kind") != "maho-update-activation-handoff"
        or value.get("authority_scope") != "activate-exact-installed-candidate-once"
    ):
        raise ValueError("activation handoff schema is invalid")
    handoff = ActivationHandoff(
        handoff_id=str(value["handoff_id"]),
        transaction_id=str(value["transaction_id"]),
        source_revision=str(value["source_revision"]),
        package_generation_id=str(value["package_generation_id"]),
        current_system_generation_id=str(value["current_system_generation_id"]),
        candidate_system_generation_id=str(value["candidate_system_generation_id"]),
        candidate_kernel_generation_id=str(value["candidate_kernel_generation_id"]),
        candidate_uuid=str(value["candidate_uuid"]),
        previous_root_uuid=str(value["previous_root_uuid"]),
        reboot_required=value["reboot_required"] is True,
        reboot_reason=str(value["reboot_reason"]),
        activation_authority=dict(value["activation_authority"]) if isinstance(value["activation_authority"], Mapping) else {},
        recovery_evidence=dict(value["recovery_evidence"]) if isinstance(value["recovery_evidence"], Mapping) else {},
        candidate_boot_identity=dict(value["candidate_boot_identity"]) if isinstance(value["candidate_boot_identity"], Mapping) else {},
        issued_at=str(value["issued_at"]),
        expires_at=str(value["expires_at"]),
    )
    if value != handoff.as_dict():
        raise ValueError("activation handoff closed schema mismatch")
    expected = str(ArtifactID.from_content(_canonical(handoff.identity_material())))
    if handoff.handoff_id != expected:
        raise ValueError("activation handoff identity mismatch")
    return handoff


def verify_activation_handoff(
    value: Mapping[str, Any],
    transaction: Mapping[str, Any],
    *,
    current_system_generation_id: str,
    now: datetime | None = None,
) -> ActivationHandoff:
    handoff = parse_activation_handoff(value)
    tx = validate_transaction(transaction)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    issued = _parse_stamp(handoff.issued_at, "activation handoff issue time")
    expires = _parse_stamp(handoff.expires_at, "activation handoff expiry")
    if current < issued - MAX_CLOCK_SKEW or current > expires or expires - issued != ACTIVATION_TTL:
        raise ValueError("activation handoff is expired or temporally invalid")
    if (
        tx["state"] != UpdateState.INSTALLED_PENDING_ACTIVATION.value
        or handoff.transaction_id != tx["transaction_id"]
        or handoff.source_revision != tx["source_revision"]
        or handoff.package_generation_id != tx["package_generation"]["id"]
        or handoff.current_system_generation_id != current_system_generation_id
    ):
        raise ValueError("activation handoff exact binding mismatch")
    return handoff


def verify_activation_handoff_reconciliation(
    value: Mapping[str, Any],
    transaction: Mapping[str, Any],
    *,
    current_system_generation_id: str,
) -> ActivationHandoff:
    """Verify exact binding for topology-proven, already-started activation.

    Expiry prevents starting a new exchange. It does not make an exact exchange
    that already happened unsafe to finish or its durable receipt untrustworthy.
    """
    handoff = parse_activation_handoff(value)
    tx = validate_transaction(transaction)
    issued = _parse_stamp(handoff.issued_at, "activation handoff issue time")
    expires = _parse_stamp(handoff.expires_at, "activation handoff expiry")
    if expires - issued != ACTIVATION_TTL:
        raise ValueError("activation handoff temporal bounds are invalid")
    if (
        tx["state"] != UpdateState.INSTALLED_PENDING_ACTIVATION.value
        or handoff.transaction_id != tx["transaction_id"]
        or handoff.source_revision != tx["source_revision"]
        or handoff.package_generation_id != tx["package_generation"]["id"]
        or handoff.current_system_generation_id != current_system_generation_id
    ):
        raise ValueError("activation handoff exact binding mismatch")
    return handoff


def handoff_path(root: Path, transaction_id: str) -> Path:
    if _TXID.fullmatch(transaction_id) is None:
        raise ValueError("activation handoff transaction identity is invalid")
    return root / "activation-handoffs" / f"{transaction_id}.json"


def handoff_consumption_path(root: Path, handoff_id: str) -> Path:
    if not isinstance(handoff_id, str) or not handoff_id.startswith("art-"):
        raise ValueError("activation handoff identity is invalid")
    return root / "activation-handoffs" / "consumed" / f"{handoff_id}.json"


def publish_activation_handoff(root: Path, handoff: ActivationHandoff) -> Path:
    path = handoff_path(root, handoff.transaction_id)
    _atomic_json(path, handoff.as_dict())
    return path


def consume_activation_handoff(
    root: Path,
    handoff: ActivationHandoff,
    *,
    activation_evidence: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    path = handoff_consumption_path(root, handoff.handoff_id)
    receipt = {
        "schema_version": 1,
        "kind": "maho-update-activation-handoff-consumption",
        "handoff_id": handoff.handoff_id,
        "transaction_id": handoff.transaction_id,
        "candidate_system_generation_id": handoff.candidate_system_generation_id,
        "candidate_uuid": handoff.candidate_uuid,
        "activation_evidence": dict(activation_evidence),
        "consumed_at": _stamp((now or datetime.now(timezone.utc)).astimezone(timezone.utc)),
    }
    try:
        _atomic_json(path, receipt, exclusive=True)
    except FileExistsError as exc:
        raise ValueError("activation handoff already consumed") from exc
    return receipt


def read_activation_handoff_consumption(
    root: Path,
    handoff: ActivationHandoff,
) -> dict[str, Any]:
    """Read and prove one completed exact activation handoff consumption.

    The receipt is meaningful only after exact root topology proves the exchange;
    callers must establish that topology independently before trusting it.
    """
    path = handoff_consumption_path(root, handoff.handoff_id)
    if path.is_symlink():
        raise ValueError("activation handoff consumption path is unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("activation handoff consumption is unavailable") from exc
    required = {
        "schema_version", "kind", "handoff_id", "transaction_id",
        "candidate_system_generation_id", "candidate_uuid",
        "activation_evidence", "consumed_at",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("activation handoff consumption schema is invalid")
    evidence = value.get("activation_evidence")
    expected_boot = dict(handoff.candidate_boot_identity.get("sha256", {}))
    if (
        value.get("schema_version") != 1
        or value.get("kind") != "maho-update-activation-handoff-consumption"
        or value.get("handoff_id") != handoff.handoff_id
        or value.get("transaction_id") != handoff.transaction_id
        or value.get("candidate_system_generation_id") != handoff.candidate_system_generation_id
        or value.get("candidate_uuid") != handoff.candidate_uuid
        or not isinstance(evidence, Mapping)
        or not isinstance(evidence.get("boot_sha256"), Mapping)
        or evidence.get("candidate_uuid") != handoff.candidate_uuid
        or evidence.get("previous_root_uuid") != handoff.previous_root_uuid
        or dict(evidence.get("boot_sha256", {})) != expected_boot
        or evidence.get("boot_unchanged") is not True
        or evidence.get("package_manager_invoked") is not False
        or evidence.get("reboot_performed") is not False
        or evidence.get("firmware_mutated") is not False
    ):
        raise ValueError("activation handoff consumption binding is invalid")
    consumed = _parse_stamp(value.get("consumed_at"), "activation handoff consumption time")
    issued = _parse_stamp(handoff.issued_at, "activation handoff issue time")
    expires = _parse_stamp(handoff.expires_at, "activation handoff expiry")
    if expires - issued != ACTIVATION_TTL:
        raise ValueError("activation handoff consumption temporal bounds are invalid")
    # Expiry authorizes starting the exchange. Once exact root topology proves
    # the exchange already happened, crash reconciliation may persist the
    # durable completion receipt after that authorization window has closed.
    if consumed < issued - MAX_CLOCK_SKEW:
        raise ValueError("activation handoff consumption time is invalid")
    return dict(value)
