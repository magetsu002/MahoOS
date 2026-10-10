#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from maho_generation_gc import CertifiedFileGC, SimulatedCrash, InventoryError, IdentityMismatchError, StaleAuthorityError, digest_payload
from maho_update_artifact_lifecycle import UpdateArchiveLifecycle, reserve_bytes, staging_budget, archive_usage
from maho_update_state import create_transaction, transition_transaction, publish_transaction, UpdateState

NOW = datetime(2026, 10, 9, 16, 0, tzinfo=timezone.utc)
REV = 'a' * 40
OLD = 'upd-20261009T160000Z-aaaaaaaaaaaa'
ACTIVE = 'upd-20261009T160001Z-bbbbbbbbbbbb'


class ArchiveLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/root' if os.getuid() == 0 else None)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.cache = self.base / 'cache'
        self.state = self.base / 'update'
        self.generations = self.base / 'generations'
        self.guardian = self.base / 'guardian/active'
        (self.base / 'guardian').mkdir()
        (self.base / 'guardian/providers').mkdir()
        (self.base / 'guardian/providers/guardian.watch.json').write_text(json.dumps({
            'kind':'guardian-provider-heartbeat', 'schema_version':1, 'provider_id':'guardian.watch',
            'health':'healthy', 'authority_boundary':'read-only-observer', 'errors':[],
            'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'last_success_at':datetime.now(timezone.utc).isoformat()}))
        for path in (self.cache, self.state, self.generations, self.guardian):
            path.mkdir()
        (self.state / 'artifact-gc').mkdir(mode=0o700)
        self.lifecycle = UpdateArchiveLifecycle(update_root=self.state, generation_root=self.generations,
            guardian_active=self.guardian, guardian_uid=os.getuid(), roots={'auto': self.cache}, owner_uid=os.getuid())
        self.write_tx(OLD, invalidated=True)
        self.write_tx(ACTIVE, invalidated=False)
        (self.state / 'coordinator.json').write_text(json.dumps({'schema_version':1, 'active_transaction_id':ACTIVE}))

    def write_tx(self, txid, *, invalidated=False, executed=False):
        tx = create_transaction(transaction_id=txid, source_revision=REV, now=NOW,
            packages=[{'name':'demo', 'installed_version':'1', 'candidate_version':'2',
                       'repository':'core', 'download_size':32, 'installed_size':64}],
            activation_requirements=[], recovery_generation_id=None)
        tx = transition_transaction(tx, UpdateState.STAGED, now=NOW)
        tx = transition_transaction(tx, UpdateState.PREPARED, now=NOW)
        if executed:
            tx = transition_transaction(tx, UpdateState.MAINTENANCE_READY, now=NOW)
            tx = transition_transaction(tx, UpdateState.INSTALLING, now=NOW)
            tx = transition_transaction(tx, UpdateState.ATTENTION_REQUIRED, now=NOW, reason="interrupted install", blockers=["interrupted"])
        elif invalidated:
            tx = transition_transaction(tx, UpdateState.BLOCKED, now=NOW,
                blockers=['repository_generation_drifted'], reason='repository generation changed')
        publish_transaction(self.state, tx)
        cache = self.cache / txid / 'staging'
        cache.mkdir(parents=True, exist_ok=True)
        path = cache / 'demo-2-1-any.pkg.tar.zst'
        path.write_bytes(b'x' * 1024)
        manifest = {'schema_version':2, 'transaction_id':txid, 'package_generation_id':tx['package_generation']['id'],
            'payloads':[{'name':'demo', 'version':'2', 'path':str(path), 'size':1024, 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]}
        (cache / ('manifest-' + tx['package_generation']['id'] + '.json')).write_text(json.dumps(manifest))
        (cache / 'pacman-stage.log').write_text('forensic log')
        return tx

    def plan(self):
        return self.lifecycle.report(source_revision=REV, now=NOW)['plan']

    def execute(self, plan, **kwargs):
        return self.lifecycle.executor.execute(plan, validate_protections=self.lifecycle.validate_protections,
                                               now=NOW, **kwargs)

    def test_retirement_preserves_active_manifest_receipt_and_logs(self):
        plan = self.plan()
        self.assertEqual({r['transaction_id'] for r in plan['objects']}, {OLD})
        receipt = self.execute(plan)
        self.assertGreater(receipt['reclaimed_bytes'], 0)
        self.assertFalse((self.cache / OLD / 'staging' / 'demo-2-1-any.pkg.tar.zst').exists())
        self.assertTrue((self.cache / ACTIVE / 'staging' / 'demo-2-1-any.pkg.tar.zst').exists())
        self.assertTrue(list((self.cache / OLD / 'staging').glob('manifest-*.json')))
        self.assertTrue((self.cache / OLD / 'staging' / 'pacman-stage.log').exists())
        self.assertTrue((self.state / 'transactions' / (OLD + '.json')).exists())
        self.assertEqual(self.lifecycle.collect(source_revision=REV, now=NOW)['phase'], 'NO_DISPOSABLE_FILES')

    def expand_roots(self):
        isolated = self.base / 'isolated'; isolated.mkdir(exist_ok=True)
        self.lifecycle = UpdateArchiveLifecycle(update_root=self.state, generation_root=self.generations,
            guardian_active=self.guardian, guardian_uid=os.getuid(),
            roots={'auto':self.cache, 'isolated-auto':isolated}, owner_uid=os.getuid())

    def test_committed_legacy_journal_survives_verified_root_expansion(self):
        plan = self.plan(); self.execute(plan); self.expand_roots()
        self.assertEqual(self.lifecycle.executor._read()['phase'], 'COMMITTED')
        self.assertEqual(self.lifecycle.collect(source_revision=REV, now=NOW)['phase'], 'NO_DISPOSABLE_FILES')
        with self.assertRaises(InventoryError): self.lifecycle.executor._validate_plan(plan)
        self.assertTrue((self.cache / ACTIVE / 'staging/demo-2-1-any.pkg.tar.zst').exists())

    def test_cancelled_legacy_journal_is_preserved_before_new_plan(self):
        plan = self.plan(); old = self.lifecycle.executor._journal(plan, 'CANCELLED')
        self.expand_roots()
        self.assertEqual(self.lifecycle.collect(source_revision=REV, now=NOW)['phase'], 'COMMITTED')
        path = self.lifecycle.executor.state_root / ('archive-history-' + plan['plan_sha256'] + '.json')
        self.assertEqual(json.loads(path.read_text()), old)

    def test_incomplete_legacy_plan_cannot_resume_with_expanded_roots(self):
        plan = self.plan()
        for phase in ('PREPARED', 'RETIRED', 'DELETING'):
            with self.subTest(phase=phase):
                self.lifecycle.executor._journal(plan, phase)
                if 'isolated-auto' not in self.lifecycle.roots: self.expand_roots()
                with self.assertRaises(InventoryError): self.lifecycle.executor._read()
        self.assertTrue((self.cache / OLD / 'staging/demo-2-1-any.pkg.tar.zst').exists())

    def test_completed_history_rejects_changed_or_missing_root_binding(self):
        plan = self.plan(); self.execute(plan)
        for roots in ({'auto':self.base/'wrong'}, {'isolated-auto':self.cache}):
            executor = CertifiedFileGC(roots=roots, state_root=self.state/'artifact-gc', owner_uid=os.getuid())
            with self.assertRaises(InventoryError): executor._read()

    def test_completed_history_rejects_object_outside_recorded_roots(self):
        plan = self.plan(); self.execute(plan)
        journal = self.lifecycle.executor._read(); journal['plan']['roots'] = {'isolated-auto':str(self.cache)}
        material = dict(journal['plan']); material.pop('plan_sha256'); journal['plan']['plan_sha256'] = digest_payload(material)
        material = dict(journal); material.pop('journal_sha256'); journal['journal_sha256'] = digest_payload(material)
        self.lifecycle.executor._write(self.lifecycle.executor.journal_path, journal)
        self.expand_roots()
        # Both roots point to the same directory to isolate object/root validation.
        self.lifecycle.executor.roots['isolated-auto'] = self.cache
        with self.assertRaises(InventoryError): self.lifecycle.executor._read()

    def test_current_pointer_and_independent_coordinator_both_protect(self):
        (self.state / 'current').write_text(OLD)
        self.assertEqual(self.plan()['objects'], [])
        (self.state / 'current').write_text(ACTIVE)
        (self.state / 'coordinator.json').write_text(json.dumps({'schema_version':1, 'active_transaction_id':OLD}))
        self.assertEqual(self.plan()['objects'], [])

    def test_generation_recovery_and_incident_references_protect(self):
        for root in (self.generations, self.state / 'recovery'):
            root.mkdir(exist_ok=True)
            p = root / 'protected.json'
            p.write_text(json.dumps({'transaction_id':OLD}))
            self.assertEqual(self.plan()['objects'], [])
            p.unlink()
        p = self.guardian / 'incident.json'
        p.write_text(json.dumps({'kind':'guardian-assessment', 'version':1, 'transaction_id':OLD,
            'decision':{'catastrophic':{'evidence_preservation_required':False}}}))
        self.assertEqual(self.plan()['objects'], [])

    def test_unscoped_forensic_requirement_refuses_retirement(self):
        (self.guardian / 'incident.json').write_text(json.dumps({'kind':'guardian-assessment', 'version':1,
            'decision':{'catastrophic':{'evidence_preservation_required':True}}}))
        with self.assertRaises(InventoryError): self.plan()

    def test_unknown_or_corrupt_evidence_refuses_retirement(self):
        (self.generations / 'bad.json').write_text('invalid')
        with self.assertRaises(ValueError): self.plan()
        (self.generations / 'bad.json').unlink()
        self.guardian.rmdir()
        with self.assertRaises(InventoryError): self.plan()

    def test_never_delete_executed_or_recoverable_transaction(self):
        self.write_tx(OLD, executed=True)
        (self.state / 'current').write_text(ACTIVE)
        self.assertEqual(self.plan()['objects'], [])

    def test_protection_arriving_after_plan_prevents_any_deletion(self):
        plan = self.plan()
        (self.generations / 'new.json').write_text(json.dumps({'tx':OLD}))
        with self.assertRaises(InventoryError): self.execute(plan)
        self.assertFalse(self.lifecycle.executor.journal_path.exists())

    def test_protection_arriving_between_unlinks_preserves_remaining_file(self):
        path = self.cache / OLD / 'staging' / 'demo-2-1-any.pkg.tar.zst.sig'
        path.write_bytes(b'signature evidence')
        plan = self.plan()
        original = self.lifecycle.validate_protections
        targets = []
        def fresh_protection(plan, *, target=None):
            if target is not None:
                targets.append(target['name'])
                if len(targets) == 2:
                    (self.generations / 'new.json').write_text(json.dumps({'tx':OLD}))
            original(plan, target=target)
        with self.assertRaises(InventoryError):
            self.lifecycle.executor.execute(plan, validate_protections=fresh_protection, now=NOW)
        self.assertEqual(len(targets), 2)
        self.assertTrue(path.exists())
        self.assertEqual(self.lifecycle.executor._read()['phase'], 'DELETING')

    def test_artifact_and_manifest_substitution_are_rejected(self):
        plan = self.plan()
        path = self.cache / OLD / 'staging' / 'demo-2-1-any.pkg.tar.zst'
        path.write_bytes(b'y' * 1024)
        with self.assertRaises(IdentityMismatchError): self.execute(plan)

    def test_symlink_hardlink_and_writable_directory_are_not_adopted(self):
        path = self.cache / OLD / 'staging' / 'demo-2-1-any.pkg.tar.zst'
        outside = self.base / 'keep'
        outside.write_bytes(path.read_bytes())
        path.unlink(); path.symlink_to(outside)
        self.assertEqual(self.plan()['objects'], [])
        path.unlink(); os.link(outside, path)
        self.assertEqual(self.plan()['objects'], [])
        path.unlink(); path.write_bytes(outside.read_bytes())
        path.parent.chmod(0o777)
        self.assertEqual(self.plan()['objects'], [])
        self.assertEqual(outside.read_bytes(), b'x' * 1024)

    def test_wrong_target_path_and_unlisted_archive_are_rejected(self):
        plan = self.plan()
        row = dict(plan['objects'][0]); row['name'] = '../keep.pkg.tar.zst'
        with self.assertRaises(IdentityMismatchError): self.lifecycle.executor._parent(row)
        extra = self.cache / OLD / 'staging' / 'extra-1-any.pkg.tar.zst'
        extra.write_bytes(b'keep')
        plan['objects'] = [self.lifecycle.executor.inspect('auto', OLD, extra.name)]
        plan.pop('plan_sha256'); plan['plan_sha256'] = digest_payload(plan)
        with self.assertRaises(InventoryError): self.execute(plan)
        self.assertTrue(extra.exists())

    def test_expired_future_and_replayed_authority_are_rejected(self):
        plan = self.plan()
        for now in (NOW + timedelta(minutes=6), NOW - timedelta(seconds=1)):
            with self.assertRaises(StaleAuthorityError):
                self.lifecycle.executor.execute(plan, validate_protections=self.lifecycle.validate_protections, now=now)
        self.execute(plan)
        with self.assertRaises(StaleAuthorityError): self.execute(plan)

    def test_restart_at_each_durable_boundary_is_idempotent(self):
        for fault in ('after_prepare', 'after_retire', 'after_unlink', 'after_first_delete'):
            with self.subTest(fault=fault):
                # Recreate this isolated fixture for every interruption.
                self.tearDown(); self.setUp()
                plan = self.plan()
                with self.assertRaises(SimulatedCrash): self.execute(plan, fault_at=fault)
                result = self.lifecycle.executor.resume_files(
                    validate_protections=self.lifecycle.validate_protections, now=NOW)
                again = self.lifecycle.executor.resume_files(
                    validate_protections=self.lifecycle.validate_protections, now=NOW)
                self.assertEqual(result['phase'], 'COMMITTED')
                self.assertEqual(again['reclaimed_bytes'], result['reclaimed_bytes'])
                self.assertTrue((self.cache / ACTIVE / 'staging' / 'demo-2-1-any.pkg.tar.zst').exists())

    def test_interrupted_retirement_rechecks_protections(self):
        plan = self.plan()
        with self.assertRaises(SimulatedCrash): self.execute(plan, fault_at='after_retire')
        (self.generations / 'new.json').write_text(json.dumps({'tx':OLD}))
        with self.assertRaises(InventoryError):
            self.lifecycle.executor.resume_files(validate_protections=self.lifecycle.validate_protections, now=NOW)
        self.assertTrue((self.cache / OLD / 'staging' / 'demo-2-1-any.pkg.tar.zst').exists())

    def test_expired_prepared_journal_does_not_start_retirement(self):
        with self.assertRaises(SimulatedCrash): self.execute(self.plan(), fault_at='after_prepare')
        with self.assertRaises(StaleAuthorityError):
            self.lifecycle.executor.resume_files(validate_protections=self.lifecycle.validate_protections,
                                                  now=NOW + timedelta(minutes=6))

    def test_stale_and_wrong_boot_guardian_evidence_refuses_retirement(self):
        path = self.guardian.parent / 'providers/guardian.watch.json'
        value = json.loads(path.read_text())
        value['last_success_at'] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        path.write_text(json.dumps(value))
        with self.assertRaises(InventoryError): self.plan()
        value['last_success_at'] = datetime.now(timezone.utc).isoformat()
        value['boot_id'] = 'wrong-boot'
        path.write_text(json.dumps(value))
        with self.assertRaises(InventoryError): self.plan()

    def test_expired_uncommitted_retirement_is_replanned_from_current_evidence(self):
        with self.assertRaises(SimulatedCrash): self.execute(self.plan(), fault_at='after_prepare')
        result = self.lifecycle.collect(source_revision=REV, now=NOW + timedelta(minutes=6))
        self.assertEqual(result['phase'], 'COMMITTED')
        self.assertEqual(len(list(self.lifecycle.executor.state_root.glob('archive-cancelled-*.json'))), 1)

    def test_disk_budget_blocks_download_before_reserve_is_consumed(self):
        tx = next(tx for tx, _ in self.lifecycle.transactions() if tx['transaction_id'] == ACTIVE)
        low = staging_budget(tx, allocated_bytes=0, total_bytes=200 * 1024**3,
                             available_bytes=9 * 1024**3)
        self.assertIn('unsafe_post_update_disk_reserve', low['blockers'])
        full = staging_budget(tx, allocated_bytes=12 * 1024**3, total_bytes=200 * 1024**3,
                              available_bytes=80 * 1024**3)
        self.assertIn('update_archive_storage_budget_exceeded', full['blockers'])
        self.assertEqual(staging_budget(tx, allocated_bytes=0, total_bytes=200 * 1024**3,
                         available_bytes=80 * 1024**3)['blockers'], [])
        self.assertGreater(archive_usage({'auto':self.cache}), 0)

    def test_budget_reserve_is_canonical(self):
        self.assertEqual(reserve_bytes(64 * 1024**3), 20 * 1024**3)
        self.assertEqual(reserve_bytes(200 * 1024**3), 30 * 1024**3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
