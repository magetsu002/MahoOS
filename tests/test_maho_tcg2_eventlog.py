#!/usr/bin/env python3
"""TCG2 log fixtures and adversarial PCR/measurement replay verification."""
from pathlib import Path
import hashlib
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from maho_limine_measurements import predict_limine_measurements  # noqa: E402
from maho_tpm_unlock_policy import observe_limine_tpm_unlock  # noqa: E402
from maho_tcg2_eventlog import (  # noqa: E402
    EventLogError, EV_IPL, EV_NO_ACTION, parse_tcg2_eventlog,
    replay_sha256_pcrs, verify_limine_pcr_event_chain,
)


def first_event():
    spec = (b"Spec ID Event03\0" + struct.pack("<I", 0) + bytes((0, 2, 0, 2))
            + struct.pack("<I", 2) + struct.pack("<HH", 0x0004, 20)
            + struct.pack("<HH", 0x000B, 32) + bytes((0,)))
    return struct.pack("<II", 0, EV_NO_ACTION) + bytes(20) + struct.pack("<I", len(spec)) + spec


def event(pcr, kind, data, sha256=None):
    digest = hashlib.sha256(data).digest() if sha256 is None else sha256
    return (struct.pack("<III", pcr, kind, 2)
            + struct.pack("<H", 0x0004) + bytes(20)
            + struct.pack("<H", 0x000B) + digest
            + struct.pack("<I", len(data)) + data)


def fixture():
    kernel, initrd = b"vmlinuz-test", b"initramfs-test"
    p0, p1 = "/EFI/MahoOS/Normal/kernel", "/EFI/MahoOS/Normal/initramfs.img"
    resources = {p0: kernel, p1: initrd}
    def path(p):
        return "boot():" + p + "#" + hashlib.blake2b(resources[p], digest_size=64).hexdigest()
    cfg = ("measured_boot: yes\nhash_mismatch_panic: yes\n"
           "/MahoOS Primary\n protocol: linux\n"
           f" path: {path(p0)}\n"
           f" module_path: {path(p1)}\n"
           " cmdline: root=UUID=test ro\n").encode()
    prediction = predict_limine_measurements(
        config=cfg, entry="MahoOS Primary", resources=resources,
        limine_version="12.9.0", secure_boot_enforced=True,
    )
    description8 = (b"cmdline: root=UUID=test ro", b"path: boot():" + p0.encode(),
                    b"module_path: boot():" + p1.encode())
    description9 = (b"limine_cfg", b"path: boot():" + p0.encode(),
                    b"module_path: boot():" + p1.encode())
    raw = first_event()
    raw += event(7, 0x80000001, b"firmware db event")
    for digest, description in zip(prediction.pcr8_event_digests, description8):
        raw += event(8, EV_IPL, description + b"\x00", bytes.fromhex(digest))
    for digest, description in zip(prediction.pcr9_event_digests, description9):
        raw += event(9, EV_IPL, description + b"\x00", bytes.fromhex(digest))
    parsed = parse_tcg2_eventlog(raw)
    hardware_pcrs = replay_sha256_pcrs(parsed)
    return prediction, raw, parsed, hardware_pcrs


class TcgEventLogTests(unittest.TestCase):
    def test_correct_log_replays_and_matches_predicted_limine_chain(self):
        pred, _, log, pcrs = fixture()
        self.assertEqual(len(log), 7)
        self.assertEqual(verify_limine_pcr_event_chain(
            prediction=pred, events=log, independently_read_sha256_pcrs=pcrs), ())

    def test_tpm_observation_is_derived_from_replay(self):
        pred, raw, _, pcrs = fixture()
        obs = observe_limine_tpm_unlock(
            prediction=pred, event_log=raw,
            independently_read_sha256_pcrs=pcrs,
            boot_generation_id="bootgen-" + "a" * 64,
            boot_mode="normal",
            luks_uuid="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            initramfs_tpm2_verified=True,
        )
        self.assertTrue(obs.event_log_replay_verified)
        self.assertEqual(obs.event_log_sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(set(obs.pcr_sha256), {7, 8, 9})
        self.assertIn("initramfs", obs.event_roles)

    def test_tpm_observation_does_not_fabricate_replay_after_pcr_drift(self):
        pred, raw, _, pcrs = fixture()
        obs = observe_limine_tpm_unlock(
            prediction=pred, event_log=raw,
            independently_read_sha256_pcrs=pcrs | {9: "f" * 64},
            boot_generation_id="bootgen-" + "a" * 64, boot_mode="normal",
            luks_uuid="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            initramfs_tpm2_verified=True,
        )
        self.assertFalse(obs.event_log_replay_verified)
        self.assertFalse(obs.event_roles)

    def test_modified_tpm_pcr_rejected(self):
        pred, _, log, pcrs = fixture()
        changed = pcrs | {9: "a" * 64}
        self.assertIn("tpm_sha256_pcr9_replay_mismatch", verify_limine_pcr_event_chain(
            prediction=pred, events=log, independently_read_sha256_pcrs=changed))

    def test_spoofed_cmdline_description_rejected_even_with_expected_digest(self):
        pred, _, log, pcrs = fixture()
        changed = list(log)
        original = changed[1]
        changed[1] = type(original)(
            original.pcr_index, original.event_type, original.sha256_digest,
            b"cmdline: root=UUID=attacker rw",
        )
        blockers = verify_limine_pcr_event_chain(
            prediction=pred, events=changed, independently_read_sha256_pcrs=pcrs,
        )
        self.assertIn("limine_pcr8_event_description_mismatch:0", blockers)

    def test_missing_event_description_nul_rejected_even_with_valid_digest(self):
        pred, _, log, pcrs = fixture()
        changed = list(log)
        original = changed[1]
        changed[1] = type(original)(
            original.pcr_index, original.event_type, original.sha256_digest,
            original.data[:-1],
        )
        self.assertIn("limine_pcr8_event_description_mismatch:0",
                      verify_limine_pcr_event_chain(
                          prediction=pred, events=changed,
                          independently_read_sha256_pcrs=pcrs))

    def test_missing_tpm_bank_rejected(self):
        pred, _, log, pcrs = fixture()
        del pcrs[7]
        self.assertIn("tpm_sha256_pcr7_missing", verify_limine_pcr_event_chain(
            prediction=pred, events=log, independently_read_sha256_pcrs=pcrs))

    def test_extra_pcr9_limine_event_rejected(self):
        pred, _, log, pcrs = fixture()
        changed = log + (log[-1],)
        self.assertIn("limine_pcr9_event_count_mismatch", verify_limine_pcr_event_chain(
            prediction=pred, events=changed, independently_read_sha256_pcrs=pcrs))

    def test_tampered_config_event_digest_rejected(self):
        pred, _, log, pcrs = fixture()
        changed = list(log)
        changed[4] = type(changed[4])(9, EV_IPL, b"q" * 32, changed[4].data)
        self.assertIn("limine_pcr9_event_digest_mismatch:0", verify_limine_pcr_event_chain(
            prediction=pred, events=changed, independently_read_sha256_pcrs=pcrs))

    def test_malformed_logs_fail_closed(self):
        _, raw, _, _ = fixture()
        cases = (b"", raw[:30], raw[:-1],
                 raw.replace(b"Spec ID Event03\0", b"Spec ID Event04\0"),
                 raw + b"\0",
                 raw[:28] + struct.pack("<I", 0xffffffff) + raw[32:],
                 raw[:4] + struct.pack("<I", EV_IPL) + raw[8:])
        for index, candidate in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(EventLogError):
                parse_tcg2_eventlog(candidate)

    def test_pcr_replay_excludes_no_action_records(self):
        _, _, log, pcrs = fixture()
        changed = log + (type(log[0])(0, EV_NO_ACTION, bytes(32), b"no action"),)
        self.assertEqual(replay_sha256_pcrs(changed)[7], pcrs[7])


if __name__ == "__main__":
    unittest.main(verbosity=2)
