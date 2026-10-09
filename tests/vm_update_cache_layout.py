#!/usr/bin/env python3
"""Real cache provisioning/exclusion/capacity proof; disposable guest only."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"lib"),str(ROOT/"tests")]
if os.environ.get("MAHO_DISPOSABLE_VM_TEST") != "1" or os.geteuid() != 0:
    raise SystemExit("Explicit disposable guest scope required")
if not Path("/sys/class/dmi/id/product_name").read_text().startswith(("Standard PC","QEMU")):
    raise SystemExit("Refusing physical boundary")

from maho_update_cache_layout import CACHE, RECORD, UNIT_NAME, UNIT_PATH, SUBVOLUME, installation_plan, install_cache, observe_layout, staging_root, transaction_root
from maho_update_campaign import _campaign_mutex
from maho_update_native import NativeBtrfsOps
from maho_update_artifact_lifecycle import UpdateArchiveLifecycle, archive_usage
from maho_generation_gc import InventoryError
from test_update_archive_lifecycle import ArchiveLifecycleTests, OLD, ACTIVE, REV, NOW


def run(*argv):
    return subprocess.run(argv,check=True,text=True,capture_output=True).stdout


class CacheVMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_revision=run("git","-C",str(ROOT),"rev-parse","HEAD").strip()
        cls.ops=NativeBtrfsOps("upd-20000101T000000Z-000000000001")
        cls.identity=cls.ops.root_identity()
        Path("/var/cache/maho").mkdir(exist_ok=True)
        RECORD.parent.mkdir(parents=True,exist_ok=True)
        cls.plan=installation_plan(cls.source_revision,cls.identity.filesystem_uuid)
        with _campaign_mutex():
            cls.layout=install_cache(cls.plan,confirmation=cls.plan["plan_sha256"],source_revision=cls.source_revision)

    def test_01_mount_identity_replay_and_missing_mount_refusal(self):
        self.assertEqual(observe_layout(),self.layout)
        self.assertEqual(staging_root("auto"),CACHE/"auto")
        self.assertIn("enabled",run("systemctl","is-enabled",UNIT_NAME))
        with _campaign_mutex(),self.assertRaises(InventoryError):
            install_cache(self.plan,confirmation=self.plan["plan_sha256"],source_revision=self.source_revision)
        run("systemctl","stop",UNIT_NAME)
        try:
            with self.assertRaises(InventoryError): staging_root("auto")
            self.assertEqual(list(CACHE.iterdir()),[])
        finally:
            run("systemctl","start",UNIT_NAME)
        self.assertEqual(observe_layout(),self.layout)

    def test_02_actual_capacity_recovers_while_root_snapshot_remains(self):
        fixture=ArchiveLifecycleTests("test_retirement_preserves_active_manifest_receipt_and_logs")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        isolated=CACHE/"auto"
        shutil.copytree(fixture.cache,isolated,dirs_exist_ok=True)
        content=os.urandom(32*1024**2)
        archive=isolated/OLD/"staging/demo-2-1-any.pkg.tar.zst"
        archive.write_bytes(content)
        for txid in (OLD,ACTIVE):
            manifest_path=next((isolated/txid/"staging").glob("manifest-*.json"))
            manifest=json.loads(manifest_path.read_text());payload=manifest["payloads"][0]
            payload["path"]=str(isolated/txid/"staging/demo-2-1-any.pkg.tar.zst")
            if txid == OLD: payload.update(size=len(content),sha256=hashlib.sha256(content).hexdigest())
            manifest_path.write_text(json.dumps(manifest))
        lifecycle=UpdateArchiveLifecycle(update_root=fixture.state,generation_root=fixture.generations,
                    guardian_active=fixture.guardian,guardian_uid=0,roots={"isolated-auto":isolated})
        self.ops._mount_top(self.identity)
        snapshot=self.ops.top/"@cache-layout-proof-retained"
        run("btrfs","subvolume","snapshot","-r","/",str(snapshot))
        excluded=snapshot/CACHE.relative_to("/")
        self.assertEqual(list(excluded.iterdir()),[])
        self.assertEqual((snapshot/UNIT_PATH.relative_to("/")).read_bytes(),UNIT_PATH.read_bytes())
        run("btrfs","filesystem","sync",str(CACHE))
        before=shutil.disk_usage(CACHE).free
        receipt=lifecycle.collect(source_revision=REV,now=NOW)
        run("btrfs","filesystem","sync",str(CACHE))
        after=shutil.disk_usage(CACHE).free
        self.assertEqual(receipt["phase"],"COMMITTED")
        self.assertGreater(after-before,24*1024**2)
        self.assertEqual(run("btrfs","property","get","-ts",str(snapshot),"ro").strip(),"ro=true")
        self.assertTrue((isolated/ACTIVE/"staging/demo-2-1-any.pkg.tar.zst").exists())
        print(json.dumps({"isolated_retired_allocation":receipt["reclaimed_bytes"],
                          "physical_available_change":after-before,"protected_root_snapshot_intact":True}),flush=True)
        # Snapshot is deliberately retained until this disposable overlay ends.
        self.ops.close()

    def test_03_legacy_path_and_budget_are_preserved(self):
        legacy=Path("/var/cache/maho/update-auto")/"upd-20000101T000000Z-000000000002"
        legacy.mkdir(parents=True)
        staging=legacy/"staging";staging.mkdir();payload=staging/"legacy-1-any.pkg.tar.zst"
        payload.write_bytes(os.urandom(4096))
        self.assertEqual(transaction_root(legacy.name,"auto"),legacy.parent)
        self.assertGreaterEqual(archive_usage(),payload.stat().st_blocks*512)
        self.assertTrue(payload.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
