#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_system_restore_journal import (  # noqa: E402
    create_journal,
    journal_path,
    new_transaction_id,
    read_journal,
    transition_journal,
    validate_journal,
    write_journal,
)

MID = "0123456789abcdef0123456789abcdef"
SHA = "a" * 40
TX = "l3-20260911T120000Z-deadbeef"


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def sample() -> dict:
    return create_journal(
        transaction_id=TX,
        source_revision=SHA,
        target={
            "generation_id": "g3-1234567890abcdef12345678",
            "snapshot_id": 349,
            "snapshot_uuid": "target-uuid",
            "root_filesystem_uuid": "ce979d1c-c145-4be0-9ce3-591b6fd0a3a1",
            "expected_kernel_sha256": "1" * 64,
            "expected_initramfs_sha256": "2" * 64,
        },
        backup={"snapshot_id": 400, "snapshot_uuid": "backup-uuid"},
        home={"subvolume_uuid": "home-uuid"},
        provider={
            "command": "/usr/bin/limine-snapper-restore",
            "package": "limine-snapper-sync",
            "version": "1.31.0-1",
        },
        now=datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc),
    )


def expect_rejected(name: str, payload: dict) -> None:
    rejected = False
    try:
        validate_journal(payload)
    except ValueError:
        rejected = True
    check(name, rejected)


def main() -> None:
    generated = new_transaction_id(
        now=datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc),
        entropy="deadbeef",
    )
    check("transaction id is deterministic under injected inputs", generated == TX)
    check(
        "journal path is machine-scoped on boot storage",
        journal_path("/boot", MID, TX) == Path(f"/boot/{MID}/maho/recovery/transactions/{TX}.json"),
    )

    prepared = sample()
    check("prepared journal validates", validate_journal(prepared)["phase"] == "prepared")
    check("prepared history begins exactly once", [x["phase"] for x in prepared["history"]] == ["prepared"])

    started = transition_journal(
        prepared,
        "restore-started",
        now=datetime(2026, 9, 11, 12, 1, tzinfo=timezone.utc),
    )
    returned = transition_journal(
        started,
        "provider-returned",
        details={"exit_code": 0},
        now=datetime(2026, 9, 11, 12, 2, tzinfo=timezone.utc),
    )
    awaiting = transition_journal(
        returned,
        "restored-awaiting-reboot",
        now=datetime(2026, 9, 11, 12, 3, tzinfo=timezone.utc),
    )
    done = transition_journal(
        awaiting,
        "structural-verified",
        now=datetime(2026, 9, 11, 12, 4, tzinfo=timezone.utc),
    )
    check("legal restore phase chain is preserved", [x["phase"] for x in done["history"]] == [
        "prepared", "restore-started", "provider-returned", "restored-awaiting-reboot", "structural-verified"
    ])

    illegal = False
    try:
        transition_journal(prepared, "provider-returned")
    except ValueError:
        illegal = True
    check("phase skipping is rejected", illegal)

    terminal = False
    try:
        transition_journal(done, "verify-failed")
    except ValueError:
        terminal = True
    check("successful terminal phase cannot be rewritten", terminal)

    tampered = json.loads(json.dumps(awaiting))
    tampered["history"][1]["phase"] = "provider-returned"
    expect_rejected("tampered transition history is rejected", tampered)

    same = sample()
    same["backup"]["snapshot_id"] = same["target"]["snapshot_id"]
    expect_rejected("target cannot also be emergency backup", same)

    provider = sample()
    provider["provider"]["version"] = "future-version"
    expect_rejected("provider version drift is rejected", provider)

    with tempfile.TemporaryDirectory() as tmp:
        path = journal_path(tmp, MID, TX)
        write_journal(path, awaiting)
        loaded = read_journal(path)
        check("atomic journal roundtrip preserves payload", loaded == awaiting)
        residue = [p.name for p in path.parent.iterdir() if p.name.startswith(".")]
        check("successful atomic write leaves no temp residue", residue == [])

        wrong = path.with_name("l3-20260911T120000Z-cafebabe.json")
        mismatch = False
        try:
            write_journal(wrong, awaiting)
        except ValueError:
            mismatch = True
        check("journal filename must match transaction identity", mismatch)

    bad_mid = False
    try:
        journal_path("/boot", "../../evil", TX)
    except ValueError:
        bad_mid = True
    check("machine id cannot escape boot journal root", bad_mid)

    print("ALL SYSTEM RESTORE JOURNAL CONTRACTS PASS")


if __name__ == "__main__":
    main()
