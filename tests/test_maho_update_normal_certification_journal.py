#!/usr/bin/env python3
"""Physical certification journals must never hijack automatic update ownership."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import maho_update_normal_campaign as campaign
from maho_update_state import create_transaction, read_transaction, transaction_path

TXID='upd-20261008T121030Z-db28c88520c6'


class CertificationJournalContracts(unittest.TestCase):
    def test_live_certification_keeps_coordinator_pointer_and_durable_journal(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'state'
            root.mkdir()
            current=root/'current'
            current.write_text('upd-20261008T120522Z-b5a625d6854b\n')
            unchanged=current.read_bytes()
            transaction=create_transaction(
                transaction_id=TXID,source_revision='a'*40,
                packages=[{'name':'hwdata','installed_version':'1','candidate_version':'2',
                           'repository':'core','download_size':10,'installed_size':20,'roles':[]}],
                activation_requirements=[],recovery_generation_id=None,
            )
            with patch.object(campaign,'STATE_ROOT',root):
                campaign._record_certification_transaction(
                    transaction,preflight_only=False,work=Path(temp)/'work',
                )
            self.assertEqual(current.read_bytes(),unchanged)
            stored=read_transaction(transaction_path(root,TXID))
            self.assertEqual(stored,transaction)
            self.assertFalse((root/'normal-certification'/'current').exists())

    def test_dry_run_never_writes_to_production_journal(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'state'
            transaction=create_transaction(
                transaction_id=TXID,source_revision='a'*40,
                packages=[{'name':'hwdata','installed_version':'1','candidate_version':'2',
                           'repository':'core','download_size':10,'installed_size':20,'roles':[]}],
                activation_requirements=[],recovery_generation_id=None,
            )
            work=Path(temp)/'work'
            with patch.object(campaign,'STATE_ROOT',root):
                campaign._record_certification_transaction(
                    transaction,preflight_only=True,work=work,
                )
            self.assertFalse((root/'transactions').exists())
            self.assertEqual((work/'state'/'current').read_text().strip(),TXID)


if __name__=='__main__':
    unittest.main(verbosity=2)
