#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_boot_authority import (  # noqa: E402
    BootArtifact, BootAuthority, BootContractError, BootGeneration, Digest,
    KeyLifecycleState, evaluate_key_continuity, transition_key_state,
)
from maho_secure_boot import (  # noqa: E402
    BootEnvironmentIdentity, EfiEntry, EfiExecutable, FakeSigningProvider,
    PostBootObservation, inventory_bypass_reasons, inventory_efi_executables,
    seal_limine_loader, validate_limine_config, verify_postboot,
)

SOURCE = "a" * 40
PACKAGE = "pkg-" + "b" * 64
SIGNER = "AB" * 32


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def rejected(name: str, fn, contains: str) -> None:
    try:
        fn()
    except (BootContractError, ValueError) as exc:
        check(name, contains in str(exc))
        return
    raise AssertionError(name)


def artifact(name: str, content: bytes, *, dual: bool = False) -> BootArtifact:
    algorithms = (("blake2b-512", "limine-artifact-integrity"),
                  ("sha256", "maho-content-identity")) if dual else (("sha256", "maho-content-identity"),)
    return BootArtifact.from_bytes(content, artifact_type=name, path=f"/EFI/MahoOS/artifacts/{name}", algorithms=algorithms)


def fixture() -> tuple[BootGeneration, BootAuthority, dict[str, bytes], bytes]:
    provider = FakeSigningProvider(SIGNER)
    contents = {
        "primary-kernel": b"primary-kernel", "primary-initramfs": b"primary-initramfs",
        "fallback-kernel": b"fallback-kernel", "fallback-initramfs": b"fallback-initramfs",
        "microcode": b"microcode", "recovery-kernel": b"recovery-kernel",
        "recovery-initramfs": b"recovery-initramfs", "guardian-runtime": b"guardian-runtime",
        "cmdline": b"root=UUID=candidate lockdown=integrity module.sig_enforce=1",
    }
    arts = {name: artifact(name, content, dual=name != "cmdline") for name, content in contents.items()}
    def suffix(name):
        return arts[name].digest("blake2b-512", "limine-artifact-integrity").digest.encode()
    normal_config = (
        b"timeout: 3\n/MahoOS Primary\n protocol: linux\n path: boot():/primary#" + suffix("primary-kernel")
        + b"\n module_path: boot():/primary-initramfs#" + suffix("primary-initramfs")
        + b"\n module_path: boot():/microcode#" + suffix("microcode")
        + b"\n/MahoOS Fallback\n protocol: linux\n path: boot():/fallback#" + suffix("fallback-kernel")
        + b"\n module_path: boot():/fallback-initramfs#" + suffix("fallback-initramfs") + b"\n"
    )
    recovery_config = (
        b"timeout: 5\n/Guardian Recovery\n protocol: linux\n path: boot():/recovery#" + suffix("recovery-kernel")
        + b"\n module_path: boot():/recovery-initramfs#" + suffix("recovery-initramfs") + b"\n"
    )
    normal = seal_limine_loader(
        b"clean-normal", normal_config, provider=provider, limine_version="9.0.0",
        loader_path="/EFI/MahoOS/Normal/limine.efi", config_path="/EFI/MahoOS/Normal/limine.conf",
        discovery_surface=("/EFI/MahoOS/Normal/limine.conf",),
        required_artifacts=(arts["primary-kernel"], arts["primary-initramfs"], arts["fallback-kernel"],
                            arts["fallback-initramfs"], arts["microcode"]),
    )
    recovery = seal_limine_loader(
        b"clean-recovery", recovery_config, provider=provider, limine_version="9.0.0",
        loader_path="/EFI/MahoOS/Recovery/limine.efi", config_path="/EFI/MahoOS/Recovery/limine.conf",
        discovery_surface=("/EFI/MahoOS/Recovery/limine.conf",),
        required_artifacts=(arts["recovery-kernel"], arts["recovery-initramfs"]),
    )
    generation = BootGeneration.create(
        source_revision=SOURCE, package_generation_id=PACKAGE, candidate_root_identity="candidate-root-sha256:" + "c" * 64,
        normal_loader=normal.loader, normal_config=normal.config, primary_kernel=arts["primary-kernel"],
        primary_initramfs=arts["primary-initramfs"], fallback_kernel=arts["fallback-kernel"],
        fallback_initramfs=arts["fallback-initramfs"], microcode=(arts["microcode"],),
        recovery_loader=recovery.loader, recovery_config=recovery.config, recovery_kernel=arts["recovery-kernel"],
        recovery_initramfs=arts["recovery-initramfs"], guardian_recovery_runtime=arts["guardian-runtime"],
        authenticated_cmdline=arts["cmdline"],
    )
    authority = BootAuthority.create(
        device_signing_certificate_fingerprint=SIGNER, release_authority_identity="maho-release-ed25519-" + "d" * 64,
        release_sequence=42, security_epoch=3, secure_boot_policy_version=1, limine_policy_version=1,
        permitted_boot_generation_id=generation.boot_generation_id, recovery_authority_identity="guardian-recovery-v1",
        source_revision=SOURCE,
    )
    observed = {arts[name].identity: content for name, content in contents.items() if name != "cmdline"}
    return generation, authority, observed, normal_config


def main() -> None:
    generation, authority, artifacts, config = fixture()
    check("Limine rejects any unhashed loaded resource",
          any("resource_hash_missing" in item for item in validate_limine_config(b"/bad\n protocol: linux\n path: boot():/kernel\n")))
    rejected("alternate Limine config discovery is not authoritative",
             lambda: generation.normal_loader.__class__(
                 generation.normal_loader.artifact, generation.normal_loader.limine_version, SIGNER,
                 generation.normal_loader.embedded_config_checksum,
                 generation.normal_loader.authoritative_config_path,
                 ("/EFI/MahoOS/Normal/limine.conf", "/limine.conf"),
                 generation.normal_loader.config_resource_digests),
             "ambiguous_limine_config_authority")
    parsed = BootGeneration.parse(generation.as_dict())
    check("BootGeneration is stable across closed-schema serialization", parsed.boot_generation_id == generation.boot_generation_id)
    reordered = BootGeneration.create(
        **{key: value for key, value in generation.__dict__.items() if key not in {"boot_generation_id", "schema_version", "microcode"}},
        microcode=reversed(generation.microcode),
    )
    check("BootGeneration canonicalizes artifact ordering", reordered.boot_generation_id == generation.boot_generation_id)
    digest = generation.primary_kernel.digests
    check("SHA-256 and BLAKE2B retain distinct purpose and algorithm", len(digest) == 2 and digest[0].algorithm != digest[1].algorithm)
    changed = deepcopy(generation.as_dict())
    changed["source_revision"] = "f" * 40
    rejected("BootGeneration source drift breaks content identity", lambda: BootGeneration.parse(changed), "identity_mismatch")
    rejected("security epoch mismatch rejects valid old authority",
             lambda: __import__("maho_boot_authority").authorize_freshness(authority, minimum_release_sequence=1, current_security_epoch=4),
             "security_epoch_mismatch")
    rejected("release sequence rejects signed downgrade",
             lambda: __import__("maho_boot_authority").authorize_freshness(authority, minimum_release_sequence=43, current_security_epoch=3),
             "release_sequence_rollback")

    check("rotation cannot retire old trust before new boot proof",
          transition_key_state(KeyLifecycleState.ACTIVE, KeyLifecycleState.ROTATION_PREPARED) is KeyLifecycleState.ROTATION_PREPARED)
    rejected("rotation proof requires actual boot evidence",
             lambda: transition_key_state(KeyLifecycleState.ROTATION_DUAL_TRUST, KeyLifecycleState.ROTATION_PROVEN),
             "boot_proof_required")
    check("TPM unavailable is explicit rather than reprovisioned",
          evaluate_key_continuity(expected_tpm_identity="tpm-a", observed_tpm_identity=None,
                                  signing_key_available=False, firmware_keys_preserved=True)
          is KeyLifecycleState.UNAVAILABLE)
    check("TPM reset requires explicit reprovision",
          evaluate_key_continuity(expected_tpm_identity="tpm-a", observed_tpm_identity="tpm-b",
                                  signing_key_available=True, firmware_keys_preserved=True)
          is KeyLifecycleState.REPROVISION_REQUIRED)

    environment = BootEnvironmentIdentity.create(
        esp_gpt_partuuid="11111111-2222-3333-4444-555555555555", esp_filesystem_identity="fat-1234",
        uefi_device_path="PciRoot/HD(1,GPT,...)/EFI/MahoOS/Normal/limine.efi",
        boot_entry=EfiEntry("Boot0001", "1" * 64, "PciRoot/HD(1,GPT,...)/EFI/MahoOS/Normal/limine.efi"),
        secure_boot=True, setup_mode=False, audit_mode=False, deployed_mode=True,
        pk_fingerprints=("pk",), kek_fingerprints=("kek",), db_fingerprints=("db",), dbx_fingerprints=("dbx",),
        tpm_available=True, measured_boot_available=True, pcr_event_log_sha256="2" * 64,
        actual_efi_image=EfiExecutable("esp", "/EFI/MahoOS/Normal/limine.efi",
                                     generation.normal_loader.artifact.digests[-1].digest, SIGNER, True),
        esp_candidates=("11111111-2222-3333-4444-555555555555",), missing_evidence=(),
    )
    loader_sha = generation.normal_loader.artifact.digest("sha256", "maho-content-identity")
    observation = PostBootObservation(
        generation.boot_generation_id, authority.boot_authority_id, SOURCE, PACKAGE,
        generation.candidate_root_identity, 42, 3, loader_sha.digest if loader_sha else None, SIGNER,
        generation.normal_loader.embedded_config_checksum.digest, config, artifacts,
        "guardian-recovery-v1", True, (),
        b"root=UUID=candidate lockdown=integrity module.sig_enforce=1",
        generation.primary_kernel.identity, "9.0.0", "normal",
    )
    environment_expectations = {
        "expected_esp_partuuid": "11111111-2222-3333-4444-555555555555",
        "expected_esp_filesystem_identity": "fat-1234",
        "expected_uefi_device_path": "PciRoot/HD(1,GPT,...)/EFI/MahoOS/Normal/limine.efi",
        "expected_boot_entry_name": "Boot0001",
    }
    result = verify_postboot(generation, authority, environment, observation,
                             expected_pk=("pk",), expected_kek=("kek",), expected_db=("db",), expected_dbx=("dbx",),
                             minimum_release_sequence=42, current_security_epoch=3, **environment_expectations)
    check("complete signed chain is the only HEALTHY result", result.trusted and result.state == "HEALTHY")
    check("BootEnvironmentIdentity roundtrips with closed content identity",
          BootEnvironmentIdentity.parse(environment.as_dict()).boot_environment_id == environment.boot_environment_id)
    def changed_environment(**changes):
        values = dict(environment.__dict__)
        values.pop("boot_environment_id")
        values.pop("schema_version")
        values.update(changes)
        return BootEnvironmentIdentity.create(**values)
    disabled_values = dict(environment.__dict__)
    disabled_values.pop("boot_environment_id")
    disabled_values.pop("schema_version")
    disabled_values["secure_boot"] = False
    disabled = BootEnvironmentIdentity.create(**disabled_values)
    failed = verify_postboot(generation, authority, disabled, observation,
                             expected_pk=("pk",), expected_kek=("kek",), expected_db=("db",), expected_dbx=("dbx",),
                             minimum_release_sequence=42, current_security_epoch=3, **environment_expectations)
    check("Secure Boot disabled is fail closed", not failed.trusted and "secure_boot_not_enabled" in failed.failures)
    missing = PostBootObservation(**(observation.__dict__ | {"loader_signer_fingerprint": None}))
    failed = verify_postboot(generation, authority, environment, missing,
                             expected_pk=("pk",), expected_kek=("kek",), expected_db=("db",), expected_dbx=("dbx",),
                             minimum_release_sequence=42, current_security_epoch=3, **environment_expectations)
    check("missing signer remains missing and never synthesized", "loader_signer_fingerprint" in failed.missing_evidence)
    for label, environment_variant, reason in (
        ("SetupMode", changed_environment(setup_mode=True), "setup_mode_not_disabled"),
        ("PK", changed_environment(pk_fingerprints=("wrong",)), "pk_mismatch"),
        ("KEK", changed_environment(kek_fingerprints=("wrong",)), "kek_mismatch"),
        ("db", changed_environment(db_fingerprints=("wrong",)), "db_mismatch"),
        ("dbx", changed_environment(dbx_fingerprints=("wrong",)), "dbx_mismatch"),
        ("ESP", changed_environment(esp_gpt_partuuid="wrong"), "esp_partuuid_mismatch"),
        ("UEFI device path", changed_environment(uefi_device_path="wrong"), "uefi_device_path_mismatch"),
    ):
        failed = verify_postboot(generation, authority, environment_variant, observation,
                                 expected_pk=("pk",), expected_kek=("kek",), expected_db=("db",), expected_dbx=("dbx",),
                                 minimum_release_sequence=42, current_security_epoch=3, **environment_expectations)
        check(f"{label} drift is never HEALTHY", not failed.trusted and reason in failed.failures)
    config_drift = replace(observation, config_bytes=config + b" ")
    failed = verify_postboot(generation, authority, environment, config_drift,
                             expected_pk=("pk",), expected_kek=("kek",), expected_db=("db",), expected_dbx=("dbx",),
                             minimum_release_sequence=42, current_security_epoch=3, **environment_expectations)
    check("one-byte Limine config drift is rejected", "limine_config_drift" in failed.failures)
    artifact_drift = replace(observation, artifact_bytes=artifacts | {generation.primary_kernel.identity: b"tampered"})
    failed = verify_postboot(generation, authority, environment, artifact_drift,
                             expected_pk=("pk",), expected_kek=("kek",), expected_db=("db",), expected_dbx=("dbx",),
                             minimum_release_sequence=42, current_security_epoch=3, **environment_expectations)
    check("kernel byte drift is rejected", any(item.startswith("artifact_drift:") for item in failed.failures))
    revoked = replace(observation, revoked_generation_ids=(generation.boot_generation_id,))
    failed = verify_postboot(generation, authority, environment, revoked,
                             expected_pk=("pk",), expected_kek=("kek",), expected_db=("db",), expected_dbx=("dbx",),
                             minimum_release_sequence=42, current_security_epoch=3, **environment_expectations)
    check("valid signatures never clear Guardian generation revocation", "boot_generation_revoked" in failed.failures)
    wrong_cmdline = replace(observation, authenticated_cmdline=b"init=/bin/sh")
    failed = verify_postboot(generation, authority, environment, wrong_cmdline,
                             expected_pk=("pk",), expected_kek=("kek",), expected_db=("db",), expected_dbx=("dbx",),
                             minimum_release_sequence=42, current_security_epoch=3, **environment_expectations)
    check("unauthenticated kernel command line is rejected", "authenticated_cmdline_mismatch" in failed.failures)
    recovery_hash = hashlib.blake2b(b"recovery-kernel", digest_size=64).hexdigest().encode()
    recovery_initramfs_hash = hashlib.blake2b(b"recovery-initramfs", digest_size=64).hexdigest().encode()
    recovery_config = (b"timeout: 5\n/Guardian Recovery\n protocol: linux\n path: boot():/recovery#" + recovery_hash
                       + b"\n module_path: boot():/recovery-initramfs#" + recovery_initramfs_hash + b"\n")
    recovery_loader_sha = generation.recovery_loader.artifact.digest("sha256", "maho-content-identity")
    recovery_path = "PciRoot/HD(1,GPT,...)/EFI/MahoOS/Recovery/limine.efi"
    recovery_environment = changed_environment(
        uefi_device_path=recovery_path,
        boot_entry=EfiEntry("Boot0008", "3" * 64, recovery_path),
        actual_efi_image=EfiExecutable("esp", "/EFI/MahoOS/Recovery/limine.efi",
                                      recovery_loader_sha.digest, SIGNER, True),
    )
    recovery_observation = replace(
        observation, loader_sha256=recovery_loader_sha.digest,
        embedded_config_checksum=generation.recovery_loader.embedded_config_checksum.digest,
        config_bytes=recovery_config, running_kernel_identity=generation.recovery_kernel.identity,
        limine_version=generation.recovery_loader.limine_version, boot_mode="recovery",
    )
    recovery_result = verify_postboot(
        generation, authority, recovery_environment, recovery_observation,
        expected_pk=("pk",), expected_kek=("kek",), expected_db=("db",), expected_dbx=("dbx",),
        minimum_release_sequence=42, current_security_epoch=3,
        expected_esp_partuuid=environment_expectations["expected_esp_partuuid"],
        expected_esp_filesystem_identity=environment_expectations["expected_esp_filesystem_identity"],
        expected_uefi_device_path=recovery_path, expected_boot_entry_name="Boot0008",
        expected_boot_mode="recovery",
    )
    check("separately signed recovery loader has an independent trusted proof", recovery_result.trusted)

    with tempfile.TemporaryDirectory(prefix="maho-esp-") as td:
        esp = Path(td)
        allowed = esp / "EFI/MahoOS/Normal/limine.efi"
        stale = esp / "EFI/backup/old.efi"
        allowed.parent.mkdir(parents=True)
        stale.parent.mkdir(parents=True)
        allowed.write_bytes(b"current")
        stale.write_bytes(b"stale")
        inventory = inventory_efi_executables({"esp": esp}, lambda path: (SIGNER, True))
        reasons = inventory_bypass_reasons(inventory, allowed={"/EFI/MahoOS/Normal/limine.efi": hashlib.sha256(b"current").hexdigest()}, trusted_signers=(SIGNER,))
        check("stale signed EFI backup is reported as a bypass", "unexpected_trusted_efi:/EFI/backup/old.efi" in reasons)

    print("ALL MAHO SIGNED BOOT AUTHORITY CONTRACTS PASS")


if __name__ == "__main__":
    main()
