#!/usr/bin/env python3
"""A dry-run certification must not become the coordinator's current update."""
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
import maho_update_normal_campaign as campaign

TXID = 'upd-20261008T120000Z-123456abcdef'
REV = 'a' * 40


class PreflightIsolationContracts(unittest.TestCase):
    def test_successful_preflight_keeps_global_current_pointer_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            state = base / 'live-state'
            state.mkdir()
            pointer = state / 'current'
            pointer.write_text('upd-20261008T100000Z-aaaaaaaaaaaa\n')
            original = pointer.read_bytes()
            work = base / 'work'
            roots = []
            def fake_publish(root, transaction):
                root = Path(root)
                roots.append(root)
                root.mkdir(parents=True, exist_ok=True)
                (root / 'current').write_text(TXID + '\n')

            btrfs = Mock()
            btrfs.create_candidate.return_value = {'uuid': 'candidate'}
            ops = Mock()
            ops.live_mutation_started = False
            ops.admission = None
            ops.install_candidate.return_value = {'ok': True}
            ops.guardian_admit.return_value = {'ok': True}
            ops.preflight_activation.return_value = {'ok': True}
            ops.cleanup_success.return_value = {'ok': True}
            staged = NS(transaction={'state': 'STAGED',
                                     'package_generation': {'packages': []}},
                        manifest={'effects': {'classification': 'normal',
                                              'effects': ['ordinary-files'],
                                              'activation_requirements': []}})
            prepared = NS(transaction={'state': 'PREPARED',
                                       'package_generation': {'id': 'pkg-' + 'b'*64}},
                          plan=Mock())
            discovery = NS(transaction={'transaction_id': TXID}, isolated_db=str(base / 'db'))
            overrides = {
                'STATE_ROOT': state, 'CACHE_ROOT': work,
                '_require_root': lambda: None,
                '_campaign_root': lambda: base,
                '_source_revision': lambda root: REV,
                '_canonical_config': lambda root: base / 'pacman.conf',
                '_required_repositories': lambda root: ('core',),
                '_power': lambda: (True, True, {}),
                '_require_certification_slot': lambda root: None,
                'IsolatedPacmanDiscovery': Mock(),
                'discover_coherent_subset_updates': Mock(return_value=discovery),
                'IsolatedPacmanStaging': Mock(),
                'stage_transaction': Mock(return_value=staged),
                'NativeBtrfsOps': Mock(return_value=btrfs),
                'prepare_normal_transaction': Mock(return_value=prepared),
                'NormalProductionOps': Mock(return_value=ops),
                'publish_transaction': fake_publish,
            }
            with ExitStack() as stack:
                for name, value in overrides.items():
                    stack.enter_context(patch.object(campaign, name, value))
                outcome = campaign.certify_normal_update(
                    ['hwdata', 'vulkan-headers'], 'CERTIFY-NORMAL:' + REV,
                    preflight_only=True,
                )
            self.assertEqual(outcome['phase'], 'preflight-ready')
            self.assertEqual(pointer.read_bytes(), original)
            self.assertEqual(len(roots), 3)
            self.assertTrue(all(root != state and work in root.parents for root in roots))
            self.assertTrue(work.is_dir())
            self.assertFalse(any(work.iterdir()))
            self.assertFalse(ops.live_mutation_started)
            btrfs.close.assert_called_once()


if __name__ == '__main__':
    unittest.main(verbosity=2)
