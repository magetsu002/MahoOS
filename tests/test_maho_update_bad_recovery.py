#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import guardian_bad_update_recovery as guardian  # noqa: E402
import maho_update_bad_recovery as recovery  # noqa: E402
from maho_update_execution_authority import (  # noqa: E402
    consume_activation_handoff, handoff_consumption_path, issue_activation_handoff,
)
from maho_update_native import NativeBtrfsOps  # noqa: E402
from maho_update_state import (  # noqa: E402
    UpdateState, create_transaction, publish_transaction, read_transaction,
    transaction_path, transition_transaction,
)


NOW = datetime(2026, 10, 2, 18, 0, tzinfo=timezone.utc)
TXID = "upd-20261002T180000Z-abcdefabcdef"
OTHER_TXID = "upd-20261002T180001Z-fedcbafedcba"
REV = "a" * 40
FAILED_UUID = "22222222-2222-2222-2222-222222222222"
PREVIOUS_UUID = "11111111-1111-1111-1111-111111111111"
FILESYSTEM_UUID = "33333333-3333-3333-3333-333333333333"
FAILED_SYSTEM = "gen-" + "4" * 64
PREVIOUS_SYSTEM = "gen-" + "1" * 64
KERNEL = "kgen-" + "2" * 64
BOOT = {
    "/boot/intel-ucode.img": "5" * 64,
    "/boot/initramfs-linux-cachyos-lts.img": "6" * 64,
    "/boot/initramfs-linux-cachyos.img": "7" * 64,
    "/boot/vmlinuz-linux-cachyos": "8" * 64,
    "/boot/vmlinuz-linux-cachyos-lts": "9" * 64,
}
EXECUTOR = {
    "executor_id": "art-" + "e" * 64,
    "campaign_root": "/usr/lib/maho/update-campaign/" + REV,
    "interpreter": "/usr/bin/python3",
    "modules": {
        "maho_update_bad_recovery.py": "a" * 64,
        "guardian_bad_update_recovery.py": "b" * 64,
        "maho_update_native.py": "c" * 64,
    },
}


def pending_transaction(transaction_id: str = TXID) -> dict:
    tx = create_transaction(
        transaction_id=transaction_id, source_revision=REV,
        packages=[{
            "name": "demo", "installed_version": "1", "candidate_version": "2",
            "repository": "core", "download_size": 1, "installed_size": 1,
            "security_relevant": False, "roles": [],
        }],
        activation_requirements=[], recovery_generation_id=None, now=NOW,
    )
    tx = transition_transaction(tx, UpdateState.STAGED, now=NOW)
    tx = transition_transaction(tx, UpdateState.PREPARED, now=NOW)
    tx = transition_transaction(tx, UpdateState.MAINTENANCE_READY, now=NOW)
    tx = transition_transaction(tx, UpdateState.INSTALLING, now=NOW)
    return transition_transaction(tx, UpdateState.INSTALLED_PENDING_ACTIVATION, now=NOW)


def provider(**overrides) -> dict:
    value = {
        "schema_version": 1,
        "kind": "maho-update-postboot-failure",
        "observed_at": recovery._stamp(NOW),
        "current": True,
        "transaction_id": TXID,
        "source_revision": REV,
        "filesystem_uuid": FILESYSTEM_UUID,
        "failed_candidate_uuid": FAILED_UUID,
        "failed_system_generation_id": FAILED_SYSTEM,
        "previous_root_uuid": PREVIOUS_UUID,
        "previous_system_generation_id": PREVIOUS_SYSTEM,
        "current_kernel_generation_id": KERNEL,
        "candidate_kernel_generation_id": KERNEL,
        "root_topology": "ARMED",
        "recovery_artifacts_intact": True,
        "failure_code": "controlled_postboot_failure",
        "postboot_verification_succeeded": False,
    }
    value.update(overrides)
    return value


def live_context():
    return (
        {
            "system_generation_id": PREVIOUS_SYSTEM,
            "kernel_generation_id": KERNEL,
            "root_subvolume_uuid": PREVIOUS_UUID,
            "filesystem_uuid": FILESYSTEM_UUID,
        },
        SimpleNamespace(
            generation_id=PREVIOUS_SYSTEM,
            root_identity=SimpleNamespace(
                snapshot_identity=f"btrfs-uuid:{PREVIOUS_UUID}",
                filesystem_identity=f"uuid:{FILESYSTEM_UUID}",
                root_manifest_sha256="f" * 64,
            ),
        ),
        SimpleNamespace(
            kernel_generation_id=KERNEL, kernel_abi="6.1-cachyos",
            modules_abi="6.1-cachyos",
        ),
    )


class FakeBtrfs:
    topology = "ARMED"
    live_uuid = FAILED_UUID
    recovered_state_path: Path | None = None
    arm_calls = 0
    make_calls = 0
    fail_arm = False

    def __init__(self, transaction_id: str):
        self.transaction_id = transaction_id

    def normal_recovery_topology(self, **_kwargs):
        return self.topology

    def root_identity(self):
        return SimpleNamespace(
            subvolume_uuid=self.live_uuid,
            filesystem_uuid=FILESYSTEM_UUID,
            fsroot="/@",
        )

    def live_boot_hashes(self):
        return dict(BOOT)

    def arm_root_recovery(self, **kwargs):
        type(self).arm_calls += 1
        assert type(self).recovered_state_path is not None
        assert (type(self).recovered_state_path / "transactions" / f"{TXID}.json").is_file()
        assert recovery.recovery_record_path(type(self).recovered_state_path, TXID).is_file()
        assert recovery.authority_path(type(self).recovered_state_path, TXID).is_file()
        if type(self).fail_arm:
            type(self).topology = "RECOVERY_EXCHANGED_PENDING_FREEZE"
            raise RuntimeError("injected interruption after root exchange")
        self.topology = "RECOVERY_ARMED"
        return {
            "failed_candidate_uuid": kwargs["expected_failed_uuid"],
            "previous_root_uuid": kwargs["expected_previous_uuid"],
            "filesystem_uuid": kwargs["expected_filesystem_uuid"],
            "failed_root_name": "@maho-update-backup-abcdefabcdef",
            "root_exchange_completed": True,
            "failed_root_read_only": True,
            "selected_root_writable": True,
            "boot_sha256": dict(BOOT),
            "package_manager_invoked": False,
            "firmware_mutated": False,
            "home_mutated": False,
            "reboot_performed": False,
            "reboot_required": True,
        }

    def recovered_state_root(self, **_kwargs):
        assert type(self).recovered_state_path is not None
        return type(self).recovered_state_path

    def selected_state_root_for_recovery(self, **_kwargs):
        assert type(self).recovered_state_path is not None
        return type(self).recovered_state_path

    def previous_state_root_for_recovery(self, **_kwargs):
        assert type(self).recovered_state_path is not None
        return type(self).recovered_state_path

    def make_recovery_target_writable(self, **_kwargs):
        type(self).make_calls += 1
        type(self).topology = "TARGET_MUTABLE"
        assert type(self).recovered_state_path is not None
        return type(self).recovered_state_path

    def previous_generation_root_for_recovery(self, **_kwargs):
        assert type(self).generation_path is not None
        return type(self).generation_path

    def selected_generation_root_for_recovery(self, **_kwargs):
        assert type(self).generation_path is not None
        return type(self).generation_path

    def close(self):
        pass


class BadUpdateRecoveryContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.state = self.base / "failed/var/lib/maho/update"
        self.recovered = self.base / "previous/var/lib/maho/update"
        self.generations = self.base / "generations"
        self.state.mkdir(parents=True)
        self.recovered.mkdir(parents=True)
        self.generations.mkdir(parents=True)
        FakeBtrfs.topology = "ARMED"
        FakeBtrfs.live_uuid = FAILED_UUID
        FakeBtrfs.recovered_state_path = self.recovered
        FakeBtrfs.generation_path = self.generations
        FakeBtrfs.arm_calls = 0
        FakeBtrfs.make_calls = 0
        FakeBtrfs.fail_arm = False
        self.tx = pending_transaction()
        publish_transaction(self.state, self.tx)
        self.authority_stub = {
            "authority_id": "art-" + "d" * 64,
            "graph_id": "art-" + "c" * 64,
        }
        self.handoff = issue_activation_handoff(
            self.tx,
            current_system_generation_id=PREVIOUS_SYSTEM,
            candidate_system_generation_id=FAILED_SYSTEM,
            candidate_kernel_generation_id=KERNEL,
            candidate_uuid=FAILED_UUID,
            previous_root_uuid=PREVIOUS_UUID,
            activation_authority=self.authority_stub,
            recovery_evidence={"ready": True},
            candidate_boot_identity={"unchanged": True, "sha256": dict(BOOT)},
            reboot_required=True, reboot_reason="explicit restart required", now=NOW,
        )
        activation = {
            "candidate_uuid": FAILED_UUID,
            "previous_root_uuid": PREVIOUS_UUID,
            "previous_root_name": "@maho-update-backup-abcdefabcdef",
            "boot_sha256": dict(BOOT),
            "boot_unchanged": True,
            "package_manager_invoked": False,
            "reboot_performed": False,
            "firmware_mutated": False,
        }
        activation_consumption = consume_activation_handoff(
            self.state, self.handoff, activation_evidence=activation, now=NOW,
        )
        self.record = {
            "schema_version": 1,
            "kind": "maho-automatic-normal-execution",
            "transaction_id": TXID,
            "source_revision": REV,
            "phase": "ACTIVATION_ARMED",
            "candidate": {
                "uuid": FAILED_UUID,
                "parent_root_uuid": PREVIOUS_UUID,
                "filesystem_uuid": FILESYSTEM_UUID,
            },
            "candidate_generation": {
                "system_generation_id": FAILED_SYSTEM,
                "kernel_generation_id": KERNEL,
                "parent_system_generation_id": PREVIOUS_SYSTEM,
            },
            "activation_handoff": self.handoff.as_dict(),
            "activation": activation,
            "handoff_consumption": activation_consumption,
        }
        recovery._atomic_json(recovery.recovery_record_path(self.state, TXID), self.record)
        self._compatibility()

    def tearDown(self):
        self.tmp.cleanup()

    def _begin(self):
        with patch.object(recovery, "NativeBtrfsOps", FakeBtrfs), \
             patch.object(recovery, "load_current_verified_generations", return_value=live_context()):
            return recovery.begin_bad_update_recovery(
                TXID, failure_code="controlled_postboot_failure",
                failure_detail="injected package mismatch", state_root=self.state,
                generation_root=self.generations, executor=EXECUTOR, now=NOW,
            )

    def _compatibility(self):
        path = self.generations / "evidence/compatibility" / f"{PREVIOUS_SYSTEM}--{KERNEL}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "system_generation_id": PREVIOUS_SYSTEM,
            "kernel_generation_id": KERNEL,
            "root_manifest_sha256": "f" * 64,
            "filesystem_identity": f"uuid:{FILESYSTEM_UUID}",
            "kernel_abi": "6.1-cachyos",
            "modules_abi": "6.1-cachyos",
            "independently_verified": True,
        }))

    def test_guardian_selects_only_exact_current_previous_generation(self):
        decision = guardian.select_exact_previous_generation(provider(), now=NOW)
        self.assertEqual(decision["outcome"], "RECOVER_EXACT_PREVIOUS")
        self.assertEqual(decision["selected_root_uuid"], PREVIOUS_UUID)
        self.assertEqual(decision["selected_system_generation_id"], PREVIOUS_SYSTEM)
        self.assertEqual(decision["recovery_scope"], "exact-previous-system-root")

    def test_stale_historical_missing_and_kernel_mismatch_never_promote_trust(self):
        cases = (
            provider(observed_at=recovery._stamp(NOW - timedelta(minutes=6))),
            provider(current=False),
            provider(recovery_artifacts_intact=False),
            provider(candidate_kernel_generation_id="kgen-" + "9" * 64),
        )
        for evidence in cases:
            with self.subTest(evidence=evidence):
                decision = guardian.select_exact_previous_generation(evidence, now=NOW)
                self.assertEqual(decision["outcome"], "ATTENTION_REQUIRED")
                self.assertIsNone(decision["selected_root_uuid"])

    def test_complete_failure_path_binds_exact_identity_and_arms_one_reboot(self):
        result = self._begin()
        self.assertEqual(result["phase"], "RECOVERING")
        self.assertEqual(result["failed_candidate_uuid"], FAILED_UUID)
        self.assertEqual(result["failed_system_generation_id"], FAILED_SYSTEM)
        self.assertEqual(result["selected_root_uuid"], PREVIOUS_UUID)
        self.assertEqual(result["selected_system_generation_id"], PREVIOUS_SYSTEM)
        self.assertEqual(result["recovery_attempts"], 1)
        self.assertTrue(result["reboot_required"])
        self.assertFalse(result["reboot_performed"])
        self.assertEqual(FakeBtrfs.arm_calls, 1)
        selected = read_transaction(transaction_path(self.recovered, TXID))
        self.assertEqual(selected["state"], "RECOVERING")
        record = recovery._read_record(self.recovered, TXID)
        execution = record["recovery_execution"]
        self.assertFalse(execution["home_mutated"])
        self.assertFalse(execution["package_manager_invoked"])
        self.assertFalse(execution["firmware_mutated"])

    def test_repeated_pre_reboot_verification_waits_without_second_recovery(self):
        self._begin()
        FakeBtrfs.topology = "RECOVERY_ARMED"
        FakeBtrfs.live_uuid = FAILED_UUID
        with patch.object(recovery, "NativeBtrfsOps", FakeBtrfs):
            result = recovery.verify_recovered_normal(
                TXID, state_root=self.recovered, generation_root=self.generations, now=NOW,
            )
        self.assertEqual(result["phase"], "RECOVERING")
        self.assertEqual(result["recovery_attempts"], 1)
        self.assertEqual(FakeBtrfs.arm_calls, 1)

    def test_post_reboot_independently_verifies_recovered_generation(self):
        self._begin()
        self._compatibility()
        FakeBtrfs.topology = "RECOVERY_ARMED"
        FakeBtrfs.live_uuid = PREVIOUS_UUID
        cmdline = self.base / "cmdline"
        cmdline.write_text("rootflags=subvol=@ rw\n")
        with patch.object(recovery, "NativeBtrfsOps", FakeBtrfs), \
             patch.object(recovery, "load_current_verified_generations", return_value=live_context()):
            result = recovery.verify_recovered_normal(
                TXID, state_root=self.recovered, generation_root=self.generations,
                now=NOW, cmdline_path=cmdline,
                package_runner=lambda *args, **kwargs: SimpleNamespace(
                    returncode=0, stdout="demo 1\n", stderr="",
                ),
                running_kernel=lambda: "6.1-cachyos",
            )
        self.assertEqual(result["phase"], "RECOVERED")
        self.assertEqual(result["root_uuid"], PREVIOUS_UUID)
        self.assertEqual(read_transaction(transaction_path(self.recovered, TXID))["state"], "RECOVERED")
        record = recovery._read_record(self.recovered, TXID)
        self.assertEqual(record["phase"], "RECOVERED_VERIFIED")
        self.assertEqual(record["recovery_attempts"], 1)

    def test_tampered_candidate_and_previous_root_are_rejected_before_mutation(self):
        for key, value in (
            ("uuid", "99999999-9999-9999-9999-999999999999"),
            ("parent_root_uuid", "88888888-8888-8888-8888-888888888888"),
        ):
            with self.subTest(key=key):
                record = json.loads(json.dumps(self.record))
                record["candidate"][key] = value
                recovery._atomic_json(recovery.recovery_record_path(self.state, TXID), record)
                with patch.object(recovery, "load_current_verified_generations", return_value=live_context()):
                    with self.assertRaisesRegex(ValueError, "binding mismatch"):
                        recovery.begin_bad_update_recovery(
                            TXID, failure_code="failure", failure_detail="tampered",
                            state_root=self.state, generation_root=self.generations,
                            executor=EXECUTOR, now=NOW,
                        )
                self.assertEqual(FakeBtrfs.arm_calls, 0)
                recovery._atomic_json(recovery.recovery_record_path(self.state, TXID), self.record)

    def test_missing_recovery_artifact_is_rejected_before_mutation(self):
        record = dict(self.record)
        record.pop("candidate_generation")
        recovery._atomic_json(recovery.recovery_record_path(self.state, TXID), record)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self._begin()
        self.assertEqual(FakeBtrfs.arm_calls, 0)

    def test_broken_retained_generation_artifact_is_rejected_before_unfreeze(self):
        with patch.object(recovery, "NativeBtrfsOps", FakeBtrfs), \
             patch.object(
                 recovery, "load_current_verified_generations",
                 side_effect=(live_context(), RuntimeError("target manifest missing")),
             ):
            with self.assertRaisesRegex(RuntimeError, "target manifest missing"):
                recovery.begin_bad_update_recovery(
                    TXID, failure_code="failure", failure_detail="broken target",
                    state_root=self.state, generation_root=self.generations,
                    executor=EXECUTOR, now=NOW,
                )
        self.assertEqual(FakeBtrfs.make_calls, 0)
        self.assertEqual(FakeBtrfs.arm_calls, 0)

    def test_recovery_evidence_parent_symlink_cannot_escape_state_root(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.state / "recovery-authorities").symlink_to(
            outside, target_is_directory=True,
        )
        with self.assertRaises((OSError, ValueError)):
            recovery._atomic_json(
                recovery.authority_path(self.state, TXID), {"escape": True},
            )
        self.assertEqual(list(outside.iterdir()), [])

    def test_missing_activation_consumption_artifact_is_rejected_before_mutation(self):
        handoff_consumption_path(self.state, self.handoff.handoff_id).unlink()
        with self.assertRaisesRegex(ValueError, "consumption is unavailable"):
            self._begin()
        self.assertEqual(FakeBtrfs.arm_calls, 0)

    def test_handoff_current_system_generation_mismatch_is_rejected(self):
        drifted = live_context()
        drifted_system = SimpleNamespace(
            generation_id="gen-" + "7" * 64,
            root_identity=drifted[1].root_identity,
        )
        with patch.object(recovery, "load_current_verified_generations", return_value=(
            {**drifted[0], "system_generation_id": drifted_system.generation_id},
            drifted_system, drifted[2],
        )):
            with self.assertRaisesRegex(ValueError, "activation binding mismatch"):
                recovery.begin_bad_update_recovery(
                    TXID, failure_code="failure", failure_detail="drift",
                    state_root=self.state, generation_root=self.generations,
                    executor=EXECUTOR, now=NOW,
                )
        self.assertEqual(FakeBtrfs.arm_calls, 0)

    def test_wrong_transaction_expired_consumed_and_wrong_executor_authority_are_rejected(self):
        recovering = transition_transaction(
            transition_transaction(self.tx, UpdateState.ACTIVE_VERIFYING, now=NOW),
            UpdateState.RECOVERING, now=NOW,
        )
        decision = guardian.select_exact_previous_generation(provider(), now=NOW)
        authority = recovery.issue_recovery_authority(
            transaction=recovering, provider_evidence=provider(),
            guardian_decision=decision, executor=EXECUTOR, now=NOW,
        )
        with self.assertRaisesRegex(ValueError, "binding mismatch"):
            recovery.verify_recovery_authority(
                authority.as_dict(), transaction={**recovering, "transaction_id": OTHER_TXID},
                provider_evidence=provider(), guardian_decision=decision,
                executor=EXECUTOR, state_root=self.state, now=NOW,
            )
        with self.assertRaisesRegex(ValueError, "expired"):
            recovery.verify_recovery_authority(
                authority.as_dict(), transaction=recovering,
                provider_evidence=provider(), guardian_decision=decision,
                executor=EXECUTOR, state_root=self.state, now=NOW + timedelta(minutes=16),
            )
        with self.assertRaisesRegex(ValueError, "executor"):
            recovery.verify_recovery_authority(
                authority.as_dict(), transaction=recovering,
                provider_evidence=provider(), guardian_decision=decision,
                executor={**EXECUTOR, "executor_id": "art-" + "f" * 64},
                state_root=self.state, now=NOW,
            )
        recovery._atomic_json(
            recovery.consumption_path(self.state, authority.authority_id),
            {"already": "consumed"},
        )
        with self.assertRaisesRegex(ValueError, "already consumed"):
            recovery.verify_recovery_authority(
                authority.as_dict(), transaction=recovering,
                provider_evidence=provider(), guardian_decision=decision,
                executor=EXECUTOR, state_root=self.state, now=NOW,
            )

    def test_authority_cannot_broaden_to_home_packages_firmware_or_arbitrary_paths(self):
        recovering = transition_transaction(
            transition_transaction(self.tx, UpdateState.ACTIVE_VERIFYING, now=NOW),
            UpdateState.RECOVERING, now=NOW,
        )
        decision = guardian.select_exact_previous_generation(provider(), now=NOW)
        authority = recovery.issue_recovery_authority(
            transaction=recovering, provider_evidence=provider(),
            guardian_decision=decision, executor=EXECUTOR, now=NOW,
        )
        baseline = {
            "failed_candidate_uuid": FAILED_UUID,
            "previous_root_uuid": PREVIOUS_UUID,
            "filesystem_uuid": FILESYSTEM_UUID,
            "failed_root_name": "@maho-update-backup-abcdefabcdef",
            "root_exchange_completed": True,
            "failed_root_read_only": True,
            "selected_root_writable": True,
            "boot_sha256": dict(BOOT),
            "package_manager_invoked": False,
            "firmware_mutated": False,
            "home_mutated": False,
            "reboot_performed": False,
            "reboot_required": True,
        }
        for key in ("package_manager_invoked", "firmware_mutated", "home_mutated", "reboot_performed"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "exceeded"):
                    recovery.consume_recovery_authority(
                        self.state, authority, {**baseline, key: True}, now=NOW,
                    )
        with self.assertRaisesRegex(ValueError, "scope is not closed"):
            recovery.consume_recovery_authority(
                self.state, authority,
                {**baseline, "arbitrary_path_mutated": True}, now=NOW,
            )

    def test_interrupted_post_exchange_recovery_only_freezes_exact_failed_root(self):
        ops = NativeBtrfsOps(TXID, run_root=self.base / "run", boot_root=self.base / "boot")
        identity = SimpleNamespace(
            subvolume_uuid=FAILED_UUID, filesystem_uuid=FILESYSTEM_UUID, fsroot="/@",
        )
        topologies = iter(("RECOVERY_EXCHANGED_PENDING_FREEZE", "RECOVERY_ARMED"))
        with patch.object(ops, "require_root"), \
             patch.object(ops, "root_identity", return_value=identity), \
             patch.object(ops, "_mount_top"), \
             patch.object(ops, "normal_recovery_topology", side_effect=lambda **kwargs: next(topologies)), \
             patch.object(ops, "live_boot_hashes", return_value=dict(BOOT)), \
             patch.object(ops, "_show_uuid", side_effect=lambda path: PREVIOUS_UUID if path.name == "@" else FAILED_UUID), \
             patch.object(ops, "_read_only", return_value=False), \
             patch.object(ops, "_set_read_only") as set_ro, \
             patch.object(ops, "_fsync_path"):
            result = ops.arm_root_recovery(
                expected_failed_uuid=FAILED_UUID,
                expected_previous_uuid=PREVIOUS_UUID,
                expected_filesystem_uuid=FILESYSTEM_UUID,
                expected_boot_hashes=BOOT,
            )
        self.assertTrue(result["root_exchange_completed"])
        set_ro.assert_called_once_with(ops.top / ops.backup, True)

    def test_interrupted_orchestration_resumes_same_authority_without_second_attempt(self):
        FakeBtrfs.fail_arm = True
        with self.assertRaisesRegex(RuntimeError, "injected interruption"):
            self._begin()
        self.assertEqual(
            read_transaction(transaction_path(self.state, TXID))["state"],
            "RECOVERING",
        )
        authorized = recovery._read_record(self.recovered, TXID)
        authority_id = authorized["recovery_authority"]["authority_id"]
        self.assertEqual(authorized["phase"], "RECOVERY_AUTHORIZED")
        FakeBtrfs.fail_arm = False
        FakeBtrfs.topology = "RECOVERY_EXCHANGED_PENDING_FREEZE"
        with patch.object(recovery, "NativeBtrfsOps", FakeBtrfs), \
             patch.object(recovery, "load_current_verified_generations", return_value=live_context()):
            result = recovery.resume_bad_update_recovery(
                TXID, state_root=self.state, executor=EXECUTOR,
                now=NOW + timedelta(minutes=1),
            )
        self.assertEqual(result["authority_id"], authority_id)
        self.assertEqual(result["recovery_attempts"], 1)
        self.assertTrue(result["reconciled_after_interruption"])
        reconciled = recovery._read_record(self.recovered, TXID)
        self.assertEqual(reconciled["phase"], "RECOVERY_ARMED")
        self.assertEqual(reconciled["recovery_authority"]["authority_id"], authority_id)

    def test_tampered_consumption_cannot_verify_recovered_root(self):
        self._begin()
        record = recovery._read_record(self.recovered, TXID)
        authority = recovery.parse_recovery_authority(record["recovery_authority"])
        receipt_path = recovery.consumption_path(self.recovered, authority.authority_id)
        receipt = json.loads(receipt_path.read_text())
        receipt["execution"]["home_mutated"] = True
        recovery._atomic_json(receipt_path, receipt)
        FakeBtrfs.topology = "RECOVERY_ARMED"
        FakeBtrfs.live_uuid = PREVIOUS_UUID
        cmdline = self.base / "cmdline-tampered"
        cmdline.write_text("rootflags=subvol=@ rw\n")
        with patch.object(recovery, "NativeBtrfsOps", FakeBtrfs):
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                recovery.verify_recovered_normal(
                    TXID, state_root=self.recovered,
                    generation_root=self.generations, now=NOW,
                    cmdline_path=cmdline,
                )

    def test_recovered_root_failure_converges_honestly_to_attention(self):
        self._begin()
        FakeBtrfs.topology = "RECOVERY_ARMED"
        FakeBtrfs.live_uuid = PREVIOUS_UUID
        cmdline = self.base / "cmdline"
        cmdline.write_text("rootflags=subvol=@ rw\n")
        with patch.object(recovery, "NativeBtrfsOps", FakeBtrfs), \
             patch.object(recovery, "load_current_verified_generations", return_value=live_context()):
            with self.assertRaisesRegex(RuntimeError, "package generation"):
                recovery.verify_recovered_normal(
                    TXID, state_root=self.recovered, generation_root=self.generations,
                    now=NOW, cmdline_path=cmdline,
                    package_runner=lambda *args, **kwargs: SimpleNamespace(
                        returncode=0, stdout="demo 2\n", stderr="",
                    ),
                    running_kernel=lambda: "6.1-cachyos",
                )
        result = recovery.attention_after_recovery_failure(
            TXID, state_root=self.recovered,
            detail="recovered package generation mismatch", now=NOW,
        )
        self.assertEqual(result["phase"], "ATTENTION_REQUIRED")
        self.assertEqual(
            read_transaction(transaction_path(self.recovered, TXID))["state"],
            "ATTENTION_REQUIRED",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
