#!/usr/bin/env python3
"""Closed, content-addressed identities for the Maho signed boot chain.

These objects describe bytes and authority.  They never infer trust from a
signature or from the SecureBoot EFI variable alone.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import re
from typing import Any, Iterable, Mapping

from maho_trust_identity import canonical_bytes


SCHEMA_VERSION = 1
_HEX = re.compile(r"[0-9a-f]+")
_SHA40 = re.compile(r"[0-9a-f]{40}")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_FINGERPRINT = re.compile(r"[0-9A-F]{40,128}")
_ID = re.compile(r"(?:bootgen|bootauth|bootenv)-[0-9a-f]{64}")
_DIGEST_LENGTHS = {"sha256": 64, "blake2b-512": 128}


class BootContractError(ValueError):
    pass


def _closed(value: Mapping[str, Any], fields: set[str], kind: str) -> None:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise BootContractError(f"{kind}_fields_invalid")


def _nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise BootContractError(f"{name}_invalid")
    return value


def certificate_fingerprint(value: str) -> str:
    normalized = value.replace(":", "").upper()
    if _FINGERPRINT.fullmatch(normalized) is None:
        raise BootContractError("certificate_fingerprint_invalid")
    return normalized


@dataclass(frozen=True)
class Digest:
    algorithm: str
    digest: str
    purpose: str

    def __post_init__(self) -> None:
        length = _DIGEST_LENGTHS.get(self.algorithm)
        if length is None:
            raise BootContractError("digest_algorithm_unsupported")
        if len(self.digest) != length or _HEX.fullmatch(self.digest) is None:
            raise BootContractError("digest_value_invalid")
        _nonempty(self.purpose, "digest_purpose")

    @classmethod
    def calculate(cls, content: bytes, *, algorithm: str, purpose: str) -> "Digest":
        if algorithm == "sha256":
            value = hashlib.sha256(content).hexdigest()
        elif algorithm == "blake2b-512":
            value = hashlib.blake2b(content, digest_size=64).hexdigest()
        else:
            raise BootContractError("digest_algorithm_unsupported")
        return cls(algorithm, value, purpose)

    def as_dict(self) -> dict[str, str]:
        return {"algorithm": self.algorithm, "digest": self.digest, "purpose": self.purpose}

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "Digest":
        _closed(value, {"algorithm", "digest", "purpose"}, "digest")
        return cls(str(value["algorithm"]), str(value["digest"]), str(value["purpose"]))


@dataclass(frozen=True)
class BootArtifact:
    identity: str
    artifact_type: str
    path: str
    digests: tuple[Digest, ...]

    def __post_init__(self) -> None:
        _nonempty(self.identity, "artifact_identity")
        _nonempty(self.artifact_type, "artifact_type")
        if not self.path.startswith("/") or ".." in self.path.split("/"):
            raise BootContractError("artifact_path_unbounded")
        keys = [(item.algorithm, item.purpose) for item in self.digests]
        if not self.digests or keys != sorted(keys) or len(keys) != len(set(keys)):
            raise BootContractError("artifact_digests_not_canonical")
        material = {"artifact_type": self.artifact_type, "path": self.path,
                    "digests": [item.as_dict() for item in self.digests]}
        expected = "bootart-" + hashlib.sha256(
            b"maho-boot-artifact-v1\0" + canonical_bytes(material)
        ).hexdigest()
        if self.identity != expected:
            raise BootContractError("artifact_identity_mismatch")

    @classmethod
    def from_bytes(
        cls, content: bytes, *, artifact_type: str, path: str,
        algorithms: Iterable[tuple[str, str]] = (("sha256", "maho-content-identity"),),
    ) -> "BootArtifact":
        digests = tuple(sorted(
            (Digest.calculate(content, algorithm=algorithm, purpose=purpose)
             for algorithm, purpose in algorithms),
            key=lambda item: (item.algorithm, item.purpose),
        ))
        material = {"artifact_type": artifact_type, "path": path,
                    "digests": [item.as_dict() for item in digests]}
        identity = "bootart-" + hashlib.sha256(b"maho-boot-artifact-v1\0" + canonical_bytes(material)).hexdigest()
        return cls(identity, artifact_type, path, digests)

    def digest(self, algorithm: str, purpose: str) -> Digest | None:
        return next((item for item in self.digests if item.algorithm == algorithm and item.purpose == purpose), None)

    def as_dict(self) -> dict[str, Any]:
        return {"identity": self.identity, "artifact_type": self.artifact_type,
                "path": self.path, "digests": [item.as_dict() for item in self.digests]}

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "BootArtifact":
        _closed(value, {"identity", "artifact_type", "path", "digests"}, "boot_artifact")
        if not isinstance(value["digests"], list):
            raise BootContractError("artifact_digests_invalid")
        artifact = cls(str(value["identity"]), str(value["artifact_type"]), str(value["path"]),
                       tuple(Digest.parse(item) for item in value["digests"]))
        return artifact


@dataclass(frozen=True)
class LoaderIdentity:
    artifact: BootArtifact
    limine_version: str
    signing_certificate_fingerprint: str
    embedded_config_checksum: Digest
    authoritative_config_path: str
    discovery_surface: tuple[str, ...]
    config_resource_digests: tuple[Digest, ...]

    def __post_init__(self) -> None:
        if self.artifact.artifact_type != "efi-loader":
            raise BootContractError("loader_artifact_type_invalid")
        _nonempty(self.limine_version, "limine_version")
        certificate_fingerprint(self.signing_certificate_fingerprint)
        if self.embedded_config_checksum.algorithm != "blake2b-512":
            raise BootContractError("limine_config_checksum_algorithm_invalid")
        if not self.authoritative_config_path.startswith("/EFI/MahoOS/"):
            raise BootContractError("loader_config_path_invalid")
        if tuple(sorted(set(self.discovery_surface))) != self.discovery_surface:
            raise BootContractError("loader_discovery_surface_not_canonical")
        if self.discovery_surface != (self.authoritative_config_path,):
            raise BootContractError("ambiguous_limine_config_authority")
        keys = [(item.algorithm, item.digest, item.purpose) for item in self.config_resource_digests]
        if not keys or keys != sorted(keys):
            raise BootContractError("loader_config_resource_digests_not_canonical")
        if any(item.algorithm != "blake2b-512" or item.purpose != "limine-artifact-integrity"
               for item in self.config_resource_digests):
            raise BootContractError("loader_config_resource_digest_invalid")

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact.as_dict(), "limine_version": self.limine_version,
            "signing_certificate_fingerprint": certificate_fingerprint(self.signing_certificate_fingerprint),
            "embedded_config_checksum": self.embedded_config_checksum.as_dict(),
            "authoritative_config_path": self.authoritative_config_path,
            "discovery_surface": list(self.discovery_surface),
            "config_resource_digests": [item.as_dict() for item in self.config_resource_digests],
        }

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "LoaderIdentity":
        _closed(value, {"artifact", "limine_version", "signing_certificate_fingerprint",
                        "embedded_config_checksum", "authoritative_config_path", "discovery_surface",
                        "config_resource_digests"}, "loader")
        if not isinstance(value["discovery_surface"], list) or not isinstance(value["config_resource_digests"], list):
            raise BootContractError("loader_discovery_surface_invalid")
        return cls(BootArtifact.parse(value["artifact"]), str(value["limine_version"]),
                   str(value["signing_certificate_fingerprint"]), Digest.parse(value["embedded_config_checksum"]),
                   str(value["authoritative_config_path"]), tuple(str(item) for item in value["discovery_surface"]),
                   tuple(Digest.parse(item) for item in value["config_resource_digests"]))


_GENERATION_FIELDS = {
    "schema_version", "boot_generation_id", "source_revision", "package_generation_id",
    "candidate_root_identity", "normal_loader", "normal_config", "primary_kernel",
    "primary_initramfs", "fallback_kernel", "fallback_initramfs", "microcode",
    "recovery_loader", "recovery_config", "recovery_kernel", "recovery_initramfs",
    "guardian_recovery_runtime", "authenticated_cmdline",
}


@dataclass(frozen=True)
class BootGeneration:
    boot_generation_id: str
    source_revision: str
    package_generation_id: str
    candidate_root_identity: str
    normal_loader: LoaderIdentity
    normal_config: BootArtifact
    primary_kernel: BootArtifact
    primary_initramfs: BootArtifact
    fallback_kernel: BootArtifact
    fallback_initramfs: BootArtifact
    microcode: tuple[BootArtifact, ...]
    recovery_loader: LoaderIdentity
    recovery_config: BootArtifact
    recovery_kernel: BootArtifact
    recovery_initramfs: BootArtifact
    guardian_recovery_runtime: BootArtifact
    authenticated_cmdline: BootArtifact
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise BootContractError("boot_generation_schema_unsupported")
        if _SHA40.fullmatch(self.source_revision) is None:
            raise BootContractError("source_revision_invalid")
        if not self.package_generation_id.startswith("pkg-"):
            raise BootContractError("package_generation_id_invalid")
        _nonempty(self.candidate_root_identity, "candidate_root_identity")
        if self.normal_loader.authoritative_config_path == self.recovery_loader.authoritative_config_path:
            raise BootContractError("normal_recovery_config_not_separated")
        if self.normal_loader.artifact.identity == self.recovery_loader.artifact.identity:
            raise BootContractError("normal_recovery_loader_not_separated")
        if self.normal_config.path != self.normal_loader.authoritative_config_path:
            raise BootContractError("normal_config_loader_binding_mismatch")
        if self.recovery_config.path != self.recovery_loader.authoritative_config_path:
            raise BootContractError("recovery_config_loader_binding_mismatch")
        normal_artifacts = (self.primary_kernel, self.primary_initramfs, self.fallback_kernel,
                            self.fallback_initramfs, *self.microcode)
        recovery_artifacts = (self.recovery_kernel, self.recovery_initramfs)
        for loader, artifacts, name in (
            (self.normal_loader, normal_artifacts, "normal"),
            (self.recovery_loader, recovery_artifacts, "recovery"),
        ):
            expected = sorted(
                item.digest("blake2b-512", "limine-artifact-integrity").digest
                for item in artifacts
                if item.digest("blake2b-512", "limine-artifact-integrity") is not None
            )
            observed = sorted(item.digest for item in loader.config_resource_digests)
            if len(expected) != len(artifacts) or observed != expected:
                raise BootContractError(f"{name}_config_artifact_binding_mismatch")
        if tuple(sorted(self.microcode, key=lambda item: item.identity)) != self.microcode:
            raise BootContractError("microcode_not_canonical")
        if self.boot_generation_id != self.derive_id(self.identity_material()):
            raise BootContractError("boot_generation_identity_mismatch")

    @staticmethod
    def derive_id(material: Mapping[str, Any]) -> str:
        return "bootgen-" + hashlib.sha256(b"maho-boot-generation-v1\0" + canonical_bytes(material)).hexdigest()

    def identity_material(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "source_revision": self.source_revision,
            "package_generation_id": self.package_generation_id,
            "candidate_root_identity": self.candidate_root_identity,
            "normal_loader": self.normal_loader.as_dict(), "normal_config": self.normal_config.as_dict(),
            "primary_kernel": self.primary_kernel.as_dict(), "primary_initramfs": self.primary_initramfs.as_dict(),
            "fallback_kernel": self.fallback_kernel.as_dict(), "fallback_initramfs": self.fallback_initramfs.as_dict(),
            "microcode": [item.as_dict() for item in self.microcode],
            "recovery_loader": self.recovery_loader.as_dict(), "recovery_config": self.recovery_config.as_dict(),
            "recovery_kernel": self.recovery_kernel.as_dict(), "recovery_initramfs": self.recovery_initramfs.as_dict(),
            "guardian_recovery_runtime": self.guardian_recovery_runtime.as_dict(),
            "authenticated_cmdline": self.authenticated_cmdline.as_dict(),
        }

    def as_dict(self) -> dict[str, Any]:
        return self.identity_material() | {"boot_generation_id": self.boot_generation_id}

    @classmethod
    def create(cls, **values: Any) -> "BootGeneration":
        values = dict(values)
        values["microcode"] = tuple(sorted(values.get("microcode", ()), key=lambda item: item.identity))
        provisional = {"schema_version": SCHEMA_VERSION,
            **{name: (value.as_dict() if hasattr(value, "as_dict") else
                      [item.as_dict() for item in value] if name == "microcode" else value)
               for name, value in values.items()}}
        return cls(boot_generation_id=cls.derive_id(provisional), **values)

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "BootGeneration":
        _closed(value, _GENERATION_FIELDS, "boot_generation")
        if value.get("schema_version") != SCHEMA_VERSION or not isinstance(value["microcode"], list):
            raise BootContractError("boot_generation_schema_invalid")
        return cls(
            boot_generation_id=str(value["boot_generation_id"]), source_revision=str(value["source_revision"]),
            package_generation_id=str(value["package_generation_id"]), candidate_root_identity=str(value["candidate_root_identity"]),
            normal_loader=LoaderIdentity.parse(value["normal_loader"]), normal_config=BootArtifact.parse(value["normal_config"]),
            primary_kernel=BootArtifact.parse(value["primary_kernel"]), primary_initramfs=BootArtifact.parse(value["primary_initramfs"]),
            fallback_kernel=BootArtifact.parse(value["fallback_kernel"]), fallback_initramfs=BootArtifact.parse(value["fallback_initramfs"]),
            microcode=tuple(BootArtifact.parse(item) for item in value["microcode"]),
            recovery_loader=LoaderIdentity.parse(value["recovery_loader"]), recovery_config=BootArtifact.parse(value["recovery_config"]),
            recovery_kernel=BootArtifact.parse(value["recovery_kernel"]), recovery_initramfs=BootArtifact.parse(value["recovery_initramfs"]),
            guardian_recovery_runtime=BootArtifact.parse(value["guardian_recovery_runtime"]),
            authenticated_cmdline=BootArtifact.parse(value["authenticated_cmdline"]),
        )


@dataclass(frozen=True)
class BootAuthority:
    boot_authority_id: str
    device_signing_certificate_fingerprint: str
    release_authority_identity: str
    release_sequence: int
    security_epoch: int
    secure_boot_policy_version: int
    limine_policy_version: int
    permitted_boot_generation_id: str
    recovery_authority_identity: str
    source_revision: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != 1 or min(self.release_sequence, self.security_epoch,
                                           self.secure_boot_policy_version, self.limine_policy_version) < 1:
            raise BootContractError("boot_authority_version_invalid")
        certificate_fingerprint(self.device_signing_certificate_fingerprint)
        _nonempty(self.release_authority_identity, "release_authority_identity")
        _nonempty(self.recovery_authority_identity, "recovery_authority_identity")
        if not self.permitted_boot_generation_id.startswith("bootgen-") or _SHA40.fullmatch(self.source_revision) is None:
            raise BootContractError("boot_authority_context_invalid")
        if self.boot_authority_id != self.derive_id(self.identity_material()):
            raise BootContractError("boot_authority_identity_mismatch")

    @staticmethod
    def derive_id(material: Mapping[str, Any]) -> str:
        return "bootauth-" + hashlib.sha256(b"maho-boot-authority-v1\0" + canonical_bytes(material)).hexdigest()

    def identity_material(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version,
                "device_signing_certificate_fingerprint": certificate_fingerprint(self.device_signing_certificate_fingerprint),
                "release_authority_identity": self.release_authority_identity, "release_sequence": self.release_sequence,
                "security_epoch": self.security_epoch, "secure_boot_policy_version": self.secure_boot_policy_version,
                "limine_policy_version": self.limine_policy_version,
                "permitted_boot_generation_id": self.permitted_boot_generation_id,
                "recovery_authority_identity": self.recovery_authority_identity,
                "source_revision": self.source_revision}

    def as_dict(self) -> dict[str, Any]:
        return self.identity_material() | {"boot_authority_id": self.boot_authority_id}

    @classmethod
    def create(cls, **values: Any) -> "BootAuthority":
        material = {"schema_version": 1, **values}
        return cls(boot_authority_id=cls.derive_id(material), **values)

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "BootAuthority":
        fields = {"schema_version", "boot_authority_id", "device_signing_certificate_fingerprint",
                  "release_authority_identity", "release_sequence", "security_epoch", "secure_boot_policy_version",
                  "limine_policy_version", "permitted_boot_generation_id", "recovery_authority_identity", "source_revision"}
        _closed(value, fields, "boot_authority")
        if isinstance(value["release_sequence"], bool) or isinstance(value["security_epoch"], bool):
            raise BootContractError("boot_authority_version_invalid")
        return cls(str(value["boot_authority_id"]), str(value["device_signing_certificate_fingerprint"]),
                   str(value["release_authority_identity"]), int(value["release_sequence"]), int(value["security_epoch"]),
                   int(value["secure_boot_policy_version"]), int(value["limine_policy_version"]),
                   str(value["permitted_boot_generation_id"]), str(value["recovery_authority_identity"]),
                   str(value["source_revision"]), int(value["schema_version"]))


class KeyLifecycleState(str, Enum):
    UNPROVISIONED = "unprovisioned"
    INSPECTED = "inspected"
    PROVISIONING_READY = "provisioning-ready"
    ENROLLED = "enrolled"
    ACTIVE = "active"
    ROTATION_PREPARED = "rotation-prepared"
    ROTATION_DUAL_TRUST = "rotation-dual-trust"
    ROTATION_PROVEN = "rotation-proven"
    RETIRED = "retired"
    COMPROMISED = "compromised"
    UNAVAILABLE = "unavailable"
    REPROVISION_REQUIRED = "reprovision-required"


_KEY_TRANSITIONS = {
    KeyLifecycleState.UNPROVISIONED: {KeyLifecycleState.INSPECTED},
    KeyLifecycleState.INSPECTED: {KeyLifecycleState.PROVISIONING_READY, KeyLifecycleState.UNAVAILABLE, KeyLifecycleState.REPROVISION_REQUIRED},
    KeyLifecycleState.PROVISIONING_READY: {KeyLifecycleState.ENROLLED, KeyLifecycleState.UNAVAILABLE},
    KeyLifecycleState.ENROLLED: {KeyLifecycleState.ACTIVE, KeyLifecycleState.UNAVAILABLE},
    KeyLifecycleState.ACTIVE: {KeyLifecycleState.ROTATION_PREPARED, KeyLifecycleState.COMPROMISED, KeyLifecycleState.UNAVAILABLE},
    KeyLifecycleState.ROTATION_PREPARED: {KeyLifecycleState.ROTATION_DUAL_TRUST, KeyLifecycleState.COMPROMISED},
    KeyLifecycleState.ROTATION_DUAL_TRUST: {KeyLifecycleState.ROTATION_PROVEN, KeyLifecycleState.COMPROMISED},
    KeyLifecycleState.ROTATION_PROVEN: {KeyLifecycleState.RETIRED, KeyLifecycleState.COMPROMISED},
    KeyLifecycleState.UNAVAILABLE: {KeyLifecycleState.INSPECTED, KeyLifecycleState.REPROVISION_REQUIRED},
    KeyLifecycleState.COMPROMISED: {KeyLifecycleState.REPROVISION_REQUIRED},
    KeyLifecycleState.REPROVISION_REQUIRED: {KeyLifecycleState.INSPECTED},
    KeyLifecycleState.RETIRED: set(),
}


def transition_key_state(current: KeyLifecycleState | str, target: KeyLifecycleState | str, *, new_boot_proven: bool = False) -> KeyLifecycleState:
    before, after = KeyLifecycleState(current), KeyLifecycleState(target)
    if after not in _KEY_TRANSITIONS[before]:
        raise BootContractError("key_lifecycle_transition_invalid")
    if after is KeyLifecycleState.ROTATION_PROVEN and not new_boot_proven:
        raise BootContractError("key_rotation_boot_proof_required")
    return after


def evaluate_key_continuity(*, expected_tpm_identity: str | None,
                            observed_tpm_identity: str | None,
                            signing_key_available: bool,
                            firmware_keys_preserved: bool | None) -> KeyLifecycleState:
    """Classify loss/reset without ever manufacturing a replacement authority."""
    if firmware_keys_preserved is False:
        return KeyLifecycleState.REPROVISION_REQUIRED
    if expected_tpm_identity is not None and observed_tpm_identity is None:
        return KeyLifecycleState.UNAVAILABLE
    if expected_tpm_identity != observed_tpm_identity:
        return KeyLifecycleState.REPROVISION_REQUIRED
    if not signing_key_available:
        return KeyLifecycleState.UNAVAILABLE
    if firmware_keys_preserved is not True:
        return KeyLifecycleState.INSPECTED
    return KeyLifecycleState.ACTIVE


def authorize_freshness(authority: BootAuthority, *, minimum_release_sequence: int,
                        current_security_epoch: int, revoked_authority_ids: Iterable[str] = ()) -> None:
    if authority.boot_authority_id in set(revoked_authority_ids):
        raise BootContractError("boot_authority_revoked")
    if authority.security_epoch != current_security_epoch:
        raise BootContractError("security_epoch_mismatch")
    if authority.release_sequence < minimum_release_sequence:
        raise BootContractError("release_sequence_rollback")
