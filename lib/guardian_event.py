#!/usr/bin/env python3
"""Normalized, sensor-independent Guardian system events.

GuardianEvent is observation data only. Events do not grant mutation authority,
establish trust by themselves, or turn temporal proximity into causality.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping
from uuid import UUID

from guardian_evidence import parse_timestamp

SCHEMA_VERSION = 1

_PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9._:-]{1,127}")
_EVENT_ID = re.compile(r"gev-[0-9a-f]{32}")
_PROCESS_ID = re.compile(r"gproc-[0-9a-f]{32}")
_SOCKET_ID = re.compile(r"gsock-[0-9a-f]{32}")


class GuardianEventKind(str, Enum):
    PROCESS_EXEC = "process.exec"
    PROCESS_EXIT = "process.exit"
    FILE_WRITE_ACCESS = "file.write-access"
    NETWORK_CONNECT_ATTEMPT = "network.connect-attempt"
    OBSERVATION_GAP = "sensor.observation-gap"
    SENSOR_RESET = "sensor.counter-reset"


@dataclass(frozen=True)
class GuardianProcessRef:
    process_id: str
    source_identity: str
    pid: int
    uid: int | None
    binary: str | None
    started_at: str | None
    parent_process_id: str | None

    def __post_init__(self) -> None:
        if _PROCESS_ID.fullmatch(self.process_id) is None:
            raise ValueError("Guardian process identity is invalid")
        if not self.source_identity:
            raise ValueError("source process identity is required")
        if self.pid < 0:
            raise ValueError("process PID is invalid")
        if self.uid is not None and self.uid < 0:
            raise ValueError("process UID is invalid")
        if self.binary is not None and not self.binary:
            raise ValueError("process binary must be non-empty when present")
        if self.started_at is not None:
            parse_timestamp(self.started_at)
        if self.parent_process_id is not None and _PROCESS_ID.fullmatch(self.parent_process_id) is None:
            raise ValueError("parent process identity is invalid")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GuardianEvent:
    event_id: str
    event_type: GuardianEventKind
    observed_at: str
    boot_id: str
    provider_id: str
    source: str
    source_event_type: str
    source_record_digest: str
    authority_boundary: str
    process: GuardianProcessRef | None
    target_kind: str | None
    target: Mapping[str, Any]
    schema_version: int = SCHEMA_VERSION
    kind: str = "guardian-event"

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or self.kind != "guardian-event":
            raise ValueError("Guardian event schema is invalid")
        if _EVENT_ID.fullmatch(self.event_id) is None:
            raise ValueError("Guardian event identity is invalid")
        parse_timestamp(self.observed_at)
        try:
            UUID(self.boot_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Guardian event boot identity is invalid") from exc
        if _PROVIDER_ID.fullmatch(self.provider_id) is None:
            raise ValueError("Guardian event provider identity is invalid")
        if not self.source or not self.source_event_type:
            raise ValueError("Guardian event provenance is incomplete")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_record_digest):
            raise ValueError("source record digest is invalid")
        if self.authority_boundary != "observation-only":
            raise ValueError("Guardian sensor events must remain observation-only")
        if (self.target_kind is None) != (not self.target):
            raise ValueError("Guardian event target kind/payload mismatch")

    @property
    def evidence_id(self) -> str:
        return self.event_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "observed_at": self.observed_at,
            "boot_id": self.boot_id,
            "provider_id": self.provider_id,
            "source": self.source,
            "source_event_type": self.source_event_type,
            "source_record_digest": self.source_record_digest,
            "authority_boundary": self.authority_boundary,
            "process": self.process.as_dict() if self.process else None,
            "target_kind": self.target_kind,
            "target": dict(self.target),
        }


def canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def process_identity(*, boot_id: str, source_identity: str) -> str:
    UUID(boot_id)
    if not source_identity:
        raise ValueError("source process identity is required")
    material = f"{boot_id}\0{source_identity}".encode("utf-8")
    return "gproc-" + hashlib.sha256(material).hexdigest()[:32]


def socket_identity(*, boot_id: str, source_identity: str) -> str:
    UUID(boot_id)
    if not source_identity:
        raise ValueError("source socket identity is required")
    material = f"{boot_id}\0{source_identity}".encode("utf-8")
    return "gsock-" + hashlib.sha256(material).hexdigest()[:32]


def event_identity(*, provider_id: str, boot_id: str, source_record_digest: str,
                   event_type: GuardianEventKind) -> str:
    if _PROVIDER_ID.fullmatch(provider_id) is None:
        raise ValueError("provider identity is invalid")
    UUID(boot_id)
    if not re.fullmatch(r"[0-9a-f]{64}", source_record_digest):
        raise ValueError("source record digest is invalid")
    material = "\0".join((provider_id, boot_id, source_record_digest, event_type.value)).encode("utf-8")
    return "gev-" + hashlib.sha256(material).hexdigest()[:32]
