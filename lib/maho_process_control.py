#!/usr/bin/env python3
"""Exact, short-lived authorities for signals to protected Maho processes."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import re
from typing import Any, Iterable, Mapping

from guardian_admission import EffectKind
from maho_mutation_authority import PARENT_KINDS, SubjectIdentity
from maho_trust_identity import ArtifactID, canonical_bytes


SCHEMA_VERSION = 1
MAX_LIFETIME_NS = 5 * 60 * 1_000_000_000
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SHA40 = re.compile(r"[0-9a-f]{40}")


class ProcessControlAuthorityError(ValueError):
    pass


def _identity_dict(identity: SubjectIdentity) -> dict[str, Any]:
    return {
        "pid": identity.pid,
        "start_time_ticks": identity.start_time_ticks,
        "executable_path": identity.executable_path,
        "executable_sha256": identity.executable_sha256,
        "executable_device": identity.executable_device,
        "executable_inode": identity.executable_inode,
        "uid": identity.uid,
    }


def _identity_from(value: Any) -> SubjectIdentity:
    expected = {
        "pid", "start_time_ticks", "executable_path", "executable_sha256",
        "executable_device", "executable_inode", "uid",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ProcessControlAuthorityError("process_identity_fields_invalid")
    try:
        identity = SubjectIdentity(**{key: value[key] for key in expected})
    except TypeError as exc:
        raise ProcessControlAuthorityError("process_identity_invalid") from exc
    if (
        not isinstance(identity.pid, int) or identity.pid <= 0
        or not isinstance(identity.start_time_ticks, int) or identity.start_time_ticks <= 0
        or not isinstance(identity.executable_device, int) or identity.executable_device < 0
        or not isinstance(identity.executable_inode, int) or identity.executable_inode <= 0
        or not isinstance(identity.uid, int) or identity.uid < 0
        or _SHA256.fullmatch(str(identity.executable_sha256)) is None
        or not str(identity.executable_path).startswith("/")
    ):
        raise ProcessControlAuthorityError("process_identity_invalid")
    return identity


@dataclass(frozen=True)
class ProcessControlAuthority:
    authority_id: ArtifactID
    transaction_id: str
    parent_authority_id: str
    parent_kind: str
    subject: SubjectIdentity
    target: SubjectIdentity
    effect: EffectKind
    signals: tuple[int, ...]
    issued_at_ns: int
    expires_at_ns: int
    boot_id: str
    source_revision: str | None
    generation_id: str | None
    mac_sha256: str

    def unsigned_material(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "maho-process-control-authority",
            "transaction_id": self.transaction_id,
            "parent_authority_id": self.parent_authority_id,
            "parent_kind": self.parent_kind,
            "subject": _identity_dict(self.subject),
            "target": _identity_dict(self.target),
            "effect": self.effect.value,
            "signals": list(self.signals),
            "issued_at_ns": self.issued_at_ns,
            "expires_at_ns": self.expires_at_ns,
            "boot_id": self.boot_id,
            "source_revision": self.source_revision,
            "generation_id": self.generation_id,
        }

    def as_dict(self) -> dict[str, Any]:
        return self.unsigned_material() | {
            "mac_sha256": self.mac_sha256,
            "authority_id": str(self.authority_id),
        }


def _validated_signals(signals: Iterable[int]) -> tuple[int, ...]:
    try:
        values = tuple(sorted({int(signal) for signal in signals}))
    except (TypeError, ValueError) as exc:
        raise ProcessControlAuthorityError("signals_invalid") from exc
    if not values or any(signal < 1 or signal > 64 for signal in values):
        raise ProcessControlAuthorityError("signals_invalid")
    return values


def issue_process_control_authority(
    *, secret: bytes, transaction_id: str, parent_authority_id: str,
    parent_kind: str, subject: SubjectIdentity, target: SubjectIdentity,
    effect: EffectKind, signals: Iterable[int], issued_at_ns: int,
    expires_at_ns: int, boot_id: str, source_revision: str | None,
    generation_id: str | None,
) -> ProcessControlAuthority:
    if len(secret) < 32 or parent_kind not in PARENT_KINDS:
        raise ProcessControlAuthorityError("authority_parent_or_secret_invalid")
    if not transaction_id or not parent_authority_id or not boot_id:
        raise ProcessControlAuthorityError("authority_context_invalid")
    if (
        issued_at_ns < 0 or expires_at_ns <= issued_at_ns
        or expires_at_ns - issued_at_ns > MAX_LIFETIME_NS
    ):
        raise ProcessControlAuthorityError("authority_lifetime_invalid")
    if source_revision is not None and _SHA40.fullmatch(source_revision) is None:
        raise ProcessControlAuthorityError("authority_source_revision_invalid")
    subject = _identity_from(_identity_dict(subject))
    target = _identity_from(_identity_dict(target))
    signal_values = _validated_signals(signals)
    provisional = ProcessControlAuthority(
        ArtifactID.from_content(b"placeholder"), transaction_id,
        parent_authority_id, parent_kind, subject, target, effect,
        signal_values, issued_at_ns, expires_at_ns, boot_id,
        source_revision, generation_id, "0" * 64,
    )
    mac = hmac.new(
        secret, canonical_bytes(provisional.unsigned_material()), hashlib.sha256,
    ).hexdigest()
    signed = provisional.unsigned_material() | {"mac_sha256": mac}
    return ProcessControlAuthority(
        ArtifactID.from_content(canonical_bytes(signed)), transaction_id,
        parent_authority_id, parent_kind, subject, target, effect,
        signal_values, issued_at_ns, expires_at_ns, boot_id,
        source_revision, generation_id, mac,
    )


def parse_process_control_authority(
    payload: Mapping[str, Any], *, secret: bytes, boot_id: str, now_ns: int,
) -> ProcessControlAuthority:
    expected = {
        "schema_version", "kind", "transaction_id", "parent_authority_id",
        "parent_kind", "subject", "target", "effect", "signals",
        "issued_at_ns", "expires_at_ns", "boot_id", "source_revision",
        "generation_id", "mac_sha256", "authority_id",
    }
    if (
        not isinstance(payload, Mapping) or set(payload) != expected
        or payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("kind") != "maho-process-control-authority"
    ):
        raise ProcessControlAuthorityError("authority_fields_invalid")
    try:
        authority = issue_process_control_authority(
            secret=secret,
            transaction_id=str(payload["transaction_id"]),
            parent_authority_id=str(payload["parent_authority_id"]),
            parent_kind=str(payload["parent_kind"]),
            subject=_identity_from(payload["subject"]),
            target=_identity_from(payload["target"]),
            effect=EffectKind(str(payload["effect"])),
            signals=payload["signals"],
            issued_at_ns=int(payload["issued_at_ns"]),
            expires_at_ns=int(payload["expires_at_ns"]),
            boot_id=str(payload["boot_id"]),
            source_revision=payload["source_revision"],
            generation_id=payload["generation_id"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ProcessControlAuthorityError):
            raise
        raise ProcessControlAuthorityError("authority_payload_invalid") from exc
    if (
        not hmac.compare_digest(authority.mac_sha256, str(payload["mac_sha256"]))
        or authority.as_dict() != dict(payload)
    ):
        raise ProcessControlAuthorityError("authority_authentication_failed")
    if authority.boot_id != boot_id:
        raise ProcessControlAuthorityError("authority_boot_identity_mismatch")
    if now_ns >= authority.expires_at_ns:
        raise ProcessControlAuthorityError("authority_expired")
    return authority


def signal_mask(signals: Iterable[int]) -> int:
    mask = 0
    for signal in _validated_signals(signals):
        mask |= 1 << (signal - 1)
    return mask
