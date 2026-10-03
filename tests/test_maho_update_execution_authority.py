#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_update_execution_authority import (  # noqa: E402
    ACTIVATION_TTL,
    EXECUTION_TTL,
    consume_activation_handoff,
    read_activation_handoff_consumption,
    consume_execution_authority,
    issue_activation_handoff,
    issue_execution_authority,
    parse_activation_handoff,
    parse_execution_authority,
    verify_activation_handoff,
    verify_execution_authority,
)
from maho_update_state import UpdateState, create_transaction, transition_transaction  # noqa: E402

NOW = datetime(2026, 9, 27, 8, 0, tzinfo=timezone.utc)
TXID = "upd-20260927T080000Z-abcdefabcdef"
REV = "a" * 40
CURRENT_SYSTEM = "gen-" + "1" * 64
CURRENT_KERNEL = "kgen-" + "2" * 64
CANDIDATE_SYSTEM = "gen-" + "3" * 64
CANDIDATE_KERNEL = "kgen-" + "4" * 64
PARENT_UUID = "11111111-1111-1111-1111-111111111111"
CANDIDATE_UUID = "22222222-2222-2222-2222-222222222222"


def transaction() -> dict:
    tx = create_transaction(
        transaction_id=TXID,
        source_revision=REV,
        packages=[{
            "name": "demo",
            "installed_version": "1",
            "candidate_version": "2",
            "repository": "core",
            "download_size": 123,
            "installed_size": 456,
            "security_relevant": False,
            "roles": [],
        }],
        activation_requirements=[],
        recovery_generation_id=None,
        now=NOW,
    )
    for state in (UpdateState.STAGED, UpdateState.PREPARED, UpdateState.MAINTENANCE_READY):
        tx = transition_transaction(tx, state, now=NOW)
    return tx


def manifest() -> dict:
    return {
        "payloads": [{
            "name": "demo",
            "sha256": "5" * 64,
        }],
    }


def target() -> dict[str, str]:
    return {
        "name": "@maho-update-candidate-abcdefabcdef",
        "uuid": CANDIDATE_UUID,
        "filesystem_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "parent_root_uuid": PARENT_UUID,
    }


def recovery() -> dict:
    return {
        "ready": True,
        "kind": "normal-known-good-current-generation",
        "current_system_generation_id": CURRENT_SYSTEM,
        "current_kernel_generation_id": CURRENT_KERNEL,
    }


def maintenance() -> dict:
    return {
        "safe": True,
        "snapshot_id": "sit-fixture",
        "captured_at": "2026-09-27T08:00:00Z",
    }


def executor() -> dict:
    return {
        "interpreter": "/usr/bin/python3.13",
        "campaign_root": f"/usr/lib/maho/update-campaign/{REV}",
        "source_revision": REV,
        "modules": {
            "maho_update_automatic_execution.py": "6" * 64,
            "maho_update_normal_host.py": "7" * 64,
        },
    }


def issue():
    return issue_execution_authority(
        transaction(),
        manifest(),
        current_system_generation_id=CURRENT_SYSTEM,
        current_kernel_generation_id=CURRENT_KERNEL,
        execution_mode="normal-candidate",
        effects=("ordinary-files-in-place",),
        activation_requirements=(),
        candidate_target=target(),
        recovery_evidence=recovery(),
        maintenance_evidence=maintenance(),
        executor=executor(),
        now=NOW,
    )


class ExecutionAuthorityContracts(unittest.TestCase):
    def test_execution_authority_is_closed_content_addressed_and_roundtrips(self):
        authority = issue()
        parsed = parse_execution_authority(authority.as_dict())
        self.assertEqual(parsed, authority)
        self.assertTrue(authority.authority_id.startswith("art-"))
        self.assertEqual(authority.transaction_id, TXID)
        self.assertEqual(authority.current_system_generation_id, CURRENT_SYSTEM)
        self.assertEqual(authority.current_kernel_generation_id, CURRENT_KERNEL)
        self.assertEqual(authority.execution_mode, "normal-candidate")
        self.assertEqual(authority.packages[0]["sha256"], "5" * 64)

    def test_exact_authority_verifies_only_inside_bounded_ttl(self):
        authority = issue()
        verified = verify_execution_authority(
            authority.as_dict(),
            transaction(),
            manifest(),
            current_system_generation_id=CURRENT_SYSTEM,
            current_kernel_generation_id=CURRENT_KERNEL,
            execution_mode="normal-candidate",
            effects=("ordinary-files-in-place",),
            activation_requirements=(),
            candidate_target=target(),
            recovery_evidence=recovery(),
            maintenance_evidence=maintenance(),
            executor=executor(),
            now=NOW + EXECUTION_TTL - timedelta(seconds=1),
        )
        self.assertEqual(verified.authority_id, authority.authority_id)
        with self.assertRaisesRegex(ValueError, "expired"):
            verify_execution_authority(
                authority.as_dict(),
                transaction(),
                manifest(),
                current_system_generation_id=CURRENT_SYSTEM,
                current_kernel_generation_id=CURRENT_KERNEL,
                execution_mode="normal-candidate",
                effects=("ordinary-files-in-place",),
                activation_requirements=(),
                candidate_target=target(),
                recovery_evidence=recovery(),
                maintenance_evidence=maintenance(),
                executor=executor(),
                now=NOW + EXECUTION_TTL + timedelta(seconds=1),
            )

    def test_wrong_transaction_package_source_and_current_generation_fail_closed(self):
        authority = issue().as_dict()
        cases = []

        wrong_tx = transaction()
        wrong_tx["transaction_id"] = "upd-20260927T080001Z-bbbbbbbbbbbb"
        wrong_tx["history"] = [
            dict(event, **({"transaction_id": wrong_tx["transaction_id"]} if "transaction_id" in event else {}))
            for event in wrong_tx["history"]
        ]
        # validate_transaction derives no transaction ID into history, so direct field drift is sufficient.
        cases.append(("transaction", wrong_tx, CURRENT_SYSTEM, CURRENT_KERNEL, manifest(), target(), executor()))

        wrong_pkg = transaction()
        wrong_pkg["package_generation"] = dict(wrong_pkg["package_generation"])
        wrong_pkg["package_generation"]["id"] = "pkg-" + "9" * 64
        cases.append(("package", wrong_pkg, CURRENT_SYSTEM, CURRENT_KERNEL, manifest(), target(), executor()))

        wrong_source = transaction()
        wrong_source["source_revision"] = "b" * 40
        cases.append(("source", wrong_source, CURRENT_SYSTEM, CURRENT_KERNEL, manifest(), target(), executor()))

        cases.append(("system", transaction(), "gen-" + "8" * 64, CURRENT_KERNEL, manifest(), target(), executor()))
        cases.append(("kernel", transaction(), CURRENT_SYSTEM, "kgen-" + "8" * 64, manifest(), target(), executor()))

        for label, tx, system_id, kernel_id, mf, target_value, exec_value in cases:
            with self.subTest(label=label):
                with self.assertRaises((ValueError, AssertionError)):
                    verify_execution_authority(
                        authority,
                        tx,
                        mf,
                        current_system_generation_id=system_id,
                        current_kernel_generation_id=kernel_id,
                        execution_mode="normal-candidate",
                        effects=("ordinary-files-in-place",),
                        activation_requirements=(),
                        candidate_target=target_value,
                        recovery_evidence=recovery(),
                        maintenance_evidence=maintenance(),
                        executor=exec_value,
                        now=NOW,
                    )

    def test_altered_package_set_candidate_and_executor_fail_closed(self):
        authority = issue().as_dict()

        altered_manifest = manifest()
        altered_manifest["payloads"][0]["sha256"] = "8" * 64
        wrong_target = target()
        wrong_target["parent_root_uuid"] = "33333333-3333-3333-3333-333333333333"
        wrong_executor = executor()
        wrong_executor["modules"] = dict(wrong_executor["modules"])
        wrong_executor["modules"]["maho_update_normal_host.py"] = "8" * 64

        for label, mf, target_value, exec_value in (
            ("package", altered_manifest, target(), executor()),
            ("candidate", manifest(), wrong_target, executor()),
            ("executor", manifest(), target(), wrong_executor),
        ):
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    verify_execution_authority(
                        authority,
                        transaction(),
                        mf,
                        current_system_generation_id=CURRENT_SYSTEM,
                        current_kernel_generation_id=CURRENT_KERNEL,
                        execution_mode="normal-candidate",
                        effects=("ordinary-files-in-place",),
                        activation_requirements=(),
                        candidate_target=target_value,
                        recovery_evidence=recovery(),
                        maintenance_evidence=maintenance(),
                        executor=exec_value,
                        now=NOW,
                    )

    def test_authority_consumption_is_one_shot_and_binds_actual_candidate(self):
        authority = issue()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = consume_execution_authority(
                root,
                authority,
                candidate_uuid=CANDIDATE_UUID,
                candidate_root_identity="root-sha256:candidate",
                now=NOW,
            )
            self.assertEqual(first["authority_id"], authority.authority_id)
            self.assertEqual(first["candidate_uuid"], CANDIDATE_UUID)
            with self.assertRaisesRegex(ValueError, "already consumed"):
                consume_execution_authority(
                    root,
                    authority,
                    candidate_uuid=CANDIDATE_UUID,
                    candidate_root_identity="root-sha256:candidate",
                    now=NOW,
                )

    def test_tampering_breaks_execution_authority_identity(self):
        value = issue().as_dict()
        value["effects"] = ["service-state"]
        with self.assertRaises(ValueError):
            parse_execution_authority(value)

    def pending_transaction(self) -> dict:
        tx = transaction()
        return transition_transaction(tx, UpdateState.INSTALLING, now=NOW)

    def test_activation_handoff_roundtrips_and_is_expiring(self):
        installing = self.pending_transaction()
        pending = transition_transaction(installing, UpdateState.INSTALLED_PENDING_ACTIVATION, now=NOW)
        handoff = issue_activation_handoff(
            pending,
            current_system_generation_id=CURRENT_SYSTEM,
            candidate_system_generation_id=CANDIDATE_SYSTEM,
            candidate_kernel_generation_id=CANDIDATE_KERNEL,
            candidate_uuid=CANDIDATE_UUID,
            previous_root_uuid=PARENT_UUID,
            activation_authority={"authority_id": "art-" + "a" * 64},
            recovery_evidence={"ready": True, "generation_id": "g3-fixture"},
            candidate_boot_identity={"unchanged": True},
            reboot_required=True,
            reboot_reason="candidate root activation requires restart",
            now=NOW,
        )
        self.assertEqual(parse_activation_handoff(handoff.as_dict()), handoff)
        verified = verify_activation_handoff(
            handoff.as_dict(), pending,
            current_system_generation_id=CURRENT_SYSTEM,
            now=NOW + ACTIVATION_TTL - timedelta(seconds=1),
        )
        self.assertEqual(verified.handoff_id, handoff.handoff_id)
        with self.assertRaisesRegex(ValueError, "expired"):
            verify_activation_handoff(
                handoff.as_dict(), pending,
                current_system_generation_id=CURRENT_SYSTEM,
                now=NOW + ACTIVATION_TTL + timedelta(seconds=1),
            )

    def test_activation_handoff_rejects_wrong_current_generation_and_replay(self):
        installing = self.pending_transaction()
        pending = transition_transaction(installing, UpdateState.INSTALLED_PENDING_ACTIVATION, now=NOW)
        handoff = issue_activation_handoff(
            pending,
            current_system_generation_id=CURRENT_SYSTEM,
            candidate_system_generation_id=CANDIDATE_SYSTEM,
            candidate_kernel_generation_id=CANDIDATE_KERNEL,
            candidate_uuid=CANDIDATE_UUID,
            previous_root_uuid=PARENT_UUID,
            activation_authority={"authority_id": "art-" + "a" * 64},
            recovery_evidence={"ready": True},
            candidate_boot_identity={"unchanged": True},
            reboot_required=True,
            reboot_reason="restart required",
            now=NOW,
        )
        with self.assertRaisesRegex(ValueError, "binding"):
            verify_activation_handoff(
                handoff.as_dict(), pending,
                current_system_generation_id="gen-" + "f" * 64,
                now=NOW,
            )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = consume_activation_handoff(
                root,
                handoff,
                activation_evidence={
                    "candidate_uuid": CANDIDATE_UUID,
                    "previous_root_uuid": PARENT_UUID,
                    "boot_sha256": {},
                    "boot_unchanged": True,
                    "package_manager_invoked": False,
                    "reboot_performed": False,
                    "firmware_mutated": False,
                },
                now=NOW,
            )
            self.assertEqual(first["handoff_id"], handoff.handoff_id)
            self.assertEqual(
                read_activation_handoff_consumption(root, handoff)["candidate_uuid"],
                CANDIDATE_UUID,
            )
            with self.assertRaisesRegex(ValueError, "already consumed"):
                consume_activation_handoff(
                    root,
                    handoff,
                    activation_evidence=first["activation_evidence"],
                    now=NOW,
                )

            path = root / "activation-handoffs" / "consumed" / f"{handoff.handoff_id}.json"
            tampered = json.loads(path.read_text())
            tampered["candidate_uuid"] = PARENT_UUID
            path.write_text(json.dumps(tampered))
            with self.assertRaisesRegex(ValueError, "consumption.*binding"):
                read_activation_handoff_consumption(root, handoff)

    def test_activation_receipt_may_be_persisted_after_handoff_expiry(self):
        installing = self.pending_transaction()
        pending = transition_transaction(
            installing, UpdateState.INSTALLED_PENDING_ACTIVATION, now=NOW,
        )
        handoff = issue_activation_handoff(
            pending,
            current_system_generation_id=CURRENT_SYSTEM,
            candidate_system_generation_id=CANDIDATE_SYSTEM,
            candidate_kernel_generation_id=CANDIDATE_KERNEL,
            candidate_uuid=CANDIDATE_UUID,
            previous_root_uuid=PARENT_UUID,
            activation_authority={"authority_id": "art-" + "a" * 64},
            recovery_evidence={"ready": True},
            candidate_boot_identity={"unchanged": True},
            reboot_required=True,
            reboot_reason="restart required",
            now=NOW,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = consume_activation_handoff(
                root,
                handoff,
                activation_evidence={
                    "candidate_uuid": CANDIDATE_UUID,
                    "previous_root_uuid": PARENT_UUID,
                    "boot_sha256": {},
                    "boot_unchanged": True,
                    "package_manager_invoked": False,
                    "reboot_performed": False,
                    "firmware_mutated": False,
                    "reconciled_after_interruption": True,
                },
                now=NOW + ACTIVATION_TTL + timedelta(days=1),
            )
            self.assertEqual(
                read_activation_handoff_consumption(root, handoff),
                receipt,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
