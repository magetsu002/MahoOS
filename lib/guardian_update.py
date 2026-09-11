#!/usr/bin/env python3
"""Non-mutating Guardian projection of authoritative Maho Update state."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from maho_update_cli import status_payload
from maho_update_state import UpdateState


@dataclass(frozen=True)
class GuardianUpdateView:
    source: str
    transaction_id: str | None
    authority_state: str
    active: bool
    guardian_level: int
    label: str
    attention_required: bool
    execution_mode: str
    mutating_recovery_allowed: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def project_update_status(status: Mapping[str, Any]) -> GuardianUpdateView:
    if not isinstance(status, Mapping) or status.get("schema_version") != 1:
        return GuardianUpdateView(
            "maho-update-authority", None, "ATTENTION_REQUIRED", True, 2, "attention",
            True, "observe", False, "authoritative update status is malformed",
        )
    state = status.get("authority_state")
    allowed = {item.value for item in UpdateState} | {"NONE"}
    if state not in allowed:
        return GuardianUpdateView(
            "maho-update-authority", None, "ATTENTION_REQUIRED", True, 2, "attention",
            True, "observe", False, "authoritative update state is ambiguous",
        )
    transaction_id = status.get("transaction_id") if isinstance(status.get("transaction_id"), str) else None
    if state == UpdateState.ATTENTION_REQUIRED.value:
        return GuardianUpdateView(
            "maho-update-authority", transaction_id, state, True, 2, "attention",
            True, "observe", False, "update authority requested an explicit user handoff",
        )
    if state in {UpdateState.RECOVERING.value, UpdateState.FAILED_RECOVERABLE.value}:
        return GuardianUpdateView(
            "maho-update-authority", transaction_id, state, True, 1, "maintenance",
            False, "observe", False, "update authority is handling a bounded recoverable failure",
        )
    return GuardianUpdateView(
        "maho-update-authority", transaction_id, state, False, 0, "normal",
        False, "observe", False, "update lifecycle is represented by its own bounded authority",
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="guardian_update.py")
    parser.add_argument("--state-root", type=Path, required=True)
    args = parser.parse_args()
    view = project_update_status(status_payload(args.state_root))
    print(json.dumps(view.as_dict(), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
