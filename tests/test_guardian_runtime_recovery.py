#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_runtime_recovery import RuntimeRecoveryStore  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def payload_identity(stage: Path) -> str:
    lines: list[bytes] = []
    for path in sorted(
        (p for p in stage.rglob("*") if p.is_file() and p.name != "manifest.json"),
        key=lambda p: ("./" + p.relative_to(stage).as_posix()).encode(),
    ):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  ./{path.relative_to(stage).as_posix()}\n".encode())
    return hashlib.sha256(b"".join(lines)).hexdigest()


def make_release(releases: Path, revision: str) -> Path:
    stage = releases / f"stage-{revision[:8]}"
    (stage / "share/maho").mkdir(parents=True)
    (stage / "bin").mkdir(parents=True)
    (stage / "bin/probe").write_text("runtime\n")
    (stage / "share/maho/runtime-source-revision").write_text(revision + "\n")
    identity = payload_identity(stage)
    final = releases / identity
    stage.rename(final)
    (final / "manifest.json").write_text(json.dumps({
        "version": 3,
        "content_sha256": identity,
        "source_revision": revision,
    }, sort_keys=True) + "\n")
    for path in sorted(final.rglob("*"), reverse=True):
        if path.is_file():
            os.chmod(path, 0o444)
        elif path.is_dir():
            os.chmod(path, 0o555)
    os.chmod(final, 0o555)
    return final


def make_tree_writable(root: Path) -> None:
    for path in root.rglob("*"):
        try:
            if path.is_dir():
                os.chmod(path, 0o755)
            else:
                os.chmod(path, 0o644)
        except OSError:
            pass


def main() -> None:
    with tempfile.TemporaryDirectory() as raw:
        base = Path(raw)
        try:
            releases = base / "runtime/releases"
            state_root = base / "state/maho/security"
            releases.mkdir(parents=True)
            failed = make_release(releases, "1" * 40)
            replacement = make_release(releases, "2" * 40)
            current = base / "runtime/current"
            current.parent.mkdir(parents=True, exist_ok=True)
            current.symlink_to(failed)

            store = RuntimeRecoveryStore(state_root, releases)
            before = current.resolve()
            started = store.begin(transaction_id="tx-success", failed=str(failed), replacement=str(replacement))
            check("valid exact previous release authorizes L2 transactional recovery", started["automatic_authorized"] is True and started["severity"] == 2)
            check("Guardian runtime store performs no pointer mutation", current.resolve() == before)
            check("runtime incident begins visible in Guardian active state", (state_root / "guardian/active" / f"{started['incident_id']}.json").exists())

            current.unlink()
            current.symlink_to(replacement)
            finished = store.finish(
                incident_id=started["incident_id"],
                observed_current=str(current.resolve()),
                wiring_verified=True,
                systemd_reload_verified=True,
            )
            check("verified postcondition records recovered", finished["verified"] is True and finished["lifecycle"] == "recovered")
            check("successful runtime recovery leaves no active incident", not (state_root / "guardian/active" / f"{started['incident_id']}.json").exists())
            check("successful runtime recovery archives resolved assessment", (state_root / "guardian/archive" / f"{started['incident_id']}.json").exists())
            history = json.loads((state_root / "guardian/recovery-history" / f"{started['incident_id']}.json").read_text())
            check("history attributes execution to setup rather than Guardian", history["executor"] == "maho-setup" and history["guardian_mutation"] is False)
            check("history records exact transactional provider", history["provider"] == "maho-runtime" and history["recovery_mode"] == "transactional")
            check("history transitions cover recovery verification", [row["state"] for row in history["transitions"]] == ["detected", "recovering", "verifying", "recovered"])

            failed2 = make_release(releases, "3" * 40)
            replacement2 = make_release(releases, "4" * 40)
            started2 = store.begin(transaction_id="tx-bad-postcondition", failed=str(failed2), replacement=str(replacement2))
            failed_finish = store.finish(
                incident_id=started2["incident_id"],
                observed_current=str(replacement2),
                wiring_verified=False,
                systemd_reload_verified=True,
            )
            check("wiring verification failure cannot become successful history", failed_finish["verified"] is False and failed_finish["lifecycle"] == "unresolved")
            bad_history = json.loads((state_root / "guardian/recovery-history" / f"{started2['incident_id']}.json").read_text())
            check("failed postcondition remains visible and unverified", bad_history["verified"] is False and (state_root / "guardian/active" / f"{started2['incident_id']}.json").exists())

            same_runtime = store.supersede_unresolved(current_runtime=str(replacement2))
            check("current rollback target cannot supersede its own unresolved incident", same_runtime["count"] == 0 and (state_root / "guardian/active" / f"{started2['incident_id']}.json").exists())

            later = make_release(releases, "9" * 40)
            superseded = store.supersede_unresolved(current_runtime=str(later))
            check("later verified immutable runtime supersedes stale unresolved incident", started2["incident_id"] in superseded["superseded"] and superseded["count"] == 1)
            check("superseded incident no longer latches Guardian active state", not (state_root / "guardian/active" / f"{started2['incident_id']}.json").exists())
            superseded_history = json.loads((state_root / "guardian/recovery-history" / f"{started2['incident_id']}.json").read_text())
            check("supersession preserves failed recovery truth", superseded_history["status"] == "superseded" and superseded_history["verified"] is False and superseded_history["superseded_by_runtime"]["verified"] is True)
            archived = json.loads((state_root / "guardian/archive" / f"{started2['incident_id']}.json").read_text())
            check("superseded assessment records explicit resolution reason", archived["resolution"]["kind"] == "superseded-by-verified-runtime")

            failed3 = make_release(releases, "5" * 40)
            replacement3 = make_release(releases, "6" * 40)
            os.chmod(replacement3 / "bin/probe", 0o644)
            started3 = store.begin(transaction_id="tx-unverified-previous", failed=str(failed3), replacement=str(replacement3))
            check("unverified previous runtime never authorizes automatic recovery", started3["automatic_authorized"] is False and started3["lifecycle"] == "unresolved")

            started4 = store.begin(transaction_id="tx-same-release", failed=str(failed3), replacement=str(failed3))
            check("current and previous same release is rejected", started4["automatic_authorized"] is False and started4["distinct_releases"] is False)

            corrupt_failed = make_release(releases, "7" * 40)
            valid_previous = make_release(releases, "8" * 40)
            os.chmod(corrupt_failed / "bin/probe", 0o644)
            (corrupt_failed / "bin/probe").write_text("corrupted after activation\n")
            os.chmod(corrupt_failed / "bin/probe", 0o444)
            corrupt_started = store.begin(
                transaction_id="tx-corrupt-new-runtime",
                failed=str(corrupt_failed),
                replacement=str(valid_previous),
            )
            check("identified corrupt new runtime may roll back to verified exact previous", corrupt_started["failed_runtime"]["verified"] is False and corrupt_started["failed_runtime_identified"] is True and corrupt_started["automatic_authorized"] is True)
        finally:
            make_tree_writable(base)

    print("ALL GUARDIAN RUNTIME RECOVERY TESTS PASS")


if __name__ == "__main__":
    main()
