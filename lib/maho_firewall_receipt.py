#!/usr/bin/env python3
"""Root-published, boot-bound firewall status receipt for unprivileged consumers."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from typing import Any, Mapping

DEFAULT_RECEIPT = Path("/run/maho/firewall/status.json")
DEFAULT_MAX_AGE_SECONDS = 45
RECEIPT_KIND = "maho-firewall-live-receipt"
AUTHORITY = "root observer of table inet maho_host only"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def root_dir() -> Path:
    explicit = os.environ.get("MAHO_ROOT")
    return Path(explicit).expanduser().resolve() if explicit else Path(__file__).resolve().parent.parent


def policy_path(root: Path | None = None) -> Path:
    return (root or root_dir()) / "config/platform/maho-host-firewall.nft"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_boot_id() -> str:
    value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError("boot id is empty")
    return value


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _live_status(root: Path) -> dict[str, Any]:
    command = [str(root / "bin/maho-firewall"), "live-status", "--json"]
    result = subprocess.run(command, text=True, capture_output=True, timeout=20, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "live firewall observation failed").strip()
        raise RuntimeError(detail)
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise ValueError("live firewall status is not an object")
    return payload


def _atomic_public(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o755)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        os.chmod(path, 0o644)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def publish(receipt: Path = DEFAULT_RECEIPT, *, root: Path | None = None) -> dict[str, Any]:
    source_root = root or root_dir()
    policy = policy_path(source_root)
    live = _live_status(source_root)
    observed = utc_now()
    payload = {
        "schema_version": 1,
        "kind": RECEIPT_KIND,
        "observed_at": iso_utc(observed),
        "boot_id": current_boot_id(),
        "authority": AUTHORITY,
        "scope": {
            "family": "inet",
            "table": "maho_host",
            "hooks": ["input"],
            "provider_global_authority": False,
            "provider_coexistence": "not-observed-outside-owned-table",
        },
        "policy_sha256": sha256_file(policy),
        "policy_path": str(policy),
        "live_status": live,
        "live_status_sha256": _canonical_hash(live),
    }
    _atomic_public(receipt, payload)
    return payload


def _secure_root_owned(path: Path, *, require_root_owner: bool) -> list[str]:
    reasons: list[str] = []
    try:
        parent = path.parent.lstat()
        item = path.lstat()
    except OSError as exc:
        return [f"receipt unavailable: {exc}"]
    if stat.S_ISLNK(item.st_mode) or not stat.S_ISREG(item.st_mode):
        reasons.append("receipt must be a regular non-symlink file")
    if stat.S_ISLNK(parent.st_mode) or not stat.S_ISDIR(parent.st_mode):
        reasons.append("receipt parent must be a real directory")
    if require_root_owner and (item.st_uid != 0 or parent.st_uid != 0):
        reasons.append("receipt and parent must be root-owned")
    if item.st_mode & 0o022:
        reasons.append("receipt must not be group/world writable")
    if parent.st_mode & 0o022:
        reasons.append("receipt parent must not be group/world writable")
    return reasons


def verify(
    receipt: Path = DEFAULT_RECEIPT,
    *,
    root: Path | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    now: datetime | None = None,
    expected_boot_id: str | None = None,
    require_root_owner: bool = True,
) -> dict[str, Any]:
    reasons = _secure_root_owned(receipt, require_root_owner=require_root_owner)
    payload: dict[str, Any] | None = None
    if not reasons:
        try:
            value = json.loads(receipt.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("receipt is not an object")
            payload = value
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reasons.append(f"receipt parse failed: {exc}")
    if payload is not None:
        if payload.get("schema_version") != 1 or payload.get("kind") != RECEIPT_KIND:
            reasons.append("receipt schema/kind is unsupported")
        if payload.get("authority") != AUTHORITY:
            reasons.append("receipt authority boundary is invalid")
        scope = payload.get("scope")
        if not isinstance(scope, dict) or scope.get("family") != "inet" or scope.get("table") != "maho_host":
            reasons.append("receipt scope is not exact table inet maho_host")
        observed = parse_timestamp(payload.get("observed_at"))
        if observed is None:
            reasons.append("receipt observation time is invalid")
        else:
            age = max(0.0, ((now or utc_now()) - observed).total_seconds())
            if age > max_age_seconds:
                reasons.append(f"receipt is stale: {age:.3f}s")
        boot = expected_boot_id or current_boot_id()
        if payload.get("boot_id") != boot:
            reasons.append("receipt boot id does not match current boot")
        try:
            expected_policy = sha256_file(policy_path(root or root_dir()))
        except OSError as exc:
            reasons.append(f"current firewall policy unavailable: {exc}")
        else:
            if payload.get("policy_sha256") != expected_policy:
                reasons.append("receipt policy hash does not match current Maho policy")
        live = payload.get("live_status")
        if not isinstance(live, dict):
            reasons.append("receipt live status is missing")
        elif payload.get("live_status_sha256") != _canonical_hash(live):
            reasons.append("receipt live status digest mismatch")

    if reasons or payload is None:
        return {
            "schema_version": 1,
            "authority": AUTHORITY,
            "state": "unknown",
            "result": "unknown",
            "table_present": None,
            "verified": False,
            "decision_usable": False,
            "receipt_valid": False,
            "receipt": str(receipt),
            "reasons": reasons,
        }

    live = payload["live_status"]
    return {
        **live,
        "receipt_valid": True,
        "receipt": str(receipt),
        "receipt_observed_at": payload["observed_at"],
        "receipt_boot_id": payload["boot_id"],
        "policy_sha256": payload["policy_sha256"],
        "authority": AUTHORITY,
        "provider_global_authority": False,
        "provider_coexistence": "not-observed-outside-owned-table",
        "reasons": list(live.get("reasons") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="maho-firewall-receipt")
    parser.add_argument("command", choices=("publish", "verify"))
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--max-age-seconds", type=int, default=DEFAULT_MAX_AGE_SECONDS)
    args = parser.parse_args()
    if args.max_age_seconds < 1:
        raise SystemExit("--max-age-seconds must be positive")
    if args.command == "publish":
        if os.geteuid() != 0 and args.receipt == DEFAULT_RECEIPT:
            raise SystemExit("publishing the system firewall receipt requires root")
        payload = publish(args.receipt)
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return 0
    payload = verify(args.receipt, max_age_seconds=args.max_age_seconds)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0 if payload.get("decision_usable") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
