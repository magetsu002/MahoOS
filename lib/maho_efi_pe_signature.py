#!/usr/bin/env python3
"""Read-only PE/COFF Authenticode certificate-table structural inspection.

A present certificate table is NOT signature verification or UEFI db trust.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct


@dataclass(frozen=True)
class PeSignatureStructure:
    status: str
    certificate_count: int
    cryptographically_verified: bool = False
    firmware_db_authorized: bool = False

    def as_dict(self) -> dict[str, str | int | bool]:
        return {
            "status": self.status,
            "certificate_count": self.certificate_count,
            "cryptographically_verified": False,
            "firmware_db_authorized": False,
        }


def inspect_pe_signature_structure(image: bytes) -> PeSignatureStructure:
    invalid = PeSignatureStructure("PE_OR_SECURITY_DIRECTORY_INVALID", 0)
    if len(image) < 64 or image[:2] != b"MZ":
        return invalid
    pe = struct.unpack_from("<I", image, 0x3c)[0]
    if pe > len(image) - 24 or image[pe:pe + 4] != b"PE\0\0":
        return invalid
    opt_size = struct.unpack_from("<H", image, pe + 20)[0]
    opt = pe + 24
    if opt_size < 2 or opt + opt_size > len(image):
        return invalid
    magic = struct.unpack_from("<H", image, opt)[0]
    if magic == 0x20b:
        number_dirs, first_dir = opt + 108, opt + 112
    elif magic == 0x10b:
        number_dirs, first_dir = opt + 92, opt + 96
    else:
        return invalid
    security = first_dir + 4 * 8
    if opt + opt_size < security + 8 or number_dirs + 4 > opt + opt_size:
        return invalid
    if struct.unpack_from("<I", image, number_dirs)[0] < 5:
        return invalid
    offset, size = struct.unpack_from("<II", image, security)
    if offset == size == 0:
        return PeSignatureStructure("AUTHENTICODE_ABSENT", 0)
    if not offset or not size or size < 8 or offset > len(image) - size:
        return invalid
    count = 0
    cursor = offset
    end = offset + size
    while cursor < end:
        if end - cursor < 8:
            return invalid
        length, revision, kind = struct.unpack_from("<IHH", image, cursor)
        if length < 8 or length > end - cursor or revision not in (0x100, 0x200) or kind != 2:
            return invalid
        cursor += (length + 7) & ~7
        if cursor > end:
            return invalid
        count += 1
    return PeSignatureStructure("AUTHENTICODE_PRESENT_UNVERIFIED", count)
