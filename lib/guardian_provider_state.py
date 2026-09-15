#!/usr/bin/env python3
"""Durable Guardian provider heartbeat state.

Heartbeat time means successful observation, not last state transition. Attempts
are tracked separately so a dead or failing observer cannot keep old clean state
fresh merely because the result file still exists.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

from guardian_evidence import ProviderHealth, parse_timestamp, utc_stamp

SCHEMA_VERSION = 1
_PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9._:-]{1,127}")
_DOMAIN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")

@dataclass(frozen=True)
class ProviderHeartbeat:
    provider_id: str
    domain: str
    source: str
    authority_boundary: str
    sequence: int
    last_attempt_at: str
    last_success_at: str | None
    health: ProviderHealth
    errors: tuple[str, ...] = ()
    boot_id: str | None = None
    details: Mapping[str, Any] | None = None
    schema_version: int = SCHEMA_VERSION
    kind: str = "guardian-provider-heartbeat"
    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or self.kind != "guardian-provider-heartbeat":
            raise ValueError("provider heartbeat schema is invalid")
        if _PROVIDER_ID.fullmatch(self.provider_id) is None or _DOMAIN.fullmatch(self.domain) is None:
            raise ValueError("provider heartbeat identity is invalid")
        if not self.source or not self.authority_boundary or self.sequence < 1:
            raise ValueError("provider heartbeat provenance is incomplete")
        parse_timestamp(self.last_attempt_at)
        if self.last_success_at is not None:
            parse_timestamp(self.last_success_at)
    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["health"] = self.health.value
        payload["errors"] = list(self.errors)
        payload["details"] = dict(self.details or {})
        return payload

def heartbeat_dir(state_root: Path) -> Path:
    return state_root / "guardian" / "providers"

def heartbeat_path(state_root: Path, provider_id: str) -> Path:
    if _PROVIDER_ID.fullmatch(provider_id) is None:
        raise ValueError("provider identity is invalid")
    return heartbeat_dir(state_root) / f"{provider_id}.json"

def _atomic_private(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass

def parse_heartbeat(payload: Mapping[str, Any]) -> ProviderHeartbeat:
    if not isinstance(payload, Mapping):
        raise ValueError("provider heartbeat must be an object")
    allowed = {"schema_version","kind","provider_id","domain","source","authority_boundary","sequence","last_attempt_at","last_success_at","health","errors","boot_id","details"}
    if set(payload) != allowed:
        raise ValueError("provider heartbeat fields are invalid")
    errors = payload.get("errors")
    if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
        raise ValueError("provider heartbeat errors are invalid")
    details = payload.get("details")
    if not isinstance(details, Mapping):
        raise ValueError("provider heartbeat details are invalid")
    try:
        health = ProviderHealth(payload.get("health"))
    except (TypeError, ValueError) as exc:
        raise ValueError("provider heartbeat health is invalid") from exc
    return ProviderHeartbeat(provider_id=payload.get("provider_id"),domain=payload.get("domain"),source=payload.get("source"),authority_boundary=payload.get("authority_boundary"),sequence=payload.get("sequence"),last_attempt_at=payload.get("last_attempt_at"),last_success_at=payload.get("last_success_at"),health=health,errors=tuple(errors),boot_id=payload.get("boot_id"),details=dict(details),schema_version=payload.get("schema_version"),kind=payload.get("kind"))

def load_heartbeat(state_root: Path, provider_id: str) -> ProviderHeartbeat | None:
    path = heartbeat_path(state_root, provider_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("provider heartbeat is not an object")
    return parse_heartbeat(raw)

def record_heartbeat(state_root: Path, *, provider_id: str, domain: str, source: str, authority_boundary: str, success: bool, health: ProviderHealth, errors: tuple[str,...]=(), boot_id: str|None=None, details: Mapping[str,Any]|None=None, now: datetime|None=None) -> ProviderHeartbeat:
    current=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    previous=None
    try:
        previous=load_heartbeat(state_root,provider_id)
    except (OSError,ValueError,json.JSONDecodeError):
        previous=None
    stamp=utc_stamp(current)
    heartbeat=ProviderHeartbeat(provider_id=provider_id,domain=domain,source=source,authority_boundary=authority_boundary,sequence=(previous.sequence+1 if previous else 1),last_attempt_at=stamp,last_success_at=stamp if success else (previous.last_success_at if previous else None),health=health,errors=errors,boot_id=boot_id,details=dict(details or {}))
    _atomic_private(heartbeat_path(state_root,provider_id),heartbeat.as_dict())
    return heartbeat

def _health(value: str) -> ProviderHealth:
    try: return ProviderHealth(value)
    except ValueError as exc: raise SystemExit(f"invalid provider health: {value}") from exc

def main(argv: list[str]|None=None) -> int:
    parser=argparse.ArgumentParser(prog="guardian_provider_state.py")
    sub=parser.add_subparsers(dest="command",required=True)
    record=sub.add_parser("record"); record.add_argument("--state-root",type=Path,required=True); record.add_argument("--provider-id",required=True); record.add_argument("--domain",required=True); record.add_argument("--source",required=True); record.add_argument("--authority-boundary",required=True); record.add_argument("--success",action="store_true"); record.add_argument("--health",default="healthy"); record.add_argument("--error",action="append",default=[]); record.add_argument("--boot-id"); record.add_argument("--details-json",default="{}")
    show=sub.add_parser("show"); show.add_argument("--state-root",type=Path,required=True); show.add_argument("--provider-id",required=True)
    args=parser.parse_args(argv)
    if args.command=="show":
        value=load_heartbeat(args.state_root,args.provider_id)
        if value is None: return 1
        print(json.dumps(value.as_dict(),sort_keys=True,separators=(",",":"))); return 0
    try: details=json.loads(args.details_json)
    except json.JSONDecodeError as exc: raise SystemExit(f"invalid details JSON: {exc}") from exc
    if not isinstance(details,Mapping): raise SystemExit("details JSON must be an object")
    value=record_heartbeat(args.state_root,provider_id=args.provider_id,domain=args.domain,source=args.source,authority_boundary=args.authority_boundary,success=args.success,health=_health(args.health),errors=tuple(args.error),boot_id=args.boot_id,details=details)
    print(json.dumps(value.as_dict(),sort_keys=True,separators=(",",":"))); return 0

if __name__ == "__main__":
    raise SystemExit(main())
