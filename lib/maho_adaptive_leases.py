#!/usr/bin/env python3
"""Temporary shadow leases and bounded reversion semantics for adaptive policy."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping, Sequence

from maho_adaptive_proposal import AdaptationProposal, Effect
from maho_adaptive_resolver import ResolvedPosture

SCHEMA_VERSION = 1
LEASE_STATES = {
    "PROPOSED",
    "ACTIVE_SHADOW",
    "VERIFIED_SHADOW",
    "EXPIRED",
    # Future-capable states. A1-A14 never enters them.
    "ACTIVE_EXECUTABLE",
    "VERIFIED_EXECUTABLE",
}


@dataclass(frozen=True)
class AntiFlap:
    entry_threshold: str
    exit_threshold: str
    minimum_dwell_seconds: int
    minimum_residency_seconds: int
    cooldown_seconds: int


@dataclass(frozen=True)
class AdaptationLease:
    schema_version: int
    lease_id: str
    effect: Effect
    source_policy: str
    source_proposal_id: str
    entered_at: str
    previous_state: str | None
    effective_state: str
    anti_flap: AntiFlap
    expiry_kind: str
    expiry_value: str | int | None
    verification_status: str
    mode: str
    state: str
    superseded_by: str | None
    released_at: str | None
    release_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LeaseBook:
    schema_version: int = SCHEMA_VERSION
    leases: tuple[AdaptationLease, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "leases": [lease.as_dict() for lease in self.leases]}


def _stamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("lease timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _elapsed(start: str, now: datetime) -> float:
    # Backward clock jumps must not accidentally satisfy dwell/cooldown gates.
    return max(0.0, (now.astimezone(timezone.utc) - _parse(start)).total_seconds())


def _lease_id(effect: Effect, proposal: AdaptationProposal, entered_at: str) -> str:
    raw = json.dumps({
        "effect": asdict(effect),
        "proposal": proposal.proposal_id,
        "policy": proposal.source_policy,
        "entered_at": entered_at,
    }, sort_keys=True, separators=(",", ":")).encode()
    return "lease-" + hashlib.sha256(raw).hexdigest()[:20]


def _anti_flap(proposal: AdaptationProposal) -> AntiFlap:
    expiry = proposal.expiry_condition
    return AntiFlap(
        entry_threshold=f"policy:{proposal.source_policy}:entry",
        exit_threshold=f"expiry:{expiry.kind}:{expiry.value if expiry.value is not None else 'condition'}",
        minimum_dwell_seconds=proposal.minimum_dwell_seconds,
        minimum_residency_seconds=proposal.minimum_residency_seconds,
        cooldown_seconds=proposal.cooldown_seconds,
    )


def _create(effect: Effect, proposal: AdaptationProposal, previous: str | None, now: datetime) -> AdaptationLease:
    entered = _stamp(now)
    anti = _anti_flap(proposal)
    initial = "ACTIVE_SHADOW" if anti.minimum_dwell_seconds == 0 else "PROPOSED"
    return AdaptationLease(
        SCHEMA_VERSION,
        _lease_id(effect, proposal, entered),
        effect,
        proposal.source_policy,
        proposal.proposal_id,
        entered,
        previous,
        effect.value,
        anti,
        proposal.expiry_condition.kind,
        proposal.expiry_condition.value,
        "pending",
        "shadow",
        initial,
        None,
        None,
        None,
    )


def validate_lease(lease: AdaptationLease) -> None:
    if lease.schema_version != SCHEMA_VERSION:
        raise ValueError("unsupported lease schema")
    if not lease.lease_id.startswith("lease-") or len(lease.lease_id) != 26:
        raise ValueError("invalid lease identity")
    if lease.state not in LEASE_STATES:
        raise ValueError("invalid lease state")
    if lease.mode not in {"shadow", "executable-disabled"}:
        raise ValueError("invalid lease mode")
    if lease.state in {"ACTIVE_EXECUTABLE", "VERIFIED_EXECUTABLE"}:
        raise ValueError("executable adaptive leases are disabled in A1-A14")
    if lease.mode != "shadow":
        raise ValueError("only shadow leases are enabled in A1-A14")
    for value in (
        lease.anti_flap.minimum_dwell_seconds,
        lease.anti_flap.minimum_residency_seconds,
        lease.anti_flap.cooldown_seconds,
    ):
        if isinstance(value, bool) or value < 0:
            raise ValueError("lease anti-flap durations must be non-negative")
    if lease.state == "EXPIRED" and not lease.released_at:
        raise ValueError("expired lease requires release timestamp")


def validate_book(book: LeaseBook) -> LeaseBook:
    if book.schema_version != SCHEMA_VERSION:
        raise ValueError("unsupported lease book schema")
    ids: set[str] = set()
    for lease in book.leases:
        validate_lease(lease)
        if lease.lease_id in ids:
            raise ValueError("duplicate lease identity")
        ids.add(lease.lease_id)
    return book


def _active(lease: AdaptationLease) -> bool:
    return lease.state in {"PROPOSED", "ACTIVE_SHADOW", "VERIFIED_SHADOW"}


def _equivalent(lease: AdaptationLease, effect: Effect, proposal: AdaptationProposal) -> bool:
    return _active(lease) and lease.effect == effect and lease.source_policy == proposal.source_policy


def _cooldown_blocked(book: LeaseBook, effect: Effect, proposal: AdaptationProposal, now: datetime) -> bool:
    expired = [lease for lease in book.leases if lease.state == "EXPIRED" and lease.effect == effect and lease.source_policy == proposal.source_policy]
    if not expired:
        return False
    last = sorted(expired, key=lambda lease: lease.released_at or "")[-1]
    if not last.released_at:
        return False
    return _elapsed(last.released_at, now) < last.anti_flap.cooldown_seconds


def _winner_for(field, proposals: Mapping[str, AdaptationProposal]) -> AdaptationProposal | None:
    for proposal_id in field.winning_proposal_ids:
        proposal = proposals.get(proposal_id)
        if proposal is not None:
            return proposal
    return None


def reconcile_leases(
    book: LeaseBook,
    resolved: ResolvedPosture,
    proposals: Sequence[AdaptationProposal],
    *,
    condition_state: Mapping[str, bool | None] | None = None,
    previous_posture: Mapping[str, str] | None = None,
    now: datetime,
) -> LeaseBook:
    """Reconcile shadow leases without restoring remembered values directly.

    ``condition_state`` is proposal-id -> True/False/None. False means the
    policy's exit condition is confirmed. None means uncertainty and preserves
    the lease. Reversion is expressed only by expiring a lease; the caller must
    run the resolver again for the remaining policies.
    """
    validate_book(book)
    conditions = condition_state or {}
    proposal_map = {proposal.proposal_id: proposal for proposal in proposals}
    leases = list(book.leases)

    # First advance or release existing leases based on confirmed condition state.
    for index, lease in enumerate(leases):
        if not _active(lease):
            continue
        condition = conditions.get(lease.source_proposal_id)
        if lease.state == "PROPOSED" and condition is not False and _elapsed(lease.entered_at, now) >= lease.anti_flap.minimum_dwell_seconds:
            leases[index] = replace(lease, state="ACTIVE_SHADOW")
            lease = leases[index]
        if condition is False:
            residency = _elapsed(lease.entered_at, now)
            if lease.state == "PROPOSED" or residency >= lease.anti_flap.minimum_residency_seconds:
                leases[index] = replace(
                    lease,
                    state="EXPIRED",
                    released_at=_stamp(now),
                    release_reason="confirmed-expiry-condition",
                )

    desired_fields = {field.effect: field for field in resolved.fields if field.status == "resolved" and field.value is not None}

    # Supersede only when the resolver has a different coherent owner/value.
    for key, field in desired_fields.items():
        winner = _winner_for(field, proposal_map)
        if winner is None:
            continue
        effect = Effect(key, str(field.value))
        if any(_equivalent(lease, effect, winner) for lease in leases):
            continue
        if _cooldown_blocked(LeaseBook(SCHEMA_VERSION, tuple(leases)), effect, winner, now):
            continue

        prior = next((lease for lease in reversed(leases) if _active(lease) and lease.effect.key == key), None)
        previous = prior.effective_state if prior else (previous_posture or {}).get(key)
        new_lease = _create(effect, winner, previous, now)
        leases.append(new_lease)
        if prior is not None:
            prior_index = leases.index(prior)
            leases[prior_index] = replace(
                prior,
                state="EXPIRED",
                superseded_by=new_lease.lease_id,
                released_at=_stamp(now),
                release_reason="superseded-by-resolver",
            )

    return validate_book(LeaseBook(SCHEMA_VERSION, tuple(leases)))


def verify_shadow(book: LeaseBook, lease_id: str) -> LeaseBook:
    validate_book(book)
    leases = list(book.leases)
    for index, lease in enumerate(leases):
        if lease.lease_id != lease_id:
            continue
        if lease.state == "VERIFIED_SHADOW":
            return book
        if lease.state != "ACTIVE_SHADOW":
            raise ValueError("only an active shadow lease can be verified")
        leases[index] = replace(lease, state="VERIFIED_SHADOW", verification_status="verified-shadow")
        return validate_book(LeaseBook(SCHEMA_VERSION, tuple(leases)))
    raise ValueError("lease not found")


def active_posture(book: LeaseBook) -> dict[str, str]:
    """Return currently leased effects. No previous-state restoration occurs."""
    validate_book(book)
    result: dict[str, str] = {}
    for lease in book.leases:
        if lease.state in {"ACTIVE_SHADOW", "VERIFIED_SHADOW"}:
            result[lease.effect.key] = lease.effective_state
    return result


def book_from_dict(payload: Mapping[str, Any]) -> LeaseBook:
    if set(payload) != {"schema_version", "leases"} or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid lease book")
    raw_leases = payload.get("leases")
    if not isinstance(raw_leases, list):
        raise ValueError("lease book leases must be a list")
    leases: list[AdaptationLease] = []
    for raw in raw_leases:
        if not isinstance(raw, Mapping):
            raise ValueError("lease must be an object")
        expected = {
            "schema_version", "lease_id", "effect", "source_policy", "source_proposal_id",
            "entered_at", "previous_state", "effective_state", "anti_flap", "expiry_kind",
            "expiry_value", "verification_status", "mode", "state", "superseded_by",
            "released_at", "release_reason",
        }
        if set(raw) != expected:
            raise ValueError("unknown or missing lease fields")
        effect_raw = raw["effect"]; anti_raw = raw["anti_flap"]
        if not isinstance(effect_raw, Mapping) or set(effect_raw) != {"key", "value"}:
            raise ValueError("invalid lease effect")
        if not isinstance(anti_raw, Mapping) or set(anti_raw) != {
            "entry_threshold", "exit_threshold", "minimum_dwell_seconds",
            "minimum_residency_seconds", "cooldown_seconds",
        }:
            raise ValueError("invalid lease anti-flap state")
        leases.append(AdaptationLease(
            schema_version=raw["schema_version"], lease_id=raw["lease_id"],
            effect=Effect(str(effect_raw["key"]), str(effect_raw["value"])),
            source_policy=raw["source_policy"], source_proposal_id=raw["source_proposal_id"],
            entered_at=raw["entered_at"], previous_state=raw["previous_state"],
            effective_state=raw["effective_state"], anti_flap=AntiFlap(**anti_raw),
            expiry_kind=raw["expiry_kind"], expiry_value=raw["expiry_value"],
            verification_status=raw["verification_status"], mode=raw["mode"], state=raw["state"],
            superseded_by=raw["superseded_by"], released_at=raw["released_at"],
            release_reason=raw["release_reason"],
        ))
    return validate_book(LeaseBook(SCHEMA_VERSION, tuple(leases)))
