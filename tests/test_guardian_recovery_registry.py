#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from guardian_recovery_registry import (
    certified_guardian_restart,
    certified_runtime_domains,
    certified_runtime_recovery,
    certified_service_recovery,
    certified_service_units,
)

EXPECTED = {
    "maho-notify.service": ("on-failure", "quickshell-notify-runtime"),
    "maho-shell.service": ("on-failure", "quickshell-shell-runtime"),
    "maho-dock.service": ("on-failure", "quickshell-dock-runtime"),
    "maho-wallpaper.service": ("on-failure", "wallpaper-watch-runtime"),
    "maho-awww-daemon.service": ("always", "awww-daemon-runtime"),
    "maho-security.service": ("on-failure", "security-monitor-runtime"),
    "maho-observe.service": ("on-failure", "observer-watch-runtime"),
    "maho-clipboard-history.service": ("always", "clipboard-history-owner"),
}

def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print("PASS", name)

def main():
    check("registry contains exact V1 delegated service set", set(certified_service_units()) == set(EXPECTED))
    for unit, (restart, health) in EXPECTED.items():
        entry = certified_service_recovery(unit)
        check(
            f"{unit} has bounded delegated certification",
            entry is not None
            and entry.ownership == "maho"
            and entry.provider == "systemd-user"
            and entry.mode == "delegated"
            and entry.expected_restart == restart
            and entry.failure_identity == "boot-id+unit+invocation-id"
            and entry.healthy_active_state == "active"
            and entry.healthy_sub_state == "running"
            and entry.health_check == health
            and bool(entry.health_process_patterns)
            and entry.replacement_timeout_seconds <= 8.0
            and entry.stability_seconds == 3.0,
        )
        check(f"{unit} grants no direct Guardian restart", certified_guardian_restart(unit) is None)

    runtime = certified_runtime_recovery("maho-runtime")
    check("registry contains exactly one Maho runtime recovery contract", certified_runtime_domains() == ("maho-runtime",))
    check(
        "Maho runtime rollback is a distinct transactional provider contract",
        runtime is not None
        and runtime.ownership == "maho"
        and runtime.provider == "maho-runtime"
        and runtime.mode == "transactional"
        and runtime.action == "rollback-previous"
        and runtime.scope == "maho-runtime"
        and runtime.executor == "maho-setup"
        and runtime.preserves_personal_files
        and runtime.previous_runtime_required
        and runtime.automatic_only_in_transaction
        and runtime.postcondition == "verified-previous-is-current-and-managed-wiring-matches-current",
    )
    check("external service cannot self-certify", certified_service_recovery("external.service") is None)
    check("malformed service identity fails closed", certified_service_recovery(True) is None)
    check("unknown runtime domain cannot self-certify", certified_runtime_recovery("system-userspace") is None)
    check("malformed runtime identity fails closed", certified_runtime_recovery(True) is None)
    print("ALL GUARDIAN RECOVERY REGISTRY TESTS PASS")

if __name__ == "__main__":
    main()
