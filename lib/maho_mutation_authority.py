#!/usr/bin/env python3
"""Exact, short-lived mutation authorities for the prevention boundary.

Authorities are machine-local HMAC envelopes.  Issuance is downstream of an
already-verified Maho transaction authority; executable names or uid 0 alone
never authorize a mutation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Iterable, Mapping

from guardian_admission import EffectKind
from maho_prevention_policy import AuthorityView, MutationOperation, SubjectIdentity
from maho_prevention_scope import normalize_target
from maho_trust_identity import ArtifactID, canonical_bytes


SCHEMA_VERSION = 1
NORMAL_MAX_LIFETIME_NS = 60 * 60 * 1_000_000_000
BREAK_GLASS_MAX_LIFETIME_NS = 5 * 60 * 1_000_000_000
PARENT_KINDS = frozenset({
    "maho-update-admission-activation-authority",
    "guardian-recovery-execution-authority",
    "maho-generation-activation-authority",
    "maho-boot-publication-authority",
    "maho-platform-install-authority",
})
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SHA40 = re.compile(r"[0-9a-f]{40}")


class MutationAuthorityError(ValueError):
    pass


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def process_identity(pid: int) -> SubjectIdentity:
    """Capture identity that changes across PID reuse and executable replacement."""
    if not isinstance(pid, int) or pid <= 0:
        raise MutationAuthorityError("subject_pid_invalid")
    proc = Path("/proc") / str(pid)
    try:
        fields = (proc / "stat").read_text(encoding="utf-8").split()
        start_ticks = int(fields[21])
        exe = (proc / "exe").resolve(strict=True)
        info = exe.stat()
        status = (proc / "status").read_text(encoding="utf-8").splitlines()
        uid_line = next(line for line in status if line.startswith("Uid:"))
        uid = int(uid_line.split()[1])
        digest = _file_sha256(exe)
    except (OSError, StopIteration, ValueError, IndexError) as exc:
        raise MutationAuthorityError("subject_identity_unavailable") from exc
    return SubjectIdentity(
        pid=pid, start_time_ns=start_ticks, executable_path=str(exe),
        executable_sha256=digest, executable_device=info.st_dev,
        executable_inode=info.st_ino, uid=uid,
    )


@dataclass(frozen=True)
class MutationAuthority:
    authority_id: ArtifactID
    transaction_id: str
    parent_authority_id: str
    parent_kind: str
    subject: SubjectIdentity
    effects: tuple[EffectKind, ...]
    operations: tuple[MutationOperation, ...]
    target_prefixes: tuple[str, ...]
    issued_at_ns: int
    expires_at_ns: int
    boot_id: str
    source_revision: str | None
    generation_id: str | None
    break_glass: bool
    mac_sha256: str

    def unsigned_material(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "maho-exact-mutation-authority",
            "transaction_id": self.transaction_id,
            "parent_authority_id": self.parent_authority_id,
            "parent_kind": self.parent_kind,
            "subject": {
                "pid": self.subject.pid,
                "start_time_ns": self.subject.start_time_ns,
                "executable_path": self.subject.executable_path,
                "executable_sha256": self.subject.executable_sha256,
                "executable_device": self.subject.executable_device,
                "executable_inode": self.subject.executable_inode,
                "uid": self.subject.uid,
            },
            "effects": [item.value for item in self.effects],
            "operations": [item.value for item in self.operations],
            "target_prefixes": list(self.target_prefixes),
            "issued_at_ns": self.issued_at_ns,
            "expires_at_ns": self.expires_at_ns,
            "boot_id": self.boot_id,
            "source_revision": self.source_revision,
            "generation_id": self.generation_id,
            "break_glass": self.break_glass,
        }

    def signed_material(self) -> dict[str, Any]:
        return self.unsigned_material() | {"mac_sha256": self.mac_sha256}

    def as_dict(self) -> dict[str, Any]:
        return self.signed_material() | {"authority_id": str(self.authority_id)}

    def as_view(self) -> AuthorityView:
        return AuthorityView(
            state="CURRENT", transaction_id=self.transaction_id, subject=self.subject,
            effects=frozenset(self.effects), operations=frozenset(self.operations),
            target_prefixes=self.target_prefixes, expires_at_ns=self.expires_at_ns,
            source_revision=self.source_revision, generation_id=self.generation_id,
            break_glass=self.break_glass,
        )


def _validate_issue(
    *, transaction_id: str, parent_authority_id: str, parent_kind: str,
    effects: Iterable[EffectKind], operations: Iterable[MutationOperation],
    target_prefixes: Iterable[str], issued_at_ns: int, expires_at_ns: int,
    boot_id: str, source_revision: str | None, break_glass: bool,
) -> tuple[tuple[EffectKind, ...], tuple[MutationOperation, ...], tuple[str, ...]]:
    if not transaction_id or len(transaction_id) > 256 or not parent_authority_id:
        raise MutationAuthorityError("transaction_authority_identity_invalid")
    if break_glass:
        if parent_kind != "maho-break-glass-authentication" or not transaction_id.startswith("break-glass-"):
            raise MutationAuthorityError("break_glass_parent_invalid")
        lifetime = BREAK_GLASS_MAX_LIFETIME_NS
    else:
        if parent_kind not in PARENT_KINDS:
            raise MutationAuthorityError("parent_authority_kind_invalid")
        lifetime = NORMAL_MAX_LIFETIME_NS
    if issued_at_ns < 0 or expires_at_ns <= issued_at_ns or expires_at_ns - issued_at_ns > lifetime:
        raise MutationAuthorityError("authority_lifetime_invalid")
    if not boot_id or source_revision is not None and _SHA40.fullmatch(source_revision) is None:
        raise MutationAuthorityError("authority_context_invalid")
    effect_values = tuple(sorted(set(effects), key=lambda item: item.value))
    operation_values = tuple(sorted(set(operations), key=lambda item: item.value))
    targets = tuple(sorted({normalize_target(path) for path in target_prefixes}))
    if not effect_values or not operation_values or not targets or "/" in targets:
        raise MutationAuthorityError("authority_scope_invalid")
    return effect_values, operation_values, targets


def issue_authority(
    *, secret: bytes, transaction_id: str, parent_authority_id: str,
    parent_kind: str, subject: SubjectIdentity, effects: Iterable[EffectKind],
    operations: Iterable[MutationOperation], target_prefixes: Iterable[str],
    issued_at_ns: int, expires_at_ns: int, boot_id: str,
    source_revision: str | None, generation_id: str | None,
    break_glass: bool = False,
) -> MutationAuthority:
    if len(secret) < 32 or _SHA256.fullmatch(subject.executable_sha256) is None:
        raise MutationAuthorityError("authority_secret_or_subject_invalid")
    effect_values, operation_values, targets = _validate_issue(
        transaction_id=transaction_id, parent_authority_id=parent_authority_id,
        parent_kind=parent_kind, effects=effects, operations=operations,
        target_prefixes=target_prefixes, issued_at_ns=issued_at_ns,
        expires_at_ns=expires_at_ns, boot_id=boot_id,
        source_revision=source_revision, break_glass=break_glass,
    )
    provisional = MutationAuthority(
        ArtifactID.from_content(b"placeholder"), transaction_id, parent_authority_id,
        parent_kind, subject, effect_values, operation_values, targets,
        issued_at_ns, expires_at_ns, boot_id, source_revision, generation_id,
        break_glass, "0" * 64,
    )
    mac = hmac.new(secret, canonical_bytes(provisional.unsigned_material()), hashlib.sha256).hexdigest()
    signed = provisional.unsigned_material() | {"mac_sha256": mac}
    return MutationAuthority(
        ArtifactID.from_content(canonical_bytes(signed)), transaction_id,
        parent_authority_id, parent_kind, subject, effect_values,
        operation_values, targets, issued_at_ns, expires_at_ns, boot_id,
        source_revision, generation_id, break_glass, mac,
    )


def parse_authority(payload: Mapping[str, Any], *, secret: bytes, boot_id: str, now_ns: int) -> MutationAuthority:
    expected = {
        "schema_version", "kind", "transaction_id", "parent_authority_id", "parent_kind",
        "subject", "effects", "operations", "target_prefixes", "issued_at_ns",
        "expires_at_ns", "boot_id", "source_revision", "generation_id", "break_glass",
        "mac_sha256", "authority_id",
    }
    if set(payload) != expected or payload.get("schema_version") != SCHEMA_VERSION or payload.get("kind") != "maho-exact-mutation-authority":
        raise MutationAuthorityError("authority_fields_invalid")
    try:
        raw_subject = payload["subject"]
        if not isinstance(raw_subject, Mapping) or set(raw_subject) != {
            "pid", "start_time_ns", "executable_path", "executable_sha256",
            "executable_device", "executable_inode", "uid",
        }:
            raise MutationAuthorityError("authority_subject_fields_invalid")
        subject = SubjectIdentity(**{key: raw_subject[key] for key in raw_subject})
        authority = issue_authority(
            secret=secret, transaction_id=str(payload["transaction_id"]),
            parent_authority_id=str(payload["parent_authority_id"]), parent_kind=str(payload["parent_kind"]),
            subject=subject, effects=(EffectKind(item) for item in payload["effects"]),
            operations=(MutationOperation(item) for item in payload["operations"]),
            target_prefixes=(str(item) for item in payload["target_prefixes"]),
            issued_at_ns=int(payload["issued_at_ns"]), expires_at_ns=int(payload["expires_at_ns"]),
            boot_id=str(payload["boot_id"]), source_revision=payload["source_revision"],
            generation_id=payload["generation_id"], break_glass=payload["break_glass"] is True,
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, MutationAuthorityError):
            raise
        raise MutationAuthorityError("authority_payload_invalid") from exc
    if not hmac.compare_digest(authority.mac_sha256, str(payload["mac_sha256"])) or authority.as_dict() != dict(payload):
        raise MutationAuthorityError("authority_authentication_failed")
    if authority.boot_id != boot_id:
        raise MutationAuthorityError("authority_boot_identity_mismatch")
    if now_ns >= authority.expires_at_ns:
        raise MutationAuthorityError("authority_expired")
    return authority


def create_secret(path: Path) -> None:
    """Create the broker secret once; refuse weak ownership or permissions."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        info = path.stat()
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
            raise MutationAuthorityError("authority_secret_permissions_invalid")
        return
    try:
        os.write(fd, os.urandom(32))
        os.fsync(fd)
    finally:
        os.close(fd)

