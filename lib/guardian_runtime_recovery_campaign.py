#!/usr/bin/env python3
"""Physical certification harness for existing Guardian runtime recovery.

The harness adds no recovery authority. It prepares a bounded reversible
integrity fault, lets the normal security/Guardian pipeline observe it, and
then consumes the existing single-use live-recovery authorization contract.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
from types import SimpleNamespace
from typing import Any, Mapping

import guardian_incident
import guardian_live_recovery
import security_incident
from maho_runtime_release import verify_release


SCHEMA_VERSION = 1
TARGET_RELATIVE_PATH = Path("share/maho/runtime-source-revision")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_private(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    data = json.dumps(payload, indent=2, sort_keys=True).encode() + b"\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("runtime recovery campaign record is not an object")
    return value


def _campaign_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"runtime-recovery-{stamp}-{secrets.token_hex(6)}"


def _campaign_path(campaign_root: Path, campaign_id: str) -> Path:
    if not campaign_id.startswith("runtime-recovery-") or "/" in campaign_id or ".." in campaign_id:
        raise ValueError("runtime recovery campaign identity is invalid")
    return campaign_root / f"{campaign_id}.json"


def _resolved_link(path: Path) -> Path:
    if not path.is_symlink():
        raise ValueError(f"runtime pointer is not a symlink:{path.name}")
    target = path.resolve(strict=True)
    if target.parent != (path.parent / "releases").resolve(strict=True):
        raise ValueError(f"runtime pointer escapes releases root:{path.name}")
    return target


def _runtime_pair(
    runtime_root: Path, *, require_current_verified: bool,
    require_previous_verified: bool = True,
) -> dict[str, Any]:
    releases = runtime_root / "releases"
    current_path = _resolved_link(runtime_root / "current")
    previous_path = _resolved_link(runtime_root / "previous")
    if current_path == previous_path:
        raise ValueError("current and previous runtime releases are not distinct")
    current = verify_release(current_path, releases)
    previous = verify_release(previous_path, releases)
    if require_current_verified and not current.verified:
        raise ValueError("current immutable runtime is not verified")
    if require_previous_verified and not previous.verified:
        raise ValueError("previous immutable runtime is not independently verified")
    def normalized(value) -> dict[str, Any]:
        payload = value.as_dict()
        payload["reasons"] = list(payload.get("reasons") or [])
        return payload
    return {"current": normalized(current), "previous": normalized(previous)}


def _active_units() -> list[str]:
    active: list[str] = []
    for unit in guardian_live_recovery.MANAGED_RUNTIME_UNITS:
        result = guardian_live_recovery.MahoSetupRollbackDriver._run(
            ["/usr/bin/systemctl", "--user", "is-active", "--quiet", unit]
        )
        if result.returncode == 0:
            active.append(unit)
    return active


def prepare_campaign(runtime_root: Path, campaign_root: Path) -> dict[str, Any]:
    pair = _runtime_pair(runtime_root, require_current_verified=True)
    current = Path(str(pair["current"]["path"]))
    target = current / TARGET_RELATIVE_PATH
    expected_parent = (current / TARGET_RELATIVE_PATH.parent).resolve(strict=True)
    if target.is_symlink() or not target.is_file() or target.parent.resolve(strict=True) != expected_parent:
        raise ValueError("bounded runtime corruption target is unavailable or unsafe")
    campaign_id = _campaign_id()
    target_sha = _sha256(target)
    confirmation = f"CORRUPT-RUNTIME:{campaign_id}:{target_sha[:16]}"
    stamp = _utc_now()
    record = {
        "schema_version": SCHEMA_VERSION,
        "kind": "maho-guardian-runtime-recovery-physical-campaign",
        "campaign_id": campaign_id,
        "phase": "PREPARED",
        "prepared_at": stamp,
        "updated_at": stamp,
        "runtime_root": str(runtime_root.resolve()),
        "runtime": pair,
        "corruption": {
            "target_relative_path": str(TARGET_RELATIVE_PATH),
            "target_path": str(target),
            "before_sha256": target_sha,
            "before_mode": target.stat().st_mode & 0o777,
            "method": "append-campaign-marker",
            "mutation_started": False,
        },
        "active_units_before": _active_units(),
        "corruption_confirmation": confirmation,
        "recovery_confirmation": None,
        "incident_id": None,
        "proposal_id": None,
        "receipt": None,
    }
    _atomic_private(_campaign_path(campaign_root, campaign_id), record)
    return record


def _security_reconcile(
    state_root: Path, runtime_root: Path, db_root: Path,
    proc_root: Path, fs_root: Path,
) -> dict[str, Any]:
    args = SimpleNamespace(
        state_root=str(state_root), db_root=str(db_root), proc_root=str(proc_root),
        fs_root=str(fs_root), runtime_root=str(runtime_root), uid=os.getuid(),
        prevention_mode="shadow", autonomy_level="guard",
    )
    raw = security_incident.reconcile(args)
    guardian_incident.reconcile_security(state_root, raw)
    return raw


def _runtime_incident_id(state_root: Path) -> str:
    active = state_root / "incidents" / "active"
    matches: list[str] = []
    paths = sorted(active.glob("inc-*.json")) if active.is_dir() else []
    for path in paths:
        try:
            row = _read_object(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        subject = row.get("subject") if isinstance(row.get("subject"), Mapping) else {}
        if row.get("status") == "active" and subject == {"type": "runtime", "id": "maho-runtime"}:
            matches.append(str(row.get("incident_id") or ""))
    if len(matches) != 1 or not matches[0]:
        raise RuntimeError("exact active runtime-integrity incident was not uniquely observed")
    return matches[0]


def corrupt_campaign(
    campaign_root: Path, campaign_id: str, *, confirm: str,
    state_root: Path, db_root: Path, proc_root: Path, fs_root: Path,
) -> dict[str, Any]:
    path = _campaign_path(campaign_root, campaign_id)
    record = _read_object(path)
    if record.get("phase") != "PREPARED" or confirm != record.get("corruption_confirmation"):
        raise ValueError("exact corruption campaign confirmation is required")
    runtime_root = Path(str(record["runtime_root"]))
    pair = _runtime_pair(runtime_root, require_current_verified=True)
    if pair != record.get("runtime"):
        raise RuntimeError("runtime pair drifted after campaign preparation")
    target = Path(str(record["corruption"]["target_path"]))
    if target.resolve(strict=True) != Path(str(pair["current"]["path"])) / TARGET_RELATIVE_PATH:
        raise RuntimeError("runtime corruption target binding drifted")
    if _sha256(target) != record["corruption"]["before_sha256"]:
        raise RuntimeError("runtime corruption target changed before campaign")
    mode = int(record["corruption"]["before_mode"])
    marker = f"\n# maho-runtime-recovery-campaign:{campaign_id}\n".encode()
    os.chmod(target, mode | 0o200)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_APPEND)
        try:
            os.write(fd, marker)
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        os.chmod(target, mode)
    after = _runtime_pair(runtime_root, require_current_verified=False)
    current_reasons = set(after["current"].get("reasons") or [])
    if after["current"].get("verified") is not False or "payload_content_identity_mismatch" not in current_reasons:
        raise RuntimeError("controlled runtime corruption did not produce exact verifier failure")
    if after["previous"].get("verified") is not True:
        raise RuntimeError("previous runtime lost independent verification after corruption")
    _security_reconcile(state_root, runtime_root, db_root, proc_root, fs_root)
    incident_id = _runtime_incident_id(state_root)
    proposal = guardian_live_recovery.plan_runtime_recovery(
        state_root, incident_id, db_root=db_root, runtime_root=runtime_root,
        proc_root=proc_root, fs_root=fs_root, uid=os.getuid(),
    )
    if proposal.get("state") != "authorization-required":
        raise RuntimeError("Guardian did not produce a bounded runtime recovery proposal")
    proposal_id = str(proposal["proposal_id"])
    record.update({
        "phase": "AWAITING_RECOVERY_AUTHORIZATION",
        "updated_at": _utc_now(),
        "incident_id": incident_id,
        "proposal_id": proposal_id,
        "recovery_confirmation": f"AUTHORIZE-RUNTIME-RECOVERY:{proposal_id}",
        "runtime_after_corruption": after,
        "corruption": {
            **dict(record["corruption"]),
            "mutation_started": True,
            "after_sha256": _sha256(target),
            "marker_sha256": hashlib.sha256(marker).hexdigest(),
        },
        "guardian_proposal": proposal,
    })
    _atomic_private(path, record)
    return record


def recover_campaign(
    campaign_root: Path, campaign_id: str, *, confirm: str,
    state_root: Path, db_root: Path, proc_root: Path, fs_root: Path,
    driver: guardian_live_recovery.RuntimeRollbackDriver | None = None,
) -> dict[str, Any]:
    path = _campaign_path(campaign_root, campaign_id)
    record = _read_object(path)
    if record.get("phase") != "AWAITING_RECOVERY_AUTHORIZATION" or confirm != record.get("recovery_confirmation"):
        raise ValueError("exact recovery authorization confirmation is required")
    runtime_root = Path(str(record["runtime_root"]))
    proposal = guardian_live_recovery.plan_runtime_recovery(
        state_root, str(record["incident_id"]), db_root=db_root, runtime_root=runtime_root,
        proc_root=proc_root, fs_root=fs_root, uid=os.getuid(),
    )
    if proposal.get("proposal_id") != record.get("proposal_id") or proposal.get("state") != "authorization-required":
        raise RuntimeError("runtime recovery proposal drifted before authorization")
    authority = guardian_live_recovery.authorize_runtime_recovery(
        state_root, str(record["incident_id"]), str(record["proposal_id"]), confirm=confirm,
    )
    if authority.get("user_authorized") is not True:
        raise RuntimeError("runtime recovery authorization was refused")
    result = guardian_live_recovery.execute_runtime_recovery(
        state_root, str(authority["authority_id"]), db_root=db_root,
        runtime_root=runtime_root, proc_root=proc_root, fs_root=fs_root,
        uid=os.getuid(), driver=driver,
    )
    _security_reconcile(state_root, runtime_root, db_root, proc_root, fs_root)
    after = _runtime_pair(
        runtime_root, require_current_verified=True,
        require_previous_verified=False,
    )
    expected_current = str(record["runtime"]["previous"]["path"])
    expected_previous = str(record["runtime"]["current"]["path"])
    active = state_root / "incidents" / "active" / f"{record['incident_id']}.json"
    verified = bool(
        result.get("result") == "recovered"
        and after["current"]["path"] == expected_current
        and after["previous"]["path"] == expected_previous
        and after["current"]["verified"] is True
        and after["previous"]["verified"] is False
        and not active.exists()
    )
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "kind": "maho-guardian-runtime-recovery-physical-receipt",
        "campaign_id": campaign_id,
        "incident_id": record["incident_id"],
        "proposal_id": record["proposal_id"],
        "authority_id": authority.get("authority_id"),
        "guardian_result": result,
        "runtime_after_recovery": after,
        "current_is_verified_previous": after["current"]["path"] == expected_current,
        "corrupted_generation_retained": after["previous"]["path"] == expected_previous and after["previous"]["verified"] is False,
        "incident_resolved": not active.exists(),
        "verified": verified,
        "completed_at": _utc_now(),
    }
    record.update({
        "phase": "VERIFIED" if verified else "VERIFICATION_FAILED",
        "updated_at": _utc_now(),
        "receipt": receipt,
    })
    _atomic_private(path, record)
    return record


def main(argv: list[str] | None = None) -> int:
    state_default = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    parser = argparse.ArgumentParser(prog="maho-guardian-runtime-recovery-certify")
    parser.add_argument("--runtime-root", type=Path, default=Path.home() / ".local/share/maho/runtime")
    parser.add_argument("--state-root", type=Path, default=state_default / "maho/security")
    parser.add_argument("--campaign-root", type=Path, default=state_default / "maho/certification/runtime-recovery")
    parser.add_argument("--db-root", type=Path, default=Path("/var/lib/pacman/local"))
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"))
    parser.add_argument("--fs-root", type=Path, default=Path("/"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    corrupt = sub.add_parser("corrupt")
    corrupt.add_argument("campaign_id")
    corrupt.add_argument("--confirm", required=True)
    recover = sub.add_parser("recover")
    recover.add_argument("campaign_id")
    recover.add_argument("--confirm", required=True)
    status = sub.add_parser("status")
    status.add_argument("campaign_id")
    sub.add_parser("history")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        result = prepare_campaign(args.runtime_root, args.campaign_root)
    elif args.command == "corrupt":
        result = corrupt_campaign(args.campaign_root, args.campaign_id, confirm=args.confirm, state_root=args.state_root, db_root=args.db_root, proc_root=args.proc_root, fs_root=args.fs_root)
    elif args.command == "recover":
        result = recover_campaign(args.campaign_root, args.campaign_id, confirm=args.confirm, state_root=args.state_root, db_root=args.db_root, proc_root=args.proc_root, fs_root=args.fs_root)
    elif args.command == "status":
        result = _read_object(_campaign_path(args.campaign_root, args.campaign_id))
    else:
        rows = []
        if args.campaign_root.is_dir():
            for item in sorted(args.campaign_root.glob("runtime-recovery-*.json"), reverse=True):
                try:
                    row = _read_object(item)
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                rows.append({
                    "campaign_id": row.get("campaign_id"), "phase": row.get("phase"),
                    "updated_at": row.get("updated_at"),
                    "verified": bool((row.get("receipt") or {}).get("verified")),
                })
        result = {"schema_version": SCHEMA_VERSION, "campaigns": rows}
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
