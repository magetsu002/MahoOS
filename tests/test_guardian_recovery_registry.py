#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_recovery_registry import (  # noqa: E402
    certified_guardian_restart,
    certified_service_recovery,
    certified_service_units,
)


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
        "Maho Notify has exact delegated systemd recovery certification",
        entry is not None
        and entry.ownership == "maho"
        and entry.provider == "systemd-user"
        and entry.mode == "delegated"
        and entry.provider_action == "restart-on-failure"
        and entry.expected_restart == "on-failure"
        and entry.failure_identity == "boot-id+unit+invocation-id"
        and entry.healthy_active_state == "active"
        and entry.healthy_sub_state == "running"
        and entry.replacement_timeout_seconds == 5.0
        and entry.stability_seconds == 3.0,
    )
    check("external service cannot self-certify", certified_service_recovery("external.service") is None)
    check("malformed service identity fails closed", certified_service_recovery(True) is None)
    check("delegated Notify contract grants no direct Guardian restart", certified_guardian_restart("maho-notify.service") is None)
    print("ALL GUARDIAN RECOVERY REGISTRY TESTS PASS")


if __name__ == "__main__":
    main()
