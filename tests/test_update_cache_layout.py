#!/usr/bin/env python3
"""Cache identity and refusal boundaries; no host mount/provision operations."""
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import maho_update_cache_layout as layout
from maho_generation_gc import InventoryError, digest_payload

FS = "11111111-1111-1111-1111-111111111111"
SUB = "22222222-2222-2222-2222-222222222222"
REV = "a" * 40


class CacheIdentityTests(unittest.TestCase):
    def setUp(self):
        self.unit = layout.mount_unit(FS).encode()
        self.record = {"kind":"maho-isolated-update-cache", "schema_version":1, "phase":"COMMITTED",
                       "source_revision":REV, "filesystem_uuid":FS, "subvolume_uuid":SUB,
                       "subvolume":layout.SUBVOLUME, "path":str(layout.CACHE),
                       "mount_unit_sha256":hashlib.sha256(self.unit).hexdigest()}
        self.record["layout_sha256"] = digest_payload(self.record)
        self.cache_mount = {"target":str(layout.CACHE), "fstype":"btrfs", "fsroot":"/"+layout.SUBVOLUME,
                            "uuid":FS, "options":"rw,nodev,nosuid,noexec,relatime"}
        self.root_mount = {"target":"/", "fstype":"btrfs", "fsroot":"/@", "uuid":FS}
        self.uuid = SUB; self.readonly = False

    def probe(self, argv):
        if argv[0].endswith("findmnt"):
            row = self.cache_mount if "--mountpoint" in argv else self.root_mount
            return json.dumps({"filesystems":[row]})
        if argv[1:3] == ("subvolume", "show"):
            return "\tUUID: " + self.uuid + "\n"
        if argv[1:3] == ("property", "get"):
            return "ro=" + str(self.readonly).lower() + "\n"
        self.fail("unexpected observer command: " + repr(argv))

    def observe(self, **kwargs):
        return layout.validate_layout(self.record, probe=self.probe, unit_bytes=self.unit,
                                      observed_uid=0, observed_mode=0o755, **kwargs)

    def test_exact_mount_and_uuid_accept(self):
        self.assertEqual(self.observe(), self.record)

    def test_wrong_mount_device_path_and_options_refuse(self):
        for key, value in [("target","/"), ("fstype","ext4"), ("fsroot","/@"),
                           ("uuid",SUB), ("options","rw,nodev,nosuid")]:
            with self.subTest(key=key):
                prior = self.cache_mount[key]; self.cache_mount[key] = value
                with self.assertRaises(InventoryError): self.observe()
                self.cache_mount[key] = prior

    def test_root_filesystem_and_cache_uuid_drift_refuse(self):
        self.root_mount["uuid"] = SUB
        with self.assertRaises(InventoryError): self.observe()
        self.root_mount["uuid"] = FS; self.uuid = FS
        with self.assertRaises(InventoryError): self.observe()
        self.uuid = SUB; self.readonly = True
        with self.assertRaises(InventoryError): self.observe()

    def test_unit_substitution_owner_and_writable_modes_refuse(self):
        for unit, uid, mode in [(self.unit+b"\n",0,0o755),(self.unit,1000,0o755),(self.unit,0,0o775)]:
            with self.assertRaises(InventoryError):
                layout.validate_layout(self.record, probe=self.probe, unit_bytes=unit,
                                       observed_uid=uid, observed_mode=mode)

    def test_rehashed_wrong_fixed_target_still_refuses(self):
        self.record["path"] = "/home/cache"
        self.record.pop("layout_sha256"); self.record["layout_sha256"] = digest_payload(self.record)
        with self.assertRaises(InventoryError): self.observe()

    def test_missing_layout_does_not_create_or_select_ordinary_directory(self):
        with patch.object(layout, "observe_layout", side_effect=FileNotFoundError), patch.object(Path, "mkdir") as mkdir:
            with self.assertRaises(FileNotFoundError): layout.staging_root("auto")
            mkdir.assert_not_called()

    def test_installation_plan_exact_short_lived_identity(self):
        now = datetime(2026,10,9,tzinfo=timezone.utc)
        plan = layout.installation_plan(REV, FS, now=now)
        self.assertEqual((datetime.fromisoformat(plan["expires_at"])-now).total_seconds(),300)
        self.assertEqual(plan["mount_unit_sha256"], hashlib.sha256(self.unit).hexdigest())
        for rev, fs in [("HEAD",FS),(REV,FS+"\nWhat=/dev/sda")]:
            with self.assertRaises(InventoryError): layout.installation_plan(rev,fs,now=now)

    def test_installation_requires_explicit_root_boundary(self):
        plan=layout.installation_plan(REV,FS)
        with patch.object(os,"geteuid",return_value=1000):
            with self.assertRaises(PermissionError):
                layout.install_cache(plan,confirmation=plan["plan_sha256"],source_revision=REV)


if __name__ == "__main__":
    unittest.main()
