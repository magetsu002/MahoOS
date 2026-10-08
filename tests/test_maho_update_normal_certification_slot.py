#!/usr/bin/env python3
"""No manual certification may steal an unresolved automatic update pointer."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
import maho_update_normal_campaign as campaign

TXID = 'upd-20261008T113213Z-0b24b789644a'


class NormalCertificationOwnership(unittest.TestCase):
    def test_empty_state_allows_first_certification(self):
        with tempfile.TemporaryDirectory() as temp:
            campaign._require_certification_slot(Path(temp))

    def test_pending_and_recovery_states_refuse_takeover(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'current').write_text(TXID + '\n')
            for state in ('DISCOVERED', 'STAGED', 'PREPARED',
                          'MAINTENANCE_READY', 'INSTALLING',
                          'INSTALLED_PENDING_ACTIVATION', 'ACTIVE_VERIFYING',
                          'FAILED_RECOVERABLE', 'RECOVERING', 'ATTENTION_REQUIRED',
                          'BLOCKED'):
                with self.subTest(state=state), patch.object(campaign, 'read_transaction',
                        return_value={'state': state}):
                    with self.assertRaisesRegex(RuntimeError, 'replace_unresolved|coordinator_evidence_unavailable'):
                        campaign._require_certification_slot(root)

    def test_prepared_coordinator_may_coexist_only_when_nonmutating(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'current').write_text(TXID + '\n')
            state = {
                'active_transaction_id': TXID, 'source_revision': 'a' * 40,
                'phase': 'WAITING_MAINTENANCE', 'lane': 'normal',
                'live_root_mutation_started': False, 'reboot_required': False,
            }
            coordinator = root / 'coordinator.json'
            with patch.object(campaign, 'read_transaction',
                              return_value={'state':'PREPARED', 'source_revision':'a'*40}):
                coordinator.write_text(json.dumps(state))
                campaign._require_certification_slot(root)
                for key, invalid in (
                    ('phase', 'INSTALLING'), ('lane', 'native'),
                    ('live_root_mutation_started', True),
                    ('active_transaction_id', 'upd-20261008T121030Z-db28c88520c6'),
                    ('source_revision', 'b' * 40),
                    ('reboot_required', True),
                ):
                    with self.subTest(key=key):
                        changed = dict(state, **{key:invalid})
                        coordinator.write_text(json.dumps(changed))
                        with self.assertRaisesRegex(RuntimeError, 'replace_unresolved'):
                            campaign._require_certification_slot(root)

    def test_only_verified_terminal_transaction_may_be_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'current').write_text(TXID + '\n')
            for state in ('HEALTHY', 'RECOVERED'):
                with patch.object(campaign, 'read_transaction', return_value={'state': state}):
                    campaign._require_certification_slot(root)

    def test_corrupt_or_symlinked_pointer_never_becomes_an_open_slot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pointer = root / 'current'
            pointer.write_text('garbage\n')
            with self.assertRaisesRegex(RuntimeError, 'identity is invalid|id invalid'):
                campaign._require_certification_slot(root)
            pointer.unlink()
            pointer.symlink_to(root / 'missing')
            with self.assertRaisesRegex(RuntimeError, 'pointer invalid'):
                campaign._require_certification_slot(root)

    def test_missing_owned_transaction_does_not_disappear(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'current').write_text(TXID + '\n')
            with self.assertRaises(ValueError):
                campaign._require_certification_slot(root)


if __name__ == '__main__':
    unittest.main(verbosity=2)
