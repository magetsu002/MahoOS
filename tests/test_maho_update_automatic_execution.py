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

import maho_update_automatic_execution as automatic  # noqa: E402
from maho_update_execution_authority import (  # noqa: E402
    issue_activation_handoff,
    publish_activation_handoff,
)
from maho_update_state import (  # noqa: E402
    UpdateState,
    create_transaction,
    publish_transaction,
    read_transaction,
    transaction_path,
    transition_transaction,
)

NOW = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)
TXID = "upd-20260927T100000Z-abcdefabcdef"
REV = "a" * 40
CURRENT_SYSTEM = "gen-" + "1" * 64
CURRENT_KERNEL = "kgen-" + "2" * 64
CANDIDATE_SYSTEM = "gen-" + "3" * 64
CANDIDATE_UUID = "22222222-2222-2222-2222-222222222222"
PARENT_UUID = "11111111-1111-1111-1111-111111111111"
BASE_UUID = "44444444-4444-4444-4444-444444444444"
FSUUID = "33333333-3333-3333-3333-333333333333"
BOOT_HASHES = {
    "/boot/intel-ucode.img": "5" * 64,
    "/boot/initramfs-linux-cachyos-lts.img": "6" * 64,
    "/boot/initramfs-linux-cachyos.img": "7" * 64,
    "/boot/vmlinuz-linux-cachyos": "8" * 64,
    "/boot/vmlinuz-linux-cachyos-lts": "9" * 64,
}


def make_transaction(payload_path: str) -> dict:
    tx = create_transaction(
        transaction_id=TXID,
        source_revision=REV,
        packages=[{
            "name": "demo",
            "installed_version": "1",
            "candidate_version": "2",
            "repository": "core",
            "download_size": 1024,
            "installed_size": 2048,
            "security_relevant": False,
            "roles": [],
        }],
        activation_requirements=[],
        recovery_generation_id=None,
        now=NOW,
    )
    tx = transition_transaction(tx, UpdateState.STAGED, now=NOW)
    plan = {
        "transaction_id": TXID,
        "package_generation_id": tx["package_generation"]["id"],
        "source_provenance_id": tx["source_provenance"]["id"],
        "payload_paths": [payload_path],
        "effects": ["ordinary-files-in-place"],
        "activation_requirements": [],
        "selection_kind": "full",
        "execution_environment": "production",
        "safe_reserve_bytes": 0,
        "reserve_after_preparation_bytes": 50 * 1024**3,
    }
    tx = transition_transaction(
        tx, UpdateState.PREPARED, evidence={"normal_plan": plan}, now=NOW,
    )
    return transition_transaction(
        tx,
        UpdateState.MAINTENANCE_READY,
        evidence={"coordinator": {"authority": "fixture"}},
        now=NOW,
    )


def live_context():
    live = {
        "system_generation_id": CURRENT_SYSTEM,
        "kernel_generation_id": CURRENT_KERNEL,
        "root_subvolume_uuid": PARENT_UUID,
        "filesystem_uuid": FSUUID,
        "recovery_generation_id": "g3-fixture",
    }
    return (
        live,
        SimpleNamespace(generation_id=CURRENT_SYSTEM),
        SimpleNamespace(kernel_generation_id=CURRENT_KERNEL, kernel_abi="6.1-cachyos"),
    )


def maintenance():
    return {
        "ready": True,
        "adaptive_snapshot_id": "sit-fixture",
        "adaptive_captured_at": "2026-09-27T10:00:00Z",
        "decision_at": "2026-09-27T10:00:00Z",
        "authority": "certified-unattended-maintenance",
        "repository_observed_at": "2026-09-27T10:00:00Z",
    }


class FakeBtrfs:
    instances = []
    offline_base: Path | None = None
    topology = "PREPARED"
    previous_record: bytes | None = None

    def __init__(self, transaction_id: str):
        self.transaction_id = transaction_id
        self.candidate = "@maho-update-candidate-abcdefabcdef"
        self.admission_base = "@maho-update-admission-base-abcdefabcdef"
        self.backup = "@maho-update-backup-abcdefabcdef"
        self.cleanup_calls = []
        self.activation_calls = []
        assert self.offline_base is not None
        self.offline_root = self.offline_base / f"offline-{len(self.instances)}"
        self.offline_root.mkdir(parents=True, exist_ok=True)
        self.base_root = self.offline_base / "base"
        self.candidate_root = self.offline_base / "candidate"
        self.base_root.mkdir(exist_ok=True)
        self.candidate_root.mkdir(exist_ok=True)
        FakeBtrfs.instances.append(self)

    def root_identity(self):
        return SimpleNamespace(
            subvolume_uuid=PARENT_UUID,
            filesystem_uuid=FSUUID,
            fsroot="/@",
        )

    def create_candidate(self):
        return {
            "name": self.candidate,
            "uuid": CANDIDATE_UUID,
            "parent_root_uuid": PARENT_UUID,
            "filesystem_uuid": FSUUID,
            "offline_root": str(self.offline_root),
            "admission_base_name": self.admission_base,
            "admission_base_uuid": BASE_UUID,
        }

    def cleanup_candidate(self, uuid):
        self.cleanup_calls.append(uuid)
        return {"ok": True, "candidate_uuid": uuid}

    def close(self):
        return None

    def live_boot_hashes(self):
        return dict(BOOT_HASHES)

    def normal_activation_topology(self, **_kwargs):
        return self.topology

    def admission_roots(self, candidate_uuid, base_uuid):
        return {
            "candidate_uuid": candidate_uuid,
            "base_uuid": base_uuid,
            "candidate_read_only": True,
            "base_read_only": True,
            "base_root": str(self.base_root),
            "candidate_root": str(self.candidate_root),
        }

    def read_previous_root_file(self, relative, *, expected_active_uuid=None):
        if self.previous_record is None:
            raise RuntimeError("previous record unavailable")
        if expected_active_uuid is not None and expected_active_uuid != CANDIDATE_UUID:
            raise RuntimeError("active root is not the expected update candidate")
        return {
            "content": self.previous_record,
            "previous_root_uuid": PARENT_UUID,
            "active_root_uuid": CANDIDATE_UUID,
            "relative_path": relative,
        }

    def arm_root_activation(self, **kwargs):
        self.activation_calls.append(kwargs)
        return {
            "candidate_uuid": CANDIDATE_UUID,
            "previous_root_uuid": PARENT_UUID,
            "previous_root_name": self.backup,
            "boot_sha256": dict(BOOT_HASHES),
            "boot_unchanged": True,
            "package_manager_invoked": False,
            "reboot_performed": False,
            "firmware_mutated": False,
        }


class FakeOps:
    production_safe = True
    fail_install = False
    instances = []

    def __init__(self, *, transaction, cache_root, btrfs, candidate):
        self.transaction = transaction
        self.cache_root = cache_root
        self.btrfs = btrfs
        self.candidate = candidate
        self.calls = []
        self.admission = None
        self.roots = None
        FakeOps.instances.append(self)

    def install_candidate(self, _plan):
        self.calls.append("install")
        if self.fail_install:
            return {"ok": False, "reason": "injected install failure"}
        return {"ok": True, "offline_candidate": True}

    def guardian_admit(self, _plan):
        self.calls.append("admit")
        self.admission = object()
        self.roots = object()
        return {"ok": True, "graph_id": "art-" + "b" * 64}


class FakeAuthority:
    authority_id = "art-" + "a" * 64

    def as_dict(self):
        return {
            "authority_id": self.authority_id,
            "graph_id": "art-" + "b" * 64,
        }


class AutomaticExecutionContracts(unittest.TestCase):
    def setUp(self):
        FakeBtrfs.instances.clear()
        FakeOps.instances.clear()
        FakeOps.fail_install = False
        FakeBtrfs.topology = "PREPARED"
        FakeBtrfs.previous_record = None
        self.state_tmp = tempfile.TemporaryDirectory()
        self.work_tmp = tempfile.TemporaryDirectory()
        self.gen_tmp = tempfile.TemporaryDirectory()
        self.offline_tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.state_tmp.name)
        self.work = Path(self.work_tmp.name)
        self.generations = Path(self.gen_tmp.name)
        FakeBtrfs.offline_base = Path(self.offline_tmp.name)
        self.cache = self.work / TXID / "staging"
        self.cache.mkdir(parents=True)
        self.payload = self.cache / "demo-2.pkg.tar.zst"
        self.payload.write_bytes(b"demo")
        self.tx = make_transaction(str(self.payload))
        self.manifest_path = self.cache / f"manifest-{self.tx['package_generation']['id']}.json"
        self.manifest_path.write_text(json.dumps({
            "payloads": [{"name": "demo", "sha256": "5" * 64}],
        }))
        publish_transaction(self.state, self.tx)

    def tearDown(self):
        self.state_tmp.cleanup()
        self.work_tmp.cleanup()
        self.gen_tmp.cleanup()
        self.offline_tmp.cleanup()

    def execution_patches(self):
        return (
            patch.object(automatic, "NativeBtrfsOps", FakeBtrfs),
            patch.object(automatic, "NormalProductionOps", FakeOps),
            patch.object(automatic, "validate_manifest", return_value={}),
            patch.object(automatic, "load_normal_execution_authority", return_value={"authority_id": "normal-fixture"}),
            patch("maho_update_normal.authorize_normal_plan", return_value={}),
            patch.object(automatic, "load_current_verified_generations", return_value=live_context()),
            patch.object(automatic, "executor_identity", return_value={
                "interpreter": "/usr/bin/python",
                "campaign_root": f"/usr/lib/maho/update-campaign/{REV}",
                "source_revision": REV,
                "modules": {"fixture.py": "d" * 64},
            }),
            patch.object(automatic, "issue_activation_authority", return_value=FakeAuthority()),
            patch.object(automatic, "_boot_identity", return_value={
                "unchanged": True,
                "sha256": dict(BOOT_HASHES),
                "cmdline_sha256": "c" * 64,
            }),
            patch.object(automatic, "publish_normal_candidate_generation", return_value={
                "system_generation_id": CANDIDATE_SYSTEM,
                "kernel_generation_id": CURRENT_KERNEL,
            }),
        )

    def run_execute(
        self, *,
        maintenance_value=None,
        repository_reobserve=None,
        maintenance_reobserve=None,
        disk_usage=None,
        installed_runner=None,
        package_lock_present=None,
        btrfs_factory=FakeBtrfs,
    ):
        patches = self.execution_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9]:
            return automatic.execute_ready_normal(
                self.tx,
                cache_root=self.cache,
                manifest_path=self.manifest_path,
                maintenance_evidence=maintenance_value or maintenance(),
                repository_evidence={"repository_hashes": {"core": "c" * 64}},
                repository_reobserve=repository_reobserve or (lambda: {"core": "c" * 64}),
                maintenance_reobserve=maintenance_reobserve or maintenance,
                state_root=self.state,
                campaign_root=ROOT,
                generation_root=self.generations,
                now=NOW,
                btrfs_factory=btrfs_factory,
                ops_factory=FakeOps,
                installed_runner=installed_runner or (
                    lambda command, **kwargs: SimpleNamespace(
                        returncode=0, stdout="demo 1\n", stderr=""
                    )
                ),
                disk_usage=disk_usage or (
                    lambda path: SimpleNamespace(
                        total=200 * 1024**3,
                        used=20 * 1024**3,
                        free=180 * 1024**3,
                    )
                ),
                package_lock_present=package_lock_present or (lambda: False),
                executor_value={
                    "interpreter": "/usr/bin/python",
                    "campaign_root": f"/usr/lib/maho/update-campaign/{REV}",
                    "source_revision": REV,
                    "modules": {"fixture.py": "d" * 64},
                },
            )

    def test_exact_execution_stops_at_pending_activation_and_never_reboots(self):
        result = self.run_execute()
        self.assertEqual(result["phase"], "INSTALLED_PENDING_ACTIVATION")
        self.assertFalse(result["reboot_performed"])
        self.assertEqual(FakeOps.instances[-1].calls, ["install", "admit"])
        stored = read_transaction(transaction_path(self.state, TXID))
        self.assertEqual(stored["state"], "INSTALLED_PENDING_ACTIVATION")
        candidate_state = FakeBtrfs.instances[-1].offline_root / "var/lib/maho/update"
        candidate_txid = (candidate_state / "current").read_text().strip()
        candidate_tx = read_transaction(transaction_path(candidate_state, candidate_txid))
        self.assertEqual(candidate_tx["state"], "INSTALLED_PENDING_ACTIVATION")
        self.assertTrue((self.state / "activation-handoffs" / f"{TXID}.json").is_file())
        consumed = self.state / "execution-authorities" / "consumed"
        self.assertEqual(len(list(consumed.glob("*.json"))), 1)

    def test_install_failure_discards_candidate_and_stops_before_s3(self):
        FakeOps.fail_install = True
        result = self.run_execute()
        self.assertEqual(result["phase"], "FAILED_RECOVERABLE")
        self.assertEqual(FakeBtrfs.instances[-1].cleanup_calls, [CANDIDATE_UUID])
        stored = read_transaction(transaction_path(self.state, TXID))
        self.assertEqual(stored["state"], "FAILED_RECOVERABLE")
        self.assertFalse((self.state / "activation-handoffs" / f"{TXID}.json").exists())

    def test_repository_drift_denies_before_candidate_mutation(self):
        with self.assertRaisesRegex(ValueError, "repository_generation_drifted"):
            self.run_execute(repository_reobserve=lambda: {"core": "e" * 64})
        self.assertFalse(FakeOps.instances)

    def test_insufficient_disk_reserve_denies_before_candidate_mutation(self):
        tiny = lambda path: SimpleNamespace(
            total=200 * 1024**3,
            used=195 * 1024**3,
            free=5 * 1024**3,
        )
        with self.assertRaisesRegex(ValueError, "safe_disk_reserve_unsatisfied"):
            self.run_execute(disk_usage=tiny)
        self.assertFalse(FakeOps.instances)

    def test_concurrent_manual_update_denies_before_candidate_mutation(self):
        with self.assertRaisesRegex(ValueError, "concurrent_package_or_build_operation"):
            self.run_execute(package_lock_present=lambda: True)
        self.assertFalse(FakeOps.instances)

    def test_stale_maintenance_evidence_denies_before_candidate_mutation(self):
        stale = maintenance()
        stale["adaptive_captured_at"] = automatic._stamp(NOW - timedelta(minutes=5))
        with self.assertRaisesRegex(ValueError, "fresh maintenance snapshot"):
            self.run_execute(maintenance_value=stale)
        self.assertFalse(FakeOps.instances)

    def test_guardian_or_maintenance_revocation_after_candidate_allocation_discards_candidate(self):
        def revoked():
            raise RuntimeError("guardian_evidence_stale")

        with self.assertRaisesRegex(RuntimeError, "guardian_evidence_stale"):
            self.run_execute(maintenance_reobserve=revoked)
        self.assertFalse(FakeOps.instances)
        self.assertEqual(FakeBtrfs.instances[-1].cleanup_calls, [CANDIDATE_UUID])
        stored = read_transaction(transaction_path(self.state, TXID))
        self.assertEqual(stored["state"], "BLOCKED")

    def test_missing_recovery_prerequisite_denies_before_mutation_and_discards_candidate(self):
        class MissingRecoveryBtrfs(FakeBtrfs):
            def create_candidate(self):
                value = super().create_candidate()
                value.pop("admission_base_uuid")
                return value

        with self.assertRaisesRegex(ValueError, "recovery prerequisite"):
            self.run_execute(btrfs_factory=MissingRecoveryBtrfs)
        self.assertFalse(FakeOps.instances)
        self.assertEqual(FakeBtrfs.instances[-1].cleanup_calls, [CANDIDATE_UUID])

    def test_double_execution_replay_is_refused(self):
        first = self.run_execute()
        self.assertEqual(first["phase"], "INSTALLED_PENDING_ACTIVATION")
        with self.assertRaisesRegex(ValueError, "record already exists"):
            self.run_execute()

    def test_interrupted_candidate_generation_publication_discards_non_authoritative_candidate(self):
        patches = self.execution_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], \
             patch.object(automatic, "publish_normal_candidate_generation", side_effect=RuntimeError("generation_publish_interrupted")):
            with self.assertRaisesRegex(RuntimeError, "generation_publish_interrupted"):
                automatic.execute_ready_normal(
                    self.tx,
                    cache_root=self.cache,
                    manifest_path=self.manifest_path,
                    maintenance_evidence=maintenance(),
                    repository_evidence={"repository_hashes": {"core": "c" * 64}},
                    repository_reobserve=lambda: {"core": "c" * 64},
                    maintenance_reobserve=maintenance,
                    state_root=self.state,
                    campaign_root=ROOT,
                    generation_root=self.generations,
                    now=NOW,
                    btrfs_factory=FakeBtrfs,
                    ops_factory=FakeOps,
                    installed_runner=lambda command, **kwargs: SimpleNamespace(returncode=0, stdout="demo 1\n", stderr=""),
                    disk_usage=lambda path: SimpleNamespace(total=200 * 1024**3, used=20 * 1024**3, free=180 * 1024**3),
                    package_lock_present=lambda: False,
                    executor_value={
                        "interpreter": "/usr/bin/python",
                        "campaign_root": f"/usr/lib/maho/update-campaign/{REV}",
                        "source_revision": REV,
                        "modules": {"fixture.py": "d" * 64},
                    },
                )
        self.assertEqual(FakeBtrfs.instances[-1].cleanup_calls, [CANDIDATE_UUID])
        self.assertEqual(
            read_transaction(transaction_path(self.state, TXID))["state"],
            "FAILED_RECOVERABLE",
        )
        self.assertFalse((self.state / "activation-handoffs" / f"{TXID}.json").exists())

    def test_interrupted_activation_handoff_publication_discards_non_authoritative_candidate(self):
        patches = self.execution_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], \
             patch.object(automatic, "publish_activation_handoff", side_effect=RuntimeError("handoff_publish_interrupted")):
            with self.assertRaisesRegex(RuntimeError, "handoff_publish_interrupted"):
                automatic.execute_ready_normal(
                    self.tx,
                    cache_root=self.cache,
                    manifest_path=self.manifest_path,
                    maintenance_evidence=maintenance(),
                    repository_evidence={"repository_hashes": {"core": "c" * 64}},
                    repository_reobserve=lambda: {"core": "c" * 64},
                    maintenance_reobserve=maintenance,
                    state_root=self.state,
                    campaign_root=ROOT,
                    generation_root=self.generations,
                    now=NOW,
                    btrfs_factory=FakeBtrfs,
                    ops_factory=FakeOps,
                    installed_runner=lambda command, **kwargs: SimpleNamespace(returncode=0, stdout="demo 1\n", stderr=""),
                    disk_usage=lambda path: SimpleNamespace(total=200 * 1024**3, used=20 * 1024**3, free=180 * 1024**3),
                    package_lock_present=lambda: False,
                    executor_value={
                        "interpreter": "/usr/bin/python",
                        "campaign_root": f"/usr/lib/maho/update-campaign/{REV}",
                        "source_revision": REV,
                        "modules": {"fixture.py": "d" * 64},
                    },
                )
        self.assertEqual(FakeBtrfs.instances[-1].cleanup_calls, [CANDIDATE_UUID])
        self.assertEqual(
            read_transaction(transaction_path(self.state, TXID))["state"],
            "FAILED_RECOVERABLE",
        )

    def test_final_pending_publish_interruption_reconciles_completed_handoff_without_replay(self):
        patches = self.execution_patches()
        real_publish = automatic.publish_transaction
        calls = {"count": 0}

        def interrupted_publish(root, transaction):
            calls["count"] += 1
            real_publish(root, transaction)
            raise RuntimeError("final_publish_interrupted")

        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], \
             patch.object(automatic, "publish_transaction", side_effect=interrupted_publish):
            result = automatic.execute_ready_normal(
                self.tx,
                cache_root=self.cache,
                manifest_path=self.manifest_path,
                maintenance_evidence=maintenance(),
                repository_evidence={"repository_hashes": {"core": "c" * 64}},
                repository_reobserve=lambda: {"core": "c" * 64},
                maintenance_reobserve=maintenance,
                state_root=self.state,
                campaign_root=ROOT,
                generation_root=self.generations,
                now=NOW,
                btrfs_factory=FakeBtrfs,
                ops_factory=FakeOps,
                installed_runner=lambda command, **kwargs: SimpleNamespace(returncode=0, stdout="demo 1\n", stderr=""),
                disk_usage=lambda path: SimpleNamespace(total=200 * 1024**3, used=20 * 1024**3, free=180 * 1024**3),
                package_lock_present=lambda: False,
                executor_value={
                    "interpreter": "/usr/bin/python",
                    "campaign_root": f"/usr/lib/maho/update-campaign/{REV}",
                    "source_revision": REV,
                    "modules": {"fixture.py": "d" * 64},
                },
            )
        self.assertTrue(result["final_publish_reconciled"])
        self.assertEqual(
            read_transaction(transaction_path(self.state, TXID))["state"],
            "INSTALLED_PENDING_ACTIVATION",
        )
        self.assertEqual(FakeBtrfs.instances[-1].cleanup_calls, [])

    def test_interrupted_install_is_discarded_without_replay(self):
        installing = transition_transaction(self.tx, UpdateState.INSTALLING, now=NOW)
        publish_transaction(self.state, installing)
        automatic._atomic_json(automatic.record_path(self.state, TXID), {
            "schema_version": 1,
            "kind": "maho-automatic-normal-execution",
            "transaction_id": TXID,
            "source_revision": REV,
            "phase": "AUTHORIZED",
            "candidate": {
                "name": "@maho-update-candidate-abcdefabcdef",
                "uuid": CANDIDATE_UUID,
                "parent_root_uuid": PARENT_UUID,
                "filesystem_uuid": FSUUID,
                "admission_base_name": "@maho-update-admission-base-abcdefabcdef",
                "admission_base_uuid": BASE_UUID,
            },
        })
        with patch.object(automatic, "NativeBtrfsOps", FakeBtrfs):
            result = automatic.recover_interrupted_normal_execution(
                TXID, state_root=self.state, now=NOW,
            )
        self.assertEqual(result["phase"], "FAILED_RECOVERABLE")
        self.assertFalse(result["replayed"])
        self.assertFalse(result["s3_recovery_invoked"])
        self.assertEqual(FakeBtrfs.instances[-1].cleanup_calls, [CANDIDATE_UUID])
        self.assertEqual(
            read_transaction(transaction_path(self.state, TXID))["state"],
            "FAILED_RECOVERABLE",
        )

    def test_activation_handoff_arms_root_only_and_never_reboots(self):
        pending = transition_transaction(
            transition_transaction(self.tx, UpdateState.INSTALLING, now=NOW),
            UpdateState.INSTALLED_PENDING_ACTIVATION,
            now=NOW,
        )
        publish_transaction(self.state, pending)
        candidate = {
            "name": "@maho-update-candidate-abcdefabcdef",
            "uuid": CANDIDATE_UUID,
            "parent_root_uuid": PARENT_UUID,
            "filesystem_uuid": FSUUID,
            "admission_base_name": "@maho-update-admission-base-abcdefabcdef",
            "admission_base_uuid": BASE_UUID,
        }
        authority = FakeAuthority().as_dict()
        handoff = issue_activation_handoff(
            pending,
            current_system_generation_id=CURRENT_SYSTEM,
            candidate_system_generation_id=CANDIDATE_SYSTEM,
            candidate_kernel_generation_id=CURRENT_KERNEL,
            candidate_uuid=CANDIDATE_UUID,
            previous_root_uuid=PARENT_UUID,
            activation_authority=authority,
            recovery_evidence={"ready": True},
            candidate_boot_identity={
                "unchanged": True,
                "sha256": dict(BOOT_HASHES),
            },
            reboot_required=True,
            reboot_reason="explicit restart required",
            now=NOW,
        )
        publish_activation_handoff(self.state, handoff)
        automatic._atomic_json(automatic.record_path(self.state, TXID), {
            "schema_version": 1,
            "kind": "maho-automatic-normal-execution",
            "transaction_id": TXID,
            "source_revision": REV,
            "phase": "INSTALLED_PENDING_ACTIVATION",
            "candidate": candidate,
            "activation_authority": authority,
            "candidate_generation": {
                "system_generation_id": CANDIDATE_SYSTEM,
                "kernel_generation_id": CURRENT_KERNEL,
            },
            "activation_handoff": handoff.as_dict(),
        })
        with patch.object(automatic, "NativeBtrfsOps", FakeBtrfs), \
             patch.object(automatic, "load_current_verified_generations", return_value=live_context()), \
             patch.object(
                 automatic,
                 "verify_normal_activation_authority",
                 return_value=SimpleNamespace(authority_id=FakeAuthority.authority_id),
             ):
            result = automatic.arm_normal_activation(
                TXID,
                state_root=self.state,
                generation_root=self.generations,
                now=NOW,
            )
        self.assertEqual(result["phase"], "ACTIVATION_ARMED")
        self.assertFalse(result["reboot_performed"])
        self.assertEqual(len(FakeBtrfs.instances[-1].activation_calls), 1)
        record = automatic.read_execution_record(self.state, TXID)
        self.assertEqual(record["phase"], "ACTIVATION_ARMED")
        self.assertFalse(record["activation"]["package_manager_invoked"])

    def test_wrong_activation_generation_is_rejected_before_root_swap(self):
        pending = transition_transaction(
            transition_transaction(self.tx, UpdateState.INSTALLING, now=NOW),
            UpdateState.INSTALLED_PENDING_ACTIVATION,
            now=NOW,
        )
        publish_transaction(self.state, pending)
        authority = FakeAuthority().as_dict()
        handoff = issue_activation_handoff(
            pending,
            current_system_generation_id=CURRENT_SYSTEM,
            candidate_system_generation_id="gen-" + "f" * 64,
            candidate_kernel_generation_id=CURRENT_KERNEL,
            candidate_uuid=CANDIDATE_UUID,
            previous_root_uuid=PARENT_UUID,
            activation_authority=authority,
            recovery_evidence={"ready": True},
            candidate_boot_identity={"unchanged": True, "sha256": dict(BOOT_HASHES)},
            reboot_required=True,
            reboot_reason="explicit restart required",
            now=NOW,
        )
        automatic._atomic_json(automatic.record_path(self.state, TXID), {
            "schema_version": 1,
            "kind": "maho-automatic-normal-execution",
            "transaction_id": TXID,
            "source_revision": REV,
            "phase": "INSTALLED_PENDING_ACTIVATION",
            "candidate": {
                "name": "@maho-update-candidate-abcdefabcdef",
                "uuid": CANDIDATE_UUID,
                "parent_root_uuid": PARENT_UUID,
                "filesystem_uuid": FSUUID,
                "admission_base_name": "@maho-update-admission-base-abcdefabcdef",
                "admission_base_uuid": BASE_UUID,
            },
            "activation_authority": authority,
            "candidate_generation": {
                "system_generation_id": CANDIDATE_SYSTEM,
                "kernel_generation_id": CURRENT_KERNEL,
            },
            "activation_handoff": handoff.as_dict(),
        })
        with patch.object(automatic, "load_current_verified_generations", return_value=live_context()):
            with self.assertRaisesRegex(ValueError, "candidate generation binding mismatch"):
                automatic.arm_normal_activation(
                    TXID, state_root=self.state, generation_root=self.generations, now=NOW,
                )
        self.assertFalse(FakeBtrfs.instances)

    def test_stale_activation_handoff_is_rejected_before_root_swap(self):
        pending = transition_transaction(
            transition_transaction(self.tx, UpdateState.INSTALLING, now=NOW),
            UpdateState.INSTALLED_PENDING_ACTIVATION,
            now=NOW,
        )
        publish_transaction(self.state, pending)
        authority = FakeAuthority().as_dict()
        handoff = issue_activation_handoff(
            pending,
            current_system_generation_id=CURRENT_SYSTEM,
            candidate_system_generation_id=CANDIDATE_SYSTEM,
            candidate_kernel_generation_id=CURRENT_KERNEL,
            candidate_uuid=CANDIDATE_UUID,
            previous_root_uuid=PARENT_UUID,
            activation_authority=authority,
            recovery_evidence={"ready": True},
            candidate_boot_identity={"unchanged": True, "sha256": dict(BOOT_HASHES)},
            reboot_required=True,
            reboot_reason="explicit restart required",
            now=NOW,
        )
        automatic._atomic_json(automatic.record_path(self.state, TXID), {
            "schema_version": 1,
            "kind": "maho-automatic-normal-execution",
            "transaction_id": TXID,
            "source_revision": REV,
            "phase": "INSTALLED_PENDING_ACTIVATION",
            "candidate": {
                "name": "@maho-update-candidate-abcdefabcdef",
                "uuid": CANDIDATE_UUID,
                "parent_root_uuid": PARENT_UUID,
                "filesystem_uuid": FSUUID,
                "admission_base_name": "@maho-update-admission-base-abcdefabcdef",
                "admission_base_uuid": BASE_UUID,
            },
            "activation_authority": authority,
            "candidate_generation": {
                "system_generation_id": CANDIDATE_SYSTEM,
                "kernel_generation_id": CURRENT_KERNEL,
            },
            "activation_handoff": handoff.as_dict(),
        })
        with patch.object(automatic, "load_current_verified_generations", return_value=live_context()):
            with self.assertRaisesRegex(ValueError, "expired"):
                automatic.arm_normal_activation(
                    TXID,
                    state_root=self.state,
                    generation_root=self.generations,
                    now=NOW + timedelta(days=2),
                )
        self.assertFalse(FakeBtrfs.instances)

    def test_post_reboot_restores_exact_handoff_record_and_candidate_generation(self):
        pending = transition_transaction(
            transition_transaction(self.tx, UpdateState.INSTALLING, now=NOW),
            UpdateState.INSTALLED_PENDING_ACTIVATION,
            now=NOW,
        )
        publish_transaction(self.state, pending)
        authority = FakeAuthority().as_dict()
        candidate = {
            "name": "@maho-update-candidate-abcdefabcdef",
            "uuid": CANDIDATE_UUID,
            "parent_root_uuid": PARENT_UUID,
            "filesystem_uuid": FSUUID,
            "admission_base_name": "@maho-update-admission-base-abcdefabcdef",
            "admission_base_uuid": BASE_UUID,
        }
        handoff = issue_activation_handoff(
            pending,
            current_system_generation_id=CURRENT_SYSTEM,
            candidate_system_generation_id=CANDIDATE_SYSTEM,
            candidate_kernel_generation_id=CURRENT_KERNEL,
            candidate_uuid=CANDIDATE_UUID,
            previous_root_uuid=PARENT_UUID,
            activation_authority=authority,
            recovery_evidence={"ready": True, "generation_id": "g3-fixture"},
            candidate_boot_identity={"unchanged": True, "sha256": dict(BOOT_HASHES)},
            reboot_required=True,
            reboot_reason="explicit restart required",
            now=NOW,
        )
        previous_record = {
            "schema_version": 1,
            "kind": "maho-automatic-normal-execution",
            "transaction_id": TXID,
            "source_revision": REV,
            "phase": "ACTIVATION_ARMED",
            "candidate": candidate,
            "activation_authority": authority,
            "recovery_evidence": {"ready": True, "generation_id": "g3-fixture"},
            "candidate_boot_identity": {"unchanged": True, "sha256": dict(BOOT_HASHES)},
            "candidate_generation": {
                "system_generation_id": CANDIDATE_SYSTEM,
                "kernel_generation_id": CURRENT_KERNEL,
            },
            "activation_handoff": handoff.as_dict(),
        }
        FakeBtrfs.previous_record = (
            json.dumps(previous_record, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        reconstructed = {
            "system_generation_id": CANDIDATE_SYSTEM,
            "kernel_generation_id": CURRENT_KERNEL,
            "candidate_uuid": CANDIDATE_UUID,
        }
        with patch.object(automatic, "NativeBtrfsOps", FakeBtrfs), \
             patch.object(automatic, "load_current_verified_generations", return_value=live_context()), \
             patch.object(automatic, "read_candidate_publication", return_value=None), \
             patch.object(automatic, "publish_normal_candidate_generation", return_value=reconstructed):
            record = automatic.finalize_pending_normal(
                TXID,
                state_root=self.state,
                generation_root=self.generations,
                now=NOW,
            )
        self.assertEqual(record["phase"], "ACTIVATION_ARMED")
        self.assertTrue(record["post_activation_evidence_restored"])
        self.assertEqual(record["candidate_generation"]["system_generation_id"], CANDIDATE_SYSTEM)
        restored = automatic.read_execution_record(self.state, TXID)
        self.assertEqual(restored["activation_handoff"]["handoff_id"], handoff.handoff_id)

    def test_activate_current_is_noop_without_pending_transaction(self):
        healthy = transition_transaction(
            transition_transaction(
                transition_transaction(self.tx, UpdateState.INSTALLING, now=NOW),
                UpdateState.INSTALLED_PENDING_ACTIVATION,
                now=NOW,
            ),
            UpdateState.ATTENTION_REQUIRED,
            reason="fixture terminal state",
            blockers=["fixture_terminal"],
            now=NOW,
        )
        publish_transaction(self.state, healthy)
        result = automatic.activate_current_pending(
            state_root=self.state,
            generation_root=self.generations,
            now=NOW,
        )
        self.assertFalse(result["activation_attempted"])
        self.assertEqual(result["phase"], "ATTENTION_REQUIRED")

    def test_source_contains_no_hidden_reboot_or_postboot_health_promotion(self):
        source = (ROOT / "lib/maho_update_automatic_execution.py").read_text()
        self.assertNotIn("systemctl reboot", source)
        self.assertNotIn("/sbin/reboot", source)
        self.assertNotIn("UpdateState.ACTIVE_VERIFYING", source)
        self.assertNotIn("UpdateState.HEALTHY", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
