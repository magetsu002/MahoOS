#!/usr/bin/env python3
"""Fail-closed TPM2 LUKS unlock readiness gate for the existing Signed Boot owner.

Pure policy only: no TPM, firmware, block-device, or key-slot mutation. The
Signed Boot verifier and independent PCR-event-log replay provider own facts.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Mapping, TYPE_CHECKING

from maho_limine_measurements import LimineMeasurement
from maho_tcg2_eventlog import parse_tcg2_eventlog, verify_limine_pcr_event_chain

if TYPE_CHECKING:
    from maho_boot_authority import BootAuthority, BootGeneration
    from maho_secure_boot import BootEnvironmentIdentity, PostBootResult

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_VERSION = re.compile(r"([0-9]+)(?:\.([0-9]+))?(?:\.[0-9]+)*\Z")
_BOOT_GENERATION_ID = re.compile(r"bootgen-[0-9a-f]{64}\Z")
PCRS = (7, 8, 9)
EVENT_ROLES = frozenset(("cmdline", "limine_cfg", "kernel", "initramfs"))
BOOT_MODES = frozenset(("normal", "fallback", "recovery"))


@dataclass(frozen=True)
class TpmUnlockObservation:
    """External evidence, NOT itself a signature or a claim of physical proof.

    event_log_replay_verified must come from an independent event-log/PCR
    replay verifier, not from a snapshot of /sys/class/tpm values alone.
    event_roles must be validated against the selected Limine entry and
    BootGeneration, not merely extracted from arbitrary event-log strings.
    """
    boot_generation_id: str
    boot_mode: str
    luks_uuid: str
    event_log_sha256: str | None
    pcr_sha256: Mapping[int, str]
    event_log_replay_verified: bool
    event_roles: tuple[str, ...]
    initramfs_tpm2_verified: bool


def observe_limine_tpm_unlock(
    *, prediction: LimineMeasurement, event_log: bytes,
    independently_read_sha256_pcrs: Mapping[int, str],
    boot_generation_id: str, boot_mode: str, luks_uuid: str,
    initramfs_tpm2_verified: bool,
) -> TpmUnlockObservation:
    """Convert strict event-log verification into bounded unlock evidence.

    The caller MUST acquire TPM PCRs independently of the supplied event log
    and bind the reads to the same boot session. The resulting observation
    remains dependent on actual Signed Boot postboot verification.
    """
    events = parse_tcg2_eventlog(event_log)
    reasons = verify_limine_pcr_event_chain(
        prediction=prediction, events=events,
        independently_read_sha256_pcrs=independently_read_sha256_pcrs,
    )
    pcrs = {index: independently_read_sha256_pcrs[index]
            for index in PCRS if index in independently_read_sha256_pcrs}
    return TpmUnlockObservation(
        boot_generation_id=boot_generation_id,
        boot_mode=boot_mode,
        luks_uuid=luks_uuid,
        event_log_sha256=hashlib.sha256(event_log).hexdigest(),
        pcr_sha256=pcrs,
        event_log_replay_verified=not reasons,
        event_roles=("cmdline", "limine_cfg", "kernel", "initramfs") if not reasons else (),
        initramfs_tpm2_verified=initramfs_tpm2_verified,
    )


@dataclass(frozen=True)
class RecoveryReadiness:
    passphrase_unlock_tested: bool
    exported_recovery_key_unlock_tested: bool
    luks_header_backup_verified: bool
    windows_recovery_material_ready: bool
    persistent_signing_authority_available: bool
    free_luks_token_slot_verified: bool


@dataclass(frozen=True)
class TpmUnlockDecision:
    eligible_for_authorized_enrollment: bool
    blockers: tuple[str, ...]
    pcr_binding: str | None
    boot_generation_id: str
    boot_mode: str


def evaluate_tpm_unlock(
    *, generation: BootGeneration, authority: BootAuthority,
    environment: BootEnvironmentIdentity, signed_boot: PostBootResult,
    observation: TpmUnlockObservation, recovery: RecoveryReadiness,
    limine_version: str, expected_luks_uuid: str, expected_boot_mode: str,
) -> TpmUnlockDecision:
    """Never substitute a SecureBoot=1 observation for Signed Boot proof.

    This is a pre-enrollment gate. A positive result is NOT authorization to
    modify LUKS slots, nor proof of a future successful physical unlock.
    """
    failures: list[str] = []
    if signed_boot.trusted is not True or signed_boot.state != "HEALTHY":
        failures.append("signed_boot_not_physically_verified")
    if environment.secure_boot is not True or environment.setup_mode is not False:
        failures.append("firmware_secure_boot_not_enforced")
    if environment.tpm_available is not True:
        failures.append("tpm2_unavailable")
    if environment.measured_boot_available is not True:
        failures.append("measured_boot_unavailable")
    match = _VERSION.fullmatch(limine_version)
    if match is None or int(match.group(1)) < 12:
        failures.append("limine_measured_boot_version_unproven")
    if expected_boot_mode not in BOOT_MODES:
        failures.append("expected_boot_mode_invalid")
    if observation.boot_mode not in BOOT_MODES:
        failures.append("boot_mode_unknown")
    elif observation.boot_mode != expected_boot_mode:
        failures.append("observed_boot_mode_mismatch")
    if (_BOOT_GENERATION_ID.fullmatch(observation.boot_generation_id) is None
            or observation.boot_generation_id != generation.boot_generation_id
            or observation.boot_generation_id != authority.permitted_boot_generation_id):
        failures.append("boot_generation_authority_mismatch")
    if _UUID.fullmatch(expected_luks_uuid) is None:
        failures.append("expected_luks_identity_invalid")
    if (_UUID.fullmatch(observation.luks_uuid) is None
            or observation.luks_uuid != expected_luks_uuid):
        failures.append("luks_identity_mismatch")
    if (_SHA256.fullmatch(observation.event_log_sha256 or "") is None
            or observation.event_log_sha256 != environment.pcr_event_log_sha256):
        failures.append("event_log_identity_unbound")
    if observation.event_log_replay_verified is not True:
        failures.append("pcr_event_log_replay_unverified")
    if (set(observation.pcr_sha256) != set(PCRS)
            or any(_SHA256.fullmatch(v) is None for v in observation.pcr_sha256.values())):
        failures.append("pcr_7_8_9_sha256_incomplete")
    if not EVENT_ROLES.issubset(set(observation.event_roles)):
        failures.append("limine_selected_payload_measurements_missing")
    if observation.initramfs_tpm2_verified is not True:
        failures.append("initramfs_tpm2_unlock_support_unverified")
    gates = (
        ("recovery_passphrase_not_tested", recovery.passphrase_unlock_tested),
        ("recovery_key_not_tested", recovery.exported_recovery_key_unlock_tested),
        ("luks_header_backup_not_verified", recovery.luks_header_backup_verified),
        ("windows_recovery_not_ready", recovery.windows_recovery_material_ready),
        ("persistent_signing_authority_unavailable", recovery.persistent_signing_authority_available),
        ("luks_token_capacity_unverified", recovery.free_luks_token_slot_verified),
    )
    failures.extend(reason for reason, value in gates if value is not True)
    failures = sorted(set(failures))
    pcr_binding = None
    if not failures:
        pcr_binding = "+".join(
            f"{i}:sha256={observation.pcr_sha256[i]}" for i in PCRS
        )
    return TpmUnlockDecision(not failures, tuple(failures), pcr_binding,
                             observation.boot_generation_id, observation.boot_mode)


def proposed_enrollment_argv(*, decision: TpmUnlockDecision, luks_partuuid: str) -> tuple[str, ...]:
    """Return an inspectable argv ONLY; never executes or requests credentials.

    Agent 0 must separately authorize exact LUKS2 header mutation and verify
    the device identity. We intentionally do not accept arbitrary /dev paths.
    """
    if not decision.eligible_for_authorized_enrollment or decision.pcr_binding is None:
        raise ValueError("tpm_enrollment_not_eligible")
    if _UUID.fullmatch(luks_partuuid) is None:
        raise ValueError("luks_partition_identity_invalid")
    return (
        "systemd-cryptenroll", "--tpm2-device=auto",
        f"--tpm2-pcrs={decision.pcr_binding}",
        f"/dev/disk/by-partuuid/{luks_partuuid}",
    )


def require_generation_unlock_coverage(
    *, current_generation_id: str, candidate_generation_id: str,
    fallback_generation_id: str, recovery_generation_id: str,
    token_confirmed: Mapping[tuple[str, str], bool],
) -> tuple[str, ...]:
    """Block activation unless current, candidate and recovery roles are covered.

    token_confirmed is evidence supplied by the authorized LUKS owner,
    not a claim that a token found in JSON necessarily unseals on hardware.
    Separate (generation, role) keys prevent a normal token being substituted
    for independent fallback/recovery boot measurements.
    """
    roles = (
        (current_generation_id, "normal"),
        (candidate_generation_id, "normal"),
        (fallback_generation_id, "fallback"),
        (recovery_generation_id, "recovery"),
    )
    blockers = []
    for generation_id, role in roles:
        if _BOOT_GENERATION_ID.fullmatch(generation_id) is None:
            blockers.append(f"unlock_generation_identity_invalid:{role}")
        elif token_confirmed.get((generation_id, role)) is not True:
            blockers.append(f"tpm_unlock_unproven:{role}:{generation_id}")
    return tuple(sorted(set(blockers)))
