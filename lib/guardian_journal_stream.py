#!/usr/bin/env python3
"""Durable continuity state for Guardian's systemd-user journal stream."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from guardian_evidence import parse_timestamp, utc_stamp

SCHEMA_VERSION = 1

class StreamContinuity(str, Enum):
    CONTINUOUS = "continuous"
    BOOTSTRAP = "bootstrap"
    LOST = "lost"
    FAILED = "failed"

class CursorProbe(str, Enum):
    VALID = "valid"
    MISSING = "missing"
    INVALID = "invalid"
    SOURCE_FAILED = "source-failed"

@dataclass(frozen=True)
class JournalStreamState:
    continuity: StreamContinuity
    reason: str
    restart_count: int
    dropped_events: int
    last_cursor: str | None
    previous_cursor: str | None
    last_started_at: str
    continuity_verified_at: str | None
    last_event_at: str | None
    boot_id: str
    schema_version: int = SCHEMA_VERSION
    kind: str = "guardian-journal-stream-health"
    provider_id: str = "guardian.service-events"
    source: str = "systemd-user-journal"
    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or self.kind != "guardian-journal-stream-health":
            raise ValueError("journal stream schema is invalid")
        if self.provider_id != "guardian.service-events" or self.source != "systemd-user-journal":
            raise ValueError("journal stream identity is invalid")
        if self.restart_count < 0 or self.dropped_events < 0 or not self.reason or not self.boot_id:
            raise ValueError("journal stream state is incomplete")
        parse_timestamp(self.last_started_at)
        for value in (self.continuity_verified_at,self.last_event_at):
            if value is not None: parse_timestamp(value)
    def as_dict(self) -> dict[str, Any]:
        payload=asdict(self); payload["continuity"]=self.continuity.value; return payload

def stream_path(state_root: Path) -> Path:
    return state_root / "guardian" / "service-events" / "stream.json"

def _atomic_private(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True); os.chmod(path.parent,0o700)
    data=(json.dumps(payload,indent=2,sort_keys=True)+"\n").encode()
    fd,tmp_name=tempfile.mkstemp(prefix=f".{path.name}.",dir=str(path.parent)); tmp=Path(tmp_name)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"wb") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.replace(tmp,path)
    finally:
        try: tmp.unlink()
        except FileNotFoundError: pass

def parse_stream(payload: Mapping[str, Any]) -> JournalStreamState:
    allowed={"schema_version","kind","provider_id","source","continuity","reason","restart_count","dropped_events","last_cursor","previous_cursor","last_started_at","continuity_verified_at","last_event_at","boot_id"}
    if not isinstance(payload,Mapping) or set(payload)!=allowed:
        raise ValueError("journal stream fields are invalid")
    try: continuity=StreamContinuity(payload.get("continuity"))
    except (TypeError,ValueError) as exc: raise ValueError("journal continuity is invalid") from exc
    return JournalStreamState(continuity=continuity,reason=payload.get("reason"),restart_count=payload.get("restart_count"),dropped_events=payload.get("dropped_events"),last_cursor=payload.get("last_cursor"),previous_cursor=payload.get("previous_cursor"),last_started_at=payload.get("last_started_at"),continuity_verified_at=payload.get("continuity_verified_at"),last_event_at=payload.get("last_event_at"),boot_id=payload.get("boot_id"),schema_version=payload.get("schema_version"),kind=payload.get("kind"),provider_id=payload.get("provider_id"),source=payload.get("source"))

def load_stream(state_root: Path) -> JournalStreamState | None:
    try: raw=json.loads(stream_path(state_root).read_text(encoding="utf-8"))
    except FileNotFoundError: return None
    if not isinstance(raw,Mapping): raise ValueError("journal stream state is not an object")
    return parse_stream(raw)

def begin_stream(previous: JournalStreamState|None, *, cursor: str|None, probe: CursorProbe, boot_id: str, now: datetime) -> JournalStreamState:
    stamp=utc_stamp(now.astimezone(timezone.utc)); restart_count=(previous.restart_count+1 if previous else 0); dropped=previous.dropped_events if previous else 0; prior=previous.last_cursor if previous else None
    if probe is CursorProbe.VALID and cursor:
        continuity=StreamContinuity.CONTINUOUS; reason="cursor_resumed"; verified=stamp
    elif probe is CursorProbe.MISSING and previous is None:
        continuity=StreamContinuity.BOOTSTRAP; reason="initial_cursor_unavailable"; verified=None
    elif probe is CursorProbe.MISSING:
        continuity=StreamContinuity.LOST; reason="cursor_missing_after_previous_stream"; verified=None
    elif probe is CursorProbe.INVALID:
        continuity=StreamContinuity.LOST; reason="cursor_invalid_or_expired"; verified=None
    else:
        continuity=StreamContinuity.FAILED; reason="event_source_failed"; verified=None
    return JournalStreamState(continuity,reason,restart_count,dropped,cursor or None,prior,stamp,verified,previous.last_event_at if previous else None,boot_id)

def persist_stream(state_root: Path, state: JournalStreamState) -> JournalStreamState:
    _atomic_private(stream_path(state_root),state.as_dict()); return state

def mark_event(state: JournalStreamState, *, cursor: str|None, now: datetime) -> JournalStreamState:
    stamp=utc_stamp(now.astimezone(timezone.utc))
    if not cursor:
        return replace(state,continuity=StreamContinuity.LOST,reason="event_cursor_missing",dropped_events=state.dropped_events+1,last_event_at=stamp)
    return replace(state,last_cursor=cursor,last_event_at=stamp)

def mark_dropped(state: JournalStreamState, *, count: int, reason: str) -> JournalStreamState:
    if count <= 0: return state
    return replace(state,continuity=StreamContinuity.LOST,reason=reason,dropped_events=state.dropped_events+count)

def mark_failed(state: JournalStreamState, *, reason: str) -> JournalStreamState:
    return replace(state,continuity=StreamContinuity.FAILED,reason=reason)
