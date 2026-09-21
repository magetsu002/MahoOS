#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_admission import EffectKind  # noqa: E402
from maho_mutation_authority import (  # noqa: E402
    BREAK_GLASS_MAX_LIFETIME_NS, MutationAuthorityError, issue_authority,
    parse_authority, process_identity,
)
from maho_prevention_policy import MutationOperation, SubjectIdentity  # noqa: E402


def check(name: str, value: bool) -> None:
    if not value:
        raise AssertionError(name)
    print("PASS", name)


def rejects(name: str, fn) -> None:
    try:
        fn()
    except MutationAuthorityError:
        print("PASS", name)
        return
    raise AssertionError(name)


SECRET = b"s" * 32
SUBJECT = SubjectIdentity(123, 456, "/usr/bin/python", "a" * 64, 8, 99, 0)


def issue(**overrides):
    values = dict(
        secret=SECRET, transaction_id="upd-exact", parent_authority_id="art-" + "1" * 64,
        parent_kind="maho-update-admission-activation-authority", subject=SUBJECT,
        effects=(EffectKind.BOOT_STATE,), operations=(MutationOperation.WRITE,),
        target_prefixes=("/boot/vmlinuz-linux",), issued_at_ns=10,
        expires_at_ns=100, boot_id="boot-exact", source_revision="b" * 40,
        generation_id="gen-exact", break_glass=False,
    )
    values.update(overrides)
    return issue_authority(**values)


def main() -> None:
    authority = issue()
    parsed = parse_authority(authority.as_dict(), secret=SECRET, boot_id="boot-exact", now_ns=50)
    check("exact authority roundtrips", parsed == authority and parsed.as_view().transaction_id == "upd-exact")
    changed = authority.as_dict() | {"transaction_id": "upd-other"}
    rejects("changed transaction fails authentication", lambda: parse_authority(changed, secret=SECRET, boot_id="boot-exact", now_ns=50))
    rejects("wrong machine secret is rejected", lambda: parse_authority(authority.as_dict(), secret=b"x" * 32, boot_id="boot-exact", now_ns=50))
    rejects("authority cannot cross boot", lambda: parse_authority(authority.as_dict(), secret=SECRET, boot_id="boot-other", now_ns=50))
    rejects("expired envelope is rejected", lambda: parse_authority(authority.as_dict(), secret=SECRET, boot_id="boot-exact", now_ns=100))
    rejects("unregistered parent kind cannot issue", lambda: issue(parent_kind="some-executable"))
    rejects("global root scope cannot be granted", lambda: issue(target_prefixes=("/",)))
    rejects("subject digest must be exact", lambda: issue(subject=replace(SUBJECT, executable_sha256="unknown")))
    break_glass = issue(
        transaction_id="break-glass-exact", parent_authority_id="auth-session-1",
        parent_kind="maho-break-glass-authentication", break_glass=True,
        expires_at_ns=10 + BREAK_GLASS_MAX_LIFETIME_NS,
    )
    check("bounded authenticated break glass is distinct", break_glass.break_glass and break_glass.target_prefixes == ("/boot/vmlinuz-linux",))
    rejects("break glass cannot outlive five minutes", lambda: issue(
        transaction_id="break-glass-exact", parent_authority_id="auth-session-1",
        parent_kind="maho-break-glass-authentication", break_glass=True,
        expires_at_ns=11 + BREAK_GLASS_MAX_LIFETIME_NS,
    ))
    current = process_identity(__import__("os").getpid())
    check("live process identity binds pid start executable inode and digest", current.pid > 0 and current.start_time_ns > 0 and current.executable_inode > 0 and len(current.executable_sha256) == 64)
    print("ALL MAHO MUTATION AUTHORITY TESTS PASS")


if __name__ == "__main__":
    main()
