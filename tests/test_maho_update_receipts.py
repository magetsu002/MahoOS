#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_update_receipts import build_receipt, format_receipt, load_history, product_status, record_receipt  # noqa: E402
from maho_update_state import UpdateState, create_transaction, transition_transaction  # noqa: E402

NOW = datetime(2026, 9, 12, 7, 0, tzinfo=timezone.utc)


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def transaction(entropy: str = "abcdef123456") -> dict:
    return create_transaction(
        transaction_id=f"upd-20260912T070000Z-{entropy}", source_revision="1" * 40,
        packages=[
            {"name": "maho-os", "installed_version": "1", "candidate_version": "2", "repository": "maho", "roles": ["maho-runtime"]},
            {"name": "linux-cachyos", "installed_version": "7.1", "candidate_version": "7.2", "repository": "core", "roles": ["kernel"], "security_relevant": True},
        ],
        activation_requirements=["restart"], recovery_generation_id="g3-1234567890abcdef12345678", now=NOW,
    )


def advance(current: dict, state: UpdateState, minutes: int, reason: str = "") -> dict:
    return transition_transaction(current, state, reason=reason, now=NOW + timedelta(minutes=minutes))


def main() -> None:
    current = transaction()
    current = advance(current, UpdateState.STAGED, 1)
    current = advance(current, UpdateState.PREPARED, 2)
    current = advance(current, UpdateState.MAINTENANCE_READY, 3)
    current = advance(current, UpdateState.INSTALLING, 4)
    pending = advance(current, UpdateState.INSTALLED_PENDING_ACTIVATION, 5, "awaiting restart")
    receipt = build_receipt(pending)
    check("receipt exposes lifecycle timestamps", receipt["discovered_time"] and receipt["staged_time"] and receipt["prepared_time"] and receipt["installation_time"])
    check("receipt exposes exact package changes", receipt["package_changes"] == [{"name": "linux-cachyos", "from": "7.1", "to": "7.2"}, {"name": "maho-os", "from": "1", "to": "2"}])
    check("receipt exposes Maho runtime, kernel, and security changes", receipt["maho_runtime_changes"] == ["maho-os"] and receipt["kernel_changes"] == ["linux-cachyos"] and receipt["security_changes"] == ["linux-cachyos"])
    check("receipt exposes recovery and activation", receipt["recovery_generation"].startswith("g3-") and receipt["activation_required"])
    status = product_status(pending)
    check("pending activation has quiet passive product wording", status["status"] == "Activates next restart" and status["activation_pending"] and status["notification_policy"] == "none")
    check("product status has no package-count badge", "package_count" not in status and "badge" not in status)

    healthy = advance(advance(pending, UpdateState.ACTIVE_VERIFYING, 6), UpdateState.HEALTHY, 7, "verified")
    healthy_status = product_status(healthy)
    check("healthy routine maintenance records history without popup", healthy_status["status"] == "Healthy" and healthy_status["last_maintenance"] and healthy_status["notification_policy"] == "none")
    human = format_receipt(build_receipt(healthy))
    check("human receipt explains transaction and changes", "Maho Update receipt" in human and "maho-os: 1 -> 2" in human and "Verified:" in human)

    attention_base = advance(advance(transaction("000000000001"), UpdateState.STAGED, 1), UpdateState.PREPARED, 2)
    attention = transition_transaction(attention_base, UpdateState.ATTENTION_REQUIRED, reason="handoff", blockers=["serious_security_issue_deferred"], now=NOW + timedelta(minutes=3))
    attention_status = product_status(attention)
    check("attention status requests one meaningful notification", attention_status["status"] == "Attention required" and attention_status["notification_policy"] == "one-meaningful-attention")

    with tempfile.TemporaryDirectory(prefix="maho-update-receipts-") as temporary:
        root = Path(temporary)
        path = record_receipt(root, pending)
        check("root-owned receipt is read-only to product consumers", path.stat().st_mode & 0o777 == 0o644 and json.loads(path.read_text())["transaction_id"] == pending["transaction_id"])
        record_receipt(root, healthy)
        record_receipt(root, attention)
        history = load_history(root)
        check("history is newest-first and bounded", history[0]["transaction_id"] == healthy["transaction_id"] and len(history) == 2)
        check("prior healthy receipt feeds last-maintenance status", product_status(attention, history=history)["last_maintenance"] == build_receipt(healthy)["verification_time"])
        try:
            record_receipt(root, pending)
        except ValueError:
            check("receipt history refuses backward rewrite", True)

    print("ALL MAHO UPDATE RECEIPT CONTRACTS PASS")


if __name__ == "__main__":
    main()
