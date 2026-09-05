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
        "failure": {"domain": "maho-runtime", "transaction_in_progress": True, "graphical_available": True},
        "availability": {"previous_runtime_verified": True},
    },
    action="rollback-maho-runtime",
    scope="maho-runtime",
    requires_confirmation=False,
    automatic_allowed=True,
    preserves_personal_files=True,
)

check(
    "post-transaction runtime rollback asks first",
    {
        "failure": {"domain": "maho-runtime", "transaction_in_progress": False, "graphical_available": False},
        "availability": {"previous_runtime_verified": True},
    },
    action="rollback-maho-runtime",
    requires_confirmation=True,
    automatic_allowed=False,
    surface="text-console",
)

check(
    "single safe service crash is silent",
    {
        "failure": {"domain": "service", "graphical_available": True},
        "service": {"name": "maho-notify.service", "consecutive_failures": 1, "restart_safe": True},
    },
    action="restart-service",
    scope="service",
    automatic_allowed=True,
    surface="silent",
)

check(
    "repeated service crashes become one incident",
    {
        "failure": {"domain": "service", "graphical_available": True},
        "service": {"name": "maho-notify.service", "consecutive_failures": 3, "restart_safe": True},
    },
    action="diagnose-service-incident",
    surface="incident",
)

check(
    "unsafe service never gets automatic restart",
    {
        "failure": {"domain": "service"},
        "service": {"name": "external.service", "consecutive_failures": 1, "restart_safe": False},
    },
    action="diagnose-service-incident",
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

# A stable JSON representation is useful for future Recovery/Guardian projection.
sample = decide_recovery({"failure": {"domain": "unknown"}}).as_dict()
encoded = json.dumps(sample, sort_keys=True, separators=(",", ":"))
assert json.loads(encoded) == sample
print("PASS deterministic JSON-safe decision contract")
print("ALL RECOVERY POLICY CONTRACTS PASS")
