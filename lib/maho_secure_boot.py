#!/usr/bin/env python3
"""Read-only firmware evidence, bounded signing providers, and postboot proof."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import subprocess
import uuid
from typing import Any, Callable, Iterable, Mapping, Protocol

from maho_boot_authority import (
    BootArtifact, BootAuthority, BootContractError, BootGeneration, Digest,
    LoaderIdentity, authorize_freshness, certificate_fingerprint,
)
from maho_trust_identity import canonical_bytes


EFI_GLOBAL_GUID = "8be4df61-93ca-11d2-aa0d-00e098032b8c"
_EFI_NAME = re.compile(r"[A-Za-z0-9_-]+-[0-9a-fA-F-]{36}")
_BOOT_ENTRY = re.compile(r"Boot[0-9A-Fa-f]{4}-")


class SecureBootError(ValueError):
    pass


_LIMINE_RESOURCE_OPTIONS = {"path", "kernel_path", "module_path", "dtb_path", "image_path"}
_BLAKE2B_SUFFIX = re.compile(r"#[0-9a-f]{128}$")


def validate_limine_config(config: bytes, *, allow_efi_chainload: bool = False) -> tuple[str, ...]:
    """Check the fail-closed subset required by Limine's enrolled-config mode."""
    try:
        text = config.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SecureBootError("limine_config_encoding_invalid") from exc
    reasons: list[str] = []
    protocol: str | None = None
    resource_count = 0
    for number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("/"):
            protocol = None
            continue
        if ":" not in line:
            reasons.append(f"limine_config_syntax:{number}")
            continue
        key, value = (item.strip() for item in line.split(":", 1))
        if key == "protocol":
            protocol = value
            if value in {"efi", "uefi", "efi_chainload"} and not allow_efi_chainload:
                reasons.append(f"foreign_efi_chainload_forbidden:{number}")
        if key in _LIMINE_RESOURCE_OPTIONS:
            resource_count += 1
            if protocol in {"efi", "uefi", "efi_chainload"}:
                continue
            if _BLAKE2B_SUFFIX.search(value) is None:
                reasons.append(f"limine_resource_hash_missing:{number}")
    if resource_count == 0:
        reasons.append("limine_config_resources_missing")
    if any(line.strip().lower() == "hash_mismatch_panic: no" for line in text.splitlines()):
        reasons.append("limine_hash_mismatch_panic_disabled")
    return tuple(sorted(set(reasons)))


def _efi_payload(path: Path) -> bytes | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    return raw[4:] if len(raw) >= 4 else None


def _efi_bool(root: Path, name: str) -> bool | None:
    payload = _efi_payload(root / f"{name}-{EFI_GLOBAL_GUID}")
    return None if not payload else payload[0] != 0


def _variable_identity(root: Path, name: str) -> str | None:
    payload = _efi_payload(root / f"{name}-{EFI_GLOBAL_GUID}")
    return None if payload is None else hashlib.sha256(payload).hexdigest()


def _signature_database_identities(root: Path, name: str) -> tuple[str, ...] | None:
    payload = _efi_payload(root / f"{name}-{EFI_GLOBAL_GUID}")
    if payload is None:
        return None
    identities: list[str] = []
    offset = 0
    while offset < len(payload):
        if len(payload) - offset < 28:
            return (f"malformed-efi-signature-database-sha256:{hashlib.sha256(payload).hexdigest()}",)
        signature_type = str(uuid.UUID(bytes_le=payload[offset:offset + 16])).lower()
        list_size = int.from_bytes(payload[offset + 16:offset + 20], "little")
        header_size = int.from_bytes(payload[offset + 20:offset + 24], "little")
        signature_size = int.from_bytes(payload[offset + 24:offset + 28], "little")
        if list_size < 28 + header_size or signature_size < 16 or offset + list_size > len(payload):
            return (f"malformed-efi-signature-database-sha256:{hashlib.sha256(payload).hexdigest()}",)
        cursor = offset + 28 + header_size
        end = offset + list_size
        if (end - cursor) % signature_size:
            return (f"malformed-efi-signature-database-sha256:{hashlib.sha256(payload).hexdigest()}",)
        while cursor < end:
            data = payload[cursor + 16:cursor + signature_size]
            if signature_type == "a5c059a1-94e4-4aa7-87b5-ab155c2bf072":
                try:
                    from cryptography import x509
                    from cryptography.hazmat.primitives import hashes
                    fingerprint = x509.load_der_x509_certificate(data).fingerprint(hashes.SHA256()).hex().upper()
                    identities.append(f"x509-sha256:{fingerprint}")
                except Exception:
                    identities.append(f"invalid-x509-sha256:{hashlib.sha256(data).hexdigest()}")
            else:
                identities.append(f"efi-signature:{signature_type}:sha256:{hashlib.sha256(data).hexdigest()}")
            cursor += signature_size
        offset += list_size
    return tuple(sorted(set(identities)))


def _load_option_file_path(payload: bytes) -> str | None:
    if len(payload) < 6:
        return None
    path_length = int.from_bytes(payload[4:6], "little")
    cursor = 6
    while cursor + 1 < len(payload):
        if payload[cursor:cursor + 2] == b"\0\0":
            cursor += 2
            break
        cursor += 2
    end = min(cursor + path_length, len(payload))
    while cursor + 4 <= end:
        node_type, subtype = payload[cursor], payload[cursor + 1]
        length = int.from_bytes(payload[cursor + 2:cursor + 4], "little")
        if length < 4 or cursor + length > end:
            return None
        if node_type == 4 and subtype == 4:
            try:
                return payload[cursor + 4:cursor + length].decode("utf-16-le").rstrip("\0").replace("\\", "/")
            except UnicodeDecodeError:
                return None
        cursor += length
    return None


def inventory_boot_entries(efivar_root: str | os.PathLike[str]) -> tuple[EfiEntry, ...]:
    root = Path(efivar_root)
    rows: list[EfiEntry] = []
    for path in sorted(root.glob("Boot[0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]-*")):
        payload = _efi_payload(path)
        if payload is None:
            continue
        rows.append(EfiEntry(path.name[:8], hashlib.sha256(payload).hexdigest(), _load_option_file_path(payload)))
    return tuple(rows)


@dataclass(frozen=True)
class EfiEntry:
    name: str
    variable_sha256: str
    device_path: str | None

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "variable_sha256": self.variable_sha256,
                "device_path": self.device_path}


@dataclass(frozen=True)
class EfiExecutable:
    esp_identity: str
    path: str
    sha256: str
    signer_fingerprint: str | None
    trusted_by_db: bool | None

    def as_dict(self) -> dict[str, Any]:
        return {"esp_identity": self.esp_identity, "path": self.path, "sha256": self.sha256,
                "signer_fingerprint": self.signer_fingerprint, "trusted_by_db": self.trusted_by_db}


@dataclass(frozen=True)
class BootEnvironmentIdentity:
    boot_environment_id: str
    esp_gpt_partuuid: str | None
    esp_filesystem_identity: str | None
    uefi_device_path: str | None
    boot_entry: EfiEntry | None
    secure_boot: bool | None
    setup_mode: bool | None
    audit_mode: bool | None
    deployed_mode: bool | None
    pk_fingerprints: tuple[str, ...] | None
    kek_fingerprints: tuple[str, ...] | None
    db_fingerprints: tuple[str, ...] | None
    dbx_fingerprints: tuple[str, ...] | None
    tpm_available: bool
    measured_boot_available: bool
    pcr_event_log_sha256: str | None
    actual_efi_image: EfiExecutable | None
    esp_candidates: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise SecureBootError("boot_environment_schema_unsupported")
        if self.esp_candidates != tuple(sorted(set(self.esp_candidates))):
            raise SecureBootError("boot_environment_esp_candidates_not_canonical")
        if self.missing_evidence != tuple(sorted(set(self.missing_evidence))):
            raise SecureBootError("boot_environment_missing_evidence_not_canonical")
        if any(item is not None and type(item) is not bool
               for item in (self.secure_boot, self.setup_mode, self.audit_mode, self.deployed_mode)):
            raise SecureBootError("boot_environment_firmware_state_invalid")
        if type(self.tpm_available) is not bool or type(self.measured_boot_available) is not bool:
            raise SecureBootError("boot_environment_tpm_state_invalid")
        expected = "bootenv-" + hashlib.sha256(
            b"maho-boot-environment-v1\0" + canonical_bytes(self.identity_material())
        ).hexdigest()
        if self.boot_environment_id != expected:
            raise SecureBootError("boot_environment_identity_mismatch")

    def identity_material(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "esp_gpt_partuuid": self.esp_gpt_partuuid,
            "esp_filesystem_identity": self.esp_filesystem_identity, "uefi_device_path": self.uefi_device_path,
            "boot_entry": self.boot_entry.as_dict() if self.boot_entry else None,
            "secure_boot": self.secure_boot, "setup_mode": self.setup_mode,
            "audit_mode": self.audit_mode, "deployed_mode": self.deployed_mode,
            "pk_fingerprints": list(self.pk_fingerprints) if self.pk_fingerprints is not None else None,
            "kek_fingerprints": list(self.kek_fingerprints) if self.kek_fingerprints is not None else None,
            "db_fingerprints": list(self.db_fingerprints) if self.db_fingerprints is not None else None,
            "dbx_fingerprints": list(self.dbx_fingerprints) if self.dbx_fingerprints is not None else None,
            "tpm_available": self.tpm_available, "measured_boot_available": self.measured_boot_available,
            "pcr_event_log_sha256": self.pcr_event_log_sha256,
            "actual_efi_image": self.actual_efi_image.as_dict() if self.actual_efi_image else None,
            "esp_candidates": list(self.esp_candidates), "missing_evidence": list(self.missing_evidence),
        }

    def as_dict(self) -> dict[str, Any]:
        return self.identity_material() | {"boot_environment_id": self.boot_environment_id}

    @classmethod
    def create(cls, **values: Any) -> "BootEnvironmentIdentity":
        values = dict(values)
        values["esp_candidates"] = tuple(sorted(set(values.get("esp_candidates", ()))))
        missing = set(values.get("missing_evidence", ()))
        for name in ("esp_gpt_partuuid", "esp_filesystem_identity", "uefi_device_path", "boot_entry",
                     "secure_boot", "setup_mode", "pk_fingerprints", "kek_fingerprints",
                     "db_fingerprints", "dbx_fingerprints", "actual_efi_image"):
            if values.get(name) is None:
                missing.add(name)
        if len(values["esp_candidates"]) != 1:
            missing.add("unambiguous_esp")
        values["missing_evidence"] = tuple(sorted(missing))
        material = {
            "schema_version": 1, "esp_gpt_partuuid": values["esp_gpt_partuuid"],
            "esp_filesystem_identity": values["esp_filesystem_identity"], "uefi_device_path": values["uefi_device_path"],
            "boot_entry": values["boot_entry"].as_dict() if values["boot_entry"] else None,
            "secure_boot": values["secure_boot"], "setup_mode": values["setup_mode"],
            "audit_mode": values["audit_mode"], "deployed_mode": values["deployed_mode"],
            "pk_fingerprints": list(values["pk_fingerprints"]) if values["pk_fingerprints"] is not None else None,
            "kek_fingerprints": list(values["kek_fingerprints"]) if values["kek_fingerprints"] is not None else None,
            "db_fingerprints": list(values["db_fingerprints"]) if values["db_fingerprints"] is not None else None,
            "dbx_fingerprints": list(values["dbx_fingerprints"]) if values["dbx_fingerprints"] is not None else None,
            "tpm_available": values["tpm_available"], "measured_boot_available": values["measured_boot_available"],
            "pcr_event_log_sha256": values["pcr_event_log_sha256"],
            "actual_efi_image": values["actual_efi_image"].as_dict() if values["actual_efi_image"] else None,
            "esp_candidates": list(values["esp_candidates"]), "missing_evidence": list(values["missing_evidence"]),
        }
        identity = "bootenv-" + hashlib.sha256(
            b"maho-boot-environment-v1\0" + canonical_bytes(material)
        ).hexdigest()
        return cls(boot_environment_id=identity, **values)

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "BootEnvironmentIdentity":
        fields = {"schema_version", "boot_environment_id", "esp_gpt_partuuid", "esp_filesystem_identity",
                  "uefi_device_path", "boot_entry", "secure_boot", "setup_mode", "audit_mode", "deployed_mode",
                  "pk_fingerprints", "kek_fingerprints", "db_fingerprints", "dbx_fingerprints", "tpm_available",
                  "measured_boot_available", "pcr_event_log_sha256", "actual_efi_image", "esp_candidates", "missing_evidence"}
        if not isinstance(value, Mapping) or set(value) != fields:
            raise SecureBootError("boot_environment_fields_invalid")
        entry_value, image_value = value["boot_entry"], value["actual_efi_image"]
        try:
            for name in ("secure_boot", "setup_mode", "audit_mode", "deployed_mode"):
                if value[name] is not None and type(value[name]) is not bool:
                    raise TypeError(name)
            if type(value["tpm_available"]) is not bool or type(value["measured_boot_available"]) is not bool:
                raise TypeError("tpm state")
            if entry_value is not None and set(entry_value) != {"name", "variable_sha256", "device_path"}:
                raise TypeError("boot entry")
            if image_value is not None and set(image_value) != {"esp_identity", "path", "sha256", "signer_fingerprint", "trusted_by_db"}:
                raise TypeError("EFI image")
            if image_value is not None and image_value["trusted_by_db"] is not None and type(image_value["trusted_by_db"]) is not bool:
                raise TypeError("EFI authorization")
            entry = None if entry_value is None else EfiEntry(
                str(entry_value["name"]), str(entry_value["variable_sha256"]), entry_value["device_path"])
            image = None if image_value is None else EfiExecutable(
                str(image_value["esp_identity"]), str(image_value["path"]), str(image_value["sha256"]),
                image_value["signer_fingerprint"], image_value["trusted_by_db"])
            def optional_tuple(name: str) -> tuple[str, ...] | None:
                item = value[name]
                return None if item is None else tuple(str(row) for row in item)
            return cls(
                str(value["boot_environment_id"]), value["esp_gpt_partuuid"], value["esp_filesystem_identity"],
                value["uefi_device_path"], entry, value["secure_boot"], value["setup_mode"], value["audit_mode"],
                value["deployed_mode"], optional_tuple("pk_fingerprints"), optional_tuple("kek_fingerprints"),
                optional_tuple("db_fingerprints"), optional_tuple("dbx_fingerprints"), value["tpm_available"],
                value["measured_boot_available"], value["pcr_event_log_sha256"], image,
                tuple(str(item) for item in value["esp_candidates"]), tuple(str(item) for item in value["missing_evidence"]),
                int(value["schema_version"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SecureBootError("boot_environment_content_invalid") from exc


def inspect_boot_environment(
    *, efivar_root: str | os.PathLike[str] = "/sys/firmware/efi/efivars",
    esp_candidates: Iterable[str] = (), actual_efi_image: EfiExecutable | None = None,
    esp_gpt_partuuid: str | None = None, esp_filesystem_identity: str | None = None,
    uefi_device_path: str | None = None,
) -> BootEnvironmentIdentity:
    """Inspect only.  This function has no firmware-writing operation."""
    root = Path(efivar_root)
    boot_current_payload = _efi_payload(root / f"BootCurrent-{EFI_GLOBAL_GUID}")
    entry: EfiEntry | None = None
    if boot_current_payload and len(boot_current_payload) >= 2:
        number = int.from_bytes(boot_current_payload[:2], "little")
        entry = next((item for item in inventory_boot_entries(root) if item.name == f"Boot{number:04X}"), None)
        if entry is not None and uefi_device_path is not None:
            entry = EfiEntry(entry.name, entry.variable_sha256, uefi_device_path)
    event_path = Path("/sys/kernel/security/tpm0/binary_bios_measurements")
    try:
        event_digest = hashlib.sha256(event_path.read_bytes()).hexdigest()
    except OSError:
        event_digest = None
    return BootEnvironmentIdentity.create(
        esp_gpt_partuuid=esp_gpt_partuuid, esp_filesystem_identity=esp_filesystem_identity,
        uefi_device_path=uefi_device_path, boot_entry=entry,
        secure_boot=_efi_bool(root, "SecureBoot"), setup_mode=_efi_bool(root, "SetupMode"),
        audit_mode=_efi_bool(root, "AuditMode"), deployed_mode=_efi_bool(root, "DeployedMode"),
        pk_fingerprints=_signature_database_identities(root, "PK"),
        kek_fingerprints=_signature_database_identities(root, "KEK"),
        db_fingerprints=_signature_database_identities(root, "db"),
        dbx_fingerprints=_signature_database_identities(root, "dbx"),
        tpm_available=Path("/sys/class/tpm/tpm0").exists(), measured_boot_available=event_digest is not None,
        pcr_event_log_sha256=event_digest, actual_efi_image=actual_efi_image,
        esp_candidates=tuple(esp_candidates), missing_evidence=(),
    )


def inventory_efi_executables(
    esp_roots: Mapping[str, str | os.PathLike[str]],
    signature_inspector: Callable[[Path], tuple[str | None, bool | None]] | None = None,
) -> tuple[EfiExecutable, ...]:
    rows: list[EfiExecutable] = []
    for esp_identity, raw_root in sorted(esp_roots.items()):
        root = Path(raw_root).resolve()
        efi = root / "EFI"
        if not efi.is_dir():
            continue
        for path in sorted(efi.rglob("*")):
            if not path.is_file() or path.suffix.lower() != ".efi":
                continue
            resolved = path.resolve()
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise SecureBootError("esp_path_escape") from exc
            signer, trusted = signature_inspector(resolved) if signature_inspector else (None, None)
            rows.append(EfiExecutable(esp_identity, "/" + str(resolved.relative_to(root)),
                                      hashlib.sha256(resolved.read_bytes()).hexdigest(), signer, trusted))
    return tuple(rows)


def inventory_bypass_reasons(
    inventory: Iterable[EfiExecutable], *, allowed: Mapping[str, str], trusted_signers: Iterable[str],
) -> tuple[str, ...]:
    expected = {path.lower(): digest for path, digest in allowed.items()}
    trusted = {certificate_fingerprint(item) for item in trusted_signers}
    reasons: list[str] = []
    seen: set[str] = set()
    for item in inventory:
        key = item.path.lower()
        if key in seen:
            reasons.append(f"duplicate_efi_path:{item.path}")
        seen.add(key)
        if key in expected and item.sha256 != expected[key]:
            reasons.append(f"efi_digest_mismatch:{item.path}")
        if key not in expected and item.signer_fingerprint and certificate_fingerprint(item.signer_fingerprint) in trusted:
            reasons.append(f"unexpected_trusted_efi:{item.path}")
    for path in expected:
        if path not in seen:
            reasons.append(f"expected_efi_missing:{path}")
    return tuple(sorted(set(reasons)))


class SigningProvider(Protocol):
    def enroll_config(self, clean_efi: bytes, config: bytes) -> bytes: ...
    def sign_efi(self, unsigned_efi: bytes) -> bytes: ...
    def verify_efi(self, signed_efi: bytes) -> tuple[bool, str | None]: ...
    def embedded_config_checksum(self, efi: bytes) -> str | None: ...


@dataclass(frozen=True)
class SealedLoader:
    signed_efi: bytes
    loader: LoaderIdentity
    config: BootArtifact


def seal_limine_loader(
    clean_efi: bytes, config: bytes, *, provider: SigningProvider,
    limine_version: str, loader_path: str, config_path: str,
    discovery_surface: Iterable[str], required_artifacts: Iterable[BootArtifact],
    metadata_transform: Callable[[bytes], bytes] | None = None,
) -> SealedLoader:
    """Enforce clean -> enroll config -> metadata -> sign -> independent verify."""
    if not clean_efi or not config:
        raise SecureBootError("limine_seal_input_missing")
    config_reasons = validate_limine_config(config)
    if config_reasons:
        raise SecureBootError("limine_config_policy_failed:" + ",".join(config_reasons))
    configured_hashes = sorted(re.findall(rb"#([0-9a-f]{128})(?=\s|$)", config))
    artifact_digests: list[Digest] = []
    for artifact in required_artifacts:
        digest = artifact.digest("blake2b-512", "limine-artifact-integrity")
        if digest is None:
            raise SecureBootError(f"limine_artifact_digest_missing:{artifact.identity}")
        artifact_digests.append(digest)
    artifact_digests.sort(key=lambda item: (item.algorithm, item.digest, item.purpose))
    if configured_hashes != sorted(item.digest.encode("ascii") for item in artifact_digests):
        raise SecureBootError("limine_config_artifact_binding_mismatch")
    config_checksum = Digest.calculate(config, algorithm="blake2b-512", purpose="limine-config-checksum")
    config_artifact = BootArtifact.from_bytes(
        config, artifact_type="limine-config", path=config_path,
        algorithms=(("blake2b-512", "limine-config-checksum"), ("sha256", "maho-content-identity")),
    )
    enrolled = provider.enroll_config(clean_efi, config)
    if enrolled == clean_efi:
        raise SecureBootError("limine_config_not_enrolled")
    transformed = metadata_transform(enrolled) if metadata_transform else enrolled
    signed = provider.sign_efi(transformed)
    if signed == transformed:
        raise SecureBootError("limine_loader_not_signed")
    valid, signer = provider.verify_efi(signed)
    if not valid or signer is None:
        raise SecureBootError("limine_signature_verification_failed")
    embedded = provider.embedded_config_checksum(signed)
    if embedded != config_checksum.digest:
        raise SecureBootError("limine_embedded_config_checksum_mismatch")
    loader_artifact = BootArtifact.from_bytes(signed, artifact_type="efi-loader", path=loader_path)
    loader = LoaderIdentity(loader_artifact, limine_version, certificate_fingerprint(signer), config_checksum,
                            config_path, tuple(sorted(set(discovery_surface))), tuple(artifact_digests))
    return SealedLoader(signed, loader, config_artifact)


class FakeSigningProvider:
    """Deterministic test provider; never presented as cryptographic signing."""
    def __init__(self, signer_fingerprint: str) -> None:
        self.signer_fingerprint = certificate_fingerprint(signer_fingerprint)

    def enroll_config(self, clean_efi: bytes, config: bytes) -> bytes:
        checksum = hashlib.blake2b(config, digest_size=64).hexdigest().encode("ascii")
        return clean_efi + b"\nMAHO-LIMINE-CONFIG-BLAKE2B=" + checksum

    def sign_efi(self, unsigned_efi: bytes) -> bytes:
        return unsigned_efi + b"\nMAHO-FAKE-SIGNER=" + self.signer_fingerprint.encode("ascii")

    def verify_efi(self, signed_efi: bytes) -> tuple[bool, str | None]:
        marker = b"\nMAHO-FAKE-SIGNER=" + self.signer_fingerprint.encode("ascii")
        return signed_efi.endswith(marker), self.signer_fingerprint if signed_efi.endswith(marker) else None

    def embedded_config_checksum(self, efi: bytes) -> str | None:
        marker = b"MAHO-LIMINE-CONFIG-BLAKE2B="
        position = efi.find(marker)
        if position < 0:
            return None
        return efi[position + len(marker):position + len(marker) + 128].decode("ascii", errors="ignore")


class SbctlProvider:
    """Allowlisted sbctl adapter.  There is deliberately no generic command method."""
    def __init__(self, executable: str = "/usr/bin/sbctl") -> None:
        self.executable = executable

    def _run(self, args: tuple[str, ...]) -> str:
        if args not in {("status",), ("list-files",)} and not (len(args) == 2 and args[0] == "verify"):
            raise SecureBootError("sbctl_operation_not_allowlisted")
        if len(args) == 2 and (not args[1].startswith("/") or "\0" in args[1]):
            raise SecureBootError("sbctl_path_invalid")
        result = subprocess.run((self.executable, *args), check=False, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            raise SecureBootError(f"sbctl_failed:{args[0]}")
        return result.stdout

    def status(self) -> str:
        return self._run(("status",))

    def list_files(self) -> str:
        return self._run(("list-files",))

    def verify(self, path: str) -> str:
        return self._run(("verify", path))


@dataclass(frozen=True)
class PostBootObservation:
    boot_generation_id: str | None
    boot_authority_id: str | None
    source_revision: str | None
    package_generation_id: str | None
    candidate_root_identity: str | None
    release_sequence: int | None
    security_epoch: int | None
    loader_sha256: str | None
    loader_signer_fingerprint: str | None
    embedded_config_checksum: str | None
    config_bytes: bytes | None
    artifact_bytes: Mapping[str, bytes]
    recovery_authority_identity: str | None
    guardian_proof_successful: bool
    revoked_generation_ids: tuple[str, ...] = ()
    authenticated_cmdline: bytes | None = None
    running_kernel_identity: str | None = None
    limine_version: str | None = None
    boot_mode: str | None = None


@dataclass(frozen=True)
class PostBootResult:
    trusted: bool
    state: str
    failures: tuple[str, ...]
    missing_evidence: tuple[str, ...]


def verify_postboot(
    generation: BootGeneration, authority: BootAuthority, environment: BootEnvironmentIdentity,
    observation: PostBootObservation, *, expected_pk: Iterable[str], expected_kek: Iterable[str],
    expected_db: Iterable[str], expected_dbx: Iterable[str], minimum_release_sequence: int,
    current_security_epoch: int, expected_esp_partuuid: str,
    expected_esp_filesystem_identity: str, expected_uefi_device_path: str,
    expected_boot_entry_name: str, expected_boot_mode: str = "normal",
    revoked_authority_ids: Iterable[str] = (),
) -> PostBootResult:
    failures: list[str] = []
    missing = list(environment.missing_evidence)
    if expected_boot_mode not in {"normal", "recovery"}:
        raise SecureBootError("postboot_expected_mode_invalid")
    selected_loader = generation.normal_loader if expected_boot_mode == "normal" else generation.recovery_loader
    selected_config = generation.normal_config if expected_boot_mode == "normal" else generation.recovery_config
    selected_kernel = generation.primary_kernel if expected_boot_mode == "normal" else generation.recovery_kernel
    if environment.secure_boot is not True: failures.append("secure_boot_not_enabled")
    if environment.setup_mode is not False: failures.append("setup_mode_not_disabled")
    if environment.esp_gpt_partuuid != expected_esp_partuuid: failures.append("esp_partuuid_mismatch")
    if environment.esp_filesystem_identity != expected_esp_filesystem_identity: failures.append("esp_filesystem_identity_mismatch")
    if environment.uefi_device_path != expected_uefi_device_path: failures.append("uefi_device_path_mismatch")
    if environment.boot_entry is None:
        missing.append("boot_entry")
    elif environment.boot_entry.name != expected_boot_entry_name:
        failures.append("boot_entry_mismatch")
    elif environment.boot_entry.device_path is None:
        missing.append("boot_entry_device_path")
    elif environment.boot_entry.device_path != expected_uefi_device_path:
        failures.append("boot_entry_device_path_mismatch")
    for name, observed, expected in (
        ("pk", environment.pk_fingerprints, tuple(sorted(expected_pk))),
        ("kek", environment.kek_fingerprints, tuple(sorted(expected_kek))),
        ("db", environment.db_fingerprints, tuple(sorted(expected_db))),
        ("dbx", environment.dbx_fingerprints, tuple(sorted(expected_dbx))),
    ):
        if observed is None:
            missing.append(f"{name}_fingerprints")
        elif tuple(sorted(observed)) != expected:
            failures.append(f"{name}_mismatch")
    try:
        authorize_freshness(authority, minimum_release_sequence=minimum_release_sequence,
                            current_security_epoch=current_security_epoch,
                            revoked_authority_ids=revoked_authority_ids)
    except BootContractError as exc:
        failures.append(str(exc))
    checks = {
        "boot_generation_mismatch": observation.boot_generation_id == generation.boot_generation_id == authority.permitted_boot_generation_id,
        "boot_authority_mismatch": observation.boot_authority_id == authority.boot_authority_id,
        "source_revision_mismatch": observation.source_revision == generation.source_revision == authority.source_revision,
        "package_generation_mismatch": observation.package_generation_id == generation.package_generation_id,
        "candidate_root_mismatch": observation.candidate_root_identity == generation.candidate_root_identity,
        "release_sequence_mismatch": observation.release_sequence == authority.release_sequence,
        "security_epoch_mismatch": observation.security_epoch == authority.security_epoch,
        "recovery_authority_mismatch": observation.recovery_authority_identity == authority.recovery_authority_identity,
        "guardian_proof_failed": observation.guardian_proof_successful,
        "running_kernel_mismatch": observation.running_kernel_identity == selected_kernel.identity,
        "limine_version_mismatch": observation.limine_version == selected_loader.limine_version,
        "unexpected_boot_environment": observation.boot_mode == expected_boot_mode,
    }
    failures.extend(reason for reason, valid in checks.items() if not valid)
    if generation.boot_generation_id in set(observation.revoked_generation_ids):
        failures.append("boot_generation_revoked")
    loader_sha = selected_loader.artifact.digest("sha256", "maho-content-identity")
    if observation.loader_sha256 is None: missing.append("loader_sha256")
    elif loader_sha is None or observation.loader_sha256 != loader_sha.digest: failures.append("loader_digest_mismatch")
    if environment.actual_efi_image is None:
        missing.append("actual_efi_image")
    else:
        actual = environment.actual_efi_image
        if actual.path != selected_loader.artifact.path: failures.append("actual_efi_path_mismatch")
        if loader_sha is None or actual.sha256 != loader_sha.digest: failures.append("actual_efi_digest_mismatch")
        if actual.signer_fingerprint is None: missing.append("actual_efi_signer")
        elif certificate_fingerprint(actual.signer_fingerprint) != certificate_fingerprint(authority.device_signing_certificate_fingerprint):
            failures.append("actual_efi_signer_mismatch")
        if actual.trusted_by_db is None: missing.append("actual_efi_db_authorization")
        elif actual.trusted_by_db is not True: failures.append("actual_efi_not_authorized_by_db")
    if observation.loader_signer_fingerprint is None: missing.append("loader_signer_fingerprint")
    elif certificate_fingerprint(observation.loader_signer_fingerprint) != certificate_fingerprint(authority.device_signing_certificate_fingerprint):
        failures.append("loader_signer_mismatch")
    if observation.embedded_config_checksum is None: missing.append("embedded_config_checksum")
    elif observation.embedded_config_checksum != selected_loader.embedded_config_checksum.digest:
        failures.append("embedded_config_checksum_mismatch")
    if observation.config_bytes is None: missing.append("config_bytes")
    else:
        for digest in selected_config.digests:
            calculated = Digest.calculate(observation.config_bytes, algorithm=digest.algorithm, purpose=digest.purpose)
            if calculated.digest != digest.digest:
                failures.append("limine_config_drift")
                break
    if observation.authenticated_cmdline is None:
        missing.append("authenticated_cmdline")
    else:
        for digest in generation.authenticated_cmdline.digests:
            calculated = Digest.calculate(observation.authenticated_cmdline, algorithm=digest.algorithm, purpose=digest.purpose)
            if calculated.digest != digest.digest:
                failures.append("authenticated_cmdline_mismatch")
                break
    required = (generation.primary_kernel, generation.primary_initramfs, generation.fallback_kernel,
                generation.fallback_initramfs, *generation.microcode, generation.recovery_kernel,
                generation.recovery_initramfs, generation.guardian_recovery_runtime)
    for artifact in required:
        content = observation.artifact_bytes.get(artifact.identity)
        if content is None:
            missing.append(f"artifact:{artifact.identity}")
            continue
        for digest in artifact.digests:
            if Digest.calculate(content, algorithm=digest.algorithm, purpose=digest.purpose).digest != digest.digest:
                failures.append(f"artifact_drift:{artifact.identity}")
                break
    if len(environment.esp_candidates) != 1:
        failures.append("esp_identity_ambiguous")
    failures, missing = sorted(set(failures)), sorted(set(missing))
    trusted = not failures and not missing
    return PostBootResult(trusted, "HEALTHY" if trusted else "UNTRUSTED", tuple(failures), tuple(missing))
