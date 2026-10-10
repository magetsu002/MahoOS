#!/usr/bin/env python3
"""Convergence gates must reduce work without caching mutation permission."""
from datetime import timedelta
import copy
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from test_maho_update_coordinator import coordinator as c, prepared_tx, NOW, REV, TXID


class ConvergenceWait(unittest.TestCase):
    def state(self):
        return {**c._base_state(NOW, REV), "active_transaction_id": TXID,
                "lane": "normal", "repository_hashes": {"core": "b" * 64},
                "first_observed_at": c.stamp(NOW - timedelta(days=1))}

    def fingerprint(self, state, tx, conditions=None):
        return c._wait_evidence(state, tx, outcome="waiting-maintenance",
            conditions=conditions or {"veto": True}, resume_when="fresh evidence")

    def test_fingerprint_ignores_observation_time_and_preserves_debt(self):
        state, tx = self.state(), prepared_tx()
        first = self.fingerprint(state, tx)
        state.update(last_attempt_at=c.stamp(NOW + timedelta(hours=2)), wait_count=9,
                     update_debt_seconds=999, repository_observed_at=c.stamp(NOW))
        second = self.fingerprint(state, tx)
        self.assertEqual(first["convergence"], second["convergence"])
        self.assertEqual(second["first_observed_at"], first["first_observed_at"])
        self.assertFalse(second["convergence"]["execution_authorized"])

    def test_fingerprint_changes_for_relevant_identity_and_prerequisites(self):
        state, tx = self.state(), prepared_tx()
        original = self.fingerprint(state, tx)["convergence"]["evidence_fingerprint"]
        for change in ({"source_revision": "c" * 40}, {"repository_hashes": {"core": "d" * 64}},
                       {"runtime_identity": {"content_sha256": "e" * 64}}):
            self.assertNotEqual(original, self.fingerprint(state | change, tx)["convergence"]["evidence_fingerprint"])
        other = prepared_tx(txid="upd-20260927T070000Z-123456abcdef")
        self.assertNotEqual(original, self.fingerprint(state, other)["convergence"]["evidence_fingerprint"])
        self.assertNotEqual(original, self.fingerprint(state, tx, {"veto": False})["convergence"]["evidence_fingerprint"])
        effects = copy.deepcopy(tx)
        effects["history"][-1]["evidence"] = {"normal_plan": {"effects": ["shared-libraries"], "activation_requirements": ["service-restart"]}}
        self.assertNotEqual(original, self.fingerprint(state, effects)["convergence"]["evidence_fingerprint"])

    def test_unchanged_capacity_skips_preparation_and_transaction_events(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"MAHO_UPDATE_STATE_ROOT": tmp, "MAHO_UPDATE_AUTO_WORK_ROOT": tmp}), \
             patch.object(c, "_authority_state", return_value="current"), \
             patch.object(c, "_power_evidence", return_value=(True, True, 100)), \
             patch.object(c.shutil, "disk_usage", return_value=SimpleNamespace(total=200*1024**3, free=1024**3)), \
             patch.object(c, "_prepare_normal") as prepare, \
             patch.object(c, "_generation_is_current") as installed:
            tx = prepared_tx()
            # Exact staged owner: resource gate must run before manifest hashing.
            tx["state"] = "STAGED"
            tx["history"] = tx["history"][:-1]
            c.publish_transaction(Path(tmp), tx)
            cache = Path(tmp) / TXID / "staging"
            cache.mkdir(parents=True)
            manifest = c._manifest_for(cache, tx)
            manifest.write_text("archive validation must not happen while reserve fails")
            before = c.transaction_path(Path(tmp), TXID).read_bytes()
            state = self.state()
            fingerprints = set()
            for n in range(12):
                state = c._resume_owned(state, REV, "unused", {}, {}, NOW + timedelta(hours=n))
                fingerprints.add(state["convergence"]["evidence_fingerprint"])
                self.assertEqual(state["convergence"]["outcome"], "capacity-constrained")
                self.assertEqual(c.transaction_path(Path(tmp), TXID).read_bytes(), before)
                self.assertIsNone(state["last_success_at"])
            self.assertEqual(len(fingerprints), 1)
            prepare.assert_not_called()
            installed.assert_not_called()

    def test_threshold_crossing_resumes_full_preparation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"MAHO_UPDATE_STATE_ROOT": tmp}), \
             patch.object(c, "_power_evidence", return_value=(True, True, 100)), \
             patch.object(c.shutil, "disk_usage", return_value=SimpleNamespace(total=200*1024**3, free=60*1024**3)):
            self.assertIsNone(c._preparation_resource_wait(prepared_tx(), self.state(), Path(tmp), NOW))

    def test_veto_skips_repository_refresh_and_resumes_after_release(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"MAHO_UPDATE_STATE_ROOT": tmp, "MAHO_UPDATE_AUTO_WORK_ROOT": tmp}), \
             patch.object(c, "_authority_state", return_value="current"), \
             patch.object(c, "_adaptive_evidence", return_value=({}, {}, False, ["guardian_unhealthy"])) as adaptive, \
             patch.object(c, "_revalidate_repository", return_value=(prepared_tx(), self.state(), False)) as refresh:
            c.publish_transaction(Path(tmp), prepared_tx())
            before = c.transaction_path(Path(tmp), TXID).read_bytes()
            state = self.state()
            fingerprints = set()
            for n in range(12):
                state = c._resume_owned(state, REV, "unused", {}, {}, NOW + timedelta(hours=n))
                fingerprints.add(state["convergence"]["evidence_fingerprint"])
                self.assertEqual(c.transaction_path(Path(tmp), TXID).read_bytes(), before)
            self.assertEqual(len(fingerprints), 1)
            self.assertEqual(adaptive.call_count, 12)
            refresh.assert_not_called()
            adaptive.return_value = ({}, {}, True, [])
            c._resume_owned(state, REV, "unused", {}, {}, NOW + timedelta(hours=13))
            refresh.assert_called_once()

    def test_stale_provider_is_reobserved_and_denies(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"MAHO_UPDATE_STATE_ROOT": tmp}), \
             patch.object(c, "_adaptive_evidence", side_effect=RuntimeError("adaptive_maintenance_evidence_stale")) as fresh:
            for n in range(2):
                result = c._maintenance_preflight_wait(prepared_tx(), self.state(), "unused", NOW)
                self.assertIn("adaptive_maintenance_evidence_stale", result["blockers"])
                self.assertFalse(result["convergence"]["execution_authorized"])
            self.assertEqual(fresh.call_count, 2)

    def test_authority_rotation_is_observed_without_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "authority.json"
            real = c.os.fstat
            with patch("maho_update_normal_authority.DEFAULT_AUTHORITY_PATH", path), patch.object(c.os, "fstat", wraps=c.os.fstat) as info:
                # Observation is root-owned in VM; emulate that owner for this pure test.
                def owner(fd):
                    st = real(fd)
                    return SimpleNamespace(st_mode=st.st_mode, st_uid=0, st_size=st.st_size)
                info.side_effect = owner
                path.write_text('{"source_revision":"' + REV + '"}')
                first = c._authority_observation(REV)
                path.write_text('{"source_revision":"' + 'b'*40 + '"}')
                second = c._authority_observation(REV)
                self.assertNotEqual(first["sha256"], second["sha256"])
                self.assertFalse(second["source_binding_matches"])
                self.assertFalse(second["execution_authorized"])
                path.unlink()
                self.assertEqual(c._authority_observation(REV)["observation"], "unavailable")

    def test_success_discards_stale_waiting_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self.fingerprint(self.state(), prepared_tx())
            state["phase"] = "HEALTHY"
            self.assertNotIn("convergence", c._save(state, Path(tmp)))


if __name__ == "__main__":
    unittest.main()
