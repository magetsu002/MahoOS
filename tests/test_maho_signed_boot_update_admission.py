#!/usr/bin/env python3
"""Agent 4 handoff contracts: no updater, signer, firmware or TPM writes."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from maho_boot_authority import BootGeneration, BootAuthority, BootContractError  # noqa: E402
from maho_signed_boot_update_admission import (  # noqa: E402
    CandidateLoaderReceipt, evaluate_signed_boot_update_admission,
)
from test_signed_boot_authority import fixture  # noqa: E402


def boot_fixture():
    current, authority, _, _ = fixture()
    source = {k: v for k, v in current.__dict__.items()
              if k not in {"boot_generation_id", "schema_version"}}
    candidate = BootGeneration.create(**(source | {
        "candidate_root_identity": "candidate-root-sha256:" + "f" * 64,
    }))
    authority_values = {k: v for k, v in authority.__dict__.items()
                        if k not in {"boot_authority_id", "schema_version"}}
    candidate_authority = BootAuthority.create(**(authority_values | {
        "permitted_boot_generation_id": candidate.boot_generation_id,
        "release_sequence": authority.release_sequence + 1,
    }))
    cert = candidate_authority.device_signing_certificate_fingerprint
    def receipt(role, loader):
        return CandidateLoaderReceipt(
            boot_generation_id=candidate.boot_generation_id, role=role,
            loader_artifact_sha256=loader.artifact.digest(
                "sha256", "maho-content-identity").digest,
            signing_certificate_fingerprint=cert,
            enrolled_config_blake2b=loader.embedded_config_checksum.digest,
            signature_cryptographically_verified=True,
            authorized_by_firmware_db=True,
            config_integrity_verified=True,
            resource_integrity_verified=True,
        )
    tokens = {
        (current.boot_generation_id, "normal"): True,
        (candidate.boot_generation_id, "normal"): True,
        (candidate.boot_generation_id, "fallback"): True,
        (candidate.boot_generation_id, "recovery"): True,
    }
    return dict(
        current=current, candidate=candidate, current_authority=authority,
        candidate_authority=candidate_authority,
        environment=SimpleNamespace(
            secure_boot=True, setup_mode=False,
            db_fingerprints=("x509-sha256:" + cert,),
            dbx_fingerprints=(),
        ),
        current_postboot=SimpleNamespace(trusted=True, state="HEALTHY"),
        normal=receipt("normal", candidate.normal_loader),
        recovery=receipt("recovery", candidate.recovery_loader),
        signer_continuity_verified=True, previous_signed_chain_retained=True,
        windows_efi_trust_preserved=True, firmware_boot_variables_unchanged=True,
        manual_luks_recovery_tested=True, tpm_token_confirmed=tokens,
    )


class UpdateAdmissionContracts(unittest.TestCase):
    def blocked(self, reason, **overrides):
        case = boot_fixture() | overrides
        result = evaluate_signed_boot_update_admission(**case)
        self.assertFalse(result.admitted_for_agent4_publication)
        self.assertTrue(any(item == reason or item.startswith(reason + ":")
                            for item in result.blockers), (reason, result.blockers))
        self.assertFalse(result.as_dict()["firmware_mutation_authorized"])
        self.assertFalse(result.as_dict()["luks_slot_mutation_authorized"])

    def test_exact_complete_evidence_is_source_admitted(self):
        result = evaluate_signed_boot_update_admission(**boot_fixture())
        self.assertTrue(result.admitted_for_agent4_publication, result.blockers)
        self.assertFalse(result.as_dict()["boot_reboot_authorized"])
        self.assertEqual(result.as_dict()["status"], "ADMITTED")

    def test_missing_critical_evidence_denied(self):
        base = boot_fixture()
        cases = (
            ("physical_secure_boot_not_active", {"environment": replace_ns(base["environment"], secure_boot=False)}),
            ("current_known_good_signed_boot_unproven", {"current_postboot": replace_ns(base["current_postboot"], trusted=False)}),
            ("signer_continuity_unverified", {"signer_continuity_verified": False}),
            ("previous_signed_recovery_not_retained", {"previous_signed_chain_retained": False}),
            ("windows_efi_trust_not_proven_preserved", {"windows_efi_trust_preserved": False}),
            ("firmware_boot_variables_changed", {"firmware_boot_variables_unchanged": False}),
            ("manual_luks_recovery_not_tested", {"manual_luks_recovery_tested": False}),
            ("normal_efi_signature_unverified", {"normal": replace(base["normal"], signature_cryptographically_verified=False)}),
            ("recovery_enrolled_config_unverified", {"recovery": replace(base["recovery"], config_integrity_verified=False)}),
            ("recovery_firmware_signature_authorization_missing", {"recovery": replace(base["recovery"], authorized_by_firmware_db=False)}),
            ("normal_resource_integrity_unverified", {"normal": replace(base["normal"], resource_integrity_verified=False)}),
            ("normal_sealed_loader_identity_mismatch", {"normal": replace(base["normal"], loader_artifact_sha256="b" * 64)}),
            ("normal_sealed_loader_identity_mismatch", {"normal": replace(base["normal"], enrolled_config_blake2b="c" * 128)}),
            ("signer_not_pinned_in_firmware_db", {"environment": replace_ns(base["environment"], db_fingerprints=())}),
            ("firmware_revocation_inventory_unknown", {"environment": replace_ns(base["environment"], dbx_fingerprints=None)}),
            ("signer_revoked_in_firmware_dbx", {"environment": replace_ns(base["environment"], dbx_fingerprints=base["environment"].db_fingerprints)}),
            ("tpm_unlock_unproven:fallback", {"tpm_token_confirmed": {
                k: v for k, v in base["tpm_token_confirmed"].items() if k[1] != "fallback"
            }}),
        )
        for index, (reason, changes) in enumerate(cases):
            with self.subTest(index=index, reason=reason):
                self.blocked(reason, **changes)

    def test_stale_authority_and_key_rotation_denied(self):
        base = boot_fixture()
        authority = base["candidate_authority"]
        values = {k: v for k, v in authority.__dict__.items()
                  if k not in {"boot_authority_id", "schema_version"}}
        self.blocked("candidate_release_sequence_not_monotonic",
                     candidate_authority=BootAuthority.create(**(
                         values | {"release_sequence": base["current_authority"].release_sequence})))
        self.blocked("signing_key_rotation_requires_separate_ceremony",
                     candidate_authority=BootAuthority.create(**(
                         values | {"device_signing_certificate_fingerprint": "F" * 64})))

    def test_types_are_not_optional(self):
        with self.assertRaisesRegex(BootContractError, "generation_type_invalid"):
            evaluate_signed_boot_update_admission(**(boot_fixture() | {"candidate": SimpleNamespace()}))


def replace_ns(value, **changes):
    return SimpleNamespace(**(vars(value) | changes))


if __name__ == "__main__":
    unittest.main(verbosity=2)
