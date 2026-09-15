#!/usr/bin/env python3
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))

from guardian_evidence import EvidenceFreshness, ProviderHealth  # noqa: E402
from guardian_signed_boot_provider import (  # noqa: E402
    PROOF_FILENAME,
    SignedBootTrust,
    observe_signed_boot,
)
from maho_secure_boot import BootEnvironmentIdentity, EfiEntry, EfiExecutable  # noqa: E402
from test_signed_boot_authority import PACKAGE, SIGNER, SOURCE, fixture  # noqa: E402

NOW = datetime(2026, 9, 15, 9, 15, tzinfo=timezone.utc)
BOOT_ID = "11111111-2222-3333-4444-555555555555"
UEFI_PATH = "PciRoot/HD(1,GPT,...)/EFI/MahoOS/Normal/limine.efi"
ESP_PARTUUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ESP_FS = "fat-1234"


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def environment_for(generation, *, secure_boot=True, setup_mode=False, esp_partuuid=ESP_PARTUUID):
    loader_sha = generation.normal_loader.artifact.digest("sha256", "maho-content-identity")
    assert loader_sha is not None
    return BootEnvironmentIdentity.create(
        esp_gpt_partuuid=esp_partuuid,
        esp_filesystem_identity=ESP_FS,
        uefi_device_path=UEFI_PATH,
        boot_entry=EfiEntry("Boot0001", "1" * 64, UEFI_PATH),
        secure_boot=secure_boot,
        setup_mode=setup_mode,
        audit_mode=False,
        deployed_mode=True,
        pk_fingerprints=("pk",),
        kek_fingerprints=("kek",),
        db_fingerprints=("db",),
        dbx_fingerprints=("dbx",),
        tpm_available=True,
        measured_boot_available=True,
        pcr_event_log_sha256="2" * 64,
        actual_efi_image=EfiExecutable(
            "esp",
            generation.normal_loader.artifact.path,
            loader_sha.digest,
            SIGNER,
            True,
        ),
        esp_candidates=(ESP_PARTUUID,),
        missing_evidence=(),
    )


def proof(*, observed_at=NOW, environment=None) -> dict:
    generation, authority, artifacts, config = fixture()
    environment = environment or environment_for(generation)
    loader_sha = generation.normal_loader.artifact.digest("sha256", "maho-content-identity")
    assert loader_sha is not None
    return {
        "schema_version": 1,
        "kind": "maho-signed-boot-postboot-proof",
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "boot_id": BOOT_ID,
        "boot_generation": generation.as_dict(),
        "boot_authority": authority.as_dict(),
        "boot_environment": environment.as_dict(),
        "postboot_observation": {
            "boot_generation_id": generation.boot_generation_id,
            "boot_authority_id": authority.boot_authority_id,
            "source_revision": SOURCE,
            "package_generation_id": PACKAGE,
            "candidate_root_identity": generation.candidate_root_identity,
            "release_sequence": authority.release_sequence,
            "security_epoch": authority.security_epoch,
            "loader_sha256": loader_sha.digest,
            "loader_signer_fingerprint": SIGNER,
            "embedded_config_checksum": generation.normal_loader.embedded_config_checksum.digest,
            "config_bytes_b64": b64(config),
            "artifact_bytes_b64": {identity: b64(content) for identity, content in artifacts.items()},
            "recovery_authority_identity": authority.recovery_authority_identity,
            "guardian_proof_successful": True,
            "revoked_generation_ids": [],
            "authenticated_cmdline_b64": b64(b"root=UUID=candidate lockdown=integrity module.sig_enforce=1"),
            "running_kernel_identity": generation.primary_kernel.identity,
            "limine_version": generation.normal_loader.limine_version,
            "boot_mode": "normal",
        },
        "verification": {
            "expected_pk": ["pk"],
            "expected_kek": ["kek"],
            "expected_db": ["db"],
            "expected_dbx": ["dbx"],
            "minimum_release_sequence": authority.release_sequence,
            "current_security_epoch": authority.security_epoch,
            "expected_esp_partuuid": ESP_PARTUUID,
            "expected_esp_filesystem_identity": ESP_FS,
            "expected_uefi_device_path": UEFI_PATH,
            "expected_boot_entry_name": "Boot0001",
            "expected_boot_mode": "normal",
            "revoked_authority_ids": [],
      },
    }


def boot_id_file(root: Path) -> Path:
    path = root / "proc/sys/kernel/random/boot_id"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(BOOT_ID + "\n", encoding="utf-8")
    return path


def observe(root: Path, payload: dict | None):
    bid = boot_id_file(root)
    proof_root = root / "signed-boot"
    proof_root.mkdir(parents=True, exist_ok=True)
    if payload is not None:
        (proof_root / PROOF_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
    return observe_signed_boot(proof_root, boot_id_path=bid, now=NOW)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        missing = observe(root / "missing", None)
        check("missing proof is UNKNOWN", missing.trust is SignedBootTrust.UNKNOWN)
        check("missing proof does not mean provider failure", missing.evidence.health is ProviderHealth.HEALTHY)
        check("missing proof has missing freshness", missing.evidence.freshness(now=NOW) is EvidenceFreshness.MISSING)

        stale_payload = proof(observed_at=NOW - timedelta(minutes=10))
        stale = observe(root / "stale", stale_payload)
        check("stale proof is UNKNOWN", stale.trust is SignedBootTrust.UNKNOWN)
        check("stale proof freshness is explicit", stale.evidence.freshness(now=NOW) is EvidenceFreshness.STALE)

        missing_component = proof()
        del missing_component["boot_generation"]
        missing_generation = observe(root / "missing-generation", missing_component)
        check("missing durable BootGeneration is UNKNOWN", missing_generation.trust is SignedBootTrust.UNKNOWN)

        malformed = proof()
        malformed["boot_generation"]["boot_generation_id"] = "bootgen-" + "0" * 64
        malformed_result = observe(root / "malformed", malformed)
        check("malformed exact identity is UNTRUSTED", malformed_result.trust is SignedBootTrust.UNTRUSTED)
        check("malformed proof keeps provider health separate", malformed_result.evidence.health is ProviderHealth.HEALTHY)

        wrong_generation = proof()
        wrong_generation["postboot_observation"]["boot_generation_id"] = "bootgen-" + "f" * 64
        result = observe(root / "wrong-generation", wrong_generation)
        check("wrong observed generation is UNTRUSTED", result.trust is SignedBootTrust.UNTRUSTED)

        wrong_authority = proof()
        wrong_authority["postboot_observation"]["boot_authority_id"] = "bootauth-" + "f" * 64
        result = observe(root / "wrong-authority", wrong_authority)
        check("wrong observed authority is UNTRUSTED", result.trust is SignedBootTrust.UNTRUSTED)

        generation, _, _, _ = fixture()
        wrong_environment = proof(environment=environment_for(generation, esp_partuuid="ffffffff-eeee-dddd-cccc-bbbbbbbbbbbb"))
        result = observe(root / "wrong-environment", wrong_environment)
        check("wrong exact environment is UNTRUSTED", result.trust is SignedBootTrust.UNTRUSTED)

        rollback = proof()
        rollback["verification"]["minimum_release_sequence"] += 1
        result = observe(root / "rollback", rollback)
        check("release sequence rollback is UNTRUSTED", result.trust is SignedBootTrust.UNTRUSTED)
        check("release sequence is surfaced", result.evidence.data["release_sequence"] == rollback["boot_authority"]["release_sequence"])

        wrong_epoch = proof()
        wrong_epoch["verification"]["current_security_epoch"] += 1
        result = observe(root / "wrong-epoch", wrong_epoch)
        check("security epoch mismatch is UNTRUSTED", result.trust is SignedBootTrust.UNTRUSTED)
        check("security epoch is surfaced", result.evidence.data["security_epoch"] == wrong_epoch["boot_authority"]["security_epoch"])

        secure_off = proof(environment=environment_for(generation, secure_boot=False))
        result = observe(root / "secure-off", secure_off)
        check("Secure Boot off is never VERIFIED", result.trust is SignedBootTrust.UNTRUSTED)

        setup_on = proof(environment=environment_for(generation, setup_mode=True))
        result = observe(root / "setup-on", setup_on)
        check("SetupMode on is never VERIFIED", result.trust is SignedBootTrust.UNTRUSTED)

        verifier_failure = proof()
        artifact_id = next(iter(verifier_failure["postboot_observation"]["artifact_bytes_b64"]))
        verifier_failure["postboot_observation"]["artifact_bytes_b64"][artifact_id] = b64(b"tampered")
        result = observe(root / "verifier-failure", verifier_failure)
        check("real verifier failure is UNTRUSTED", result.trust is SignedBootTrust.UNTRUSTED)
        check("verifier failures are preserved", bool(result.evidence.data.get("verifier", {}).get("failures")))

        verified = observe(root / "verified", proof())
        check("complete proof is VERIFIED only through real verifier", verified.trust is SignedBootTrust.VERIFIED)
        check("verified provider is healthy", verified.evidence.health is ProviderHealth.HEALTHY)
        check("exact BootGeneration identity is surfaced", verified.evidence.data["boot_generation_id"].startswith("bootgen-"))
        check("exact BootAuthority identity is surfaced", verified.evidence.data["boot_authority_id"].startswith("bootauth-"))
        check("exact BootEnvironmentIdentity is surfaced", verified.evidence.data["boot_environment_id"].startswith("bootenv-"))

        failure_root = root / "provider-failure"
        bid = boot_id_file(failure_root)
        broken_root = failure_root / "signed-boot"
        broken_root.mkdir(parents=True)
        (broken_root / PROOF_FILENAME).mkdir()
        provider_failure = observe_signed_boot(broken_root, boot_id_path=bid, now=NOW)
        check("provider failure reports FAILED health", provider_failure.evidence.health is ProviderHealth.FAILED)
        check("provider failure does not invent UNTRUSTED trust", provider_failure.trust is SignedBootTrust.UNKNOWN)
        check("trust failure can coexist with healthy provider", malformed_result.evidence.health is ProviderHealth.HEALTHY and malformed_result.trust is SignedBootTrust.UNTRUSTED)

    print("ALL GUARDIAN SIGNED BOOT PROVIDER TESTS PASS")


if __name__ == "__main__":
    main()
