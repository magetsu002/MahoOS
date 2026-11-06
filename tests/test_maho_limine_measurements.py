#!/usr/bin/env python3
"""Adversarial offline Limine PCR prediction contracts; never use a real TPM."""
from pathlib import Path
import hashlib
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from maho_limine_measurements import MeasurementError, predict_limine_measurements  # noqa: E402


def fixture(*, kernel=b"kernel-1", cmdline="root=UUID=abc ro", prefix=""):
    paths = {"/EFI/MahoOS/Normal/kernel": kernel,
             "/EFI/MahoOS/Normal/initramfs.img": b"initramfs-1",
             "/EFI/MahoOS/Recovery/kernel": b"lts-kernel",
             "/EFI/MahoOS/Recovery/initramfs.img": b"rescue-initramfs"}
    def resource(path):
        return "boot():" + path + "#" + hashlib.blake2b(paths[path], digest_size=64).hexdigest()
    cfg = ("measured_boot: yes\nhash_mismatch_panic: yes\n"
           "/MahoOS Primary\n protocol: linux\n"
           f" path: {resource('/EFI/MahoOS/Normal/kernel')}\n"
           f" module_path: {resource('/EFI/MahoOS/Normal/initramfs.img')}\n"
           f" cmdline: {cmdline}\n"
           "/MahoOS Fallback\n protocol: linux\n"
           f" kernel_path: {resource('/EFI/MahoOS/Recovery/kernel')}\n"
           f" module_path: {resource('/EFI/MahoOS/Recovery/initramfs.img')}\n"
           " kernel_cmdline: root=UUID=abc ro recovery=yes\n")
    return (prefix + cfg).encode(), paths


def predict(cfg, paths, entry="MahoOS Primary", **overrides):
    args = dict(config=cfg, resources=paths, entry=entry,
                limine_version="12.9.0", secure_boot_enforced=False)
    args.update(overrides)
    return predict_limine_measurements(**args)


class MeasuredBootContracts(unittest.TestCase):
    def test_primary_selected_even_with_following_fallback(self):
        config, paths = fixture()
        result = predict(config, paths)
        self.assertEqual(result.entry, "MahoOS Primary")
        self.assertEqual(len(result.measured_resources), 2)
        self.assertEqual(len(result.pcr8_event_digests), 3)
        self.assertEqual(len(result.pcr9_event_digests), 3)
        self.assertEqual(result.config_sha256, hashlib.sha256(config).hexdigest())

    def test_pcr8_ignores_hash_suffix_but_pcr9_follows_kernel_update(self):
        a, paths_a = fixture(kernel=b"kernel-1")
        b, paths_b = fixture(kernel=b"kernel-2")
        old = predict(a, paths_a)
        new = predict(b, paths_b)
        self.assertEqual(old.pcr8_limine_only, new.pcr8_limine_only)
        self.assertNotEqual(old.pcr9_limine_only, new.pcr9_limine_only)

    def test_pcr8_tracks_kernel_commandline(self):
        a, paths = fixture()
        b, _ = fixture(cmdline="root=UUID=abc ro debug=yes")
        self.assertNotEqual(predict(a, paths).pcr8_limine_only,
                            predict(b, paths).pcr8_limine_only)

    def test_pcr9_tracks_exact_config_bytes(self):
        config, paths = fixture()
        self.assertNotEqual(predict(config, paths).pcr9_limine_only,
                            predict(b"# harmless comment\n" + config, paths).pcr9_limine_only)

    def test_fallback_is_distinct_selection(self):
        config, paths = fixture()
        primary = predict(config, paths)
        fallback = predict(config, paths, "MahoOS Fallback")
        self.assertNotEqual(primary.pcr8_limine_only, fallback.pcr8_limine_only)
        self.assertNotEqual(primary.pcr9_limine_only, fallback.pcr9_limine_only)

    def rejects(self, config, paths, reason, **overrides):
        with self.assertRaisesRegex(MeasurementError, reason):
            predict(config, paths, **overrides)

    def test_invalid_inputs_rejected(self):
        cfg, paths = fixture()
        tests = (
            (b"\xff" + cfg, paths, "utf8", {}),
            (cfg, paths, "version_unproven", {"limine_version": "11.1"}),
            (cfg, paths, "entry_not_unique", {"entry": "Missing"}),
            (cfg, paths, "resource_bytes_missing", {"resources": {}}),
            (cfg, {**paths, "/EFI/MahoOS/Normal/kernel": b"tampered"}, "resource_integrity_mismatch", {}),
            (cfg.replace(b"boot():/EFI/MahoOS/Normal/kernel#", b"boot():/EFI/MahoOS/Normal/../kernel#"),
             paths, "resource_path_unsafe", {}),
            (cfg.replace(b"path: boot():/EFI/MahoOS/Normal/kernel", b"path: disk():/kernel"),
             paths, "resource_path_not_exact_and_hashed", {}),
            (cfg.replace(b"/MahoOS Primary", b"/MahoOS Primary\n protocol: efi"),
             paths, "option_duplicated", {}),
            (cfg.replace(b"/MahoOS Primary", b"/MahoOS Primary\n bootloader_untrusted: yes"),
             paths, "option_unmodelled", {}),
            (cfg.replace(b"hash_mismatch_panic: yes", b"hash_mismatch_panic: no"),
             paths, "hash_mismatch_panic_disabled", {}),
            (cfg.replace(b"measured_boot: yes", b"measured_boot: no"),
             paths, "measured_boot_inactive", {}),
            (cfg.replace(b"module_path: boot():/EFI/MahoOS/Normal/initramfs.img", b"module_path: boot():/EFI/MahoOS/Normal/../initramfs.img"),
             paths, "resource_path_unsafe", {}),
        )
        for index, (config, resources, reason, options) in enumerate(tests):
            with self.subTest(index=index):
                if "resources" in options:
                    resource_map = options["resources"]
                    options = {}
                else:
                    resource_map = resources
                self.rejects(config, resource_map, reason, **options)

    def test_secure_boot_forces_measuring_when_config_omits_option(self):
        cfg, paths = fixture()
        cfg = cfg.replace(b"measured_boot: yes\n", b"")
        result = predict(cfg, paths, secure_boot_enforced=True)
        self.assertEqual(len(result.pcr9_event_digests), 3)

    def test_missing_measurement_and_disabled_secure_boot_rejected(self):
        cfg, paths = fixture()
        self.rejects(cfg.replace(b"measured_boot: yes\n", b""), paths, "measured_boot_inactive")

    def test_repeated_selected_entry_is_ambiguous(self):
        cfg, paths = fixture()
        self.rejects(cfg + cfg[cfg.find(b"/MahoOS Primary"):cfg.find(b"/MahoOS Fallback")],
                     paths, "entry_not_unique")


if __name__ == "__main__":
    unittest.main(verbosity=2)
