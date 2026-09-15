#!/usr/bin/env python3
"""Authority contract for exact, reversible Guardian containment."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any

from guardian_evidence import parse_timestamp, utc_stamp


class ContainmentPlanState(str, Enum):
    READY = "ready"
    REFUSE = "refuse"


@dataclass(frozen=True, order=True)
class ProcessIdentity:
    pid: int
    start_time_ticks: int
    exe: str

    def __post_init__(self) -> None:
        if self.pid <= 1 or self.start_time_ticks <= 0:
            raise ValueError("containment process identity is incomplete")
        if not self.exe.startswith("/") or "*" in self.exe:
            raise ValueError("containment executable must be an exact absolute path")


@dataclass(frozen=True)
class ContainmentTarget:
    package: str
    version: str
    finding_id: str
    processes: tuple[ProcessIdentity, ...]

    def __post_init__(self) -> None:
        for value in (self.package, self.version, self.finding_id):
            if not value or "*" in value:
                raise ValueError("containment target must use exact identities")
        if not self.processes:
            raise ValueError("containment target requires at least one exact process")
        pids = [item.pid for item in self.processes]
        if len(set(pids)) != len(pids):
            raise ValueError("containment target contains duplicate pids")

    def canonical(self) -> dict[str, Any]:
        return {
            "package": self.package,
            "version": self.version,
            "finding_id": self.finding_id,
            "processes": [asdict(item) for item in sorted(self.processes)],
        }

    @property
    def digest(self) -> str:
        raw = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ContainmentAuthority:
    authority_id: str
    issuer: str
    verified: bool
    issued_at: str
    expires_at: str
    target_digest: str
    evidence_ids: tuple[str, ...]
    reversible: bool = True

    def __post_init__(self) -> None:
        if not self.authority_id or not self.issuer:
            raise ValueError("containment authority identity is incomplete")
        issued = parse_timestamp(self.issued_at)
        expires = parse_timestamp(self.expires_at)
        if issued is None or expires is None or expires <= issued:
            raise ValueError("containment authority window is invalid")
        if len(self.target_digest) != 64:
            raise ValueError("containment authority target digest is invalid")
        if not self.evidence_ids:
            raise ValueError("containment authority requires supporting evidence")


@dataclass(frozen=True)
class ContainmentPlan:
    state: ContainmentPlanState
    authority_id: str | None
    target: ContainmentTarget
    rollback_action: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "authority_id": self.authority_id,
            "target": self.target.canonical(),
            "target_digest": self.target.digest,
            "rollback_action": self.rollback_action,
            "reason": self.reason,
        }


def plan_containment(
    target: ContainmentTarget,
    authority: ContainmentAuthority,
    *,
    now: str | None = None,
) -> ContainmentPlan:
    observed = parse_timestamp(now or utc_stamp(datetime.now(timezone.utc)))
    issued = parse_timestamp(authority.issued_at)
    expires = parse_timestamp(authority.expires_at)
    assert observed is not None and issued is not None and expires is not None

    if not authority.verified:
        return ContainmentPlan(ContainmentPlanState.REFUSE, authority.authority_id, target, "none", "containment authority is not independently verified")
    if not authority.reversible:
        return ContainmentPlan(ContainmentPlanState.REFUSE, authority.authority_id, target, "none", "irreversible containment authority is forbidden")
    if authority.target_digest != target.digest:
        return ContainmentPlan(ContainmentPlanState.REFUSE, authority.authority_id, target, "none", "authority does not bind this exact target")
    if observed < issued or observed > expires:
        return ContainmentPlan(ContainmentPlanState.REFUSE, authority.authority_id, target, "none", "containment authority is outside its bounded time window")
    return ContainmentPlan(
        ContainmentPlanState.READY,
        authority.authority_id,
        target,
        "resume-exact-session",
        "verified authority binds the exact reversible process target",
    )
