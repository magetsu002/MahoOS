#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_recovery_registry import certified_service_recovery, certified_service_units  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def main() -> None:
    entry = certified_service_recovery("maho-notify.service")
    check(
        "registry contains exactly one initial V1 recovery",
        certified_service_units() == ("maho-notify.service",),
    )
    check(
        "Maho Notify has exact bounded restart certification",
        entry is not None
        and entry.action == "restart-service"
        and entry.max_consecutive_failures == 2
        and entry.postcondition == "systemd-user-active",
    )
    check("external service cannot self-certify", certified_service_recovery("external.service") is None)
    check("malformed service identity fails closed", certified_service_recovery(True) is None)
    print("ALL GUARDIAN RECOVERY REGISTRY TESTS PASS")


if __name__ == "__main__":
    main()
