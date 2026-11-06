#!/usr/bin/env python3
"""Pure, fail-closed Agent-4 boot-critical update admission contract.

Does not sign, write ESP files, touch firmware, enroll TPM/LUKS, or reboot.
External evidence providers must independently verify receipts before calling.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from maho_boot_authority import (
    BootAuthority, BootGeneration, BootContractError, certificate_fingerprint,
)
from maho_secure_boot import BootEnvironmentIdentity, PostBootResult
from maho_tpm_unlock_policy import require_generation_unlock_coverage


@dataclass(frozen=True)
class CandidateLoaderReceipt:
    """Externally verified identity for a sealed, signed candidate loader."""
    boot_generation_id: str
    role: str
    loader_artifact_sha256: str
    signing_certificate_fingerprint: str
    enrolled_config_blake2b: str
    signature_cryptographically_verified: bool
    authorized_by_firmware_db: bool
    config_integrity_verified: bool
    resource_integrity_verified: bool


@dataclass(frozen=True)
class BootUpdateAdmission:
    admitted_for_agent4_publication: bool
    blockers: tuple[str, ...]
    candidate_boot_generation_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "status": "ADMITTED" if self.admitted_for_agent4_publication else "BLOCKED",
            "candidate_boot_generation_id": self.candidate_boot_generation_id,
            "blockers": list(self.blockers),
            "firmware_mutation_authorized": False,
            "luks_slot_mutation_authorized": False,
            "boot_reboot_authorized": False,
        }


def evaluate_signed_boot_update_admission(
    *, current: BootGeneration, candidate: BootGeneration,
    current_authority: BootAuthority, candidate_authority: BootAuthority,
    environment: BootEnvironmentIdentity, current_postboot: PostBootResult,
    normal: CandidateLoaderReceipt, recovery: CandidateLoaderReceipt,
    signer_continuity_verified: bool, previous_signed_chain_retained: bool,
    windows_efi_trust_preserved: bool, firmware_boot_variables_unchanged: bool,
    manual_luks_recovery_tested: bool,
    tpm_token_confirmed: Mapping[tuple[str, str], bool],
) -> BootUpdateAdmission:
    """Admission is a prerequisite, never a mutation command.

    The receipt source MUST cryptographically inspect staged EFI bytes against
    the signed BootGeneration and the firmware trust database. TPM token facts
    MUST come from an independent exact-policy/slot authority, not presence
    alone. A positive receipt is never self-authenticating.
    """
    if not isinstance(current, BootGeneration) or not isinstance(candidate, BootGeneration):
        raise BootContractError("signed_boot_generation_type_invalid")
    if not isinstance(current_authority, BootAuthority) or not isinstance(candidate_authority, BootAuthority):
        raise BootContractError("signed_boot_authority_type_invalid")
    blockers: list[str] = []
    if candidate.boot_generation_id == current.boot_generation_id:
        blockers.append("candidate_boot_generation_unchanged")
    if current_authority.permitted_boot_generation_id != current.boot_generation_id:
        blockers.append("current_boot_authority_mismatch")
    if candidate_authority.permitted_boot_generation_id != candidate.boot_generation_id:
        blockers.append("candidate_boot_authority_mismatch")
    if candidate_authority.source_revision != candidate.source_revision:
        blockers.append("candidate_release_source_mismatch")
    if candidate_authority.security_epoch != current_authority.security_epoch:
        blockers.append("security_epoch_change_requires_separate_ceremony")
    if candidate_authority.release_sequence <= current_authority.release_sequence:
        blockers.append("candidate_release_sequence_not_monotonic")
    expected_signer = certificate_fingerprint(
        candidate_authority.device_signing_certificate_fingerprint
    )
    if expected_signer != certificate_fingerprint(current_authority.device_signing_certificate_fingerprint):
        blockers.append("signing_key_rotation_requires_separate_ceremony")
    if environment.secure_boot is not True or environment.setup_mode is not False:
        blockers.append("physical_secure_boot_not_active")
    if current_postboot.trusted is not True or current_postboot.state != "HEALTHY":
        blockers.append("current_known_good_signed_boot_unproven")
    db_certificate = "x509-sha256:" + expected_signer
    if environment.db_fingerprints is None or db_certificate not in environment.db_fingerprints:
        blockers.append("signer_not_pinned_in_firmware_db")
    if environment.dbx_fingerprints is None:
        blockers.append("firmware_revocation_inventory_unknown")
    elif db_certificate in environment.dbx_fingerprints:
        blockers.append("signer_revoked_in_firmware_dbx")

    for role, observed, expected in (
        ("normal", normal, candidate.normal_loader),
        ("recovery", recovery, candidate.recovery_loader),
    ):
        digest = expected.artifact.digest("sha256", "maho-content-identity")
        if (observed.boot_generation_id != candidate.boot_generation_id
                or observed.role != role or digest is None
                or observed.loader_artifact_sha256 != digest.digest
                or observed.enrolled_config_blake2b != expected.embedded_config_checksum.digest
                or observed.signing_certificate_fingerprint != expected_signer
                or certificate_fingerprint(expected.signing_certificate_fingerprint) != expected_signer):
            blockers.append(f"{role}_sealed_loader_identity_mismatch")
        if observed.signature_cryptographically_verified is not True:
            blockers.append(f"{role}_efi_signature_unverified")
        if observed.authorized_by_firmware_db is not True:
            blockers.append(f"{role}_firmware_signature_authorization_missing")
        if observed.config_integrity_verified is not True:
            blockers.append(f"{role}_enrolled_config_unverified")
        if observed.resource_integrity_verified is not True:
            blockers.append(f"{role}_resource_integrity_unverified")

    for label, proven in (
        ("signer_continuity_unverified", signer_continuity_verified),
        ("previous_signed_recovery_not_retained", previous_signed_chain_retained),
        ("windows_efi_trust_not_proven_preserved", windows_efi_trust_preserved),
        ("firmware_boot_variables_changed", firmware_boot_variables_unchanged),
        ("manual_luks_recovery_not_tested", manual_luks_recovery_tested),
    ):
        if proven is not True:
            blockers.append(label)
    blockers.extend(require_generation_unlock_coverage(
        current_generation_id=current.boot_generation_id,
        candidate_generation_id=candidate.boot_generation_id,
        fallback_generation_id=candidate.boot_generation_id,
        recovery_generation_id=candidate.boot_generation_id,
        token_confirmed=tpm_token_confirmed,
    ))
    failures = tuple(sorted(set(blockers)))
    return BootUpdateAdmission(not failures, failures, candidate.boot_generation_id)
