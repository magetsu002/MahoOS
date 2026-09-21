#!/usr/bin/env python3
"""Deterministic pure policy for protected mutation attempts."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet

from guardian_admission import EffectKind
from maho_prevention_scope import ProtectedDomain, ScopeMatch


class MutationOperation(str, Enum):
    WRITE = "WRITE"
    CREATE = "CREATE"
    UNLINK = "UNLINK"
    RENAME = "RENAME"
    LINK = "LINK"
    SYMLINK = "SYMLINK"
    SETATTR = "SETATTR"
    MOUNT = "MOUNT"
    REMOUNT = "REMOUNT"
    DEVICE_WRITE = "DEVICE_WRITE"
    SIGNAL = "SIGNAL"


class PreventionOutcome(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_AUTHORITY = "REQUIRE_AUTHORITY"
    BREAK_GLASS_REQUIRED = "BREAK_GLASS_REQUIRED"


@dataclass(frozen=True)
class SubjectIdentity:
    pid: int
    start_time_ticks: int
    executable_path: str
    executable_sha256: str
    executable_device: int
    executable_inode: int
    uid: int


@dataclass(frozen=True)
class AuthorityView:
    state: str = "ABSENT"
    transaction_id: str | None = None
    subject: SubjectIdentity | None = None
    effects: FrozenSet[EffectKind] = frozenset()
    operations: FrozenSet[MutationOperation] = frozenset()
    target_prefixes: tuple[str, ...] = ()
    expires_at_ns: int = 0
    source_revision: str | None = None
    generation_id: str | None = None
    break_glass: bool = False


@dataclass(frozen=True)
class MutationRequest:
    subject: SubjectIdentity
    target: ScopeMatch
    operation: MutationOperation
    transaction_id: str | None
    expected_scope: tuple[str, ...]
    reversible: bool
    now_ns: int
    source_revision: str | None = None
    generation_id: str | None = None
    guardian_healthy: bool = True
    provider_healthy: bool = True


@dataclass(frozen=True)
class PreventionDecision:
    outcome: PreventionOutcome
    reason: str
    protected: bool
    host_mutation_performed: bool = False


def _within(target: str, prefixes: tuple[str, ...]) -> bool:
    return any(
        target == prefix or (prefix != "/" and target.startswith(prefix.rstrip("/") + "/"))
        for prefix in prefixes
    )


def _authority_matches(request: MutationRequest, authority: AuthorityView) -> tuple[bool, str]:
    if authority.state != "CURRENT":
        return False, "authority_" + authority.state.lower().replace("_", "-")
    if request.now_ns >= authority.expires_at_ns:
        return False, "authority_expired"
    if authority.subject != request.subject:
        return False, "subject_identity_mismatch"
    if not request.transaction_id or authority.transaction_id != request.transaction_id:
        return False, "transaction_identity_mismatch"
    if request.target.effect not in authority.effects or request.operation not in authority.operations:
        return False, "effect_not_authorized"
    if not _within(request.target.target, authority.target_prefixes):
        return False, "target_scope_exceeded"
    if request.source_revision != authority.source_revision:
        return False, "source_revision_mismatch"
    if request.generation_id != authority.generation_id:
        return False, "generation_identity_mismatch"
    return True, "exact_authority"


def decide_mutation(request: MutationRequest, authority: AuthorityView = AuthorityView()) -> PreventionDecision:
    if not request.target.protected:
        return PreventionDecision(PreventionOutcome.ALLOW, "unprotected_scope", False)
    if not request.guardian_healthy or not request.provider_healthy:
        return PreventionDecision(PreventionOutcome.DENY, "protection_authority_health_uncertain", True)
    matched, reason = _authority_matches(request, authority)
    if matched:
        return PreventionDecision(PreventionOutcome.ALLOW, "exact_break_glass_authority" if authority.break_glass else reason, True)
    if authority.state != "ABSENT":
        return PreventionDecision(PreventionOutcome.DENY, reason, True)
    catastrophic = (
        not request.reversible
        and request.target.domain in {ProtectedDomain.ROOT, ProtectedDomain.BOOT, ProtectedDomain.RECOVERY}
        and request.operation in {
            MutationOperation.UNLINK, MutationOperation.RENAME,
            MutationOperation.MOUNT, MutationOperation.REMOUNT,
            MutationOperation.DEVICE_WRITE,
        }
    )
    if catastrophic:
        return PreventionDecision(PreventionOutcome.BREAK_GLASS_REQUIRED, "catastrophic_protected_mutation", True)
    return PreventionDecision(PreventionOutcome.REQUIRE_AUTHORITY, "exact_mutation_authority_required", True)
