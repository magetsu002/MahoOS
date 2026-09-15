#!/usr/bin/env python3
"""Authorized-change correlation for Guardian.

Maintenance is not a blanket suppression bit. A change is expected only when a
verified bounded authority predicts that exact kind/subject during its active
window. Ambiguity and unrelated drift remain visible to Guardian.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable

from guardian_evidence import parse_timestamp, utc_stamp

class OperationKind(str, Enum):
    MAHO_UPDATE = "maho-update"
    NATIVE_ADMISSION = "native-admission"
    PACKAGE_TRANSACTION = "package-transaction"
    RUNTIME_DEPLOYMENT = "maho-runtime-deployment"
    MAHO_SETUP = "maho-setup"
    RECOVERY = "guardian-recovery"
    BOOT_GENERATION = "boot-generation-construction"
    SECURE_BOOT = "secure-boot-authority"

class OperationState(str, Enum):
    ACTIVE = "active"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"

class CorrelationStatus(str, Enum):
    AUTHORIZED_EXPECTED = "authorized-expected"
    UNRELATED = "unrelated"
    OUTSIDE_WINDOW = "outside-window"
    UNVERIFIED_AUTHORITY = "unverified-authority"
    AMBIGUOUS = "ambiguous"
    NO_AUTHORITY = "no-authority"

@dataclass(frozen=True)
class ChangeExpectation:
    kind: str
    subject: str
    def __post_init__(self) -> None:
        if not self.kind or not self.subject:
            raise ValueError("change expectation requires kind and subject")
        if "*" in self.subject and not self.subject.endswith("/*"):
            raise ValueError("only bounded prefix subject patterns are supported")
        if self.subject.count("*") > 1:
            raise ValueError("change expectation subject pattern is too broad")
    def matches(self, *, kind: str, subject: str) -> bool:
        if kind != self.kind:
            return False
        if self.subject.endswith("/*"):
            prefix = self.subject[:-2].rstrip("/")
            return subject == prefix or subject.startswith(prefix + "/")
        return subject == self.subject

@dataclass(frozen=True)
class AuthorizedOperation:
    operation_id: str
    kind: OperationKind
    state: OperationState
    authority: str
    authority_verified: bool
    started_at: str
    expires_at: str
    expected_changes: tuple[ChangeExpectation, ...]
    source: str
    transaction_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    def __post_init__(self) -> None:
        if not self.operation_id or not self.authority or not self.source:
            raise ValueError("authorized operation identity/provenance is incomplete")
        start = parse_timestamp(self.started_at)
        end = parse_timestamp(self.expires_at)
        if start is None or end is None or end <= start:
            raise ValueError("authorized operation time window is invalid")
        if not self.expected_changes:
            raise ValueError("authorized operation must declare expected changes")
    def active_at(self, observed_at: str) -> bool:
        if self.state not in {OperationState.ACTIVE, OperationState.VERIFYING}:
            return False
        observed = parse_timestamp(observed_at); start = parse_timestamp(self.started_at); end = parse_timestamp(self.expires_at)
        assert observed is not None and start is not None and end is not None
        return start <= observed <= end
    def predicts(self, change: "ChangeObservation") -> bool:
        return any(expected.matches(kind=change.kind, subject=change.subject) for expected in self.expected_changes)
    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        payload["state"] = self.state.value
        payload["expected_changes"] = [asdict(item) for item in self.expected_changes]
        payload["evidence_ids"] = list(self.evidence_ids)
        return payload

@dataclass(frozen=True)
class ChangeObservation:
    kind: str
    subject: str
    observed_at: str
    source: str
    def __post_init__(self) -> None:
        if not self.kind or not self.subject or not self.source:
            raise ValueError("change observation is incomplete")
        if parse_timestamp(self.observed_at) is None:
            raise ValueError("change observation timestamp is required")

@dataclass(frozen=True)
class IntentCorrelation:
    status: CorrelationStatus
    operation_ids: tuple[str, ...]
    authority: str | None
    suppress_escalation: bool
    reason: str
    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["operation_ids"] = list(self.operation_ids)
        return payload

def correlate_change(change: ChangeObservation, operations: Iterable[AuthorizedOperation]) -> IntentCorrelation:
    candidates = tuple(op for op in operations if op.predicts(change))
    if not candidates:
        return IntentCorrelation(CorrelationStatus.NO_AUTHORITY, (), None, False, "no authorized operation predicts this change")
    active = tuple(op for op in candidates if op.active_at(change.observed_at))
    if not active:
        return IntentCorrelation(CorrelationStatus.OUTSIDE_WINDOW, tuple(sorted(op.operation_id for op in candidates)), None, False, "a declared operation predicts the change, but not at this observation time")
    verified = tuple(op for op in active if op.authority_verified)
    if not verified:
        return IntentCorrelation(CorrelationStatus.UNVERIFIED_AUTHORITY, tuple(sorted(op.operation_id for op in active)), None, False, "matching operations exist, but none has independently verified authority")
    authorities = {op.authority for op in verified}; identities = {op.operation_id for op in verified}
    if len(authorities) != 1 or len(identities) != 1:
        return IntentCorrelation(CorrelationStatus.AMBIGUOUS, tuple(sorted(identities)), None, False, "multiple verified authorities predict the same change; Guardian will not suppress it")
    operation = verified[0]
    return IntentCorrelation(CorrelationStatus.AUTHORIZED_EXPECTED, (operation.operation_id,), operation.authority, True, "exact verified authority predicted this change inside its bounded operation window")

def now_observation(kind: str, subject: str, source: str) -> ChangeObservation:
    return ChangeObservation(kind=kind, subject=subject, observed_at=utc_stamp(datetime.now(timezone.utc)), source=source)
