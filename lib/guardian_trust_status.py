#!/usr/bin/env python3
"""Read-only Guardian trust and recovery-history status surface."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import platform
from typing import Any, Mapping

DEFAULT_STATE_ROOT = Path("/var/lib/maho/guardian-recovery-r3/campaigns")

@dataclass(frozen=True)
class RecoveryRecord:
    campaign_id: str
    outcome: str
    phase: str
    reason: str
    kernel_release: str | None
    kernel_generation_id: str | None
    system_generation_id: str | None
    root_uuid: str | None
    home_subvolume_uuid: str | None
    boot_artifacts_verified: bool
    firmware_mutated: bool
    valid: bool
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

def _load_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("evidence is not a JSON object")
    return payload

def _optional_string(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) and value else None

def _record_from_postboot(path: Path) -> RecoveryRecord:
    try:
        data = _load_json(path)
        campaign = _optional_string(data, "campaign_id")
        if campaign is None:
            raise ValueError("campaign identity missing")
        valid = (
            data.get("schema_version") == 1
            and data.get("outcome") == "PASS"
            and data.get("phase") == "VERIFIED"
            and data.get("reason") == "native_kernel_recovery_postboot_verified"
            and data.get("normal_root_active") is True
            and data.get("boot_artifacts_verified") is True
            and data.get("firmware_mutated") is False
            and _optional_string(data, "running_kernel_release") is not None
            and _optional_string(data, "target_kernel_generation_id") is not None
            and _optional_string(data, "target_system_generation_id") is not None
            and _optional_string(data, "root_uuid") is not None
            and _optional_string(data, "home_subvolume_uuid") is not None
        )
        return RecoveryRecord(
            campaign_id=campaign,
            outcome=str(data.get("outcome", "UNKNOWN")),
            phase=str(data.get("phase", "UNKNOWN")),
            reason=str(data.get("reason", "unknown")),
            kernel_release=_optional_string(data, "running_kernel_release"),
            kernel_generation_id=_optional_string(data, "target_kernel_generation_id"),
            system_generation_id=_optional_string(data, "target_system_generation_id"),
            root_uuid=_optional_string(data, "root_uuid"),
            home_subvolume_uuid=_optional_string(data, "home_subvolume_uuid"),
            boot_artifacts_verified=data.get("boot_artifacts_verified") is True,
            firmware_mutated=data.get("firmware_mutated") is True,
            valid=valid,
            error=None if valid else "postboot proof contract invalid",
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return RecoveryRecord(
            campaign_id=path.parent.name,
            outcome="INVALID", phase="INVALID", reason="evidence_parse_failed",
            kernel_release=None, kernel_generation_id=None, system_generation_id=None,
            root_uuid=None, home_subvolume_uuid=None, boot_artifacts_verified=False,
            firmware_mutated=False, valid=False, error=str(exc),
        )

def recovery_history(state_root: str | Path) -> tuple[RecoveryRecord, ...]:
    root = Path(state_root)
    try:
        paths = list(root.glob("*/postboot.json")) if root.is_dir() else []
    except OSError:
        return ()
    records = [_record_from_postboot(path) for path in paths]
    return tuple(sorted(records, key=lambda item: item.campaign_id, reverse=True))

def status_payload(state_root: str | Path, *, current_kernel_release: str | None = None) -> dict[str, Any]:
    root = Path(state_root)
    history = recovery_history(root)
    verified = next((item for item in history if item.valid), None)
    running = current_kernel_release or platform.release()
    accessible = root.is_dir() and bool(history)
    return {
        "schema_version": 1,
        "evidence_root": str(root),
        "evidence_available": accessible,
        "current_kernel_release": running,
        "current_generation_trust": "UNRESOLVED",
        "trust_note": "historical recovery proof cannot promote the current generation; exact live trust evidence is required",
        "last_verified_recovery": verified.as_dict() if verified else None,
        "current_kernel_matches_last_verified_recovery": bool(verified and verified.kernel_release == running),
        "invalid_history_records": sum(1 for item in history if not item.valid),
    }

def render_status(payload: Mapping[str, Any]) -> str:
    recovery = payload.get("last_verified_recovery")
    lines = [
        "Maho Guardian trust status", "",
        f"current kernel              {payload['current_kernel_release']}",
        f"current generation trust    {payload['current_generation_trust']}",
        f"recovery evidence           {'available' if payload['evidence_available'] else 'unavailable'}",
    ]
    if isinstance(recovery, Mapping):
        lines.extend((
            f"last verified recovery      {recovery['campaign_id']}",
            f"verified kernel             {recovery.get('kernel_release') or 'unknown'}",
            f"KernelGeneration            {recovery.get('kernel_generation_id') or 'unknown'}",
            f"SystemGeneration            {recovery.get('system_generation_id') or 'unknown'}",
            f"boot artifacts verified     {'yes' if recovery.get('boot_artifacts_verified') else 'no'}",
            f"firmware mutated            {'yes' if recovery.get('firmware_mutated') else 'no'}",
            f"running kernel matches      {'yes' if payload['current_kernel_matches_last_verified_recovery'] else 'no'}",
        ))
    else:
        lines.append("last verified recovery      unavailable")
    if payload.get("invalid_history_records"):
        lines.append(f"invalid history records     {payload['invalid_history_records']}")
    lines.extend(("", str(payload["trust_note"])))
    return "\n".join(lines)

def render_history(records: tuple[RecoveryRecord, ...]) -> str:
    if not records:
        return "No Guardian recovery history is readable."
    lines = ["Maho Guardian recovery history", ""]
    for record in records:
        state = "VERIFIED" if record.valid else "INVALID"
        lines.append(f"{record.campaign_id}  {state}  {record.kernel_release or '-'}")
        if record.error:
            lines.append(f"  reason: {record.error}")
    return "\n".join(lines)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maho-trust")
    parser.add_argument("--state-root", default=str(DEFAULT_STATE_ROOT))
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "history"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "status":
        payload = status_payload(args.state_root)
        print(json.dumps(payload, sort_keys=True) if args.json else render_status(payload))
        return 0
    records = recovery_history(args.state_root)
    if args.json:
        print(json.dumps([record.as_dict() for record in records], sort_keys=True))
    else:
        print(render_history(records))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
