#!/usr/bin/env python3
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import maho_update_coordinator as coordinator  # noqa: E402
from maho_update_discovery import IsolatedPacmanDiscovery  # noqa: E402
from maho_update_maintenance import MaintenanceContext, evaluate_maintenance  # noqa: E402
from maho_update_state import (  # noqa: E402
    UpdateState,
    create_transaction,
    publish_transaction,
    read_transaction,
    transaction_path,
    transition_transaction,
)

NOW = datetime(2026, 9, 27, 7, 0, tzinfo=timezone.utc)
REV = "a" * 40
TXID = "upd-20260927T070000Z-abcdefabcdef"


def prepared_tx(*, txid: str = TXID, revision: str = REV) -> dict:
    tx = create_transaction(
        transaction_id=txid,
        source_revision=revision,
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
    return transition_transaction(tx, UpdateState.PREPARED, now=NOW)


def adaptive_record(**overrides) -> dict:
    situation = {
        "session": {
            "locked": True,
            "lock_dwell_seconds": 3600,
            "idle_seconds": 3600,
            "freshness": "fresh",
        },
        "power": {
            "ac_online": True,
            "battery_present": True,
            "percentage": 100,
            "freshness": "fresh",
        },
        "thermal": {"level": "normal", "freshness": "fresh"},
        "workload": {
            "gaming": False,
            "compile": False,
            "rendering": False,
            "interactive": False,
            "confidence": 1.0,
            "freshness": "fresh",
        },
        "network": {
            "connectivity": "online",
            "stability": "stable",
            "freshness": "fresh",
        },
        "maintenance": {
            "transaction_state": "PREPARED",
            "in_critical_section": False,
            "freshness": "fresh",
        },
        "guardian": {
            "active_incident": False,
            "severity_level": 0,
            "recovery_in_progress": False,
            "freshness": "fresh",
        },
    }
    for domain, changes in overrides.items():
        if domain in situation and isinstance(changes, dict):
            situation[domain].update(changes)
    return {
        "schema_version": 1,
        "captured_at": coordinator.stamp(NOW),
        "snapshot_id": "sit-test",
        "situation": situation,
        "active_posture": {"maintenance": "eligible"},
        "blocked": None,
    }


class FakeDiscovery:
    def __init__(self, root, **kwargs):
        self.root = Path(root)
        self.db = self.root / "db"

    def sync_database_hashes(self):
        return {
            "core": "1" * 64,
            "extra": "2" * 64,
            "multilib": "3" * 64,
            "cachyos": "4" * 64,
        }


class CoordinatorContracts(unittest.TestCase):
    def test_clean_startup_state_is_idle_and_non_mutating(self):
        state = coordinator._base_state(NOW, REV)
        self.assertEqual(state["phase"], "IDLE")
        self.assertFalse(state["live_root_mutation_started"])
        self.assertFalse(state["reboot_performed"])
        self.assertIsNone(state["active_transaction_id"])

    def test_retry_from_prior_source_revision_does_not_defer_new_campaign(self):
        previous_revision = "b" * 40
        previous = {
            **coordinator._base_state(NOW, previous_revision),
            "phase": "RETRY_DEFERRED",
            "next_retry_at": coordinator.stamp(NOW + timedelta(minutes=10)),
            "blockers": ["package_repo_config_unavailable"],
        }
        discovered = {**coordinator._base_state(NOW, REV), "phase": "WAITING_MAINTENANCE"}
        runtime = {"source_revision": REV}
        repo = {"config_path": "/etc/maho/pacman.conf", "repositories": ["core"]}
        with patch.object(coordinator, "_require_root"), \
             patch.object(coordinator, "_root", return_value=ROOT), \
             patch.object(coordinator, "_source_revision", return_value=REV), \
             patch.object(coordinator, "read_coordinator_state", return_value=previous), \
             patch.object(coordinator, "coordinator_mutex", return_value=nullcontext()), \
             patch.object(coordinator, "_coordinator_user", return_value="magetsu"), \
             patch.object(coordinator, "_runtime_identity", return_value=runtime), \
             patch.object(coordinator, "_repo_contract", return_value=repo), \
             patch.object(coordinator, "_current_transaction", return_value=None), \
             patch.object(coordinator, "_new_discovery", return_value=discovered) as new_discovery:
            result = coordinator.run_once(now=NOW)
        self.assertEqual(result["phase"], "WAITING_MAINTENANCE")
        new_discovery.assert_called_once()

    def test_schedule_is_periodic_persistent_and_boot_started(self):
        timer = (ROOT / "config/systemd/system/maho-update-coordinator.timer").read_text()
        service = (ROOT / "config/systemd/system/maho-update-coordinator.service").read_text()
        package = (ROOT / "packaging/arch/PKGBUILD.in").read_text()
        self.assertIn("OnBootSec=90s", timer)
        self.assertIn("OnUnitInactiveSec=5min", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("Unit=maho-update-coordinator.service", timer)
        self.assertIn("/usr/lib/maho/update-campaign/current/bin/maho-update-coordinator run", service)
        self.assertIn("timers.target.wants/maho-update-coordinator.timer", package)

    def test_explicit_reboot_hook_arms_activation_without_initiating_reboot(self):
        service = (ROOT / "config/systemd/system/maho-update-activate-on-reboot.service").read_text()
        package = (ROOT / "packaging/arch/PKGBUILD.in").read_text()
        installer = (ROOT / "bin/maho-update-campaign-install").read_text()
        self.assertIn("activate-current", service)
        self.assertIn("DefaultDependencies=no", service)
        self.assertIn("After=local-fs.target", service)
        self.assertIn("Conflicts=reboot.target", service)
        self.assertIn("Before=reboot.target", service)
        self.assertIn("RefuseManualStop=yes", service)
        self.assertIn("ExecStart=/usr/bin/true", service)
        self.assertIn("ExecStop=/usr/lib/maho/update-campaign/current/bin/maho-update-coordinator activate-current", service)
        self.assertIn("RemainAfterExit=yes", service)
        self.assertIn("TimeoutStopSec=45s", service)
        self.assertNotIn("TimeoutStartSec=", service)
        self.assertIn("WantedBy=multi-user.target reboot.target", service)
        self.assertNotIn("systemctl reboot", service)
        self.assertNotIn("/sbin/reboot", service)
        self.assertIn("reboot.target.wants/maho-update-activate-on-reboot.service", package)
        self.assertIn("multi-user.target.wants/maho-update-activate-on-reboot.service", package)
        self.assertIn("systemctl start maho-update-activate-on-reboot.service", installer)
        self.assertIn("systemctl is-active --quiet maho-update-activate-on-reboot.service", installer)

    def test_reboot_activation_is_an_active_stop_hook_before_filesystem_teardown(self):
        service = (ROOT / "config/systemd/system/maho-update-activate-on-reboot.service").read_text()
        unit = {
            key: value
            for key, value in (
                line.split("=", 1)
                for line in service.splitlines()
                if "=" in line and not line.lstrip().startswith("#")
            )
        }
        self.assertEqual(unit["DefaultDependencies"], "no")
        self.assertEqual(unit["After"], "local-fs.target")
        self.assertEqual(unit["Conflicts"], "reboot.target")
        self.assertEqual(unit["Before"], "reboot.target")
        self.assertEqual(unit["ExecStart"], "/usr/bin/true")
        self.assertEqual(
            unit["ExecStop"],
            "/usr/lib/maho/update-campaign/current/bin/maho-update-coordinator activate-current",
        )
        self.assertEqual(unit["RemainAfterExit"], "yes")
        self.assertNotIn("shutdown.target", unit["Conflicts"])
        self.assertNotIn("poweroff.target", unit["Conflicts"])
        self.assertNotIn("umount.target", unit["Conflicts"])

    def test_native_ready_fails_closed_before_mutation_without_exact_boot_generation_publication(self):
        with tempfile.TemporaryDirectory() as state_tmp:
            env = {"MAHO_UPDATE_STATE_ROOT": state_tmp}
            ready = transition_transaction(
                prepared_tx(),
                UpdateState.MAINTENANCE_READY,
                reason="fixture native maintenance ready",
                now=NOW,
            )
            state = {
                **coordinator._base_state(NOW, REV),
                "active_transaction_id": TXID,
                "package_generation_id": ready["package_generation"]["id"],
                "lane": "native",
                "phase": "MAINTENANCE_READY",
                "repository_hashes": {"core": "1" * 64},
                "repository_observed_at": coordinator.stamp(NOW),
            }
            with patch.dict(os.environ, env, clear=False):
                publish_transaction(Path(state_tmp), ready)
                result = coordinator._resume_owned(
                    state,
                    REV,
                    "magetsu",
                    {"source_revision": REV},
                    {"config_path": "/etc/maho/pacman.conf", "repositories": ["core"]},
                    NOW,
                )
                stored = read_transaction(transaction_path(Path(state_tmp), TXID))
            self.assertIsNotNone(result)
            self.assertEqual(result["phase"], "BLOCKED")
            self.assertEqual(
                result["blockers"],
                ["native_boot_generation_publication_unavailable"],
            )
            self.assertFalse(result["live_root_mutation_started"])
            self.assertFalse(result["reboot_performed"])
            self.assertEqual(stored["state"], "BLOCKED")
            self.assertEqual(
                stored["blockers"],
                ["native_boot_generation_publication_unavailable"],
            )

    def test_post_reboot_pending_state_verifies_and_reports_healthy(self):
        with tempfile.TemporaryDirectory() as state_tmp:
            root = Path(state_tmp)
            pending = transition_transaction(
                transition_transaction(
                    transition_transaction(
                        prepared_tx(),
                        UpdateState.MAINTENANCE_READY,
                        reason="fixture maintenance ready",
                        now=NOW,
                    ),
                    UpdateState.INSTALLING,
                    now=NOW,
                ),
                UpdateState.INSTALLED_PENDING_ACTIVATION,
                now=NOW,
            )
            publish_transaction(root, pending)
            state = {
                **coordinator._base_state(NOW, REV),
                "active_transaction_id": TXID,
                "package_generation_id": pending["package_generation"]["id"],
                "lane": "normal",
                "phase": "MAINTENANCE_READY",
            }
            record = {
                "phase": "ACTIVATION_ARMED",
                "activation_handoff": {"handoff_id": "art-" + "a" * 64},
                "candidate_generation": {"system_generation_id": "gen-" + "b" * 64},
            }
            with patch.dict(os.environ, {"MAHO_UPDATE_STATE_ROOT": state_tmp}, clear=False), \
                 patch("maho_update_automatic_execution.finalize_pending_normal", return_value=record), \
                 patch("maho_update_automatic_execution.verify_activated_normal", return_value={
                     "phase": "HEALTHY",
                     "root_uuid": "22222222-2222-2222-2222-222222222222",
                 }):
                result = coordinator._resume_owned(
                    state,
                    REV,
                    "magetsu",
                    {"source_revision": REV},
                    {"config_path": "/etc/maho/pacman.conf", "repositories": ["core"]},
                    NOW,
                )
            self.assertEqual(result["phase"], "HEALTHY")
            self.assertFalse(result["reboot_required"])
            self.assertTrue(result["reboot_performed"])
            self.assertEqual(result["user_status"], "Update verified after restart.")

    def test_postboot_failure_enters_exact_recovery_instead_of_false_healthy(self):
        with tempfile.TemporaryDirectory() as state_tmp:
            root = Path(state_tmp)
            pending = transition_transaction(
                transition_transaction(
                    transition_transaction(
                        prepared_tx(), UpdateState.MAINTENANCE_READY, now=NOW,
                    ),
                    UpdateState.INSTALLING, now=NOW,
                ),
                UpdateState.INSTALLED_PENDING_ACTIVATION, now=NOW,
            )
            publish_transaction(root, pending)
            state = {
                **coordinator._base_state(NOW, REV),
                "active_transaction_id": TXID,
                "package_generation_id": pending["package_generation"]["id"],
                "lane": "normal", "phase": "READY_TO_RESTART",
            }
            record = {
                "phase": "ACTIVATION_ARMED",
                "activation_handoff": {"handoff_id": "art-" + "a" * 64},
                "candidate_generation": {"system_generation_id": "gen-" + "b" * 64},
            }
            recovery_result = {
                "phase": "RECOVERING",
                "reboot_required": True,
                "reboot_performed": False,
                "failed_candidate_uuid": "22222222-2222-2222-2222-222222222222",
                "selected_root_uuid": "11111111-1111-1111-1111-111111111111",
                "filesystem_uuid": "33333333-3333-3333-3333-333333333333",
            }
            selected_state = root / "selected-state"
            selected_state.mkdir()

            class SelectedRootOps:
                closed = False

                def __init__(self, transaction_id):
                    self.transaction_id = transaction_id

                def selected_state_root_for_recovery(self, **kwargs):
                    type(self).assertions = kwargs
                    return selected_state

                def close(self):
                    assert (selected_state / "coordinator.json").is_file()
                    type(self).closed = True
            with patch.dict(os.environ, {"MAHO_UPDATE_STATE_ROOT": state_tmp}, clear=False), \
                 patch("maho_update_automatic_execution.finalize_pending_normal", return_value=record), \
                 patch("maho_update_automatic_execution.verify_activated_normal", side_effect=RuntimeError("controlled failure")), \
                 patch("maho_update_bad_recovery.begin_bad_update_recovery", return_value=recovery_result) as begin, \
                 patch.object(coordinator, "NativeBtrfsOps", SelectedRootOps):
                result = coordinator._resume_owned(
                    state, REV, "magetsu", {"source_revision": REV},
                    {"config_path": "/etc/maho/pacman.conf", "repositories": ["core"]},
                    NOW,
                )
            self.assertEqual(result["phase"], "RECOVERING")
            self.assertTrue(result["reboot_required"])
            self.assertFalse(result["reboot_performed"])
            self.assertTrue((selected_state / "coordinator.json").is_file())
            self.assertEqual(
                SelectedRootOps.assertions,
                {
                    "expected_failed_uuid": "22222222-2222-2222-2222-222222222222",
                    "expected_previous_uuid": "11111111-1111-1111-1111-111111111111",
                    "expected_filesystem_uuid": "33333333-3333-3333-3333-333333333333",
                },
            )
            self.assertTrue(SelectedRootOps.closed)
            self.assertNotEqual(result["phase"], "HEALTHY")
            begin.assert_called_once()

    def test_postboot_recovery_interruption_resumes_before_attention(self):
        with tempfile.TemporaryDirectory() as state_tmp:
            root = Path(state_tmp)
            pending = transition_transaction(
                transition_transaction(
                    transition_transaction(
                        prepared_tx(), UpdateState.MAINTENANCE_READY, now=NOW,
                    ),
                    UpdateState.INSTALLING, now=NOW,
                ),
                UpdateState.INSTALLED_PENDING_ACTIVATION, now=NOW,
            )
            publish_transaction(root, pending)
            state = {
                **coordinator._base_state(NOW, REV),
                "active_transaction_id": TXID,
                "package_generation_id": pending["package_generation"]["id"],
                "lane": "normal", "phase": "READY_TO_RESTART",
            }
            record = {
                "phase": "ACTIVATION_ARMED",
                "activation_handoff": {"handoff_id": "art-" + "a" * 64},
                "candidate_generation": {"system_generation_id": "gen-" + "b" * 64},
            }

            def interrupted_begin(*_args, **_kwargs):
                durable = read_transaction(transaction_path(root, TXID))
                durable = transition_transaction(
                    durable, UpdateState.ACTIVE_VERIFYING, now=NOW,
                )
                durable = transition_transaction(
                    durable, UpdateState.RECOVERING, now=NOW,
                )
                publish_transaction(root, durable)
                raise RuntimeError("interrupted after root exchange")

            resumed = {
                "phase": "RECOVERING", "reboot_required": True,
                "reboot_performed": False, "recovery_attempts": 1,
                "reconciled_after_interruption": True,
            }
            with patch.dict(os.environ, {"MAHO_UPDATE_STATE_ROOT": state_tmp}, clear=False), \
                 patch("maho_update_automatic_execution.finalize_pending_normal", return_value=record), \
                 patch("maho_update_automatic_execution.verify_activated_normal", side_effect=RuntimeError("controlled failure")), \
                 patch("maho_update_bad_recovery.begin_bad_update_recovery", side_effect=interrupted_begin), \
                 patch("maho_update_bad_recovery.resume_bad_update_recovery", return_value=resumed) as resume, \
                 patch("maho_update_bad_recovery.attention_after_recovery_failure") as attention:
                result = coordinator._resume_owned(
                    state, REV, "magetsu", {"source_revision": REV},
                    {"config_path": "/etc/maho/pacman.conf", "repositories": ["core"]},
                    NOW,
                )
            self.assertEqual(result["phase"], "RECOVERING")
            self.assertTrue(result["reboot_required"])
            self.assertFalse(result["reboot_performed"])
            resume.assert_called_once()
            attention.assert_not_called()

    def test_postboot_recovery_start_failure_converges_to_attention(self):
        with tempfile.TemporaryDirectory() as state_tmp:
            root = Path(state_tmp)
            pending = transition_transaction(
                transition_transaction(
                    transition_transaction(
                        prepared_tx(), UpdateState.MAINTENANCE_READY, now=NOW,
                    ),
                    UpdateState.INSTALLING, now=NOW,
                ),
                UpdateState.INSTALLED_PENDING_ACTIVATION, now=NOW,
            )
            publish_transaction(root, pending)
            state = {
                **coordinator._base_state(NOW, REV),
                "active_transaction_id": TXID,
                "package_generation_id": pending["package_generation"]["id"],
                "lane": "normal", "phase": "READY_TO_RESTART",
            }
            record = {
                "phase": "ACTIVATION_ARMED",
                "activation_handoff": {"handoff_id": "art-" + "a" * 64},
                "candidate_generation": {"system_generation_id": "gen-" + "b" * 64},
            }
            with patch.dict(os.environ, {"MAHO_UPDATE_STATE_ROOT": state_tmp}, clear=False), \
                 patch("maho_update_automatic_execution.finalize_pending_normal", return_value=record), \
                 patch("maho_update_automatic_execution.verify_activated_normal", side_effect=RuntimeError("package query failed")), \
                 patch("maho_update_bad_recovery.begin_bad_update_recovery", side_effect=RuntimeError("recovery evidence invalid")), \
                 patch("maho_update_bad_recovery.attention_after_recovery_failure", return_value={"phase": "ATTENTION_REQUIRED"}) as attention:
                result = coordinator._resume_owned(
                    state, REV, "magetsu", {"source_revision": REV},
                    {"config_path": "/etc/maho/pacman.conf", "repositories": ["core"]},
                    NOW,
                )
            self.assertEqual(result["phase"], "ATTENTION_REQUIRED")
            self.assertEqual(result["blockers"], ["bad_update_recovery_evidence_invalid"])
            self.assertEqual(result["last_error"], "recovery evidence invalid")
            self.assertFalse(result["reboot_required"])
            self.assertTrue(result["reboot_performed"])
            attention.assert_called_once()

    def test_recovering_transaction_verifies_once_and_converges_recovered(self):
        with tempfile.TemporaryDirectory() as state_tmp:
            root = Path(state_tmp)
            transaction = transition_transaction(
                transition_transaction(
                    transition_transaction(
                        transition_transaction(
                            prepared_tx(), UpdateState.MAINTENANCE_READY, now=NOW,
                        ),
                        UpdateState.INSTALLING, now=NOW,
                    ),
                    UpdateState.INSTALLED_PENDING_ACTIVATION, now=NOW,
                ),
                UpdateState.ACTIVE_VERIFYING, now=NOW,
            )
            transaction = transition_transaction(transaction, UpdateState.RECOVERING, now=NOW)
            publish_transaction(root, transaction)
            state = {
                **coordinator._base_state(NOW, REV),
                "active_transaction_id": TXID,
                "package_generation_id": transaction["package_generation"]["id"],
                "lane": "normal", "phase": "RECOVERING",
            }
            recovered = {
                "phase": "RECOVERED", "reboot_required": False,
                "reboot_performed": True, "recovery_attempts": 1,
            }
            with patch.dict(os.environ, {"MAHO_UPDATE_STATE_ROOT": state_tmp}, clear=False), \
                 patch("maho_update_bad_recovery._read_record", return_value={"phase": "RECOVERY_ARMED"}), \
                 patch("maho_update_bad_recovery.verify_recovered_normal", return_value=recovered) as verify:
                result = coordinator._resume_owned(
                    state, REV, "magetsu", {"source_revision": REV},
                    {"config_path": "/etc/maho/pacman.conf", "repositories": ["core"]},
                    NOW,
                )
            self.assertEqual(result["phase"], "RECOVERED")
            self.assertFalse(result["reboot_required"])
            self.assertTrue(result["reboot_performed"])
            verify.assert_called_once()

    def test_pending_terminal_verification_survives_preterminal_coordinator_error(self):
        with tempfile.TemporaryDirectory() as state_tmp:
            root = Path(state_tmp)
            transaction = prepared_tx()
            for phase in (
                UpdateState.MAINTENANCE_READY,
                UpdateState.INSTALLING,
                UpdateState.INSTALLED_PENDING_ACTIVATION,
                UpdateState.ACTIVE_VERIFYING,
                UpdateState.RECOVERING,
            ):
                transaction = transition_transaction(transaction, phase, now=NOW)
            publish_transaction(root, transaction)
            verification = {
                "failed_candidate_uuid": "2" * 8 + "-2222-2222-2222-" + "2" * 12,
                "failed_system_generation_id": "gen-" + "3" * 64,
                "recovered_root_uuid": "1" * 8 + "-1111-1111-1111-" + "1" * 12,
                "recovered_system_generation_id": "gen-" + "4" * 64,
                "kernel_generation_id": "kgen-" + "5" * 64,
                "package_versions": {"demo": "1"},
                "recovery_attempts": 1,
            }
            pending = {
                "phase": "RECOVERED_VERIFIED_PENDING_TRANSACTION",
                "transaction_state": "RECOVERING",
                "recovery_attempts": 1,
                "post_recovery_verification": verification,
            }
            state = {
                **coordinator._base_state(NOW, REV),
                "active_transaction_id": TXID,
                "lane": "normal", "phase": "RECOVERING",
            }
            with patch.dict(os.environ, {"MAHO_UPDATE_STATE_ROOT": state_tmp}, clear=False), \
                 patch("maho_update_bad_recovery._read_record", return_value=pending), \
                 patch(
                     "maho_update_bad_recovery.verify_recovered_normal",
                     side_effect=OSError("injected transaction publication interruption"),
                 ), \
                 patch("maho_update_bad_recovery.resume_bad_update_recovery") as resume, \
                 patch("maho_update_bad_recovery.attention_after_recovery_failure") as attention:
                result = coordinator._resume_owned(
                    state, REV, "magetsu", {"source_revision": REV},
                    {"config_path": "/etc/maho/pacman.conf", "repositories": ["core"]},
                    NOW,
                )
            self.assertEqual(result["phase"], "RECOVERING")
            self.assertEqual(result["blockers"], ["recovery_terminal_commit_retry_required"])
            self.assertEqual(
                read_transaction(transaction_path(root, TXID))["state"], "RECOVERING",
            )
            resume.assert_not_called()
            attention.assert_not_called()

    def test_pending_terminal_verification_reconciles_after_postterminal_coordinator_error(self):
        with tempfile.TemporaryDirectory() as state_tmp:
            root = Path(state_tmp)
            transaction = prepared_tx()
            for phase in (
                UpdateState.MAINTENANCE_READY,
                UpdateState.INSTALLING,
                UpdateState.INSTALLED_PENDING_ACTIVATION,
                UpdateState.ACTIVE_VERIFYING,
                UpdateState.RECOVERING,
            ):
                transaction = transition_transaction(transaction, phase, now=NOW)
            publish_transaction(root, transaction)
            recovered_root = "1" * 8 + "-1111-1111-1111-" + "1" * 12
            recovered_generation = "gen-" + "4" * 64
            verification = {
                "failed_candidate_uuid": "2" * 8 + "-2222-2222-2222-" + "2" * 12,
                "failed_system_generation_id": "gen-" + "3" * 64,
                "recovered_root_uuid": recovered_root,
                "recovered_system_generation_id": recovered_generation,
                "kernel_generation_id": "kgen-" + "5" * 64,
                "package_versions": {"demo": "1"},
                "recovery_attempts": 1,
            }
            armed = {"phase": "RECOVERY_ARMED", "recovery_attempts": 1}
            pending = {
                "phase": "RECOVERED_VERIFIED_PENDING_TRANSACTION",
                "transaction_state": "RECOVERING",
                "recovery_attempts": 1,
                "post_recovery_verification": verification,
            }
            state = {
                **coordinator._base_state(NOW, REV),
                "active_transaction_id": TXID,
                "lane": "normal", "phase": "RECOVERING",
            }

            def interrupt_after_terminal(*_args, **_kwargs):
                durable = read_transaction(transaction_path(root, TXID))
                durable = transition_transaction(
                    durable, UpdateState.RECOVERED, evidence=verification, now=NOW,
                )
                publish_transaction(root, durable)
                raise OSError("injected final record interruption")

            with patch.dict(os.environ, {"MAHO_UPDATE_STATE_ROOT": state_tmp}, clear=False), \
                 patch("maho_update_bad_recovery._read_record", side_effect=(armed, pending)), \
                 patch(
                     "maho_update_bad_recovery.verify_recovered_normal",
                     side_effect=interrupt_after_terminal,
                 ), \
                 patch("maho_update_bad_recovery.attention_after_recovery_failure") as attention:
                interrupted = coordinator._resume_owned(
                    state, REV, "magetsu", {"source_revision": REV},
                    {"config_path": "/etc/maho/pacman.conf", "repositories": ["core"]},
                    NOW,
                )
            self.assertEqual(interrupted["phase"], "ATTENTION_REQUIRED")
            self.assertEqual(
                interrupted["blockers"], ["recovery_terminal_commit_retry_required"],
            )
            self.assertEqual(
                read_transaction(transaction_path(root, TXID))["state"], "RECOVERED",
            )
            self.assertEqual(interrupted["recovery"]["root_uuid"], recovered_root)
            attention.assert_not_called()

            final_record = {
                **pending,
                "phase": "RECOVERED_VERIFIED",
                "transaction_state": "RECOVERED",
            }
            current = {
                "phase": "RECOVERED", "root_uuid": recovered_root,
                "system_generation_id": recovered_generation,
                "recovery_attempts": 1,
            }
            with patch.dict(os.environ, {"MAHO_UPDATE_STATE_ROOT": state_tmp}, clear=False), \
                 patch("maho_update_bad_recovery.reverify_recovered_normal", return_value=current), \
                 patch("maho_update_bad_recovery._read_record", return_value=final_record):
                reconciled = coordinator._resume_owned(
                    interrupted, REV, "magetsu", {"source_revision": REV},
                    {"config_path": "/etc/maho/pacman.conf", "repositories": ["core"]},
                    NOW + timedelta(minutes=1),
                )
            self.assertEqual(reconciled["phase"], "RECOVERED")
            self.assertEqual(reconciled["recovery"]["recovery_attempts"], 1)

    def test_recovered_transaction_is_terminal_only_with_exact_current_verified_evidence(self):
        with tempfile.TemporaryDirectory() as state_tmp:
            root = Path(state_tmp)
            transaction = prepared_tx()
            for phase in (
                UpdateState.MAINTENANCE_READY,
                UpdateState.INSTALLING,
                UpdateState.INSTALLED_PENDING_ACTIVATION,
                UpdateState.ACTIVE_VERIFYING,
                UpdateState.RECOVERING,
                UpdateState.RECOVERED,
            ):
                transaction = transition_transaction(transaction, phase, now=NOW)
            publish_transaction(root, transaction)
            recovered_root = "1" * 8 + "-1111-1111-1111-" + "1" * 12
            recovered_generation = "gen-" + "2" * 64
            state = {
                **coordinator._base_state(NOW, REV),
                "active_transaction_id": TXID,
                "lane": "normal",
                "phase": "RECOVERED",
                "reboot_required": False,
                "reboot_performed": True,
                "recovery": {
                    "transaction_id": TXID,
                    "phase": "RECOVERED",
                    "root_uuid": recovered_root,
                    "system_generation_id": recovered_generation,
                    "recovery_attempts": 1,
                },
            }
            record = {
                "phase": "RECOVERED_VERIFIED",
                "transaction_state": "RECOVERED",
                "recovery_attempts": 1,
                "post_recovery_verification": {
                    "recovered_root_uuid": recovered_root,
                    "recovered_system_generation_id": recovered_generation,
                    "recovery_attempts": 1,
                },
            }
            current = {
                "phase": "RECOVERED",
                "root_uuid": recovered_root,
                "system_generation_id": recovered_generation,
                "recovery_attempts": 1,
            }
            with patch.dict(os.environ, {"MAHO_UPDATE_STATE_ROOT": state_tmp}, clear=False), \
                 patch("maho_update_bad_recovery._read_record", return_value=record), \
                 patch("maho_update_bad_recovery.reverify_recovered_normal", return_value=current) as reverify:
                result = coordinator._resume_owned(
                    state, REV, "magetsu", {"source_revision": REV},
                    {"config_path": "/etc/maho/pacman.conf", "repositories": ["core"]},
                    NOW + timedelta(minutes=1),
                )
            self.assertEqual(result["phase"], "RECOVERED")
            self.assertEqual(result["active_transaction_id"], TXID)
            self.assertFalse(result["reboot_required"])
            self.assertTrue(result["reboot_performed"])
            reverify.assert_called_once()

            with patch.dict(os.environ, {"MAHO_UPDATE_STATE_ROOT": state_tmp}, clear=False), \
                 patch(
                     "maho_update_bad_recovery.reverify_recovered_normal",
                     side_effect=RuntimeError("live recovered root identity drifted"),
                 ):
                drifted = coordinator._resume_owned(
                    state, REV, "magetsu", {"source_revision": REV},
                    {"config_path": "/etc/maho/pacman.conf", "repositories": ["core"]},
                    NOW + timedelta(minutes=2),
                )
            self.assertEqual(drifted["phase"], "ATTENTION_REQUIRED")
            self.assertEqual(drifted["blockers"], ["recovered_state_evidence_invalid"])
            self.assertIn("identity drifted", drifted["last_error"])

    def test_historical_recovered_transaction_is_not_treated_as_current(self):
        with tempfile.TemporaryDirectory() as state_tmp:
            root = Path(state_tmp)
            recovered = prepared_tx()
            for phase in (
                UpdateState.MAINTENANCE_READY,
                UpdateState.INSTALLING,
                UpdateState.INSTALLED_PENDING_ACTIVATION,
                UpdateState.ACTIVE_VERIFYING,
                UpdateState.RECOVERING,
                UpdateState.RECOVERED,
            ):
                recovered = transition_transaction(recovered, phase, now=NOW)
            publish_transaction(root, recovered)
            newer_id = "upd-20260927T080000Z-bbbbbbbbbbbb"
            publish_transaction(root, prepared_tx(txid=newer_id))
            state = {
                **coordinator._base_state(NOW, REV),
                "active_transaction_id": TXID,
                "lane": "normal",
                "phase": "RECOVERED",
            }
            with patch.dict(os.environ, {"MAHO_UPDATE_STATE_ROOT": state_tmp}, clear=False):
                result = coordinator._resume_owned(
                    state, REV, "magetsu", {"source_revision": REV},
                    {"config_path": "/etc/maho/pacman.conf", "repositories": ["core"]},
                    NOW + timedelta(minutes=1),
                )
            self.assertIsNone(result)

    def test_discovery_uses_isolated_database_not_live_pacman_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = IsolatedPacmanDiscovery(Path(tmp) / "discovery")
            command = backend.refresh_command
            dbpath = command[command.index("--dbpath") + 1]
            self.assertNotEqual(Path(dbpath).resolve(), Path("/var/lib/pacman").resolve())
            self.assertTrue(str(Path(dbpath)).startswith(tmp))
            self.assertNotIn("/var/lib/pacman", command)

    def test_canonical_repository_policy_requires_signatures(self):
        pacman = (ROOT / "config/platform/maho-pacman.conf").read_text()
        platform = json.loads((ROOT / "config/platform.json").read_text())
        self.assertIn("SigLevel = Required", pacman)
        self.assertEqual(
            platform["update"]["required_repositories"],
            ["core", "extra", "multilib", "cachyos"],
        )

    def test_no_update_observation_is_healthy_without_fake_transaction(self):
        with tempfile.TemporaryDirectory() as state_tmp, tempfile.TemporaryDirectory() as work_tmp:
            env = {
                "MAHO_UPDATE_STATE_ROOT": state_tmp,
                "MAHO_UPDATE_AUTO_WORK_ROOT": work_tmp,
            }
            repo = {
                "config_path": "/etc/maho/pacman.conf",
                "repositories": ["core", "extra", "multilib", "cachyos"],
            }
            with patch.dict(os.environ, env, clear=False),                  patch.object(coordinator, "IsolatedPacmanDiscovery", FakeDiscovery),                  patch.object(
                     coordinator,
                     "discover_independent_normal_updates",
                     side_effect=LookupError("no coherent update candidates were discovered"),
                 ),                  patch.object(coordinator, "_authority_state", return_value="stale-or-invalid"):
                state = coordinator._new_discovery(
                    None, REV, "testuser", {"source_revision": REV}, repo, NOW,
                )
            self.assertEqual(state["phase"], "UP_TO_DATE")
            self.assertEqual(state["candidate_count"], 0)
            self.assertIsNone(state["active_transaction_id"])
            self.assertEqual(state["update_debt_seconds"], 0)
            self.assertFalse((Path(state_tmp) / "transactions").exists())

    def test_update_debt_preserves_first_observed_time_across_runs(self):
        state = coordinator._base_state(NOW, REV)
        state["first_observed_at"] = coordinator.stamp(NOW)
        later = NOW + timedelta(days=3, seconds=17)
        updated = coordinator._with_debt(state, later)
        self.assertEqual(updated["first_observed_at"], coordinator.stamp(NOW))
        self.assertEqual(updated["update_debt_seconds"], 3 * 86400 + 17)

    def test_duplicate_coordinator_work_coalesces_on_shared_campaign_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "campaign.lock"
            with coordinator.coordinator_mutex(lock):
                with self.assertRaises(coordinator.CoordinatorBusy):
                    with coordinator.coordinator_mutex(lock):
                        pass

    def test_retry_is_bounded_and_not_a_busy_loop(self):
        values = [coordinator._retry_delay(i).total_seconds() for i in range(1, 12)]
        self.assertEqual(values[0], 300)
        self.assertTrue(all(a <= b for a, b in zip(values, values[1:])))
        self.assertLessEqual(values[-1], 3600)

    def test_valid_adaptive_opportunity_is_accepted(self):
        ready, reasons = coordinator._adaptive_ready(adaptive_record())
        self.assertTrue(ready)
        self.assertEqual(reasons, [])

    def test_user_activity_cancels_maintenance_readiness(self):
        for domain, change, expected in (
            ("session", {"locked": False}, "session_not_locked"),
            ("session", {"idle_seconds": 10}, "idle_dwell_too_short_or_unknown"),
            ("workload", {"interactive": True}, "interactive_workload"),
        ):
            with self.subTest(expected=expected):
                ready, reasons = coordinator._adaptive_ready(adaptive_record(**{domain: change}))
                self.assertFalse(ready)
                self.assertIn(expected, reasons)

    def test_power_thermal_and_network_loss_cancel_readiness(self):
        for domain, change, expected in (
            ("power", {"ac_online": False}, "stable_ac_required"),
            ("power", {"percentage": 10}, "battery_not_healthy"),
            ("thermal", {"level": "hot"}, "thermal_state_not_acceptable"),
            ("network", {"connectivity": "offline"}, "network_not_stable"),
        ):
            with self.subTest(expected=expected):
                ready, reasons = coordinator._adaptive_ready(adaptive_record(**{domain: change}))
                self.assertFalse(ready)
                self.assertIn(expected, reasons)

    def test_gaming_compile_and_render_cancel_readiness(self):
        for key, expected in (
            ("gaming", "interactive_workload"),
            ("compile", "compile_in_progress"),
            ("rendering", "render_in_progress"),
        ):
            with self.subTest(workload=key):
                ready, reasons = coordinator._adaptive_ready(
                    adaptive_record(workload={key: True}),
                )
                self.assertFalse(ready)
                self.assertIn(expected, reasons)

    def test_guardian_incident_cancels_readiness(self):
        ready, reasons = coordinator._adaptive_ready(
            adaptive_record(guardian={"active_incident": True, "severity_level": 2}),
        )
        self.assertFalse(ready)
        self.assertIn("guardian_unhealthy", reasons)
        self.assertIn("guardian_severity_blocks_maintenance", reasons)

    def test_missing_or_stale_adaptive_evidence_fails_closed(self):
        uid = os.getuid()
        with tempfile.TemporaryDirectory() as home:
            record = SimpleNamespace(pw_uid=uid, pw_dir=home)
            path = Path(home) / ".local/state/maho/adaptive/current.json"
            with patch.object(coordinator.pwd, "getpwnam", return_value=record):
                with self.assertRaisesRegex(RuntimeError, "adaptive_maintenance_evidence_missing"):
                    coordinator._read_adaptive_status("user", NOW)
                path.parent.mkdir(parents=True)
                stale = adaptive_record()
                stale["captured_at"] = coordinator.stamp(NOW - timedelta(minutes=5))
                path.write_text(json.dumps(stale))
                path.chmod(0o600)
                with self.assertRaisesRegex(RuntimeError, "adaptive_maintenance_evidence_stale"):
                    coordinator._read_adaptive_status("user", NOW)

    def test_stale_repository_generation_invalidates_prepared_transaction(self):
        tx = prepared_tx()
        state = {
            "repository_observed_at": coordinator.stamp(NOW - timedelta(hours=1)),
            "repository_hashes": {"core": "old"},
        }
        repo = {"config_path": "/etc/maho/pacman.conf", "repositories": ["core"]}
        with patch.object(coordinator, "_repo_hashes", return_value={"core": "new"}):
            current, next_state, ok = coordinator._revalidate_repository(tx, state, repo, NOW)
        self.assertFalse(ok)
        self.assertEqual(current["state"], "BLOCKED")
        self.assertEqual(current["blockers"], ["repository_generation_drifted"])
        self.assertEqual(next_state["phase"], "INVALIDATED")

    def test_invalidated_transaction_is_not_resumed_after_restart(self):
        state = {
            "schema_version": 1,
            "source_revision": REV,
            "phase": "INVALIDATED",
            "active_transaction_id": TXID,
            "lane": "normal",
            "blockers": ["repository_generation_drifted"],
        }
        resumed = coordinator._resume_owned(
            state,
            REV,
            "testuser",
            {"source_revision": REV},
            {"config_path": "/etc/maho/pacman.conf", "repositories": ["core"]},
            NOW,
        )
        self.assertIsNone(resumed)

    def test_normal_authority_must_cover_exact_prepared_plan_scope(self):
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
        tx = transition_transaction(
            tx,
            UpdateState.PREPARED,
            evidence={
                "normal_plan": {
                    "effects": ["ordinary-files-in-place"],
                    "activation_requirements": [],
                },
            },
            now=NOW,
        )
        with patch.object(coordinator, "load_normal_execution_authority", return_value={"authority_id": "fixture"}), \
             patch.object(coordinator, "authorize_normal_plan", side_effect=ValueError("scope exceeded")) as authorize:
            observed = coordinator._authority_state(REV, "normal", transaction=tx)
        self.assertEqual(observed, "scope-mismatch")
        authorize.assert_called_once_with(
            {"authority_id": "fixture"},
            source_revision=REV,
            effects=("ordinary-files-in-place",),
            activation_requirements=(),
        )

    def test_stale_normal_execution_authority_is_a_real_ready_blocker(self):
        tx = prepared_tx()
        state = {
            "lane": "normal",
            "repository_hashes": {"core": "1" * 64},
            "repository_observed_at": coordinator.stamp(NOW),
            "first_observed_at": coordinator.stamp(NOW),
        }
        with patch.object(coordinator, "_authority_state", return_value="stale-or-invalid"):
            current, evidence = coordinator._maintenance_transition(
                tx, state, "testuser", {"source_revision": REV}, NOW,
            )
        self.assertEqual(current["state"], "PREPARED")
        self.assertFalse(evidence["ready"])
        self.assertEqual(
            evidence["reasons"],
            ["normal_execution_authority_stale_or_invalid"],
        )

    def test_valid_ready_transition_binds_exact_evidence(self):
        tx = prepared_tx()
        state = {
            "lane": "normal",
            "repository_hashes": {"core": "1" * 64},
            "repository_observed_at": coordinator.stamp(NOW),
            "first_observed_at": coordinator.stamp(NOW - timedelta(days=2)),
        }
        runtime = {
            "source_revision": REV,
            "content_sha256": "b" * 64,
            "verified": True,
        }
        fake_usage = SimpleNamespace(total=20 * 1024**3, used=1, free=15 * 1024**3)
        with tempfile.TemporaryDirectory() as work_tmp:
            cache = Path(work_tmp) / TXID / "staging"
            cache.mkdir(parents=True)
            with patch.dict(os.environ, {"MAHO_UPDATE_AUTO_WORK_ROOT": work_tmp}, clear=False),                  patch.object(coordinator, "_authority_state", return_value="current"),                  patch.object(coordinator, "_read_adaptive_status", return_value=adaptive_record()),                  patch.object(coordinator, "_generation_is_current", return_value=True),                  patch.object(coordinator, "_candidate_capability", return_value=True),                  patch.object(coordinator.shutil, "disk_usage", return_value=fake_usage):
                current, evidence = coordinator._maintenance_transition(
                    tx, state, "testuser", runtime, NOW,
                )
        self.assertEqual(current["state"], "MAINTENANCE_READY")
        self.assertTrue(evidence["ready"])
        event = current["history"][-1]
        bound = event["evidence"]["coordinator"]
        self.assertEqual(bound["transaction_id"], TXID)
        self.assertEqual(bound["package_generation_id"], tx["package_generation"]["id"])
        self.assertEqual(bound["source_revision"], REV)
        self.assertEqual(bound["runtime_identity"], runtime)
        self.assertEqual(bound["adaptive_snapshot_id"], "sit-test")
        self.assertTrue(bound["evidence_fresh"])
        self.assertTrue(bound["recovery_ready"])
        self.assertTrue(bound["disk_ready"])
        self.assertEqual(bound["decision_at"], coordinator.stamp(NOW))

    def test_insufficient_disk_and_recovery_capability_defer(self):
        tx = prepared_tx()
        state = {
            "lane": "normal",
            "repository_hashes": {"core": "1" * 64},
            "repository_observed_at": coordinator.stamp(NOW),
            "first_observed_at": coordinator.stamp(NOW),
        }
        fake_usage = SimpleNamespace(total=2 * 1024**3, used=1, free=512 * 1024**2)
        with tempfile.TemporaryDirectory() as work_tmp:
            (Path(work_tmp) / TXID / "staging").mkdir(parents=True)
            with patch.dict(os.environ, {"MAHO_UPDATE_AUTO_WORK_ROOT": work_tmp}, clear=False),                  patch.object(coordinator, "_authority_state", return_value="current"),                  patch.object(coordinator, "_read_adaptive_status", return_value=adaptive_record()),                  patch.object(coordinator, "_generation_is_current", return_value=True),                  patch.object(coordinator, "_candidate_capability", return_value=False),                  patch.object(coordinator.shutil, "disk_usage", return_value=fake_usage):
                current, evidence = coordinator._maintenance_transition(
                    tx, state, "testuser", {"source_revision": REV}, NOW,
                )
        self.assertEqual(current["state"], "PREPARED")
        self.assertIn("disk_headroom_unconfirmed", evidence["reasons"])
        self.assertIn("recovery_prerequisites_unready", evidence["reasons"])

    def test_prepared_restart_resumes_waiting_without_execution(self):
        with tempfile.TemporaryDirectory() as state_tmp:
            env = {"MAHO_UPDATE_STATE_ROOT": state_tmp}
            tx = prepared_tx()
            with patch.dict(os.environ, env, clear=False):
                publish_transaction(Path(state_tmp), tx)
                state = {
                    "schema_version": 1,
                    "source_revision": REV,
                    "phase": "WAITING_MAINTENANCE",
                    "active_transaction_id": TXID,
                    "lane": "normal",
                    "repository_hashes": {"core": "1" * 64},
                    "repository_observed_at": coordinator.stamp(NOW),
                    "first_observed_at": coordinator.stamp(NOW),
                    "blockers": [],
                }
                with patch.object(coordinator, "_authority_state", return_value="stale-or-invalid"):
                    resumed = coordinator._resume_owned(
                        state,
                        REV,
                        "testuser",
                        {"source_revision": REV},
                        {"config_path": "/etc/maho/pacman.conf", "repositories": ["core"]},
                        NOW,
                    )
                stored = read_transaction(transaction_path(Path(state_tmp), TXID))
            self.assertEqual(stored["state"], "PREPARED")
            self.assertEqual(resumed["phase"], "WAITING_MAINTENANCE")
            self.assertIn("normal_execution_authority_stale_or_invalid", resumed["blockers"])
            self.assertFalse(resumed.get("live_root_mutation_started", False))

    def test_maintenance_policy_records_exact_authority_envelope(self):
        tx = prepared_tx()
        context = MaintenanceContext(
            intent="none",
            active_user=False,
            fullscreen_or_gaming=False,
            idle_seconds=3600,
            locked=True,
            power_status_known=True,
            on_ac=True,
            battery_percent=100,
            system_safe=True,
            concurrent_package_or_build_operation=False,
            unattended_allowed=True,
            serious_security_issue=False,
            update_debt_days=2,
            adaptive_maintenance="eligible",
        )
        envelope = {
            "transaction_id": TXID,
            "package_generation_id": tx["package_generation"]["id"],
            "source_revision": REV,
            "evidence_fresh": True,
        }
        decision = evaluate_maintenance(
            tx, context, authority_evidence=envelope, now=NOW,
        )
        self.assertEqual(decision.transaction["state"], "MAINTENANCE_READY")
        self.assertEqual(
            decision.transaction["history"][-1]["evidence"]["coordinator"],
            envelope,
        )

    def test_s2_source_contains_no_execution_or_reboot_path(self):
        source = (ROOT / "lib/maho_update_coordinator.py").read_text()
        wrapper = (ROOT / "bin/maho-update-coordinator").read_text()
        self.assertNotIn("execute_normal_update", source)
        self.assertNotIn("execute_native_campaign", source)
        self.assertNotIn("arm_native_activation", source)
        self.assertNotIn("verify_native_activation", source)
        self.assertNotIn("pacman -Syu", source)
        self.assertNotIn("systemctl reboot", source)
        self.assertNotIn("/sbin/reboot", source)
        self.assertIn('"live_root_mutation_started": False', source)
        self.assertIn('"reboot_performed": False', source)
        self.assertIn("refusing non-root-owned campaign payload", wrapper)


if __name__ == "__main__":
    unittest.main(verbosity=2)
