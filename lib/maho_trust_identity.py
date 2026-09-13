#!/usr/bin/env python3
"""Canonical identities and provisional trust semantics for Maho architecture.

Schema version 1 is intentionally closed: unknown fields and forward schema
versions are rejected.  A future reader must explicitly add a migration rather
than interpreting evidence it does not understand.  Signatures and provenance
are evidence; neither grants VERIFIED by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
import unicodedata
from typing import Any, ClassVar, Mapping, TypeVar


SCHEMA_VERSION = 1


class TrustState(str, Enum):
    VERIFIED = "VERIFIED"
    UNKNOWN = "UNKNOWN"
    REVOKED = "REVOKED"
    CONTAMINATED = "CONTAMINATED"
    REVALIDATED = "REVALIDATED"


def parse_trust_state(value: Any) -> TrustState:
    try:
        return TrustState(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("unknown trust state") from exc


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        raise ValueError("floating point values are not canonical identity inputs")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("canonical object keys must be strings")
        normalized = {unicodedata.normalize("NFC", key): _normalize(item) for key, item in value.items()}
        if len(normalized) != len(value):
            raise ValueError("object keys collide after Unicode normalization")
        return normalized
    raise ValueError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return deterministic UTF-8 JSON suitable for identity derivation."""
    return json.dumps(
        _normalize(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


TID = TypeVar("TID", bound="DigestID")


class DigestID(str):
    PREFIX: ClassVar[str]
    _PATTERN: ClassVar[re.Pattern[str]]

    def __new__(cls: type[TID], value: str) -> TID:
        if not isinstance(value, str) or cls._PATTERN.fullmatch(value) is None:
            raise ValueError(f"malformed {cls.__name__}")
        return str.__new__(cls, value)

    @classmethod
    def derive(cls: type[TID], value: Any) -> TID:
        digest = hashlib.sha256(cls.PREFIX.encode() + b"\0" + canonical_bytes(value)).hexdigest()
        return cls(f"{cls.PREFIX}-{digest}")


class ArtifactID(DigestID):
    PREFIX = "art"
    _PATTERN = re.compile(r"art-[0-9a-f]{64}")

    @classmethod
    def from_content(cls, content: bytes) -> "ArtifactID":
        if not isinstance(content, bytes):
            raise ValueError("artifact content must be bytes")
        return cls("art-" + hashlib.sha256(content).hexdigest())


class TransactionID(DigestID):
    PREFIX = "txn"
    _PATTERN = re.compile(r"txn-[0-9a-f]{64}")


class GenerationID(DigestID):
    PREFIX = "gen"
    _PATTERN = re.compile(r"gen-[0-9a-f]{64}")


class KernelGenerationID(DigestID):
    PREFIX = "kgen"
    _PATTERN = re.compile(r"kgen-[0-9a-f]{64}")


class ProvenanceID(DigestID):
    PREFIX = "prv"
    _PATTERN = re.compile(r"prv-[0-9a-f]{64}")


@dataclass(frozen=True)
class TrustEvidence:
    authority: str
    evidence_id: str
    independently_verified: bool = False

    def __post_init__(self) -> None:
        if not self.authority or not self.evidence_id:
            raise ValueError("trust evidence requires authority and identity")


def transition_trust(
    current: TrustState | str,
    target: TrustState | str,
    evidence: TrustEvidence | None = None,
) -> TrustState:
    """Apply a trust transition without allowing evidence-free promotion."""
    before = parse_trust_state(current)
    after = parse_trust_state(target)
    if before == after:
        return before
    if after in {TrustState.REVOKED, TrustState.CONTAMINATED, TrustState.UNKNOWN}:
        return after
    if evidence is None or not evidence.independently_verified:
        raise ValueError("trust promotion requires independent verification evidence")
    if before in {TrustState.REVOKED, TrustState.CONTAMINATED}:
        if after is not TrustState.REVALIDATED:
            raise ValueError("revoked or contaminated state must pass through REVALIDATED")
        return after
    if after is TrustState.REVALIDATED:
        raise ValueError("REVALIDATED is reserved for independently repaired revoked evidence")
    return after


_ARTIFACT_FIELDS = {
    "schema_version", "artifact_id", "content_sha256", "artifact_type",
    "source_identity", "source_revision", "producer_identity", "transaction_id",
    "provenance_id", "signing_authority", "trust_state",
}


@dataclass(frozen=True)
class Artifact:
    artifact_id: ArtifactID
    content_sha256: str
    artifact_type: str
    source_identity: str
    source_revision: str | None
    producer_identity: str
    transaction_id: TransactionID | None
    provenance_id: ProvenanceID
    signing_authority: str | None
    trust_state: TrustState = TrustState.UNKNOWN
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported artifact schema version")
        if re.fullmatch(r"[0-9a-f]{64}", self.content_sha256) is None:
            raise ValueError("artifact content hash must be lowercase SHA-256")
        if str(self.artifact_id) != "art-" + self.content_sha256:
            raise ValueError("artifact identity does not match content digest")
        for name in ("artifact_type", "source_identity", "producer_identity"):
            if not getattr(self, name):
                raise ValueError(f"artifact {name} is required")
        parse_trust_state(self.trust_state)

    @classmethod
    def from_content(
        cls,
        content: bytes,
        *,
        artifact_type: str,
        source_identity: str,
        source_revision: str | None,
        producer_identity: str,
        transaction_id: TransactionID | None,
        provenance_id: ProvenanceID,
        signing_authority: str | None = None,
        trust_state: TrustState = TrustState.UNKNOWN,
    ) -> "Artifact":
        identity = ArtifactID.from_content(content)
        return cls(
            artifact_id=identity,
            content_sha256=str(identity).removeprefix("art-"),
            artifact_type=artifact_type,
            source_identity=source_identity,
            source_revision=source_revision,
            producer_identity=producer_identity,
            transaction_id=transaction_id,
            provenance_id=provenance_id,
            signing_authority=signing_authority,
            trust_state=trust_state,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": str(self.artifact_id),
            "content_sha256": self.content_sha256,
            "artifact_type": self.artifact_type,
            "source_identity": self.source_identity,
            "source_revision": self.source_revision,
            "producer_identity": self.producer_identity,
            "transaction_id": str(self.transaction_id) if self.transaction_id else None,
            "provenance_id": str(self.provenance_id),
            "signing_authority": self.signing_authority,
            "trust_state": self.trust_state.value,
        }

    def canonical(self) -> str:
        return canonical_json(self.as_dict())

    @classmethod
    def parse(cls, payload: Mapping[str, Any]) -> "Artifact":
        if not isinstance(payload, Mapping):
            raise ValueError("artifact manifest must be an object")
        unknown = set(payload) - _ARTIFACT_FIELDS
        missing = _ARTIFACT_FIELDS - set(payload)
        if unknown:
            raise ValueError(f"unknown artifact fields: {sorted(unknown)}")
        if missing:
            raise ValueError(f"missing artifact fields: {sorted(missing)}")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported artifact schema version")
        tx = payload.get("transaction_id")
        return cls(
            artifact_id=ArtifactID(payload["artifact_id"]),
            content_sha256=payload["content_sha256"],
            artifact_type=payload["artifact_type"],
            source_identity=payload["source_identity"],
            source_revision=payload["source_revision"],
            producer_identity=payload["producer_identity"],
            transaction_id=TransactionID(tx) if tx is not None else None,
            provenance_id=ProvenanceID(payload["provenance_id"]),
            signing_authority=payload["signing_authority"],
            trust_state=parse_trust_state(payload["trust_state"]),
        )
