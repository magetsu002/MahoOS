#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_recovery_policy import decide_recovery  # noqa: E402


def check(name: str, state: dict, **expected: object) -> None:
    original = copy.deepcopy(state)
    result = decide_recovery(state).as_dict()
    assert state == original, f"{name}: planner mutated input"
    for key, value in expected.items():
        assert result[key] == value, f"{name}: {key}={result[key]!r}, expected {value!r}"
    print(f"PASS {name}")


check(
    "kernel failure offers LTS without silently switching",
    {"failure": {"domain": "kernel"}, "availability": {"lts_kernel": True}},
    action="boot-lts-kernel",
    scope="kernel",
    requires_confirmation=True,
    automatic_allowed=False,
    surface="boot-recovery",
)

check(
    "kernel failure without fallback is diagnostic only",
    {"failure": {"domain": "kernel"}, "availability": {"lts_kernel": False}},
    action="open-recovery-console",
    scope="diagnostic",
    automatic_allowed=True,
)

check(
    "userspace failure prefers root state over kernel rollback",
    {
        "failure": {"domain": "system-userspace", "graphical_available": False},
        "availability": {"root_snapshot": True, "lts_kernel": True, "home_excluded_from_root_snapshot": True},
    },
    action="restore-system-state",
    scope="root-filesystem",
    requires_confirmation=True,
    automatic_allowed=False,
    surface="text-console",
    preserves_personal_files=True,
)

check(
    "userspace recovery reports personal-data risk when home is included",
    {
        "failure": {"domain": "system-userspace", "graphical_available": True},
        "availability": {"root_snapshot": True, "home_excluded_from_root_snapshot": False},
    },
    action="restore-system-state",
    preserves_personal_files=False,
    surface="graphical-recovery",
)

check(
    "runtime activation transaction may rollback automatically",
    {
        "failure": {
            "domain": "maho-runtime",
            "domain_confidence": "confirmed",
            "transaction_in_progress": True,
            "graphical_available": True,
        },
        "availability": {"previous_runtime_verified": True},
    },
    action="rollback-previous",
    scope="maho-runtime",
    requires_confirmation=False,
    automatic_allowed=True,
    preserves_personal_files=True,
    target="previous-runtime",
    provider="maho-runtime",
    recovery_mode="transactional",
)

check(
    "post-transaction runtime rollback asks first",
    {
        "failure": {
            "domain": "maho-runtime",
            "domain_confidence": "confirmed",
            "transaction_in_progress": False,
            "graphical_available": False,
        },
        "availability": {"previous_runtime_verified": True},
    },
    action="rollback-previous",
    requires_confirmation=True,
    automatic_allowed=False,
    surface="text-console",
    provider="maho-runtime",
    recovery_mode="transactional",
)

check(
    "unconfirmed runtime domain fails closed even with a previous runtime",
    {
        "failure": {
            "domain": "maho-runtime",
            "domain_confidence": "high",
            "transaction_in_progress": True,
        },
        "availability": {"previous_runtime_verified": True},
    },
    action="open-recovery-console",
    scope="diagnostic",
    automatic_allowed=True,
)

check(
    "missing runtime confidence fails closed",
    {
        "failure": {"domain": "maho-runtime", "transaction_in_progress": True},
        "availability": {"previous_runtime_verified": True},
    },
    action="open-recovery-console",
    scope="diagnostic",
)

check(
    "certified Maho Notify failure delegates recovery to systemd-user",
    {
        "failure": {"domain": "service", "graphical_available": True},
        "service": {"name": "maho-notify.service", "consecutive_failures": 1, "restart_safe": False},
    },
    action="observe-service-recovery",
    target="maho-notify.service",
    scope="service",
    automatic_allowed=True,
    surface="incident",
    provider="systemd-user",
    recovery_mode="delegated",
)

check(
    "second Maho Notify invocation remains a delegated event, not a threshold",
    {
        "failure": {"domain": "service", "graphical_available": True},
        "service": {"name": "maho-notify.service", "consecutive_failures": 2},
    },
    action="observe-service-recovery",
    automatic_allowed=True,
)

check(
    "runtime crash counters do not revoke or grant provider certification",
    {
        "failure": {"domain": "service", "graphical_available": True},
        "service": {"name": "maho-notify.service", "consecutive_failures": 3, "restart_safe": True},
    },
    action="observe-service-recovery",
    surface="incident",
)

check(
    "external service cannot self-certify automatic restart",
    {
        "failure": {"domain": "service"},
        "service": {"name": "external.service", "consecutive_failures": 1, "restart_safe": True},
    },
    action="diagnose-service-incident",
    automatic_allowed=True,
    target="external.service",
)

check(
    "exhausted delegated provider becomes diagnosis only",
    {
        "failure": {"domain": "service"},
        "service": {"name": "maho-notify.service", "provider_recovery_unresolved": True},
    },
    action="diagnose-service-incident",
    automatic_allowed=True,
)

check(
    "malformed facts fail closed",
    {
        "failure": {"domain": 17, "graphical_available": "yes"},
        "availability": {"root_snapshot": "true"},
        "service": {"consecutive_failures": True},
    },
    action="diagnose-only",
    scope="diagnostic",
    automatic_allowed=True,
    surface="text-console",
)

sample = decide_recovery({"failure": {"domain": "unknown"}}).as_dict()
encoded = json.dumps(sample, sort_keys=True, separators=(",", ":"))
assert json.loads(encoded) == sample
print("PASS deterministic JSON-safe decision contract")
print("ALL RECOVERY POLICY CONTRACTS PASS")
