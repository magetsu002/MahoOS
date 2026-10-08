#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_update_receipts import record_receipt  # noqa: E402
from maho_update_cli import _presentation_status, status_payload  # noqa: E402
from maho_update_normal_authority import issue_normal_execution_authority, publish_normal_execution_authority  # noqa: E402
from maho_update_state import UpdateState, create_transaction, publish_transaction, transition_transaction  # noqa: E402

NOW = datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc)


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment.update({"MAHO_ROOT": str(ROOT), "MAHO_UPDATE_STATE_ROOT": str(root)})
    return subprocess.run([str(ROOT / "bin/maho-update"), *arguments], text=True, capture_output=True, check=False, env=environment)


def pending() -> dict:
    transaction = create_transaction(
        transaction_id="upd-20260912T080000Z-abcdef123456", source_revision="2" * 40,
        packages=[{"name": "maho-os", "installed_version": "1", "candidate_version": "2", "repository": "maho", "roles": ["maho-runtime"]}],
        activation_requirements=["restart"], recovery_generation_id="g3-1234567890abcdef12345678", now=NOW,
    )
    for state in (UpdateState.STAGED, UpdateState.PREPARED, UpdateState.MAINTENANCE_READY, UpdateState.INSTALLING, UpdateState.INSTALLED_PENDING_ACTIVATION):
        transaction = transition_transaction(transaction, state, now=NOW)
    return transaction


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maho-update-cli-") as temporary:
        root = Path(temporary)
        empty = run(root, "status", "--json")
        empty_status = json.loads(empty.stdout)
        check("no active transaction is quietly healthy", empty.returncode == 0 and empty_status["authority_state"] == "NONE" and empty_status["notification_policy"] == "none")

        transaction = pending()
        publish_transaction(root, transaction)
        record_receipt(root, transaction)
        status = run(root, "status", "--json")
        payload = json.loads(status.stdout)
        check("CLI projects exact authoritative activation state", payload["authority_state"] == "INSTALLED_PENDING_ACTIVATION" and payload["activation_pending"])
        check("CLI exposes receipt history without package badges", payload["history_count"] == 1 and "package_count" not in payload)
        check("install-pending state renders Ready to restart", payload["presentation_status"] == "Ready to restart")
        check("PREPARED without current authority renders Waiting for certification", _presentation_status({"authority_state":"PREPARED","normal_execution_certified":False,"blockers":[]}) == "Waiting for certification")
        check("PREPARED with current authority renders Ready", _presentation_status({"authority_state":"PREPARED","normal_execution_certified":True,"blockers":[]}) == "Ready")
        check("ACTIVE_VERIFYING renders Verifying", _presentation_status({"authority_state":"ACTIVE_VERIFYING","normal_execution_certified":True,"blockers":[]}) == "Verifying")
        check("coordinator up-to-date state stays calm", _presentation_status({"authority_state":"HEALTHY","normal_execution_certified":False,"blockers":[],"coordinator":{"phase":"UP_TO_DATE","blockers":[]}}) == "Up to date")
        check("coordinator waiting state is explicit", _presentation_status({"authority_state":"PREPARED","normal_execution_certified":False,"blockers":[],"coordinator":{"phase":"WAITING_MAINTENANCE","blockers":[]}}) == "Waiting for maintenance opportunity")
        check("coordinator ready state is bounded", _presentation_status({"authority_state":"PREPARED","normal_execution_certified":False,"blockers":[],"coordinator":{"phase":"MAINTENANCE_READY","blockers":[]}}) == "Ready when safe")
        check("coordinator activation handoff renders Ready to restart", _presentation_status({"authority_state":"INSTALLED_PENDING_ACTIVATION","normal_execution_certified":True,"blockers":[],"coordinator":{"phase":"READY_TO_RESTART","blockers":[]}}) == "Ready to restart")
        check("post-restart coordinator state renders Verifying after restart", _presentation_status({"authority_state":"INSTALLED_PENDING_ACTIVATION","normal_execution_certified":True,"blockers":[],"coordinator":{"phase":"VERIFYING_AFTER_RESTART","blockers":[]}}) == "Verifying after restart")
        check("coordinator blocker exposes one real reason", _presentation_status({"authority_state":"HEALTHY","normal_execution_certified":False,"blockers":[],"coordinator":{"phase":"BLOCKED","blockers":["normal_execution_authority_stale_or_invalid"]}}) == "Blocked: normal_execution_authority_stale_or_invalid")
        receipt = run(root, "receipt", "current")
        check("CLI renders human-readable current receipt", receipt.returncode == 0 and "Maho Update receipt" in receipt.stdout and "maho-os: 1 -> 2" in receipt.stdout)
        history = run(root, "history", "--json")
        check("CLI exposes durable receipt history", len(json.loads(history.stdout)) == 1)

        campaign_root = root / "campaign-current"
        revision = "a" * 40
        campaign_root.mkdir()
        (campaign_root / "SOURCE_REVISION").write_text(revision + "\n", encoding="utf-8")
        authority_path = root / "normal-execution-authority.json"
        authority = issue_normal_execution_authority(
            source_revision=revision,
            transaction_id="upd-20260912T080000Z-123456789abc",
            package_generation_id="pkg-" + "b" * 64,
            graph_id="art-" + "c" * 64,
            packages=[{
                "name": "fixture", "installed_version": "1", "candidate_version": "2",
                "sha256": "d" * 64,
            }],
            effects=["ordinary-files-in-place"],
            activation_requirements=[],
            verification={"ok": True},
            candidate_root_identity="candidate-root",
            base_root_identity="base-root",
            now=NOW,
        )
        publish_normal_execution_authority(authority, path=authority_path)
        direct = status_payload(
            root, campaign_root=campaign_root, authority_path=authority_path,
        )
        check(
            "direct status validates authority against the installed update campaign",
            direct["normal_execution_certified"] is True
            and direct["normal_authority_state"] == "current"
            and direct["normal_authority_id"] == authority["authority_id"],
        )

        composite_runtime = root / "runtime-current"
        (composite_runtime / "share/maho").mkdir(parents=True)
        (composite_runtime / "share/maho/runtime-source-revision").write_text(
            "composite:files@" + "e" * 40 + "\n", encoding="utf-8",
        )
        independent = status_payload(
            root,
            maho_root=composite_runtime,
            campaign_root=campaign_root,
            authority_path=authority_path,
        )
        check(
            "componentized user runtime does not invalidate update campaign authority",
            independent["normal_execution_certified"] is True
            and independent["normal_authority_state"] == "current",
        )

        (root / "current").write_text("../../escape\n")
        malformed = json.loads(run(root, "status", "--json").stdout)
        check("malformed current authority fails closed", malformed["authority_state"] == "ATTENTION_REQUIRED" and malformed["notification_policy"] == "one-meaningful-attention")

    print("ALL MAHO UPDATE CLI CONTRACTS PASS")


if __name__ == "__main__":
    main()
