#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_tetragon_policy import TracePolicyScope, generate_trace_policy

BASELINE = ROOT / "config" / "guardian" / "tetragon-baseline.yaml"

FORBIDDEN = (
    "matchActions:",
    "action:",
    "Sigkill",
    "Override",
    "Signal",
    "policy-mode: enforce",
    "value: enforce",
)


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def assert_observation_only(name: str, policy: str) -> None:
    check(f"{name} contains no enforcement primitive",
          not any(token in policy for token in FORBIDDEN))


def main() -> None:
    baseline = BASELINE.read_text(encoding="utf-8")
    assert_observation_only("baseline", baseline)
    check("baseline policy is bounded to system prefixes",
          all(path in baseline for path in (
              "/etc",
              "/boot",
              "/usr",
              "/opt",
              "/var/lib/maho",
              "/sys/fs/bpf",
          )))
    check("baseline does not globally record home writes", "/home" not in baseline)
    check("baseline records write access only",
          "security_file_permission" in baseline
          and "operator: Equal" in baseline
          and '- "2"' in baseline)
    check("baseline does not enable network tracing", "tcp_connect" not in baseline)

    pid_policy = generate_trace_policy(
        policy_name="maho-trace-123",
        scope=TracePolicyScope.PID_FAMILY,
        pid=4242,
    )
    assert_observation_only("PID trace", pid_policy)
    check("PID trace uses exact host PID family selector",
          "matchPIDs:" in pid_policy
          and "followForks: true" in pid_policy
          and "isNamespacePID: false" in pid_policy
          and "- 4242" in pid_policy)
    check("PID trace does not broaden to binary family", "matchBinaries:" not in pid_policy)
    check("PID trace adds bounded write and connect observation",
          "security_file_permission" in pid_policy
          and "tcp_connect" in pid_policy)

    binary_policy = generate_trace_policy(
        policy_name="maho-trace-bin",
        scope=TracePolicyScope.BINARY_FAMILY,
        binary="/usr/bin/example",
    )
    assert_observation_only("binary trace", binary_policy)
    check("binary trace scope is explicit",
          "matchBinaries:" in binary_policy
          and '"/usr/bin/example"' in binary_policy
          and "followChildren: true" in binary_policy)
    check("binary trace does not claim exact PID scope", "matchPIDs:" not in binary_policy)

    bad_cases = (
        dict(policy_name="../bad", scope=TracePolicyScope.PID_FAMILY, pid=1),
        dict(policy_name="good", scope=TracePolicyScope.PID_FAMILY, pid=0),
        dict(policy_name="good", scope=TracePolicyScope.PID_FAMILY, pid=1,
             binary="/usr/bin/nope"),
        dict(policy_name="good", scope=TracePolicyScope.BINARY_FAMILY,
             binary="relative/path"),
        dict(policy_name="good", scope=TracePolicyScope.BINARY_FAMILY,
             binary='/usr/bin/bad"\npath'),
        dict(policy_name="good", scope=TracePolicyScope.BINARY_FAMILY,
             binary="/usr/bin/example", pid=42),
    )
    for index, kwargs in enumerate(bad_cases, start=1):
        try:
            generate_trace_policy(**kwargs)
        except ValueError:
            continue
        raise AssertionError(f"invalid policy case {index} was accepted")
    check("unsafe policy identities and scopes fail closed", True)

    print("ALL GUARDIAN TETRAGON POLICY TESTS PASS")


if __name__ == "__main__":
    main()
