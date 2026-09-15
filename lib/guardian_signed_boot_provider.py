#!/usr/bin/env python3
"""Read-only Guardian provider for the landed MahoOS Signed Boot authority.

Guardian does not reimplement Signed Boot policy. This adapter only:
- loads one durable postboot proof receipt,
- parses the exact landed BootGeneration/BootAuthority/BootEnvironmentIdentity models,
- reconstructs the landed PostBootObservation,
- calls the landed verify_postboot() verifier,
- exposes provider health separately from signed-boot trust.

A healthy provider can legitimately report UNKNOWN or UNTRUSTED trust.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping

from guardian_evidence import (
    EvidenceConfidence,
    EvidenceEnvelope,
    FreshnessPolicy,
    ProviderHealth,
    parse_timestamp,
    utc_stamp,
)
from maho_boot_authority import BootAuthority, BootContractError, BootGeneration
from maho_secure_boot import (
    BootEnvironmentIdentity,
    PostBootObservation,
    SecureBootError,
    verify_postboot,
)


PROVIDER_ID = "boot.authority"
DOMAIN = "boot"
SCHEMA_VERSION = 1
PROOF_FILENAME = "current-postboot.json"
DEFAULT_MAX_AGE_SECONDS = 300.0
SOURCE = "maho-signed-boot-postboot-proof"
AUTHORITY_BOUNDARY = "landed-signed-boot-verifier-read-only"


class SignedBootTrust(str, Enum):
    VERIFIED = "VERIFIED"
    UNKNOWN = "UNKNOWN"
    UNTRUSTED = "UNTRUSTED"


@dataclass(frozen=True)
class SignedBootProviderResult:
    evidence: EvidenceEnvelope
    trust: SignedBootTrust
    reason: str

    def as_dict(self, *, now: datetime | None = None) -> dict[str, Any]:
        return {
            "provider_health": self.evidence.health.value,
            "trust": self.trust.value,
            "reason": self.reason,
            "evidence": self.evidence.as_dict(now=now),
        }


_RECEIPT_FIELDS = {
    "schema_version",
    "kind",
    "observed_at",
    "boot_id",
    "boot_generation",
    "boot_authority",
    "boot_environment",
    "postboot_observation",
    "verification",
}
_OBSERVATION_FIELDS = {
    "boot_generation_id",
    "boot_authority_id",
    "source_revision",
    "package_generation_id",
    "candidate_root_identity",
    "release_sequence",
    "security_epoch",
    "loader_sha256",
    "loader_signer_fingerprint",
    "embedded_config_checksum",
    "config_bytes_b64",
    "artifact_bytes_b64",
    "recovery_authority_identity",
    "guardian_proof_successful",
    "revoked_generation_ids",
    "authenticated_cmdline_b64",
    "running_kernel_identity",
    "limine_version",
    "boot_mode",
}
_VERIFICATION_FIELDS = {
    "expected_pk",
    "expected_kek",
    "expected_db",
    "expected_dbx",
    "minimum_release_sequence",
    "current_security_epoch",
    "expected_esp_partuuid",
    "expected_esp_filesystem_identity",
    "expected_uefi_device_path",
    "expected_boot_entry_name",
    "expected_boot_mode",
    "revoked_authority_ids",
}


def _closed(value: Any, expected: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError(f"{name}_fields_invalid")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name}_invalid")
    return value


def _optional_string(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _string(value, name)


def _optional_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name}_invalid")
    return value


def _string_tuple(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{name}_invalid")
    return tuple(value)


def _decode_optional(value: Any, name: str) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name}_invalid")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise ValueError(f"{name}_invalid") from exc


def _observation(value: Any) -> PostBootObservation:
    raw = _closed(value, _OBSERVATION_FIELDS, "postboot_observation")
    artifacts_raw = raw["artifact_bytes_b64"]
    if not isinstance(artifacts_raw, Mapping):
        raise ValueError("artifact_bytes_invalid")
    artifacts: dict[str, bytes] = {}
    for key, encoded in artifacts_raw.items():
        if not isinstance(key, str) or not key:
            raise ValueError("artifact_identity_invalid")
        decoded = _decode_optional(encoded, f"artifact:{key}")
        if decoded is None:
            raise ValueError("artifact_bytes_invalid")
        artifacts[key] = decoded
    guardian_proof = raw["guardian_proof_successful"]
    if type(guardian_proof) is not bool:
        raise ValueError("guardian_proof_successful_invalid")
    return PostBootObservation(
        boot_generation_id=_optional_string(raw["boot_generation_id"], "boot_generation_id"),
        boot_authority_id=_optional_string(raw["boot_authority_id"], "boot_authority_id"),
        source_revision=_optional_string(raw["source_revision"], "source_revision"),
        package_generation_id=_optional_string(raw["package_generation_id"], "package_generation_id"),
        candidate_root_identity=_optional_string(raw["candidate_root_identity"], "candidate_root_identity"),
        release_sequence=_optional_int(raw["release_sequence"], "release_sequence"),
        security_epoch=_optional_int(raw["security_epoch"], "security_epoch"),
        loader_sha256=_optional_string(raw["loader_sha256"], "loader_sha256"),
        loader_signer_fingerprint=_optional_string(raw["loader_signer_fingerprint"], "loader_signer_fingerprint"),
        embedded_config_checksum=_optional_string(raw["embedded_config_checksum"], "embedded_config_checksum"),
        config_bytes=_decode_optional(raw["config_bytes_b64"], "config_bytes_b64"),
        artifact_bytes=artifacts,
        recovery_authority_identity=_optional_string(raw["recovery_authority_identity"], "recovery_authority_identity"),
        guardian_proof_successful=guardian_proof,
        revoked_generation_ids=_string_tuple(raw["revoked_generation_ids"], "revoked_generation_ids"),
        authenticated_cmdline=_decode_optional(raw["authenticated_cmdline_b64"], "authenticated_cmdline_b64"),
        running_kernel_identity=_optional_string(raw["running_kernel_identity"], "running_kernel_identity"),
        limine_version=_optional_string(raw["limine_version"], "limine_version"),
        boot_mode=_optional_string(raw["boot_mode"], "boot_mode"),
    )


def _verification(value: Any) -> dict[str, Any]:
    raw = _closed(value, _VERIFICATION_FIELDS, "verification")
    minimum = raw["minimum_release_sequence"]
    epoch = raw["current_security_epoch"]
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ValueError("minimum_release_sequence_invalid")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1:
        raise ValueError("current_security_epoch_invalid")
    mode = _string(raw["expected_boot_mode"], "expected_boot_mode")
    if mode not in {"normal", "recovery"}:
        raise ValueError("expected_boot_mode_invalid")
    return {
        "expected_pk": _string_tuple(raw["expected_pk"], "expected_pk"),
        "expected_kek": _string_tuple(raw["expected_kek"], "expected_kek"),
        "expected_db": _string_tuple(raw["expected_db"], "expected_db"),
        "expected_dbx": _string_tuple(raw["expected_dbx"], "expected_dbx"),
        "minimum_release_sequence": minimum,
        "current_security_epoch": epoch,
        "expected_esp_partuuid": _string(raw["expected_esp_partuuid"], "expected_esp_partuuid"),
        "expected_esp_filesystem_identity": _string(raw["expected_esp_filesystem_identity"], "expected_esp_filesystem_identity"),
        "expected_uefi_device_path": _string(raw["expected_uefi_device_path"], "expected_uefi_device_path"),
        "expected_boot_entry_name": _string(raw["expected_boot_entry_name"], "expected_boot_entry_name"),
        "expected_boot_mode": mode,
        "revoked_authority_ids": _string_tuple(raw["revoked_authority_ids"], "revoked_authority_ids"),
    }



def _complete(
    generation: BootGeneration,
    environment: BootEnvironmentIdentity,
    observation: PostBootObservation,
) -> tuple[bool, tuple[str, ...]]:
    missing: list[str] = []
    for name in (
        "boot_generation_id",
        "boot_authority_id",
        "source_revision",
        "package_generation_id",
        "candidate_root_identity",
        "release_sequence",
        "security_epoch",
        "loader_sha256",
        "loader_signer_fingerprint",
        "embedded_config_checksum",
        "config_bytes",
        "recovery_authority_identity",
        "authenticated_cmdline",
        "running_kernel_identity",
        "limine_version",
        "boot_mode",
    ):
        if getattr(observation, name) is None:
            missing.append(name)
    if environment.missing_evidence:
        missing.extend(f"environment:{item}" for item in environment.missing_evidence)
    required_artifacts = (
        generation.primary_kernel,
        generation.primary_initramfs,
        generation.fallback_kernel,
        generation.fallback_initramfs,
        *generation.microcode,
        generation.recovery_kernel,
        generation.recovery_initramfs,
        generation.guardian_recovery_runtime,
    )
    for artifact in required_artifacts:
        if artifact.identity not in observation.artifact_bytes:
            missing.append(f"artifact:{artifact.identity}")
    return not missing, tuple(sorted(set(missing)))


def _envelope(
    *,
    now: datetime,
    observed_at: str | None,
    health: ProviderHealth,
    trust: SignedBootTrust,
    reason: str,
    errors: tuple[str, ...] = (),
    data: Mapping[str, Any] | None = None,
    confidence: EvidenceConfidence = EvidenceConfidence.NONE,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
) -> SignedBootProviderResult:
    payload = {"trust_state": trust.value, "trust_reason": reason, **dict(data or {})}
    return SignedBootProviderResult(
        EvidenceEnvelope(
            provider_id=PROVIDER_ID,
            domain=DOMAIN,
            schema_version=SCHEMA_VERSION,
            observed_at=observed_at,
            source=SOURCE,
            freshness_policy=FreshnessPolicy(max_age_seconds, required=True),
            health=health,
            data=payload,
            confidence=confidence,
            errors=errors,
            authority_boundary=AUTHORITY_BOUNDARY,
        ),
        trust,
        reason,
    )


def observe_signed_boot(
    proof_root: str | Path,
    *,
    boot_id_path: str | Path = "/proc/sys/kernel/random/boot_id",
    now: datetime | None = None,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
) -> SignedBootProviderResult:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        boot_id = Path(boot_id_path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        return _envelope(
            now=current,
            observed_at=None,
            health=ProviderHealth.FAILED,
            trust=SignedBootTrust.UNKNOWN,
            reason="current boot identity unavailable",
            errors=(f"boot_id_unreadable:{type(exc).__name__}",),
            max_age_seconds=max_age_seconds,
        )
    if not boot_id:
        return _envelope(
            now=current,
            observed_at=None,
            health=ProviderHealth.FAILED,
            trust=SignedBootTrust.UNKNOWN,
            reason="current boot identity unavailable",
            errors=("boot_id_empty",),
            max_age_seconds=max_age_seconds,
        )

    proof_path = Path(proof_root) / PROOF_FILENAME
    try:
        raw_text = proof_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _envelope(
            now=current,
            observed_at=None,
            health=ProviderHealth.HEALTHY,
            trust=SignedBootTrust.UNKNOWN,
            reason="durable Signed Boot postboot proof is missing",
            errors=("postboot_proof_missing",),
            data={"current_boot_id": boot_id, "proof_path": str(proof_path)},
            max_age_seconds=max_age_seconds,
        )
    except (OSError, UnicodeError) as exc:
        return _envelope(
            now=current,
            observed_at=None,
            health=ProviderHealth.FAILED,
            trust=SignedBootTrust.UNKNOWN,
            reason="Signed Boot proof provider could not read durable state",
            errors=(f"postboot_proof_unreadable:{type(exc).__name__}",),
            data={"current_boot_id": boot_id, "proof_path": str(proof_path)},
            max_age_seconds=max_age_seconds,
        )

    try:
        value = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return _envelope(
            now=current,
            observed_at=utc_stamp(current),
            health=ProviderHealth.HEALTHY,
            trust=SignedBootTrust.UNTRUSTED,
            reason="durable Signed Boot postboot proof is malformed",
            errors=(f"postboot_proof_json_invalid:{exc.msg}",),
            data={"current_boot_id": boot_id, "proof_path": str(proof_path)},
            max_age_seconds=max_age_seconds,
        )

    proof_observed_at: str | None = None
    if not isinstance(value, Mapping):
        return _envelope(
            now=current,
            observed_at=utc_stamp(current),
            health=ProviderHealth.HEALTHY,
            trust=SignedBootTrust.UNTRUSTED,
            reason="durable Signed Boot postboot proof is malformed",
            errors=("signed_boot_receipt_not_object",),
            data={"current_boot_id": boot_id, "proof_path": str(proof_path)},
            max_age_seconds=max_age_seconds,
        )
    missing_components = {
        "boot_generation", "boot_authority", "boot_environment",
        "postboot_observation", "verification", "observed_at", "boot_id",
    } - set(value)
    if missing_components:
        return _envelope(
            now=current,
            observed_at=None,
            health=ProviderHealth.HEALTHY,
            trust=SignedBootTrust.UNKNOWN,
            reason="durable Signed Boot proof components are missing",
            errors=tuple(f"proof_component_missing:{name}" for name in sorted(missing_components)),
            data={"current_boot_id": boot_id, "proof_path": str(proof_path), "missing_components": sorted(missing_components)},
            max_age_seconds=max_age_seconds,
        )
    try:
        receipt = _closed(value, _RECEIPT_FIELDS, "signed_boot_receipt")
        if receipt["schema_version"] != 1 or receipt["kind"] != "maho-signed-boot-postboot-proof":
            raise ValueError("signed_boot_receipt_schema_invalid")
        proof_observed_at = _string(receipt["observed_at"], "observed_at")
        observed = parse_timestamp(proof_observed_at)
        if observed is None:
            raise ValueError("observed_at_invalid")
        receipt_boot_id = _string(receipt["boot_id"], "boot_id")
        if not isinstance(receipt["boot_generation"], Mapping):
            raise ValueError("boot_generation_invalid")
        if not isinstance(receipt["boot_authority"], Mapping):
            raise ValueError("boot_authority_invalid")
        if not isinstance(receipt["boot_environment"], Mapping):
            raise ValueError("boot_environment_invalid")
        generation = BootGeneration.parse(receipt["boot_generation"])
        authority = BootAuthority.parse(receipt["boot_authority"])
        environment = BootEnvironmentIdentity.parse(receipt["boot_environment"])
        observation = _observation(receipt["postboot_observation"])
        verification = _verification(receipt["verification"])
    except (BootContractError, SecureBootError, ValueError, TypeError, KeyError) as exc:
        return _envelope(
            now=current,
            observed_at=utc_stamp(current),
            health=ProviderHealth.HEALTHY,
            trust=SignedBootTrust.UNTRUSTED,
            reason="durable Signed Boot proof failed exact schema or identity validation",
            errors=(f"postboot_proof_invalid:{exc}",),
            data={"current_boot_id": boot_id, "proof_path": str(proof_path)},
            confidence=EvidenceConfidence.HIGH,
            max_age_seconds=max_age_seconds,
        )

    identities = {
        "current_boot_id": boot_id,
        "proof_boot_id": receipt_boot_id,
        "proof_path": str(proof_path),
        "boot_generation_id": generation.boot_generation_id,
        "boot_authority_id": authority.boot_authority_id,
        "boot_environment_id": environment.boot_environment_id,
        "release_sequence": authority.release_sequence,
        "security_epoch": authority.security_epoch,
        "secure_boot": environment.secure_boot,
        "setup_mode": environment.setup_mode,
    }

    if receipt_boot_id != boot_id:
        return _envelope(
            now=current,
            observed_at=proof_observed_at,
            health=ProviderHealth.HEALTHY,
            trust=SignedBootTrust.UNTRUSTED,
            reason="Signed Boot proof belongs to a different boot",
            errors=("boot_id_mismatch",),
            data=identities,
            confidence=EvidenceConfidence.CONFIRMED,
            max_age_seconds=max_age_seconds,
        )

    age = (current - observed).total_seconds()
    if age < -300:
        return _envelope(
            now=current,
            observed_at=utc_stamp(current),
            health=ProviderHealth.HEALTHY,
            trust=SignedBootTrust.UNTRUSTED,
            reason="Signed Boot proof timestamp is inconsistent with the local clock",
            errors=("postboot_proof_from_future",),
            data=identities,
            confidence=EvidenceConfidence.HIGH,
            max_age_seconds=max_age_seconds,
        )
    if age > max_age_seconds:
        return _envelope(
            now=current,
            observed_at=proof_observed_at,
            health=ProviderHealth.HEALTHY,
            trust=SignedBootTrust.UNKNOWN,
            reason="Signed Boot postboot proof is stale",
            errors=("postboot_proof_stale",),
            data=identities,
            confidence=EvidenceConfidence.HIGH,
            max_age_seconds=max_age_seconds,
        )

    complete, missing = _complete(generation, environment, observation)
    if not complete:
        return _envelope(
            now=current,
            observed_at=proof_observed_at,
            health=ProviderHealth.HEALTHY,
            trust=SignedBootTrust.UNKNOWN,
            reason="Signed Boot postboot proof is incomplete",
            errors=tuple(f"missing:{item}" for item in missing),
            data={**identities, "missing_proof": list(missing)},
            confidence=EvidenceConfidence.HIGH,
            max_age_seconds=max_age_seconds,
        )

    try:
        verified = verify_postboot(
            generation,
            authority,
            environment,
            observation,
            expected_pk=verification["expected_pk"],
            expected_kek=verification["expected_kek"],
            expected_db=verification["expected_db"],
            expected_dbx=verification["expected_dbx"],
            minimum_release_sequence=verification["minimum_release_sequence"],
            current_security_epoch=verification["current_security_epoch"],
            expected_esp_partuuid=verification["expected_esp_partuuid"],
            expected_esp_filesystem_identity=verification["expected_esp_filesystem_identity"],
            expected_uefi_device_path=verification["expected_uefi_device_path"],
            expected_boot_entry_name=verification["expected_boot_entry_name"],
            expected_boot_mode=verification["expected_boot_mode"],
            revoked_authority_ids=verification["revoked_authority_ids"],
        )
    except (BootContractError, SecureBootError, ValueError, TypeError) as exc:
        return _envelope(
            now=current,
            observed_at=proof_observed_at,
            health=ProviderHealth.HEALTHY,
            trust=SignedBootTrust.UNTRUSTED,
            reason="Signed Boot verifier rejected the supplied proof context",
            errors=(f"signed_boot_verifier_error:{exc}",),
            data=identities,
            confidence=EvidenceConfidence.CONFIRMED,
            max_age_seconds=max_age_seconds,
        )

    verifier_data = {
        **identities,
        "verifier": {
            "trusted": verified.trusted,
            "state": verified.state,
            "failures": list(verified.failures),
            "missing_evidence": list(verified.missing_evidence),
        },
    }
    if verified.trusted:
        return _envelope(
            now=current,
            observed_at=proof_observed_at,
            health=ProviderHealth.HEALTHY,
            trust=SignedBootTrust.VERIFIED,
            reason="complete Signed Boot postboot proof passed the landed verifier",
            data=verifier_data,
            confidence=EvidenceConfidence.CONFIRMED,
            max_age_seconds=max_age_seconds,
        )
    return _envelope(
        now=current,
        observed_at=proof_observed_at,
        health=ProviderHealth.HEALTHY,
        trust=SignedBootTrust.UNTRUSTED,
        reason="complete Signed Boot postboot proof failed the landed verifier",
        errors=tuple(verified.failures) + tuple(f"missing:{item}" for item in verified.missing_evidence),
        data=verifier_data,
        confidence=EvidenceConfidence.CONFIRMED,
        max_age_seconds=max_age_seconds,
    )
