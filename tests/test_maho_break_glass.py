#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_admission import EffectKind  # noqa: E402
from maho_break_glass import BreakGlassRequest, validate_request  # noqa: E402
from maho_mutation_authority import MutationAuthorityError  # noqa: E402
from maho_prevention_policy import MutationOperation  # noqa: E402
from maho_prevention_scope import TargetContext  # noqa: E402


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


def main() -> None:
    context = TargetContext(root_device="/dev/root-fixture", boot_device="/dev/boot-fixture")
    request = BreakGlassRequest(42, "/boot/vmlinuz", EffectKind.BOOT_STATE, MutationOperation.WRITE, 120, 1000)
    validate_request(request, context=context)
    check("confirmation binds exact target and operation", request.confirmation == "BYPASS /boot/vmlinuz FOR WRITE")
    rejects("break glass cannot target ordinary project data", lambda: validate_request(
        BreakGlassRequest(42, "/home/test/project", EffectKind.FILE, MutationOperation.UNLINK, 120, 1000), context=context,
    ))
    rejects("break glass effect must match canonical target", lambda: validate_request(
        BreakGlassRequest(42, "/boot/vmlinuz", EffectKind.FILE, MutationOperation.WRITE, 120, 1000), context=context,
    ))
    rejects("break glass cannot exceed five minutes", lambda: validate_request(
        BreakGlassRequest(42, "/boot/vmlinuz", EffectKind.BOOT_STATE, MutationOperation.WRITE, 301, 1000), context=context,
    ))
    source = (ROOT / "bin/maho-break-glass").read_text()
    check("break glass requires interactive exact phrase", "sys.stdin.isatty()" in source and "request.confirmation" in source)
    check("break glass uses polkit authentication", 'os.execvp("pkexec"' in source and '"PKEXEC_UID" in os.environ' in source)
    check("there is no force or environment bypass", "--force" not in source and "MAHO_BREAK_GLASS" not in source)
    print("ALL MAHO BREAK GLASS TESTS PASS")


if __name__ == "__main__":
    main()
