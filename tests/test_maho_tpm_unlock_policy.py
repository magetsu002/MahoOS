#!/usr/bin/env python3
"""Deterministic non-hardware checks: no shell commands or TPM writes."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from maho_tpm_unlock_policy import (  # noqa: E402
    RecoveryReadiness, TpmUnlockObservation, evaluate_tpm_unlock,
    proposed_enrollment_argv, require_generation_unlock_coverage,
)

GEN = "bootgen-" + "a" * 64
LUKS = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
LOG = "b" * 64
PCR = {7: "7" * 64, 8: "8" * 64, 9: "9" * 64}


def setup():
    generation = SimpleNamespace(boot_generation_id=GEN)
    authority = SimpleNamespace(permitted_boot_generation_id=GEN)
    environment = SimpleNamespace(secure_boot=True, setup_mode=False,
                                  tpm_available=True, measured_boot_available=True,
                                  pcr_event_log_sha256=LOG)
    signed_boot = SimpleNamespace(trusted=True, state="HEALTHY")
    observation = TpmUnlockObservation(GEN, "normal", LUKS, LOG, PCR, True,
                                      ("cmdline", "limine_cfg", "kernel", "initramfs"), True)
    recovery = RecoveryReadiness(True, True, True, True, True, True)
    return dict(generation=generation, authority=authority, environment=environment,
                signed_boot=signed_boot, observation=observation, recovery=recovery,
                limine_version="12.2.1", expected_luks_uuid=LUKS,
                expected_boot_mode="normal")


def blocked(name, args, reason):
    result = evaluate_tpm_unlock(**args)
    assert not result.eligible_for_authorized_enrollment, name
    assert reason in result.blockers, (name, result.blockers)
    assert result.pcr_binding is None, name
    try:
        proposed_enrollment_argv(decision=result, luks_partuuid=LUKS)
        raise AssertionError("invalid enrollment was planned")
    except ValueError as exc:
        assert str(exc) == "tpm_enrollment_not_eligible"


def replace_ns(value, **changes):
    return SimpleNamespace(**(vars(value) | changes))


def main():
    args = setup()
    positive = evaluate_tpm_unlock(**args)
    assert positive.eligible_for_authorized_enrollment and not positive.blockers
    assert positive.pcr_binding == "+".join(f"{i}:sha256={PCR[i]}" for i in (7, 8, 9))
    argv = proposed_enrollment_argv(decision=positive, luks_partuuid=LUKS)
    assert argv[0] == "systemd-cryptenroll" and argv[-1] == f"/dev/disk/by-partuuid/{LUKS}"
    try:
        proposed_enrollment_argv(decision=positive, luks_partuuid="/dev/nvme0n1p2")
        raise AssertionError("arbitrary block device accepted")
    except ValueError as exc:
        assert str(exc) == "luks_partition_identity_invalid"

    tests = [
        ("signed proof", "signed_boot", "signed_boot_not_physically_verified", SimpleNamespace(trusted=False, state="UNTRUSTED")),
        ("firmware", "environment", "firmware_secure_boot_not_enforced", replace_ns(args["environment"], secure_boot=False)),
        ("setup mode", "environment", "firmware_secure_boot_not_enforced", replace_ns(args["environment"], setup_mode=True)),
        ("TPM", "environment", "tpm2_unavailable", replace_ns(args["environment"], tpm_available=False)),
        ("measured boot", "environment", "measured_boot_unavailable", replace_ns(args["environment"], measured_boot_available=False)),
        ("older Limine", "limine_version", "limine_measured_boot_version_unproven", "11.0"),
        ("wrong generation", "observation", "boot_generation_authority_mismatch", replace(args["observation"], boot_generation_id="bootgen-b")),
        ("malformed generation", "observation", "boot_generation_authority_mismatch", replace(args["observation"], boot_generation_id="bootgen-"+("g"*64))),
        ("wrong expected LUKS", "expected_luks_uuid", "luks_identity_mismatch", "ffffffff-bbbb-4ccc-8ddd-eeeeeeeeeeee"),
        ("invalid expected LUKS", "expected_luks_uuid", "expected_luks_identity_invalid", "/dev/mapper/foo"),
        ("wrong observed LUKS", "observation", "luks_identity_mismatch", replace(args["observation"], luks_uuid="ffffffff-bbbb-4ccc-8ddd-eeeeeeeeeeee")),
        ("wrong boot mode", "observation", "observed_boot_mode_mismatch", replace(args["observation"], boot_mode="recovery")),
        ("invalid requested boot mode", "expected_boot_mode", "expected_boot_mode_invalid", "invalid"),
        ("wrong log", "observation", "event_log_identity_unbound", replace(args["observation"], event_log_sha256="a" * 64)),
        ("unreplayed log", "observation", "pcr_event_log_replay_unverified", replace(args["observation"], event_log_replay_verified=False)),
        ("PCR7 alone", "observation", "pcr_7_8_9_sha256_incomplete", replace(args["observation"], pcr_sha256={7: PCR[7]})),
        ("bad digest", "observation", "pcr_7_8_9_sha256_incomplete", replace(args["observation"], pcr_sha256={7:"z"*64, 8:PCR[8],9:PCR[9]})),
        ("no kernel measurement", "observation", "limine_selected_payload_measurements_missing", replace(args["observation"], event_roles=("cmdline", "limine_cfg", "initramfs"))),
        ("no initrd unlock", "observation", "initramfs_tpm2_unlock_support_unverified", replace(args["observation"], initramfs_tpm2_verified=False)),
        ("no passphrase test", "recovery", "recovery_passphrase_not_tested", replace(args["recovery"], passphrase_unlock_tested=False)),
        ("no recovery key", "recovery", "recovery_key_not_tested", replace(args["recovery"], exported_recovery_key_unlock_tested=False)),
        ("no header backup", "recovery", "luks_header_backup_not_verified", replace(args["recovery"], luks_header_backup_verified=False)),
        ("no Windows escrow", "recovery", "windows_recovery_not_ready", replace(args["recovery"], windows_recovery_material_ready=False)),
        ("lost signing key", "recovery", "persistent_signing_authority_unavailable", replace(args["recovery"], persistent_signing_authority_available=False)),
        ("no token space", "recovery", "luks_token_capacity_unverified", replace(args["recovery"], free_luks_token_slot_verified=False)),
    ]
    for name, field, reason, value in tests:
        changed = dict(args)
        changed[field] = value
        blocked(name, changed, reason)

    roles = {(GEN, "normal"): True, (GEN, "fallback"): True, (GEN, "recovery"): True}
    kw = dict(current_generation_id=GEN, candidate_generation_id=GEN,
              fallback_generation_id=GEN, recovery_generation_id=GEN,
              token_confirmed=roles)
    assert require_generation_unlock_coverage(**kw) == ()
    roles[(GEN, "recovery")] = False
    assert any("recovery" in item for item in require_generation_unlock_coverage(**kw))
    del roles[(GEN, "fallback")]
    assert any("fallback" in item for item in require_generation_unlock_coverage(**kw))
    bad = kw | {"candidate_generation_id": "bootgen-" + ("q" * 64)}
    assert any("identity_invalid:normal" in item for item in require_generation_unlock_coverage(**bad))
    print(f"PASS: {len(tests) + 6} TPM policy positive/negative and lifecycle checks")


if __name__ == "__main__":
    main()
