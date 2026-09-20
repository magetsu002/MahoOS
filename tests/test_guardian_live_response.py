#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import guardian_live_response as live  # noqa: E402
from guardian_containment import ContainmentTarget  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


class FakeDriver:
    def __init__(self) -> None:
        self.frozen: list[ContainmentTarget] = []
        self.released: list[str] = []

    def freeze_exact(self, target: ContainmentTarget) -> dict:
        self.frozen.append(target)
        return {
            "result": "contained",
            "session_id": "contain-live-response-test",
            "contained": [asdict(item) for item in target.processes],
            "failed": [],
        }

    def release_exact(self, session_id: str, target: ContainmentTarget) -> dict:
        self.released.append(session_id)
        return {
            "result": "released",
            "released": [{"pid": item.pid, "state": "S"} for item in target.processes],
            "failed": [],
        }


class PartialReleaseDriver(FakeDriver):
    def release_exact(self, session_id: str, target: ContainmentTarget) -> dict:
        self.released.append(session_id)
        return {
            "result": "partial",
            "released": [{"pid": target.processes[0].pid, "state": "S"}],
            "failed": [{"pid": target.processes[-1].pid, "reason": "process-gone"}],
        }


def _write_status(proc: Path, uid: int) -> None:
    proc.joinpath("status").write_text(
        f"Name:\tmaho-test\nState:\tS (sleeping)\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n",
        encoding="utf-8",
    )


def _write_stat(proc: Path, pid: int, start: int) -> None:
    rest = ["S", "1"] + ["0"] * 17 + [str(start)]
    proc.joinpath("stat").write_text(
        f"{pid} (maho-test) {' '.join(rest)}\n",
        encoding="utf-8",
    )


def _json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fixture(root: Path, pids: tuple[int, ...] = (201,)) -> dict:
    uid = 1000
    state = root / "state"
    db = root / "db"
    fs = root / "fs"
    proc = root / "proc"
    pkg = db / "alpha-1.0-1"
    pkg.mkdir(parents=True)
    pkg.joinpath("desc").write_text(
        "%NAME%\nalpha\n\n%VERSION%\n1.0-1\n\n%FILES%\nusr/bin/alpha\n\n",
        encoding="utf-8",
    )
    binary = fs / "usr/bin/alpha"
    binary.parent.mkdir(parents=True)
    binary.write_text("alpha-v1", encoding="utf-8")

    observations = []
    for index, pid in enumerate(pids, 1):
        node = proc / str(pid)
        node.mkdir(parents=True)
        node.joinpath("exe").symlink_to(binary)
        node.joinpath("cmdline").write_bytes(b"alpha\0")
        _write_status(node, uid)
        _write_stat(node, pid, 9000 + index)
        observations.append({"pid": pid, "exe": str(binary)})

    incident_id = "inc-live-alpha"
    incident = {
        "kind": "security-incident",
        "incident_id": incident_id,
        "status": "active",
        "subject": {"type": "package", "id": "alpha"},
        "risk": "critical",
        "confidence": "confirmed",
        "containment_eligible": True,
        "response_reversible": True,
        "runtime_pids": list(pids),
        "signals": [
            {
                "kind": "confirmed-finding",
                "source": "test-feed",
                "details": {
                    "finding_id": "finding-alpha-001",
                    "installed_version": "1.0-1",
                    "summary": "Alpha is confirmed affected.",
                },
            },
            {
                "kind": "runtime-executable",
                "source": "procfs",
                "details": {"observations": observations},
            },
        ],
    }
    assessment = {
        "kind": "guardian-assessment",
        "incident_id": incident_id,
        "source_kind": "security-incident",
        "status": "active",
        "subject": {"type": "package", "id": "alpha"},
        "decision": {"severity": {"level": 3, "label": "severe", "reason": "fixture"}},
    }
    source_path = state / "incidents/active" / f"{incident_id}.json"
    assessment_path = state / "guardian/active" / f"{incident_id}.json"
    _json(source_path, incident)
    _json(assessment_path, assessment)
    return {
        "state": state,
        "db": db,
        "fs": fs,
        "proc": proc,
        "uid": uid,
        "binary": binary,
        "incident_id": incident_id,
        "source_path": source_path,
    }


def plan(ctx: dict) -> dict:
    return live.plan_incident(
        ctx["state"],
        ctx["incident_id"],
        db_root=ctx["db"],
        proc_root=ctx["proc"],
        fs_root=ctx["fs"],
        uid=ctx["uid"],
    )


def authorize(ctx: dict, proposal: dict) -> dict:
    return live.authorize_containment(
        ctx["state"],
        ctx["incident_id"],
        proposal["proposal_id"],
        confirm=f"AUTHORIZE-CONTAIN:{proposal['proposal_id']}",
    )


def execute(ctx: dict, authority: dict) -> dict:
    return live.execute_authorized(
        ctx["state"],
        authority["authority_id"],
        db_root=ctx["db"],
        proc_root=ctx["proc"],
        fs_root=ctx["fs"],
        uid=ctx["uid"],
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as raw:
        ctx = fixture(Path(raw))
        proposal = plan(ctx)
        check(
            "confirmed exact package process produces authorization-required proposal",
            proposal.get("state") == "authorization-required",
        )
        check("proposal has proven causal edges", bool(proposal.get("proof_edge_ids")))
        check(
            "proposal carries exact executable object identity",
            proposal["target"]["processes"][0].get("exe_identity") is not None,
        )
        check("automatic authority remains false", proposal["automatic_authority"] is False)

        reconciled = live.reconcile(
            ctx["state"],
            db_root=ctx["db"],
            proc_root=ctx["proc"],
            fs_root=ctx["fs"],
            uid=ctx["uid"],
        )
        check("reconcile persists authorization-required state", reconciled["state"] == "authorization-required")
        denied = live.authorize_containment(
            ctx["state"],
            ctx["incident_id"],
            proposal["proposal_id"],
            confirm="no",
        )
        check("explicit authorization token is mandatory", denied["result"] == "denied")

        active = live.containment_status(ctx["state"])
        check("denial does not mutate containment state", active["state"] == "authorization-required")

        authority = authorize(ctx, proposal)
        check("authorization is explicit and bounded", authority.get("user_authorized") is True)

        driver = FakeDriver()
        old_driver = live._driver
        live._driver = lambda **_kwargs: driver
        try:
            result = execute(ctx, authority)
            check("authorized exact target is contained", result["result"] == "contained" and result["verified"])
            check("adapter receives one exact target", len(driver.frozen) == 1)
            status = live.containment_status(ctx["state"])
            check("canonical containment state is contained", status["state"] == "contained")
            check("canonical containment never invents automatic authority", status["automatic_authority"] is False)

            replay = execute(ctx, authority)
            check("containment authorization is single-use", replay["result"] == "refused")
            record = live._read_object(
                live._active_path(ctx["state"], ctx["incident_id"])
            )
            assert record is not None
            receipt_id = str(record["receipt_id"])
            bad_release = live.authorize_release(
                ctx["state"],
                ctx["incident_id"],
                receipt_id,
                confirm="wrong",
            )
            check(
                "release requires a separate explicit authorization",
                bad_release["result"] == "denied",
            )

            release_auth = live.authorize_release(
                ctx["state"],
                ctx["incident_id"],
                receipt_id,
                confirm=f"AUTHORIZE-RELEASE:{receipt_id}",
            )
            released = live.execute_release(
                ctx["state"],
                release_auth["authority_id"],
                db_root=ctx["db"],
                proc_root=ctx["proc"],
                fs_root=ctx["fs"],
                uid=ctx["uid"],
            )
            check(
                "authorized release verifies exact receipt",
                released["result"] == "released" and released["verified"],
            )
            check(
                "canonical containment returns to none",
                live.containment_status(ctx["state"])["state"] == "none",
            )

            replay_release = live.execute_release(
                ctx["state"],
                release_auth["authority_id"],
                db_root=ctx["db"],
                proc_root=ctx["proc"],
                fs_root=ctx["fs"],
                uid=ctx["uid"],
            )
            check(
                "release authorization is single-use",
                replay_release["result"] == "refused",
            )
            history = list(
                (ctx["state"] / "guardian/live-response/history").glob("*.json")
            )
            check(
                "proposal containment and release history are retained",
                len(history) >= 6,
            )
        finally:
            live._driver = old_driver

    with tempfile.TemporaryDirectory() as raw:
        ctx = fixture(Path(raw))
        source = json.loads(ctx["source_path"].read_text())
        source["containment_eligible"] = False
        _json(ctx["source_path"], source)
        check(
            "ineligible incident cannot propose containment",
            plan(ctx)["state"] == "none",
        )
    with tempfile.TemporaryDirectory() as raw:
        ctx = fixture(Path(raw))
        source = json.loads(ctx["source_path"].read_text())
        source["confidence"] = "high"
        _json(ctx["source_path"], source)
        check(
            "non-confirmed incident cannot propose containment",
            plan(ctx)["state"] == "none",
        )

    with tempfile.TemporaryDirectory() as raw:
        ctx = fixture(Path(raw))
        source = json.loads(ctx["source_path"].read_text())
        source["signals"] = [
            signal for signal in source["signals"]
            if signal.get("kind") != "runtime-executable"
        ]
        _json(ctx["source_path"], source)
        result = plan(ctx)
        check(
            "correlated package finding without process causal evidence cannot mutate",
            result["state"] == "none"
            and result["reason"] == "causal-process-evidence-missing",
        )

    with tempfile.TemporaryDirectory() as raw:
        ctx = fixture(Path(raw))
        proposal = plan(ctx)
        live.reconcile(
            ctx["state"],
            db_root=ctx["db"],
            proc_root=ctx["proc"],
            fs_root=ctx["fs"],
            uid=ctx["uid"],
        )
        authority = authorize(ctx, proposal)
        authority_path = live._authority_path(
            ctx["state"], authority["authority_id"]
        )
        tampered = json.loads(authority_path.read_text())
        tampered["target"]["processes"][0]["exe_identity"] = "tampered"
        _json(authority_path, tampered)
        result = execute(ctx, tampered)
        check(
            "tampered authority target is rejected before mutation",
            result["result"] == "refused"
            and result["reason"] == "authorization-binding-changed",
        )

    with tempfile.TemporaryDirectory() as raw:
        ctx = fixture(Path(raw))
        proposal = plan(ctx)
        live.reconcile(
            ctx["state"], db_root=ctx["db"], proc_root=ctx["proc"],
            fs_root=ctx["fs"], uid=ctx["uid"],
        )
        authority = authorize(ctx, proposal)
        authority_path = live._authority_path(
            ctx["state"], authority["authority_id"]
        )
        expired = json.loads(authority_path.read_text())
        expired["issued_at"] = "2000-01-01T00:00:00Z"
        expired["expires_at"] = "2000-01-01T00:01:00Z"
        _json(authority_path, expired)
        result = execute(ctx, expired)
        check(
            "expired authorization fails closed",
            result["result"] == "refused"
            and result["reason"] == "authorization-expired",
        )

    with tempfile.TemporaryDirectory() as raw:
        ctx = fixture(Path(raw))
        proposal = plan(ctx)
        live.reconcile(
            ctx["state"], db_root=ctx["db"], proc_root=ctx["proc"],
            fs_root=ctx["fs"], uid=ctx["uid"],
        )
        authority = authorize(ctx, proposal)
        source = json.loads(ctx["source_path"].read_text())
        source["signals"][0]["details"]["summary"] = "evidence changed"
        _json(ctx["source_path"], source)
        result = execute(ctx, authority)
        check(
            "evidence drift after authorization invalidates the binding",
            result["result"] == "refused"
            and result["reason"] == "authorization-binding-changed",
        )

    with tempfile.TemporaryDirectory() as raw:
        ctx = fixture(Path(raw))
        proposal = plan(ctx)
        live.reconcile(
            ctx["state"], db_root=ctx["db"], proc_root=ctx["proc"],
            fs_root=ctx["fs"], uid=ctx["uid"],
        )
        authority = authorize(ctx, proposal)
        binary = ctx["binary"]
        binary.unlink()
        binary.write_text("alpha-v2-same-path", encoding="utf-8")
        result = execute(ctx, authority)
        check(
            "same-path executable object replacement invalidates authorization",
            result["result"] == "refused"
            and result["reason"] == "authorization-binding-changed",
        )

    with tempfile.TemporaryDirectory() as raw:
        ctx = fixture(Path(raw), pids=(201, 202))
        proposal = plan(ctx)
        live.reconcile(
            ctx["state"], db_root=ctx["db"], proc_root=ctx["proc"],
            fs_root=ctx["fs"], uid=ctx["uid"],
        )
        authority = authorize(ctx, proposal)
        shutil.rmtree(ctx["proc"] / "202")
        result = execute(ctx, authority)
        check(
            "partial target disappearance requires a new authorization",
            result["result"] == "refused"
            and result["reason"] == "authorization-binding-changed",
        )

    with tempfile.TemporaryDirectory() as raw:
        ctx = fixture(Path(raw))
        proposal = plan(ctx)
        live.reconcile(
            ctx["state"], db_root=ctx["db"], proc_root=ctx["proc"],
            fs_root=ctx["fs"], uid=ctx["uid"],
        )
        authority = authorize(ctx, proposal)
        shutil.rmtree(ctx["proc"] / "201")
        result = execute(ctx, authority)
        check(
            "fully disappeared target becomes verified no-longer-applicable",
            result["result"] == "no-longer-applicable"
            and result["verified"] is True,
        )
        check(
            "no-longer-applicable containment clears active response state",
            live.containment_status(ctx["state"])["state"] == "none",
        )

    with tempfile.TemporaryDirectory() as raw:
        ctx = fixture(Path(raw))
        proposal = plan(ctx)
        live.reconcile(
            ctx["state"], db_root=ctx["db"], proc_root=ctx["proc"],
            fs_root=ctx["fs"], uid=ctx["uid"],
        )
        authority = authorize(ctx, proposal)
        driver = FakeDriver()
        old_driver = live._driver
        live._driver = lambda **_kwargs: driver
        try:
            contained = execute(ctx, authority)
            check("receipt tamper fixture contained", contained["result"] == "contained")
            active = live._read_object(
                live._active_path(ctx["state"], ctx["incident_id"])
            )
            assert active is not None
            receipt_id = str(active["receipt_id"])
            release_auth = live.authorize_release(
                ctx["state"],
                ctx["incident_id"],
                receipt_id,
                confirm=f"AUTHORIZE-RELEASE:{receipt_id}",
            )
            receipt_path = live._receipt_path(ctx["state"], receipt_id)
            receipt_row = json.loads(receipt_path.read_text())
            receipt_row["receipt"]["reason"] = "tampered"
            _json(receipt_path, receipt_row)
            released = live.execute_release(
                ctx["state"],
                release_auth["authority_id"],
                db_root=ctx["db"],
                proc_root=ctx["proc"],
                fs_root=ctx["fs"],
                uid=ctx["uid"],
            )
            check(
                "tampered containment receipt blocks release",
                released["result"] == "refused"
                and released["reason"] == "receipt-integrity-invalid",
            )
        finally:
            live._driver = old_driver

    with tempfile.TemporaryDirectory() as raw:
        ctx = fixture(Path(raw))
        proposal = plan(ctx)
        live.reconcile(
            ctx["state"], db_root=ctx["db"], proc_root=ctx["proc"],
            fs_root=ctx["fs"], uid=ctx["uid"],
        )
        authority = authorize(ctx, proposal)
        node = ctx["proc"] / "202"
        node.mkdir(parents=True)
        node.joinpath("exe").symlink_to(ctx["binary"])
        node.joinpath("cmdline").write_bytes(b"alpha\0")
        _write_status(node, ctx["uid"])
        _write_stat(node, 202, 9010)
        source = json.loads(ctx["source_path"].read_text())
        source["runtime_pids"].append(202)
        source["signals"][1]["details"]["observations"].append(
            {"pid": 202, "exe": str(ctx["binary"])}
        )
        _json(ctx["source_path"], source)
        result = execute(ctx, authority)
        check(
            "target broadening after authorization is rejected",
            result["result"] == "refused"
            and result["reason"] == "authorization-binding-changed",
        )

    with tempfile.TemporaryDirectory() as raw:
        ctx = fixture(Path(raw), pids=(201, 202))
        proposal = plan(ctx)
        live.reconcile(
            ctx["state"], db_root=ctx["db"], proc_root=ctx["proc"],
            fs_root=ctx["fs"], uid=ctx["uid"],
        )
        authority = authorize(ctx, proposal)
        driver = PartialReleaseDriver()
        old_driver = live._driver
        live._driver = lambda **_kwargs: driver
        try:
            contained = execute(ctx, authority)
            check("partial release fixture contained", contained["result"] == "contained")
            active = live._read_object(
                live._active_path(ctx["state"], ctx["incident_id"])
            )
            assert active is not None
            receipt_id = str(active["receipt_id"])
            release_auth = live.authorize_release(
                ctx["state"],
                ctx["incident_id"],
                receipt_id,
                confirm=f"AUTHORIZE-RELEASE:{receipt_id}",
            )
            released = live.execute_release(
                ctx["state"],
                release_auth["authority_id"],
                db_root=ctx["db"],
                proc_root=ctx["proc"],
                fs_root=ctx["fs"],
                uid=ctx["uid"],
            )
            check(
                "partial release is never certified successful",
                released["result"] == "verification-failed"
                and released["verified"] is False,
            )
            check(
                "partial release remains visible as verification-failed",
                live.containment_status(ctx["state"])["state"] == "verification-failed",
            )
        finally:
            live._driver = old_driver

    with tempfile.TemporaryDirectory() as raw:
        ctx = fixture(Path(raw))
        pkg = ctx["db"] / "alpha-1.0-1" / "desc"
        pkg.write_text(
            "%NAME%\nalpha\n\n%VERSION%\n2.0-1\n\n%FILES%\nusr/bin/alpha\n\n",
            encoding="utf-8",
        )
        result = plan(ctx)
        check(
            "package version drift blocks a containment proposal",
            result["state"] == "none"
            and result["reason"] == "package-version-changed",
        )

    print("ALL GUARDIAN LIVE RESPONSE TESTS PASS")


if __name__ == "__main__":
    main()
