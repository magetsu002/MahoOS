#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_admission import EffectKind  # noqa: E402
from maho_prevention_policy import (  # noqa: E402
    AuthorityView, MutationOperation, MutationRequest, PreventionOutcome,
    SubjectIdentity, decide_mutation,
)
from maho_prevention_scope import ProtectedDomain, TargetContext, classify_target  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


subject = SubjectIdentity(42, 1000, "/usr/bin/maho-update", "a" * 64, 8, 99, 0)


def request(path: str, operation: MutationOperation = MutationOperation.WRITE, **kw) -> MutationRequest:
    context = kw.pop("context", TargetContext(owner_home="/home/test", root_device="/dev/nvme0n1p2", boot_device="/dev/nvme0n1p1"))
    values = dict(
        subject=subject, target=classify_target(path, context=context), operation=operation,
        transaction_id="upd-exact", expected_scope=(path,), reversible=True,
        now_ns=10, source_revision="b" * 40, generation_id="gen-exact",
    )
    values.update(kw)
    return MutationRequest(**values)


def main() -> None:
    check("ordinary project deletion is unprotected", not classify_target("/home/test/src/build/output.o").protected)
    check("Maho runtime is narrowly protected inside home", classify_target("/home/test/.local/share/maho/runtime/current/manifest.json", context=TargetContext(owner_home="/home/test")).protected)
    check("unrelated home data stays unprotected", not classify_target("/home/test/Documents/report.md", context=TargetContext(owner_home="/home/test")).protected)
    for path, domain in (
        ("/boot/vmlinuz-linux", ProtectedDomain.BOOT),
        ("/usr/lib/modules/7.1/kernel.ko", ProtectedDomain.KERNEL),
        ("/etc/sudoers", ProtectedDomain.PRIVILEGE),
        ("/etc/ld.so.preload", ProtectedDomain.LOADER),
        ("/etc/systemd/system/sshd.service", ProtectedDomain.SERVICE),
        ("/var/lib/pacman/local/pkg/desc", ProtectedDomain.PACKAGE),
        ("/var/lib/maho/guardian/authority.json", ProtectedDomain.GUARDIAN),
        ("/var/lib/maho/recovery/generations.json", ProtectedDomain.RECOVERY),
    ):
        match = classify_target(path)
        check(f"{domain.value} is protected", match.protected and match.domain is domain)
    ordinary = request("/home/test/src/build", MutationOperation.UNLINK)
    check("unprotected mutation is allowed", decide_mutation(ordinary).outcome is PreventionOutcome.ALLOW)
    root_destroy = request("/dev/nvme0n1p2", MutationOperation.DEVICE_WRITE, reversible=False)
    check("live root device destruction requires break glass", decide_mutation(root_destroy).outcome is PreventionOutcome.BREAK_GLASS_REQUIRED)
    protected = request("/boot/vmlinuz-linux")
    check("protected mutation without authority is not allowed", decide_mutation(protected).outcome is PreventionOutcome.REQUIRE_AUTHORITY)
    authority = AuthorityView(
        state="CURRENT", transaction_id="upd-exact", subject=subject,
        effects=frozenset({EffectKind.BOOT_STATE}), operations=frozenset({MutationOperation.WRITE}),
        target_prefixes=("/boot/vmlinuz-linux",), expires_at_ns=100,
        source_revision="b" * 40, generation_id="gen-exact",
    )
    check("exact bounded authority allows mutation", decide_mutation(protected, authority).outcome is PreventionOutcome.ALLOW)
    check("authority cannot escape target scope", decide_mutation(request("/boot/loader/loader.conf"), authority).outcome is PreventionOutcome.DENY)
    check("wrong transaction is denied", decide_mutation(replace(protected, transaction_id="upd-wrong"), authority).outcome is PreventionOutcome.DENY)
    check("expired authority is denied", decide_mutation(replace(protected, now_ns=100), authority).reason == "authority_expired")
    drifted = replace(protected, subject=replace(subject, executable_sha256="c" * 64))
    check("executable identity drift is denied", decide_mutation(drifted, authority).reason == "subject_identity_mismatch")
    reused = replace(protected, subject=replace(subject, start_time_ns=1001))
    check("PID reuse is denied", decide_mutation(reused, authority).reason == "subject_identity_mismatch")
    check("Guardian uncertainty never promotes authority", decide_mutation(replace(protected, guardian_healthy=False), authority).outcome is PreventionOutcome.DENY)
    print("ALL MAHO PREVENTION POLICY TESTS PASS")


if __name__ == "__main__":
    main()
