#!/usr/bin/env python3
"""Pure mutation-graph and admission policy for isolated candidate roots."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import posixpath
import re
from typing import Any, Iterable, Mapping

from maho_trust_identity import ArtifactID, TransactionID, canonical_bytes, canonical_json


class EffectKind(str, Enum):
    FILE = "FILE"
    SYSTEM_SERVICE = "SYSTEM_SERVICE"
    KERNEL_MODULE = "KERNEL_MODULE"
    BOOT_STATE = "BOOT_STATE"
    STARTUP_PERSISTENCE = "STARTUP_PERSISTENCE"
    PACMAN_HOOK = "PACMAN_HOOK"
    PRIVILEGE_AUTHORITY = "PRIVILEGE_AUTHORITY"
    LOADER_POLICY = "LOADER_POLICY"
    PACKAGE_FILE_OVERRIDE = "PACKAGE_FILE_OVERRIDE"
    NETWORK_LISTENER = "NETWORK_LISTENER"


class AdmissionOutcome(str, Enum):
    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


SECURITY_BOUNDARY_EFFECTS = {
    EffectKind.SYSTEM_SERVICE, EffectKind.KERNEL_MODULE, EffectKind.BOOT_STATE,
    EffectKind.STARTUP_PERSISTENCE, EffectKind.PACMAN_HOOK,
    EffectKind.PRIVILEGE_AUTHORITY, EffectKind.LOADER_POLICY,
    EffectKind.PACKAGE_FILE_OVERRIDE, EffectKind.NETWORK_LISTENER,
}


@dataclass(frozen=True)
class FileObservation:
    sha256: str
    mode: int
    package_owner: str | None
    file_type: str = "file"
    link_target: str | None = None
    uid: int = 0
    gid: int = 0
    xattrs_sha256: str | None = None
    security_capability: str | None = None

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("file observation requires SHA-256")
        if self.mode < 0 or self.mode > 0o7777:
            raise ValueError("file mode is invalid")
        if self.file_type not in {"file", "directory", "symlink", "other"}:
            raise ValueError("file observation type is invalid")
        if self.file_type == "symlink" and not isinstance(self.link_target, str):
            raise ValueError("symlink observation requires link target")
        if self.file_type != "symlink" and self.link_target is not None:
            raise ValueError("non-symlink observation cannot have link target")
        if self.uid < 0 or self.gid < 0:
            raise ValueError("file ownership identity is invalid")
        if self.xattrs_sha256 is not None and re.fullmatch(r"[0-9a-f]{64}", self.xattrs_sha256) is None:
            raise ValueError("extended attribute identity is invalid")
        if self.security_capability is not None and re.fullmatch(r"[0-9a-f]+", self.security_capability) is None:
            raise ValueError("file capability evidence is invalid")

    def as_dict(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "mode": self.mode,
            "package_owner": self.package_owner,
            "file_type": self.file_type,
            "link_target": self.link_target,
            "uid": self.uid,
            "gid": self.gid,
            "xattrs_sha256": self.xattrs_sha256,
            "security_capability": self.security_capability,
        }


@dataclass(frozen=True)
class CandidateDeclaration:
    package_identity: str
    path_prefixes: tuple[str, ...]
    effect_kinds: tuple[EffectKind, ...]
    package_identities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.package_identity:
            raise ValueError("candidate package identity is required")
        if any(not item for item in self.package_identities) or len(set(self.package_identities)) != len(self.package_identities):
            raise ValueError("candidate package identities must be unique and non-empty")
        for prefix in self.path_prefixes:
            if (
                not prefix.startswith("/")
                or prefix == "/"
                or ".." in prefix.split("/")
                or posixpath.normpath(prefix) != prefix
            ):
                raise ValueError("declared path prefix must be absolute and bounded")

    @property
    def allowed_package_identities(self) -> frozenset[str]:
        return frozenset(self.package_identities or (self.package_identity,))

    def declares(self, path: str, kind: EffectKind) -> bool:
        path_ok = any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in self.path_prefixes)
        return path_ok and kind in self.effect_kinds


@dataclass(frozen=True)
class MutationEffect:
    kind: EffectKind
    operation: str
    subject: str
    declared: bool
    owner_before: str | None = None
    owner_after: str | None = None
    before: FileObservation | None = None
    after: FileObservation | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value, "operation": self.operation,
            "subject": self.subject, "declared": self.declared,
            "owner_before": self.owner_before, "owner_after": self.owner_after,
            "before": self.before.as_dict() if self.before else None,
            "after": self.after.as_dict() if self.after else None,
        }


@dataclass(frozen=True)
class ListenerObservation:
    protocol: str
    address: str
    port: int

    def __post_init__(self) -> None:
        if self.protocol not in {"tcp", "udp"} or not self.address or not (1 <= self.port <= 65535):
            raise ValueError("listener observation is invalid")

    @property
    def subject(self) -> str:
        return f"{self.protocol}:{self.address}:{self.port}"


@dataclass(frozen=True)
class MutationGraph:
    transaction_id: TransactionID
    graph_id: ArtifactID
    effects: tuple[MutationEffect, ...]
    inspection_complete: bool

    def identity_material(self) -> dict[str, Any]:
        return {
            "schema_version": 2, "transaction_id": str(self.transaction_id),
            "effects": [item.as_dict() for item in self.effects],
            "inspection_complete": self.inspection_complete,
        }

    def canonical(self) -> str:
        return canonical_json(self.identity_material() | {"graph_id": str(self.graph_id)})


def _kind(path: str) -> EffectKind:
    if path in {"/etc/kernel/cmdline", "/etc/ld.so.preload", "/etc/securetty"} or path.startswith("/etc/kernel/cmdline.d/") or path.startswith("/boot/loader/"):
        return EffectKind.LOADER_POLICY
    if path.startswith((
        "/boot/", "/efi/", "/etc/mkinitcpio", "/usr/lib/initcpio/",
        "/usr/lib/kernel/install.d/", "/etc/kernel/install.d/",
    )):
        return EffectKind.BOOT_STATE
    if path.startswith((
        "/usr/lib/modules/", "/lib/modules/", "/usr/src/", "/var/lib/dkms/",
        "/etc/modules-load.d/", "/etc/modprobe.d/",
    )):
        return EffectKind.KERNEL_MODULE
    if path in {"/etc/passwd", "/etc/group", "/etc/shadow", "/etc/gshadow"} or path.startswith((
        "/etc/sudoers", "/etc/polkit-1/", "/usr/share/polkit-1/rules.d/",
        "/etc/pam.d/", "/usr/lib/security/", "/etc/ssh/",
    )):
        return EffectKind.PRIVILEGE_AUTHORITY
    if path.startswith(("/usr/share/libalpm/hooks/", "/etc/pacman.d/hooks/")):
        return EffectKind.PACMAN_HOOK
    if path.startswith((
        "/etc/xdg/autostart/", "/etc/systemd/user/", "/usr/lib/systemd/user/",
        "/etc/cron", "/var/spool/cron/", "/etc/profile.d/",
    )):
        return EffectKind.STARTUP_PERSISTENCE
    if path.startswith(("/etc/systemd/system/", "/usr/lib/systemd/system/")):
        if any(part.endswith((".wants", ".requires", ".upholds")) for part in path.split("/")):
            return EffectKind.STARTUP_PERSISTENCE
    if path.startswith(("/etc/systemd/system/", "/usr/lib/systemd/system/")) and path.endswith((".service", ".socket", ".timer", ".path", ".mount", ".automount")):
        return EffectKind.SYSTEM_SERVICE
    return EffectKind.FILE


def derive_mutation_graph(
    before: Mapping[str, FileObservation], after: Mapping[str, FileObservation], *,
    transaction_id: TransactionID, declaration: CandidateDeclaration,
    listeners: Iterable[ListenerObservation] = (), inspection_complete: bool = True,
) -> MutationGraph:
    effects: list[MutationEffect] = []
    all_paths = sorted(set(before) | set(after))
    for path in all_paths:
        if not path.startswith("/") or ".." in path.split("/"):
            raise ValueError("candidate-root observation path is invalid")
        old = before.get(path)
        new = after.get(path)
        if old == new:
            continue
        operation = "ADD" if old is None else "REMOVE" if new is None else "CHANGE"
        kind = _kind(path)
        owner_before = old.package_owner if old else None
        owner_after = new.package_owner if new else None
        effects.append(MutationEffect(
            kind=kind, operation=operation, subject=path,
            declared=declaration.declares(path, kind),
            owner_before=owner_before, owner_after=owner_after,
            before=old, after=new,
        ))
        if (
            new is not None
            and new.file_type == "file"
            and (new.mode & 0o6000 or new.security_capability is not None)
            and kind is not EffectKind.PRIVILEGE_AUTHORITY
        ):
            privileged = EffectKind.PRIVILEGE_AUTHORITY
            effects.append(MutationEffect(
                kind=privileged, operation=operation, subject=path,
                declared=declaration.declares(path, privileged),
                owner_before=owner_before, owner_after=owner_after,
                before=old, after=new,
            ))
        if old is not None and owner_before is not None and owner_before not in declaration.allowed_package_identities:
            override = EffectKind.PACKAGE_FILE_OVERRIDE
            effects.append(MutationEffect(
                kind=override, operation=operation, subject=path,
                declared=declaration.declares(path, override),
                owner_before=owner_before, owner_after=owner_after,
                before=old, after=new,
            ))
    for listener in sorted(listeners, key=lambda item: item.subject):
        kind = EffectKind.NETWORK_LISTENER
        effects.append(MutationEffect(
            kind=kind, operation="ADD", subject=listener.subject,
            declared=kind in declaration.effect_kinds,
        ))
    effects.sort(key=lambda item: (item.subject, item.kind.value, item.operation))
    material = {
        "schema_version": 2, "transaction_id": str(transaction_id),
        "effects": [item.as_dict() for item in effects],
        "inspection_complete": inspection_complete,
    }
    return MutationGraph(
        transaction_id=transaction_id,
        graph_id=ArtifactID.from_content(canonical_bytes(material)),
        effects=tuple(effects), inspection_complete=inspection_complete,
    )


@dataclass(frozen=True)
class AdmissionDecision:
    outcome: AdmissionOutcome
    reasons: tuple[str, ...]
    transaction_id: TransactionID
    graph_id: ArtifactID
    promotion_authorized: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value, "reasons": list(self.reasons),
            "transaction_id": str(self.transaction_id), "graph_id": str(self.graph_id),
            "promotion_authorized": self.promotion_authorized,
        }


def evaluate_admission(
    graph: MutationGraph, *, known_safe_graph_ids: Iterable[ArtifactID] = (),
) -> AdmissionDecision:
    known = {ArtifactID(str(item)) for item in known_safe_graph_ids}
    if not graph.inspection_complete:
        return AdmissionDecision(AdmissionOutcome.REJECT, ("candidate_inspection_incomplete",), graph.transaction_id, graph.graph_id, False)
    if not graph.effects:
        return AdmissionDecision(AdmissionOutcome.REJECT, ("candidate_has_no_observed_mutation",), graph.transaction_id, graph.graph_id, False)
    if graph.graph_id in known:
        return AdmissionDecision(AdmissionOutcome.ALLOW, ("exact_known_safe_transition",), graph.transaction_id, graph.graph_id, True)
    undeclared_boundary = [item for item in graph.effects if item.kind in SECURITY_BOUNDARY_EFFECTS and not item.declared]
    if undeclared_boundary:
        reasons = tuple(sorted({f"undeclared_{item.kind.value.lower()}" for item in undeclared_boundary}))
        return AdmissionDecision(AdmissionOutcome.REJECT, reasons, graph.transaction_id, graph.graph_id, False)
    declared_boundary = [item for item in graph.effects if item.kind in SECURITY_BOUNDARY_EFFECTS]
    undeclared_files = [item for item in graph.effects if not item.declared]
    if declared_boundary:
        reasons = tuple(sorted({f"review_{item.kind.value.lower()}" for item in declared_boundary}))
        return AdmissionDecision(AdmissionOutcome.REVIEW, reasons, graph.transaction_id, graph.graph_id, False)
    if undeclared_files:
        return AdmissionDecision(AdmissionOutcome.REVIEW, ("declared_transaction_scope_exceeded",), graph.transaction_id, graph.graph_id, False)
    return AdmissionDecision(AdmissionOutcome.ALLOW, ("bounded_declared_transition",), graph.transaction_id, graph.graph_id, True)
