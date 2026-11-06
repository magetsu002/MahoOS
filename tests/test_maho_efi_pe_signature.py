#!/usr/bin/env python3
"""EFI PE/COFF Authenticode presence is never confused with firmware trust."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from maho_efi_pe_signature import inspect_pe_signature_structure  # noqa: E402


def fixture(*, signed=False, bad_directory=False):
    data = bytearray(512)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3c, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<H", data, 128 + 20, 240)
    optional = 128 + 24
    struct.pack_into("<H", data, optional, 0x20b)
    struct.pack_into("<I", data, optional + 108, 16)
    if signed or bad_directory:
        struct.pack_into("<II", data, optional + 112 + 4 * 8,
                         480 if bad_directory else 448, 40 if bad_directory else 16)
    if signed:
        struct.pack_into("<IHH", data, 448, 16, 0x200, 2)
        data[456:464] = b"sigbytes"
    return bytes(data)


class PeSignaturePresenceTests(unittest.TestCase):
    def test_unsigned_efi_is_definitely_unsigned(self):
        result = inspect_pe_signature_structure(fixture())
        self.assertEqual(result.status, "AUTHENTICODE_ABSENT")
        self.assertFalse(result.cryptographically_verified)
        self.assertFalse(result.firmware_db_authorized)

    def test_certificate_table_present_not_verified(self):
        result = inspect_pe_signature_structure(fixture(signed=True))
        self.assertEqual(result.status, "AUTHENTICODE_PRESENT_UNVERIFIED")
        self.assertEqual(result.certificate_count, 1)
        self.assertFalse(result.as_dict()["cryptographically_verified"])
        self.assertFalse(result.as_dict()["firmware_db_authorized"])

    def test_malformed_certificate_table_rejects(self):
        self.assertEqual(inspect_pe_signature_structure(fixture(bad_directory=True)).status,
                         "PE_OR_SECURITY_DIRECTORY_INVALID")

    def test_invalid_pe_refused(self):
        cases = [b"", b"not a PE", fixture()[:80],
                 fixture().replace(b"PE\0\0", b"ZZ\0\0", 1)]
        for data in cases:
            with self.subTest(size=len(data)):
                self.assertEqual(inspect_pe_signature_structure(data).status,
                                 "PE_OR_SECURITY_DIRECTORY_INVALID")

    def test_invalid_cert_header_refused(self):
        data = bytearray(fixture(signed=True))
        struct.pack_into("<I", data, 448, 4)
        self.assertEqual(inspect_pe_signature_structure(bytes(data)).status,
                         "PE_OR_SECURITY_DIRECTORY_INVALID")


if __name__ == "__main__":
    unittest.main(verbosity=2)
