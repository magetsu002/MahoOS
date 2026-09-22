#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import os
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_admission import EffectKind  # noqa: E402
from maho_mutation_authority import process_identity  # noqa: E402
from maho_process_control import (  # noqa: E402
    ProcessControlAuthorityError, issue_process_control_authority,
    parse_process_control_authority, signal_mask,
)
import maho_prevention_kernel as kernel  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def main() -> None:
    subject = process_identity(os.getpid())
    secret = b"p" * 32
    authority = issue_process_control_authority(
        secret=secret,
        transaction_id="recovery-process-control",
        parent_authority_id="recovery-" + "1" * 64,
        parent_kind="guardian-recovery-execution-authority",
        subject=subject,
        target=subject,
        effect=EffectKind.SYSTEM_SERVICE,
        signals=(15, 9),
        issued_at_ns=100,
        expires_at_ns=200,
        boot_id="boot-fixture",
        source_revision="a" * 40,
        generation_id="gen-fixture",
    )
    check("signals canonicalize exactly", authority.signals == (9, 15))
    check("signal mask is exact", signal_mask(authority.signals) == (1 << 8) | (1 << 14))
    parsed = parse_process_control_authority(
        authority.as_dict(), secret=secret, boot_id="boot-fixture", now_ns=150,
    )
    check("signed process authority roundtrips", parsed == authority)

    tampered = authority.as_dict()
    tampered["signals"] = [9]
    try:
        parse_process_control_authority(
            tampered, secret=secret, boot_id="boot-fixture", now_ns=150,
        )
    except ProcessControlAuthorityError as exc:
        check("signal tampering is rejected", str(exc) == "authority_authentication_failed")
    else:
        raise AssertionError("tampered process authority accepted")

    try:
        parse_process_control_authority(
            authority.as_dict(), secret=secret, boot_id="other-boot", now_ns=150,
        )
    except ProcessControlAuthorityError as exc:
        check("process authority cannot cross boot", str(exc) == "authority_boot_identity_mismatch")
    else:
        raise AssertionError("cross-boot process authority accepted")

    try:
        parse_process_control_authority(
            authority.as_dict(), secret=secret, boot_id="boot-fixture", now_ns=200,
        )
    except ProcessControlAuthorityError as exc:
        check("expired process authority is rejected", str(exc) == "authority_expired")
    else:
        raise AssertionError("expired process authority accepted")

    updates: list[tuple[bytes, bytes]] = []
    original_get = kernel._object_get
    original_update = kernel._map_update
    original_identity = kernel.process_identity
    kernel._object_get = lambda path: os.open("/dev/null", os.O_RDONLY)
    kernel._map_update = lambda fd, key, value: updates.append((key, value))
    kernel.process_identity = lambda pid: subject
    try:
        registered = kernel.register_protected_process(
            subject.pid, Path("/fixture/protected_processes"), EffectKind.SYSTEM_SERVICE,
        )
        check("protected registration returns exact identity", registered == subject)
        check("protected process key has stable C layout", len(updates[-1][0]) == 32)
        process_value = struct.unpack("=QII", updates[-1][1])
        check(
            "protected registration carries only requested effect",
            process_value[0] == kernel.EFFECT_BITS[EffectKind.SYSTEM_SERVICE],
        )
        projected = kernel.project_process_authority(
            authority, Path("/fixture/process_control_authorities"),
        )
        check("one process authority is projected", projected == 1)
        check("caller and target identity form exact kernel key", len(updates[-1][0]) == 64)
        expiry, effect, signals, transaction = struct.unpack("=QQQQ", updates[-1][1])
        check("kernel process authority keeps exact expiry", expiry == 200)
        check("kernel process authority keeps exact effect", effect == kernel.EFFECT_BITS[EffectKind.SYSTEM_SERVICE])
        check("kernel process authority keeps exact signals", signals == signal_mask((9, 15)))
        check("kernel process authority carries transaction tag", transaction != 0)

        drifted = replace(subject, start_time_ticks=subject.start_time_ticks + 1)
        kernel.process_identity = lambda pid: drifted
        try:
            kernel.project_process_authority(
                authority, Path("/fixture/process_control_authorities"),
            )
        except PermissionError:
            check("PID reuse or target drift blocks projection", True)
        else:
            raise AssertionError("drifted process authority projected")
    finally:
        kernel._object_get = original_get
        kernel._map_update = original_update
        kernel.process_identity = original_identity

    print("ALL MAHO PROCESS CONTROL TESTS PASS")


if __name__ == "__main__":
    main()
