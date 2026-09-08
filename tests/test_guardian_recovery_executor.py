#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_recovery_executor import execute_guardian_recovery, recovery_history_record  # noqa: E402


def decision(target: str, *, mode: str = "automatic", allowed: bool = True) -> dict:
    return {
        "execution_mode": mode,
        "mutating_recovery_allowed": allowed,
        "recovery": {"action": "restart-service", "target": target},
    }


class FakeRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, argv):
        self.calls.append(tuple(argv))
        if not self.responses:
            raise AssertionError("unexpected runner call")
        return self.responses.pop(0)


def result(code=0, stdout=""):
    return subprocess.CompletedProcess(args=(), returncode=code, stdout=stdout, stderr="")


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def main() -> None:
    runner = FakeRunner([])
    execution = execute_guardian_recovery(
        decision("maho-notify.service", mode="observe", allowed=False),
        runner=runner,
    )
    check("executor refuses decision without automatic mutation authority", execution.status == "refused" and not runner.calls)

    runner = FakeRunner([])
    execution = execute_guardian_recovery(decision("external.service"), runner=runner)
    check("executor refuses unregistered service without touching systemd", execution.status == "refused" and not runner.calls)

    runner = FakeRunner([result(0, "not-found\n")])
    execution = execute_guardian_recovery(decision("maho-notify.service"), runner=runner)
    check(
        "missing service fails precondition before restart",
        execution.status == "precondition-failed"
        and runner.calls == [("systemctl", "--user", "show", "maho-notify.service", "--property=LoadState", "--value")],
    )

    runner = FakeRunner([result(0, "loaded\n"), result(1)])
    execution = execute_guardian_recovery(decision("maho-notify.service"), runner=runner)
    check(
        "healthy or recovering service is never restarted",
        execution.status == "precondition-failed"
        and not execution.attempted
        and runner.calls[-1] == ("systemctl", "--user", "is-failed", "--quiet", "maho-notify.service"),
    )

    runner = FakeRunner([result(0, "loaded\n"), result(0), result(1)])
    execution = execute_guardian_recovery(decision("maho-notify.service"), runner=runner)
    check("failed restart is attempted but never verified", execution.status == "action-failed" and execution.attempted and not execution.verified)

    runner = FakeRunner([result(0, "loaded\n"), result(0), result(0), result(3)])
    execution = execute_guardian_recovery(decision("maho-notify.service"), runner=runner)
    history = recovery_history_record(execution)
    check(
        "postcondition failure cannot enter history as successful",
        execution.status == "verification-failed"
        and not execution.verified
        and history["status"] == "failed"
        and history["verified"] is False,
    )

    runner = FakeRunner([result(0, "loaded\n"), result(0), result(0), result(0)])
    execution = execute_guardian_recovery(decision("maho-notify.service"), runner=runner)
    history = recovery_history_record(execution)
    check(
        "verified active postcondition is required for success history",
        execution.status == "verified"
        and execution.verified
        and history["status"] == "succeeded"
        and history["verified"] is True,
    )
    check(
        "executor uses only exact bounded systemd argv",
        runner.calls == [
            ("systemctl", "--user", "show", "maho-notify.service", "--property=LoadState", "--value"),
            ("systemctl", "--user", "is-failed", "--quiet", "maho-notify.service"),
            ("systemctl", "--user", "restart", "maho-notify.service"),
            ("systemctl", "--user", "is-active", "--quiet", "maho-notify.service"),
        ],
    )

    print("ALL GUARDIAN RECOVERY EXECUTOR TESTS PASS")


if __name__ == "__main__":
    main()
