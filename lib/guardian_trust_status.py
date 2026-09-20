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
DEFAULT_RUNTIME_CAMPAIGN_ROOT = Path.home() / ".local/state/maho/certification/runtime-recovery"

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
    mode: str = "KERNEL_OR_FULL_GENERATION"
    incident_id: str | None = None
    receipt_id: str | None = None

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
            mode=str(data.get("mode") or "KERNEL_OR_FULL_GENERATION"),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return RecoveryRecord(
            campaign_id=path.parent.name,
            outcome="INVALID", phase="INVALID", reason="evidence_parse_failed",
            kernel_release=None, kernel_generation_id=None, system_generation_id=None,
            root_uuid=None, home_subvolume_uuid=None, boot_artifacts_verified=False,
            firmware_mutated=False, valid=False, error=str(exc),
        )

def _record_from_runtime_campaign(path: Path) -> RecoveryRecord:
    try:
        data = _load_json(path)
        campaign = _optional_string(data, "campaign_id")
        receipt = data.get("receipt")
        if campaign is None or path.stem != campaign or not isinstance(receipt, Mapping):
            raise ValueError("runtime campaign identity or receipt missing")
        result = receipt.get("guardian_result")
        valid = (
            data.get("schema_version") == 1
            and data.get("kind") == "maho-guardian-runtime-recovery-physical-campaign"
            and data.get("phase") == "VERIFIED"
            and receipt.get("schema_version") == 1
            and receipt.get("kind") == "maho-guardian-runtime-recovery-physical-receipt"
            and receipt.get("campaign_id") == campaign
            and receipt.get("verified") is True
            and receipt.get("current_is_verified_previous") is True
            and receipt.get("corrupted_generation_retained") is True
            and receipt.get("incident_resolved") is True
            and isinstance(result, Mapping)
            and result.get("result") == "recovered"
            and result.get("verified") is True
        )
        runtime = receipt.get("runtime_after_recovery")
        current = runtime.get("current") if isinstance(runtime, Mapping) else None
        return RecoveryRecord(
            campaign_id=campaign,
            outcome="PASS" if valid else "INVALID",
            phase=str(data.get("phase", "UNKNOWN")),
            reason="immutable_runtime_recovery_verified" if valid else "runtime_recovery_contract_invalid",
            kernel_release=None,
            kernel_generation_id=None,
            system_generation_id=(
                str(current.get("content_sha256"))
                if isinstance(current, Mapping) and current.get("content_sha256")
                else None
            ),
            root_uuid=None,
            home_subvolume_uuid=None,
            boot_artifacts_verified=False,
            firmware_mutated=False,
            valid=valid,
            error=None if valid else "runtime recovery receipt contract invalid",
            mode="RUNTIME",
            incident_id=_optional_string(receipt, "incident_id"),
            receipt_id=(
                _optional_string(result, "receipt_id") if isinstance(result, Mapping) else None
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return RecoveryRecord(
            campaign_id=path.stem,
            outcome="INVALID", phase="INVALID", reason="evidence_parse_failed",
            kernel_release=None, kernel_generation_id=None, system_generation_id=None,
            root_uuid=None, home_subvolume_uuid=None, boot_artifacts_verified=False,
            firmware_mutated=False, valid=False, error=str(exc), mode="RUNTIME",
        )

def recovery_history(state_root: str | Path) -> tuple[RecoveryRecord, ...]:
    root = Path(state_root)
    try:
        paths = list(root.glob("*/postboot.json")) if root.is_dir() else []
    except OSError:
        return ()
    records = [_record_from_postboot(path) for path in paths]
    return tuple(sorted(records, key=lambda item: item.campaign_id, reverse=True))

def runtime_recovery_history(campaign_root: str | Path) -> tuple[RecoveryRecord, ...]:
    root = Path(campaign_root)
    try:
        paths = list(root.glob("runtime-recovery-*.json")) if root.is_dir() else []
    except OSError:
        return ()
    records = [_record_from_runtime_campaign(path) for path in paths]
    return tuple(sorted(records, key=lambda item: item.campaign_id, reverse=True))

def unified_recovery_history(
    state_root: str | Path, runtime_campaign_root: str | Path,
) -> tuple[RecoveryRecord, ...]:
    records = (*recovery_history(state_root), *runtime_recovery_history(runtime_campaign_root))
    return tuple(sorted(records, key=lambda item: item.campaign_id, reverse=True))

def status_payload(
    state_root: str | Path, *, current_kernel_release: str | None = None,
    runtime_campaign_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(state_root)
    history = recovery_history(root)
    verified = next((item for item in history if item.valid), None)
    runtime_history = runtime_recovery_history(runtime_campaign_root) if runtime_campaign_root is not None else ()
    verified_runtime = next((item for item in runtime_history if item.valid), None)
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
        "last_verified_runtime_recovery": verified_runtime.as_dict() if verified_runtime else None,
        "unified_history_count": len(history) + len(runtime_history),
        "recovery_modes": sorted({item.mode for item in (*history, *runtime_history) if item.valid}),
        "invalid_unified_history_records": sum(1 for item in (*history, *runtime_history) if not item.valid),
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
    runtime = payload.get("last_verified_runtime_recovery")
    if isinstance(runtime, Mapping):
        lines.extend((
            f"last runtime recovery       {runtime['campaign_id']}",
            f"runtime recovery receipt    {runtime.get('receipt_id') or 'unknown'}",
        ))
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
        identity = record.kernel_release or record.receipt_id or "-"
        lines.append(f"{record.campaign_id}  {record.mode}  {state}  {identity}")
        if record.error:
            lines.append(f"  reason: {record.error}")
    return "\n".join(lines)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maho-trust")
    parser.add_argument("--state-root", default=str(DEFAULT_STATE_ROOT))
    parser.add_argument("--runtime-campaign-root", default=str(DEFAULT_RUNTIME_CAMPAIGN_ROOT))
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "history"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "status":
        payload = status_payload(args.state_root, runtime_campaign_root=args.runtime_campaign_root)
        print(json.dumps(payload, sort_keys=True) if args.json else render_status(payload))
        return 0
    records = unified_recovery_history(args.state_root, args.runtime_campaign_root)
    if args.json:
        print(json.dumps([record.as_dict() for record in records], sort_keys=True))
    else:
        print(render_history(records))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
