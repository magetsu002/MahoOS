#!/usr/bin/env python3
"""Detached Ed25519 release manifests with verify-before-parse semantics."""
from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
import re
from typing import Any, Mapping

from maho_boot_authority import BootContractError, BootGeneration, Digest
from maho_trust_identity import canonical_bytes


SCHEMA_VERSION = 1
_SHA40 = re.compile(r"[0-9a-f]{40}")
_MANIFEST_FIELDS = {
    "schema_version", "release_sequence", "security_epoch", "maho_version",
    "source_revision", "package_generation_id", "runtime_release",
    "boot_generation", "recovery_artifacts", "expected_payload_digests",
    "secure_boot_policy_version", "limine_policy_version", "release_authority_identity",
}
_SIGNATURE_FIELDS = {"schema_version", "algorithm", "release_authority_identity", "signature"}


class ReleaseManifestError(ValueError):
    pass


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseManifestError("release_manifest_duplicate_key")
        result[key] = value
    return result


def _strict_json(raw: bytes) -> Mapping[str, Any]:
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(text, object_pairs_hook=_pairs_no_duplicates,
                           parse_constant=lambda value: (_ for _ in ()).throw(
                               ReleaseManifestError("release_manifest_number_invalid")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseManifestError("release_manifest_malformed") from exc
    if not isinstance(value, Mapping):
        raise ReleaseManifestError("release_manifest_not_object")
    return value


def release_authority_identity(public_key_bytes: bytes) -> str:
    if len(public_key_bytes) != 32:
        raise ReleaseManifestError("release_public_key_invalid")
    return "maho-release-ed25519-" + hashlib.sha256(public_key_bytes).hexdigest()


@dataclass(frozen=True)
class ReleaseManifest:
    release_sequence: int
    security_epoch: int
    maho_version: str
    source_revision: str
    package_generation_id: str
    runtime_release: str
    boot_generation: BootGeneration
    recovery_artifacts: tuple[str, ...]
    expected_payload_digests: tuple[Digest, ...]
    secure_boot_policy_version: int
    limine_policy_version: int
    release_authority_identity: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ReleaseManifestError("release_manifest_schema_unsupported")
        ints = (self.release_sequence, self.security_epoch, self.secure_boot_policy_version,
                self.limine_policy_version)
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 1 for item in ints):
            raise ReleaseManifestError("release_manifest_version_invalid")
        if not self.maho_version or not self.runtime_release or _SHA40.fullmatch(self.source_revision) is None:
            raise ReleaseManifestError("release_manifest_identity_invalid")
        if not self.package_generation_id.startswith("pkg-"):
            raise ReleaseManifestError("release_manifest_package_generation_invalid")
        if self.boot_generation.source_revision != self.source_revision or self.boot_generation.package_generation_id != self.package_generation_id:
            raise ReleaseManifestError("release_manifest_boot_generation_mismatch")
        if tuple(sorted(set(self.recovery_artifacts))) != self.recovery_artifacts or not self.recovery_artifacts:
            raise ReleaseManifestError("release_manifest_recovery_artifacts_invalid")
        keys = [(item.algorithm, item.purpose) for item in self.expected_payload_digests]
        if keys != sorted(keys) or len(keys) != len(set(keys)) or not keys:
            raise ReleaseManifestError("release_manifest_payload_digests_invalid")
        if not self.release_authority_identity.startswith("maho-release-ed25519-"):
            raise ReleaseManifestError("release_authority_identity_invalid")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "release_sequence": self.release_sequence,
            "security_epoch": self.security_epoch, "maho_version": self.maho_version,
            "source_revision": self.source_revision, "package_generation_id": self.package_generation_id,
            "runtime_release": self.runtime_release, "boot_generation": self.boot_generation.as_dict(),
            "recovery_artifacts": list(self.recovery_artifacts),
            "expected_payload_digests": [item.as_dict() for item in self.expected_payload_digests],
            "secure_boot_policy_version": self.secure_boot_policy_version,
            "limine_policy_version": self.limine_policy_version,
            "release_authority_identity": self.release_authority_identity,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self.as_dict())

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "ReleaseManifest":
        if set(value) != _MANIFEST_FIELDS:
            raise ReleaseManifestError("release_manifest_fields_invalid")
        if not isinstance(value.get("recovery_artifacts"), list) or not isinstance(value.get("expected_payload_digests"), list):
            raise ReleaseManifestError("release_manifest_lists_invalid")
        try:
            return cls(
                release_sequence=value["release_sequence"], security_epoch=value["security_epoch"],
                maho_version=value["maho_version"], source_revision=value["source_revision"],
                package_generation_id=value["package_generation_id"], runtime_release=value["runtime_release"],
                boot_generation=BootGeneration.parse(value["boot_generation"]),
                recovery_artifacts=tuple(value["recovery_artifacts"]),
                expected_payload_digests=tuple(Digest.parse(item) for item in value["expected_payload_digests"]),
                secure_boot_policy_version=value["secure_boot_policy_version"],
                limine_policy_version=value["limine_policy_version"],
                release_authority_identity=value["release_authority_identity"],
                schema_version=value["schema_version"],
            )
        except (BootContractError, KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ReleaseManifestError):
                raise
            raise ReleaseManifestError("release_manifest_content_invalid") from exc


@dataclass(frozen=True)
class DetachedSignature:
    release_authority_identity: str
    signature: str
    algorithm: str = "ed25519"
    schema_version: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "algorithm": self.algorithm,
                "release_authority_identity": self.release_authority_identity, "signature": self.signature}

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self.as_dict())

    @classmethod
    def parse_raw(cls, raw: bytes) -> "DetachedSignature":
        value = _strict_json(raw)
        if set(value) != _SIGNATURE_FIELDS or value.get("schema_version") != 1 or value.get("algorithm") != "ed25519":
            raise ReleaseManifestError("release_signature_fields_invalid")
        try:
            signature = base64.b64decode(value["signature"], validate=True)
        except (TypeError, ValueError) as exc:
            raise ReleaseManifestError("release_signature_encoding_invalid") from exc
        if len(signature) != 64:
            raise ReleaseManifestError("release_signature_length_invalid")
        return cls(str(value["release_authority_identity"]), str(value["signature"]))


class Ed25519ReleaseSigner:
    """Small adapter over pyca/cryptography; private keys never enter manifests."""
    def __init__(self, private_key: Any) -> None:
        self._private_key = private_key

    @classmethod
    def generate(cls) -> "Ed25519ReleaseSigner":
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        return cls(Ed25519PrivateKey.generate())

    def public_key_bytes(self) -> bytes:
        from cryptography.hazmat.primitives import serialization
        return self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
        )

    @property
    def authority_identity(self) -> str:
        return release_authority_identity(self.public_key_bytes())

    def sign(self, raw_manifest: bytes) -> DetachedSignature:
        signature = self._private_key.sign(raw_manifest)
        return DetachedSignature(self.authority_identity, base64.b64encode(signature).decode("ascii"))


def verify_release_manifest(
    raw_manifest: bytes, raw_signature: bytes, public_key_bytes: bytes, *,
    expected_release_authority: str, minimum_release_sequence: int,
    current_security_epoch: int, revoked_authorities: tuple[str, ...] = (),
) -> ReleaseManifest:
    """Authenticate exact bytes before parsing and enforcing freshness."""
    signature = DetachedSignature.parse_raw(raw_signature)
    actual_authority = release_authority_identity(public_key_bytes)
    if actual_authority != expected_release_authority or signature.release_authority_identity != actual_authority:
        raise ReleaseManifestError("release_authority_mismatch")
    if actual_authority in set(revoked_authorities):
        raise ReleaseManifestError("release_authority_revoked")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
            base64.b64decode(signature.signature, validate=True), raw_manifest,
        )
    except Exception as exc:
        raise ReleaseManifestError("release_signature_invalid") from exc
    value = _strict_json(raw_manifest)
    manifest = ReleaseManifest.parse(value)
    if raw_manifest != manifest.canonical_bytes():
        raise ReleaseManifestError("release_manifest_not_canonical")
    if manifest.release_authority_identity != actual_authority:
        raise ReleaseManifestError("release_manifest_authority_mismatch")
    if manifest.security_epoch != current_security_epoch:
        raise ReleaseManifestError("release_manifest_security_epoch_mismatch")
    if manifest.release_sequence < minimum_release_sequence:
        raise ReleaseManifestError("release_manifest_sequence_rollback")
    return manifest


def verify_release_payloads(manifest: ReleaseManifest, payloads: Mapping[str, bytes]) -> None:
    """Require one exact payload for every purpose named by the signed manifest."""
    expected = {item.purpose: item for item in manifest.expected_payload_digests}
    if set(payloads) != set(expected):
        raise ReleaseManifestError("release_payload_set_mismatch")
    for purpose, content in payloads.items():
        if not isinstance(content, bytes):
            raise ReleaseManifestError("release_payload_type_invalid")
        digest = expected[purpose]
        if Digest.calculate(content, algorithm=digest.algorithm, purpose=purpose).digest != digest.digest:
            raise ReleaseManifestError(f"release_payload_digest_mismatch:{purpose}")
