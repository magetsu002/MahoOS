#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_intent_guard import IntentOutcome, assess_shell_intent  # noqa: E402
from maho_prevention_scope import TargetContext  # noqa: E402


def check(name: str, value: bool) -> None:
    if not value:
        raise AssertionError(name)
    print("PASS", name)


def outcome(source: str) -> IntentOutcome:
    return assess_shell_intent(
        source, cwd="/home/test/src",
        context=TargetContext(root_device="/dev/root-device", boot_device="/dev/boot-device", owner_home="/home/test"),
    ).outcome


def main() -> None:
    check("recursive project cleanup remains allowed", outcome("rm -rf -- ./build") is IntentOutcome.ALLOW)
    check("quoted project cleanup remains allowed", outcome("rm -rf 'generated output'") is IntentOutcome.ALLOW)
    check("exact root destruction requires break glass", outcome("rm --no-preserve-root -rf /") is IntentOutcome.BREAK_GLASS_REQUIRED)
    check("quoted boot target cannot bypass parser", outcome("rm -rf '/boot'") is IntentOutcome.BREAK_GLASS_REQUIRED)
    check("destructive pipeline member is still found", outcome("printf yes | rm -rf /boot") is IntentOutcome.BREAK_GLASS_REQUIRED)
    check("root-device overwrite requires break glass", outcome("dd if=/dev/zero of=/dev/root-device bs=1M") is IntentOutcome.BREAK_GLASS_REQUIRED)
    check("formatting boot device requires break glass", outcome("mkfs.ext4 /dev/boot-device") is IntentOutcome.BREAK_GLASS_REQUIRED)
    check("protected truncating redirection is blocked", outcome("printf bad > /etc/sudoers") is IntentOutcome.BLOCK)
    check("ordinary project redirection remains allowed", outcome("printf ok > ./generated.txt") is IntentOutcome.ALLOW)
    check("opaque Python is unknown rather than accused", outcome("python payload.py") is IntentOutcome.UNKNOWN)
    check("shell expansion is unknown rather than guessed", outcome("rm -rf \"$TARGET\"") is IntentOutcome.UNKNOWN)
    source = (ROOT / "lib/maho_intent_guard.py").read_text()
    check("guard has structured tokenization and no regex", "shlex.shlex" in source and "import re" not in source)
    print("ALL MAHO INTENT GUARD TESTS PASS")


if __name__ == "__main__":
    main()
