#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import signal
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_containment import ContainmentAuthority, ContainmentPlanState, ContainmentTarget, ProcessIdentity, plan_containment
from guardian_containment_adapter import ExactProcessContainmentDriver, execute_containment, release_containment

NOW = "2026-09-15T12:00:00Z"


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def target() -> ContainmentTarget:
    return ContainmentTarget(
        package="maho-runtime",
        version="1.2.3-1",
        finding_id="finding-001",
        processes=(
            ProcessIdentity(201, 9001, "/usr/bin/maho-runtime"),
            ProcessIdentity(202, 9002, "/usr/bin/maho-runtime"),
        ),
    )


def authority(value: ContainmentTarget, *, verified: bool = True, digest: str | None = None, expires: str = "2026-09-15T12:05:00Z") -> ContainmentAuthority:
    return ContainmentAuthority(
        authority_id="contain-auth-001",
        issuer="guardian-policy",
        verified=verified,
        issued_at="2026-09-15T11:55:00Z",
        expires_at=expires,
        target_digest=digest or value.digest,
        evidence_ids=("incident:001", "causal-edge:001"),
        reversible=True,
    )


class FakeDriver:
    def __init__(self, mode: str = "exact") -> None:
        self.mode = mode
        self.releases: list[str] = []

    def freeze_exact(self, value: ContainmentTarget):
        rows = [item.__dict__ for item in value.processes]
        if self.mode == "subset":
            rows = rows[:1]
        return {"result": "contained", "session_id": "contain-test-session", "contained": rows, "failed": []}

    def release_exact(self, session_id: str, value: ContainmentTarget):
        self.releases.append(session_id)
        return {"result": "released", "released": [item.pid for item in value.processes], "failed": []}


def _write_status(proc: Path, uid: int, state: str) -> None:
    proc.joinpath("status").write_text(
        f"Name:\tmaho-runtime\nState:\t{state}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n",
        encoding="utf-8",
    )


def _write_stat(proc: Path, pid: int, start_ticks: int, state: str = "S") -> None:
    rest = [state, "1"] + ["0"] * 17 + [str(start_ticks)]
    proc.joinpath("stat").write_text(f"{pid} (maho-runtime) {' '.join(rest)}\n", encoding="utf-8")


def _real_driver_fixture(tmp: Path, *, fail_second_stop: bool = False, rollback_stuck: bool = False):
    uid = 1000
    db = tmp / "db"
    fs = tmp / "fs"
    proc_root = tmp / "proc"
    state_root = tmp / "state"
    pkg = db / "maho-runtime-1.2.3-1"
    pkg.mkdir(parents=True)
    pkg.joinpath("desc").write_text(
        "%NAME%\nmaho-runtime\n\n%VERSION%\n1.2.3-1\n\n%FILES%\nusr/bin/maho-runtime\n\n",
        encoding="utf-8",
    )
    binary = fs / "usr/bin/maho-runtime"
    binary.parent.mkdir(parents=True)
    binary.write_text("test", encoding="utf-8")
    identities: list[ProcessIdentity] = []
    for pid, start in ((201, 9001), (202, 9002)):
        proc = proc_root / str(pid)
        proc.mkdir(parents=True)
        proc.joinpath("exe").symlink_to(binary)
        proc.joinpath("cmdline").write_bytes(b"maho-runtime\0")
        _write_status(proc, uid, "S (sleeping)")
        _write_stat(proc, pid, start)
        identities.append(ProcessIdentity(pid, start, str(binary)))

    signals: list[tuple[int, int]] = []

    def signaler(pid: int, sig: int) -> None:
        signals.append((pid, sig))
        proc = proc_root / str(pid)
        if sig == signal.SIGSTOP:
            if fail_second_stop and pid == 202:
                raise OSError("synthetic stop failure")
            _write_status(proc, uid, "T (stopped)")
        elif sig == signal.SIGCONT and not rollback_stuck:
            _write_status(proc, uid, "S (sleeping)")

    driver = ExactProcessContainmentDriver(
        db_root=db,
        proc_root=proc_root,
        fs_root=fs,
        state_root=state_root,
        uid=uid,
        signaler=signaler,
        sleeper=lambda _seconds: None,
        protected_pids=set(),
    )
    exact_target = ContainmentTarget("maho-runtime", "1.2.3-1", "finding-001", tuple(identities))
    return driver, exact_target, proc_root, fs, state_root, signals


def main() -> None:
    value = target()
    ready = plan_containment(value, authority(value), now=NOW)
    check("verified exact bounded authority produces ready plan", ready.state is ContainmentPlanState.READY)
    check("rollback action is explicitly reversible", ready.rollback_action == "resume-exact-session")

    unverified = plan_containment(value, authority(value, verified=False), now=NOW)
    check("unverified authority cannot contain", unverified.state is ContainmentPlanState.REFUSE)

    mismatch = plan_containment(value, authority(value, digest="0" * 64), now=NOW)
    check("authority for another target cannot contain", mismatch.state is ContainmentPlanState.REFUSE)

    expired = plan_containment(value, authority(value, expires="2026-09-15T11:59:59Z"), now=NOW)
    check("expired containment authority fails closed", expired.state is ContainmentPlanState.REFUSE)

    try:
        ContainmentTarget("maho-*", "1", "finding", (ProcessIdentity(201, 1, "/bin/x"),))
    except ValueError:
        broad_rejected = True
    else:
        broad_rejected = False
    check("wildcard containment targets are structurally rejected", broad_rejected)

    driver = FakeDriver()
    receipt = execute_containment(ready, driver)
    check("adapter executes only ready plan", receipt.result == "contained" and receipt.verified)
    check("receipt binds exact target digest", receipt.target_digest == value.digest)
    check("receipt carries exact rollback session", receipt.rollback.get("session_id") == "contain-test-session")
    released = release_containment(receipt, value, driver)
    check("bound receipt can release exact session", released["result"] == "released" and driver.releases == ["contain-test-session"])

    bad_driver = FakeDriver("subset")
    failed = execute_containment(ready, bad_driver)
    check("partial or broadened adapter result is not certified", failed.result == "verification-failed" and not failed.verified)
    check("failed exact verification requests rollback", bad_driver.releases == ["contain-test-session"])

    refused_receipt = execute_containment(unverified, FakeDriver())
    check("adapter cannot invent authority", refused_receipt.result == "refused")

    with tempfile.TemporaryDirectory() as raw:
        real_driver, exact, proc_root, _fs, _state, signals = _real_driver_fixture(Path(raw))
        frozen = real_driver.freeze_exact(exact)
        check("production adapter freezes the entire exact stable target", frozen["result"] == "contained" and len(frozen["contained"]) == 2)
        check("production adapter verifies stopped process state", all((proc_root / str(pid) / "status").read_text().split("State:\t", 1)[1].startswith("T") for pid in (201, 202)))
        resumed = real_driver.release_exact(frozen["session_id"], exact)
        check("production adapter verifies exact release", resumed["result"] == "released" and len(resumed["released"]) == 2)
        check("production release signaled only exact authorized pids", {pid for pid, sig in signals if sig == signal.SIGCONT} == {201, 202})

    with tempfile.TemporaryDirectory() as raw:
        rollback_driver, exact, _proc_root, _fs, _state, _signals = _real_driver_fixture(Path(raw), fail_second_stop=True, rollback_stuck=True)
        rolled = rollback_driver.freeze_exact(exact)
        check("partial freeze with unverifiable rollback is never reported safe", rolled["result"] == "failed-rollback-incomplete")
        check("rollback state verification failure is explicit", any(str(item.get("reason", "")).startswith("resume-not-verified:") for item in rolled["failed"]))

    with tempfile.TemporaryDirectory() as raw:
        drift_driver, exact, proc_root, fs, _state, signals = _real_driver_fixture(Path(raw))
        frozen = drift_driver.freeze_exact(exact)
        drifted = fs / "usr/bin/drifted-runtime"
        drifted.write_text("drift", encoding="utf-8")
        exe_link = proc_root / "201/exe"
        exe_link.unlink()
        exe_link.symlink_to(drifted)
        before = len(signals)
        release = drift_driver.release_exact(frozen["session_id"], exact)
        new_signals = signals[before:]
        check("release revalidates bound executable identity", any(item.get("pid") == 201 and item.get("reason") == "executable-mismatch" for item in release["failed"]))
        check("identity drift is not signaled during release", not any(pid == 201 and sig == signal.SIGCONT for pid, sig in new_signals))

    print("ALL GUARDIAN CONTAINMENT TESTS PASS")


if __name__ == "__main__":
    main()
