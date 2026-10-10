#!/usr/bin/env python3
"""Adversarial attribution contract; real kernel boundary is tested in the VM."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'lib'), str(ROOT / 'tests')]
import guardian_generation_observation as observer
from test_maho_live_generation import fixture, PREVIOUS
from maho_live_generation import publish_live_generations


class FixtureInputs:
    def __init__(self):
        self.records = {}
    def read(self, path):
        data = path.read_bytes()
        self.records[path] = data
        return data
    def digest(self, path):
        return self.boot[str(path)]
    @contextmanager
    def opened(self, path):
        yield 0
    def verify_unchanged(self):
        if any(path.read_bytes() != content for path, content in self.records.items()):
            raise observer.ObservationUnavailable('publication changed')


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.gen, self.up = self.root / 'generations', self.root / 'update'
        tx, journal, receipt, observation = fixture()
        self.tx, self.observation = tx, observation
        self.publication = publish_live_generations(tx, journal, receipt, observation,
            publisher_source_revision='a'*40, root=self.gen)
        self.txpath = self.up / 'transactions' / (tx['transaction_id']+'.json')
        self.txpath.parent.mkdir(parents=True)
        self.txpath.write_text(json.dumps(tx))
        self.current = self.up / 'current'
        self.current.write_text('upd-20261010T000000Z-111111111111')
        self.physical = {key: self.publication[key] for key in ('filesystem_uuid', 'root_subvolume_uuid')}
        self.context = ('boot-id', observation.running_kernel, observation.cmdline, 'real-host-view')
        FixtureInputs.boot = self.publication['boot_sha256']
        for target, value in (
            ('ProtectedInputs', FixtureInputs),
            ('root_identity', lambda fd: dict(self.physical)),
            ('_boot_context', lambda proc, fd: self.context),
            ('_packages', lambda expected: dict(observation.package_versions)),
        ):
            p = patch.object(observer, target, value); p.start(); self.addCleanup(p.stop)

    def observe(self):
        return observer.attribute_running_generation(self.gen, self.up)

    def test_accepted_generation_with_staged_candidate(self):
        self.assertEqual(self.observe(), self.publication)

    def test_concurrent_pointer_changes_do_not_change_acceptance(self):
        def query(expected):
            self.current.write_text('another-candidate')
            return dict(expected)
        with patch.object(observer, '_packages', query):
            self.assertEqual(self.observe(), self.publication)

    def test_wrong_root_cannot_inherit_metadata(self):
        self.physical['root_subvolume_uuid'] = PREVIOUS
        self.assertIsNone(self.observe())

    def test_wrong_filesystem(self):
        self.physical['filesystem_uuid'] = PREVIOUS
        self.assertIsNone(self.observe())

    def test_package_drift(self):
        with patch.object(observer, '_packages', lambda e: dict(e) | {'linux-cachyos': 'wrong'}):
            self.assertIsNone(self.observe())

    def test_package_change_during_observation(self):
        with patch.object(observer, '_packages', side_effect=[self.observation.package_versions, {}]):
            self.assertIsNone(self.observe())

    def test_missing_current_root(self):
        with patch.object(observer, 'root_identity', side_effect=OSError('unavailable')):
            self.assertIsNone(self.observe())

    def test_replayed_publication_on_different_live_root(self):
        # All historic artifacts/receipt remain valid, but the mounted root does not.
        self.physical['root_subvolume_uuid'] = PREVIOUS
        self.assertIsNone(self.observe())

    def test_publication_replaced_during_observation(self):
        def query(expected):
            (self.gen / 'live.json').write_text('{}')
            return dict(expected)
        with patch.object(observer, '_packages', query):
            self.assertIsNone(self.observe())

    def test_expired_observation(self):
        with patch.object(observer.time, 'monotonic', side_effect=[100, 116]):
            self.assertIsNone(self.observe())

    def test_interrupted_acceptance_missing_manifest(self):
        (self.gen / 'manifests/system' / (self.publication['system_generation_id']+'.json')).unlink()
        self.assertIsNone(self.observe())

    def test_interrupted_acceptance_nonhealthy_transaction(self):
        self.tx['state'] = 'ACTIVE_VERIFYING'
        self.txpath.write_text(json.dumps(self.tx))
        self.assertIsNone(self.observe())

    def test_unpublished_incomplete_candidate_leaves_accepted_identity(self):
        (self.gen / 'initial-pending.json').write_text('{}')
        self.assertEqual(self.observe(), self.publication)

    def test_boot_drift(self):
        with patch.object(FixtureInputs, 'boot', dict(FixtureInputs.boot) | {'/boot/intel-ucode.img':'f'*64}):
            self.assertIsNone(self.observe())

    def test_boot_change_during_observation(self):
        with patch.object(observer, '_boot_context', side_effect=[self.context, ('new-boot', *self.context[1:])]):
            self.assertIsNone(self.observe())

    def test_running_root_replaced_during_observation(self):
        with patch.object(observer, 'root_identity', side_effect=[self.physical, self.physical, self.physical | {'root_subvolume_uuid':PREVIOUS}]):
            self.assertIsNone(self.observe())

    def test_receipt_tampering_denies_acceptance(self):
        self.tx['updated_at'] = '2026-10-10T00:00:00Z'
        self.txpath.write_text(json.dumps(self.tx))
        self.assertIsNone(self.observe())


class InputBoundaryTests(unittest.TestCase):
    def test_real_kernel_root_is_available_without_privilege(self):
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            if not any(' - btrfs ' in line and line.split()[4]=='/' for line in Path('/proc/self/mountinfo').read_text().splitlines()):
                self.skipTest('host is not Btrfs')
            result = observer.root_identity(fd)
            self.assertEqual(len(result['root_subvolume_uuid']),36)
            self.assertEqual(len(result['filesystem_uuid']),36)
        finally:
            os.close(fd)

    def test_user_controlled_generation_evidence_is_rejected(self):
        if os.geteuid()==0:
            self.skipTest('root fixture cannot demonstrate unprivileged ownership')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'evidence'; path.write_text('{}')
            with self.assertRaises(observer.ObservationUnavailable):
                observer.ProtectedInputs().read(path)

    def test_world_writable_or_symlinked_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'evidence'; path.write_text('{}')
            with self.assertRaises(observer.ObservationUnavailable):
                observer.ProtectedInputs().read(path)

    def test_real_boot_context_matches_open_root_mount(self):
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            self.assertEqual(observer._boot_context(Path('/proc'),fd)[1],os.uname().release)
        finally:
            os.close(fd)

if __name__ == '__main__':
    unittest.main()
