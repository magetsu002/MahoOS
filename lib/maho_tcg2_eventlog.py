#!/usr/bin/env python3
"""Strict read-only TCG PC Client crypto-agile event-log parser and PCR replay.

This verifies *provided bytes*. Hardware trust additionally requires an
independent TPM PCR read/quote bound to the actual boot session and firmware
Secure Boot observations. Do not call source-level replay hardware proof.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import struct
from typing import Mapping, Sequence

from maho_limine_measurements import LimineMeasurement

SHA256_ALG = 0x000B
EV_NO_ACTION = 0x00000003
EV_IPL = 0x0000000D
MAX_LOG_BYTES = 32 * 1024 * 1024
MAX_EVENTS = 50000
MAX_EVENT_BYTES = 16 * 1024 * 1024


class EventLogError(ValueError):
    pass


@dataclass(frozen=True)
class TcgEvent:
    pcr_index: int
    event_type: int
    sha256_digest: bytes
    data: bytes


def _u32(raw: bytes, cursor: int, end: int) -> int:
    if cursor < 0 or cursor + 4 > end:
        raise EventLogError("tcg_log_truncated")
    return struct.unpack_from("<I", raw, cursor)[0]


def parse_tcg2_eventlog(raw: bytes) -> tuple[TcgEvent, ...]:
    if not isinstance(raw, bytes) or not 32 <= len(raw) <= MAX_LOG_BYTES:
        raise EventLogError("tcg_log_size_invalid")
    if (_u32(raw, 0, len(raw)) != 0 or _u32(raw, 4, len(raw)) != EV_NO_ACTION
            or raw[8:28] != bytes(20)):
        raise EventLogError("tcg_spec_event_invalid")
    size = _u32(raw, 28, len(raw))
    if size < 29 or size > MAX_EVENT_BYTES or 32 + size > len(raw):
        raise EventLogError("tcg_spec_event_size_invalid")
    spec = raw[32:32 + size]
    if spec[:16] != b"Spec ID Event03\x00":
        raise EventLogError("tcg_spec_event_signature_invalid")
    count = _u32(spec, 24, len(spec))
    if not 1 <= count <= 16 or 28 + count * 4 + 1 > len(spec):
        raise EventLogError("tcg_spec_algorithm_count_invalid")
    algorithms: dict[int, int] = {}
    for index in range(count):
        alg, length = struct.unpack_from("<HH", spec, 28 + index * 4)
        if alg in algorithms or not 1 <= length <= 128:
            raise EventLogError("tcg_spec_algorithm_invalid")
        algorithms[alg] = length
    if algorithms.get(SHA256_ALG) != 32:
        raise EventLogError("tcg_sha256_bank_missing")
    vendor = 28 + count * 4
    if vendor + 1 + spec[vendor] != len(spec):
        raise EventLogError("tcg_spec_vendor_data_invalid")
    cursor = 32 + size
    events: list[TcgEvent] = []
    while cursor < len(raw):
        if len(events) >= MAX_EVENTS:
            raise EventLogError("tcg_event_count_exceeded")
        if cursor + 12 > len(raw):
            raise EventLogError("tcg_event_header_truncated")
        pcr, event_type, digest_count = struct.unpack_from("<III", raw, cursor)
        cursor += 12
        if pcr >= 24 or digest_count != len(algorithms):
            raise EventLogError("tcg_event_pcr_or_digest_count_invalid")
        digests: dict[int, bytes] = {}
        for _ in range(digest_count):
            if cursor + 2 > len(raw):
                raise EventLogError("tcg_event_digest_truncated")
            algorithm = struct.unpack_from("<H", raw, cursor)[0]
            cursor += 2
            if algorithm not in algorithms or algorithm in digests:
                raise EventLogError("tcg_event_digest_algorithm_invalid")
            length = algorithms[algorithm]
            if cursor + length > len(raw):
                raise EventLogError("tcg_event_digest_truncated")
            digests[algorithm] = raw[cursor:cursor + length]
            cursor += length
        if cursor + 4 > len(raw):
            raise EventLogError("tcg_event_size_missing")
        payload_length = _u32(raw, cursor, len(raw))
        cursor += 4
        if payload_length > MAX_EVENT_BYTES or cursor + payload_length > len(raw):
            raise EventLogError("tcg_event_payload_invalid")
        payload = raw[cursor:cursor + payload_length]
        cursor += payload_length
        if event_type == EV_NO_ACTION and any(value.strip(b"\0") for value in digests.values()):
            raise EventLogError("tcg_no_action_nonzero_digest")
        events.append(TcgEvent(pcr, event_type, digests[SHA256_ALG], payload))
    return tuple(events)


def replay_sha256_pcrs(events: Sequence[TcgEvent]) -> dict[int, str]:
    pcrs = {index: bytes(32) for index in range(24)}
    for event in events:
        if event.pcr_index not in pcrs or len(event.sha256_digest) != 32:
            raise EventLogError("tcg_event_sha256_invalid")
        if event.event_type != EV_NO_ACTION:
            pcrs[event.pcr_index] = hashlib.sha256(
                pcrs[event.pcr_index] + event.sha256_digest
            ).digest()
    return {i: value.hex() for i, value in pcrs.items()}


def verify_limine_pcr_event_chain(
    *, prediction: LimineMeasurement, events: Sequence[TcgEvent],
    independently_read_sha256_pcrs: Mapping[int, str],
) -> tuple[str, ...]:
    """Compare exact Limine EV_IPL sequence, replay and independent TPM PCRs.

    Returns fail-closed blockers; never marks a boot trusted by itself.
    Other PCR8/9 EV_IPL events are rejected because they could invalidate the
    predicted chain or indicate an unmodelled earlier boot attempt.
    """
    reasons: list[str] = []
    expected8 = prediction.pcr8_event_digests
    expected9 = prediction.pcr9_event_digests
    got8 = tuple(e for e in events if e.pcr_index == 8 and e.event_type == EV_IPL)
    got9 = tuple(e for e in events if e.pcr_index == 9 and e.event_type == EV_IPL)
    descriptions8 = (
        b"cmdline: ",
        b"path: " + prediction.measured_resources[0].encode(),
        *(b"module_path: " + path.encode() for path in prediction.measured_resources[1:]),
    )
    descriptions9 = (
        b"limine_cfg",
        b"path: " + prediction.measured_resources[0].encode(),
        *(b"module_path: " + path.encode() for path in prediction.measured_resources[1:]),
    )
    for number, records, predicted, expected_descriptions in (
        (8, got8, expected8, descriptions8),
        (9, got9, expected9, descriptions9),
    ):
        if len(records) != len(predicted):
            reasons.append(f"limine_pcr{number}_event_count_mismatch")
            continue
        for index, (item, digest, description) in enumerate(
            zip(records, predicted, expected_descriptions)
        ):
            if item.sha256_digest.hex() != digest:
                reasons.append(f"limine_pcr{number}_event_digest_mismatch:{index}")
            if number == 8 and index == 0:
                if not item.data.startswith(description):
                    reasons.append("limine_pcr8_cmdline_event_mismatch")
            elif item.data.rstrip(b"\x00") != description:
                reasons.append(f"limine_pcr{number}_event_description_mismatch:{index}")
    replayed = replay_sha256_pcrs(events)
    for index in (7, 8, 9):
        expected = independently_read_sha256_pcrs.get(index)
        if (not isinstance(expected, str) or len(expected) != 64
                or any(c not in "0123456789abcdef" for c in expected)):
            reasons.append(f"tpm_sha256_pcr{index}_missing")
        elif replayed[index] != expected:
            reasons.append(f"tpm_sha256_pcr{index}_replay_mismatch")
    return tuple(sorted(set(reasons)))
