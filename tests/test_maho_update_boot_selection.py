#!/usr/bin/env python3
"""Regression: boot package isolation must precede automatic normal staging."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))

import maho_update_coordinator as coordinator
from maho_update_discovery import (
    CommandResult, IsolatedPacmanDiscovery, discover_independent_normal_updates,
    package_roles,
)
from maho_update_effects import classify_artifact, preliminary_boot_critical
from maho_update_state import create_transaction

NOW = datetime(2026, 10, 8, 11, 0, tzinfo=timezone.utc)
REV = 'a' * 40
BOOT = ('linux', 'linux-headers', 'systemd', 'systemd-libs')
FULL = ('linux', 'linux-headers', 'systemd', 'systemd-libs', 'demo-service')
VERSIONS = {'linux': '7.2-1', 'linux-headers': '7.2-1', 'systemd': '260-1',
            'systemd-libs': '260-1', 'demo-service': '2-1'}


class MixedRunner:
    def __init__(self, *, dependency_conflict=False, version_drift=False):
        self.dependency_conflict = dependency_conflict
        self.version_drift = version_drift
        self.excluded = ()

    def __call__(self, command):
        if '--refresh' in command:
            return CommandResult(0, '')
        if '--query' in command:
            return CommandResult(0, '\n'.join(f'{name} 1-1' for name in FULL) + '\n')
        if '--info' in command:
            return CommandResult(0, ''.join(
                f'Repository : core\nName : {name}\nVersion : {VERSIONS[name]}\n'
                'Download Size : 1 MiB\nInstalled Size : 2 MiB\n\n'
                for name in FULL
            ))
        if '--sysupgrade' in command:
            selected = FULL
            if '--ignore' in command:
                self.excluded = tuple(command[command.index('--ignore') + 1].split(','))
                if self.dependency_conflict:
                    return CommandResult(1, '', 'failed to prepare transaction: systemd-libs requires systemd=260')
                selected = ('demo-service',)
            return CommandResult(0, ''.join(
                f'core\t{name}\t'
                f'{"3-1" if self.version_drift and name == "demo-service" and "--ignore" in command else VERSIONS[name]}\n'
                for name in selected
            ))
        raise AssertionError(f'unexpected command: {command!r}')


def full_transaction(names):
    packages = [
        {'name': name, 'installed_version': '1-1', 'candidate_version': VERSIONS.get(name, '2-1'),
         'repository': 'core', 'download_size': 1024, 'installed_size': 2048,
         'roles': package_roles(name)}
        for name in names
    ]
    return create_transaction(
        transaction_id='upd-20261008T110000Z-123456abcdef', source_revision=REV,
        packages=packages, activation_requirements=['restart'] if 'linux-cachyos' in names else [],
        recovery_generation_id=None, now=NOW,
    )


class BootSelectionContracts(unittest.TestCase):
    def test_exact_arch_boot_packages_have_preliminary_authority(self):
        for name in (*BOOT, 'linux-lts', 'linux-lts-headers', 'linux-zen',
                     'linux-hardened-headers', 'linux-firmware', 'systemd-sysvcompat'):
            with self.subTest(package=name):
                self.assertTrue(preliminary_boot_critical(package_roles(name)))
        for name in ('linux-api-headers', 'demo-service'):
            with self.subTest(normal=name):
                self.assertFalse(preliminary_boot_critical(package_roles(name)))

    def test_mixed_generation_isolated_solver_keeps_only_independent_normal(self):
        with tempfile.TemporaryDirectory() as temp:
            installed = Path(temp) / 'local'
            installed.mkdir()
            runner = MixedRunner()
            backend = IsolatedPacmanDiscovery(Path(temp) / 'discovery', installed_db=installed, runner=runner)
            discovered = discover_independent_normal_updates(backend, source_revision=REV, now=NOW,
                                                              entropy='123456abcdef')
            self.assertEqual(set(discovered.deferred_boot_packages), set(BOOT))
            self.assertEqual(runner.excluded, tuple(sorted(BOOT)))
            names = {p['name'] for p in discovered.transaction['package_generation']['packages']}
            self.assertEqual(names, {'demo-service'})
            self.assertEqual(discovered.selection_kind, 'independent-normal')
            proof = discovered.transaction['selection']['solver_proof']
            self.assertTrue(proof['selected_versions_match_full'])
            self.assertTrue(proof['selected_repositories_match_full'])
            self.assertFalse(proof['production_ignore_execution'])
            self.assertTrue(all(str(backend.db) in cmd for cmd in backend.commands))

    def test_dependency_conflict_does_not_become_a_partial_upgrade(self):
        with tempfile.TemporaryDirectory() as temp:
            installed = Path(temp) / 'local'
            installed.mkdir()
            backend = IsolatedPacmanDiscovery(Path(temp) / 'discovery', installed_db=installed,
                                              runner=MixedRunner(dependency_conflict=True))
            with self.assertRaisesRegex(RuntimeError, 'independent_non_boot_solver_incoherent'):
                discover_independent_normal_updates(backend, source_revision=REV, now=NOW)

    def test_version_drift_cannot_cross_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            installed = Path(temp) / 'local'
            installed.mkdir()
            backend = IsolatedPacmanDiscovery(Path(temp) / 'discovery', installed_db=installed,
                                              runner=MixedRunner(version_drift=True))
            with self.assertRaisesRegex(RuntimeError, 'independent_non_boot_solver_version_drift:demo-service'):
                discover_independent_normal_updates(backend, source_revision=REV, now=NOW)

    def test_exact_artifacts_can_elevate_unknown_name_to_boot_critical(self):
        effect = classify_artifact(package_name='demo-service', roles=[],
                                   files=['/usr/lib/modules/7.2/extra/demo.ko.zst'])
        self.assertEqual(effect['classification'], 'boot-critical')
        self.assertIn('explicit-reboot', effect['activation_requirements'])
        for name in BOOT:
            with self.subTest(package=name):
                effect = classify_artifact(package_name=name, roles=package_roles(name),
                                           files=['/usr/bin/innocent-looking'])
                self.assertEqual(effect['classification'], 'boot-critical')

    def test_unsupported_boot_only_generation_never_invokes_native(self):
        with tempfile.TemporaryDirectory() as state, tempfile.TemporaryDirectory() as work:
            repository = {'config_path': '/fixture/pacman.conf', 'repositories': ['core']}
            full = full_transaction(BOOT)
            with patch.dict(os.environ, {'MAHO_UPDATE_STATE_ROOT': state, 'MAHO_UPDATE_AUTO_WORK_ROOT': work}), \
                 patch.object(coordinator, 'IsolatedPacmanDiscovery') as backend_cls, \
                 patch.object(coordinator, 'discover_independent_normal_updates',
                              side_effect=LookupError('no coherent non-boot update candidates were discovered')), \
                 patch.object(coordinator, '_observe_boot_only', return_value={
                     'transaction': full, 'candidate_count': len(BOOT),
                     'repository_hashes': {'core': '1' * 64}}), \
                 patch.object(coordinator, 'prepare_native_campaign') as native:
                backend_cls.return_value.sync_database_hashes.return_value = {'core': '1' * 64}
                result = coordinator._new_discovery(None, REV, 'fixture', {}, repository, NOW)
            self.assertEqual(result['phase'], 'BLOCKED')
            self.assertEqual(result['lane'], 'native-required')
            self.assertEqual(set(result['deferred_boot_packages']), set(BOOT))
            self.assertIn('boot_only_generation_requires_native_preparation', result['blockers'])
            native.assert_not_called()

    def test_certified_cachyos_boot_generation_uses_existing_native_path(self):
        with tempfile.TemporaryDirectory() as state, tempfile.TemporaryDirectory() as work:
            repository = {'config_path': '/fixture/pacman.conf', 'repositories': ['core']}
            full = full_transaction(('linux-cachyos', 'linux', 'systemd'))
            native_result = {'transaction_id': full['transaction_id'], 'journal_path': '/fixture/native.json'}
            with patch.dict(os.environ, {'MAHO_UPDATE_STATE_ROOT': state, 'MAHO_UPDATE_AUTO_WORK_ROOT': work}), \
                 patch.object(coordinator, 'IsolatedPacmanDiscovery'), \
                 patch.object(coordinator, 'discover_independent_normal_updates',
                              side_effect=LookupError('no coherent non-boot update candidates were discovered')), \
                 patch.object(coordinator, '_observe_boot_only', return_value={
                     'transaction': full, 'candidate_count': 3,
                     'repository_hashes': {'core': '1' * 64}}), \
                 patch.object(coordinator, 'prepare_native_campaign', return_value=native_result) as native, \
                 patch.object(coordinator, 'read_transaction', return_value=full), \
                 patch.object(coordinator, '_read_json', return_value={
                     'package_repo': {'sync_db_sha256': {'core': '1' * 64}}}):
                result = coordinator._new_discovery(None, REV, 'fixture', {}, repository, NOW)
            self.assertEqual(result['lane'], 'native')
            self.assertEqual(result['phase'], 'WAITING_MAINTENANCE')
            self.assertEqual(result['normal_execution_authority'], 'native-execution-certified')
            native.assert_called_once_with()


if __name__ == '__main__':
    unittest.main(verbosity=2)
