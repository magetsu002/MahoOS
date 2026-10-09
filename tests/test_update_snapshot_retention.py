import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"lib"))
from maho_update_snapshot_retention import protection_report
from maho_generation_gc import InventoryError

UUID="a"*8+"-"+"a"*4+"-"+"a"*4+"-"+"a"*4+"-"+"a"*12


class SnapperProtectionTests(unittest.TestCase):
    def report(self, userdata=(), **fields):
        row={"fields":{"num":"1","type":"single","cleanup":"timeline",**fields},
             "userdata":list(userdata),"sha256":"b"*64}
        return protection_report([row],uuid_by_number={1:UUID},referenced_uuids=[],source_revision="c"*40)

    def test_ordinary_label_never_becomes_mutation_authority(self):
        report=self.report()
        self.assertFalse(report["execution_authorized"])
        self.assertIsNone(report["plan"])
        self.assertFalse(report["objects"][0]["retirement_eligible"])
        self.assertIn("recovery_writer_exclusion_uncertified",report["blockers"])

    def test_unreferenced_important_and_maho_snapshots_are_protected(self):
        report=self.report([{"key":"important","value":"yes"},{"key":"maho.restore_backup","value":"yes"}])
        self.assertEqual(report["objects"][0]["protection_reasons"],["snapper_important_marker","maho_recovery_marker"])

    def test_unclassified_and_unknown_identity_are_protected(self):
        report=self.report(cleanup=None)
        self.assertIn("manual_or_unclassified_snapshot",report["objects"][0]["protection_reasons"])
        row={"fields":{"num":"1","type":"single","cleanup":"timeline"},"userdata":[]}
        report=protection_report([row],uuid_by_number={},referenced_uuids=[],source_revision="c"*40)
        self.assertIn("snapshot_uuid_unresolved",report["objects"][0]["protection_reasons"])

    def test_corrupt_or_duplicate_metadata_refuses(self):
        row={"fields":{"num":"1","type":"single","cleanup":"timeline"},"userdata":[]}
        for rows in ([row,row],[{"fields":{"num":"../1"},"userdata":[]}],[{"fields":{"num":"1"},"userdata":[{}]}]):
            with self.assertRaises(InventoryError):
                protection_report(rows,uuid_by_number={1:UUID},referenced_uuids=[],source_revision="c"*40)
