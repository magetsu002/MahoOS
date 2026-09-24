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


def classify_effect(path: str) -> EffectKind:
    """Return Guardian's canonical effect classification for an absolute path."""
    # Loader/interpreter policy can redirect execution before an application or
    # service reaches its own trust boundary.
    if (
        path in {
            "/etc/kernel/cmdline", "/etc/ld.so.preload", "/etc/ld.so.conf",
            "/etc/securetty",
        }
        or path.startswith((
            "/etc/kernel/cmdline.d/", "/boot/loader/",
            "/etc/ld.so.conf.d/", "/etc/binfmt.d/", "/usr/lib/binfmt.d/",
        ))
    ):
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
    if path in {
        "/etc/passwd", "/etc/group", "/etc/shadow", "/etc/gshadow",
        "/etc/subuid", "/etc/subgid", "/etc/login.defs",
        "/root/.ssh/authorized_keys",
    } or path.startswith((
        "/etc/sudoers", "/etc/polkit-1/", "/usr/share/polkit-1/rules.d/",
        "/etc/pam.d/", "/usr/lib/security/", "/etc/security/", "/etc/ssh/",
        "/etc/dbus-1/system.d/", "/usr/share/dbus-1/system.d/",
        "/etc/sysusers.d/", "/usr/lib/sysusers.d/",
        "/etc/udev/rules.d/", "/usr/lib/udev/rules.d/",
        "/etc/sysctl.d/", "/usr/lib/sysctl.d/",
    )):
        return EffectKind.PRIVILEGE_AUTHORITY
    if path.startswith(("/usr/share/libalpm/hooks/", "/etc/pacman.d/hooks/")):
        return EffectKind.PACMAN_HOOK
    if path in {
        "/etc/profile", "/etc/bash.bashrc", "/etc/environment",
        "/etc/zsh/zshenv", "/etc/zsh/zprofile", "/etc/zsh/zlogin",
    } or path.startswith((
        "/etc/xdg/autostart/", "/etc/systemd/user/", "/usr/lib/systemd/user/",
        "/etc/cron", "/var/spool/cron/", "/etc/profile.d/",
        "/etc/tmpfiles.d/", "/usr/lib/tmpfiles.d/",
        "/etc/NetworkManager/dispatcher.d/", "/usr/lib/NetworkManager/dispatcher.d/",
        "/etc/systemd/system-generators/", "/usr/lib/systemd/system-generators/",
        "/etc/systemd/user-generators/", "/usr/lib/systemd/user-generators/",
        "/etc/systemd/system-environment-generators/", "/usr/lib/systemd/system-environment-generators/",
        "/etc/systemd/user-environment-generators/", "/usr/lib/systemd/user-environment-generators/",
        "/root/.config/systemd/user/", "/root/.config/autostart/",
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
        kind = classify_effect(path)
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
    return _evaluate_effect_rows(
        transaction_id=graph.transaction_id,
        graph_id=graph.graph_id,
        inspection_complete=graph.inspection_complete,
        effects=((item.kind, item.declared) for item in graph.effects),
        known_safe_graph_ids=known_safe_graph_ids,
    )


def _evaluate_effect_rows(
    *, transaction_id: TransactionID, graph_id: ArtifactID,
    inspection_complete: bool, effects: Iterable[tuple[EffectKind, bool]],
    known_safe_graph_ids: Iterable[ArtifactID] = (),
) -> AdmissionDecision:
    known = {ArtifactID(str(item)) for item in known_safe_graph_ids}
    rows = tuple(effects)
    if not inspection_complete:
        return AdmissionDecision(AdmissionOutcome.REJECT, ("candidate_inspection_incomplete",), transaction_id, graph_id, False)
    if not rows:
        return AdmissionDecision(AdmissionOutcome.REJECT, ("candidate_has_no_observed_mutation",), transaction_id, graph_id, False)
    if graph_id in known:
        return AdmissionDecision(AdmissionOutcome.ALLOW, ("exact_known_safe_transition",), transaction_id, graph_id, True)
    undeclared_boundary = [kind for kind, declared in rows if kind in SECURITY_BOUNDARY_EFFECTS and not declared]
    if undeclared_boundary:
        reasons = tuple(sorted({f"undeclared_{kind.value.lower()}" for kind in undeclared_boundary}))
        return AdmissionDecision(AdmissionOutcome.REJECT, reasons, transaction_id, graph_id, False)
    declared_boundary = [kind for kind, _ in rows if kind in SECURITY_BOUNDARY_EFFECTS]
    undeclared_files = [kind for kind, declared in rows if not declared]
    if declared_boundary:
        reasons = tuple(sorted({f"review_{kind.value.lower()}" for kind in declared_boundary}))
        return AdmissionDecision(AdmissionOutcome.REVIEW, reasons, transaction_id, graph_id, False)
    if undeclared_files:
        return AdmissionDecision(AdmissionOutcome.REVIEW, ("declared_transaction_scope_exceeded",), transaction_id, graph_id, False)
    return AdmissionDecision(AdmissionOutcome.ALLOW, ("bounded_declared_transition",), transaction_id, graph_id, True)


def evaluate_serialized_admission(
    value: Mapping[str, Any], *, known_safe_graph_ids: Iterable[ArtifactID] = (),
) -> AdmissionDecision:
    """Validate and evaluate a persisted canonical graph without rescanning roots."""
    required = {"schema_version", "transaction_id", "effects", "inspection_complete", "graph_id"}
    if set(value) != required or value.get("schema_version") != 2:
        raise ValueError("serialized mutation graph schema invalid")
    try:
        transaction_id = TransactionID(str(value["transaction_id"]))
        graph_id = ArtifactID(str(value["graph_id"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("serialized mutation graph identity invalid") from exc
    effects = value.get("effects")
    complete = value.get("inspection_complete")
    if not isinstance(effects, list) or not isinstance(complete, bool):
        raise ValueError("serialized mutation graph content invalid")
    material = {
        "schema_version": 2,
        "transaction_id": str(transaction_id),
        "effects": effects,
        "inspection_complete": complete,
    }
    if ArtifactID.from_content(canonical_bytes(material)) != graph_id:
        raise ValueError("serialized mutation graph digest mismatch")
    rows: list[tuple[EffectKind, bool]] = []
    effect_fields = {
        "kind", "operation", "subject", "declared", "owner_before", "owner_after", "before", "after",
    }
    observation_fields = {
        "sha256", "mode", "package_owner", "file_type", "link_target", "uid", "gid",
        "xattrs_sha256", "security_capability",
    }
    for effect in effects:
        if not isinstance(effect, Mapping) or set(effect) != effect_fields:
            raise ValueError("serialized mutation effect invalid")
        try:
            kind = EffectKind(str(effect["kind"]))
        except ValueError as exc:
            raise ValueError("serialized mutation effect kind invalid") from exc
        if (
            effect.get("operation") not in {"ADD", "REMOVE", "CHANGE"}
            or not isinstance(effect.get("subject"), str)
            or not str(effect["subject"]).startswith("/")
            or ".." in str(effect["subject"]).split("/")
            or not isinstance(effect.get("declared"), bool)
            or not all(effect.get(name) is None or isinstance(effect.get(name), str) for name in ("owner_before", "owner_after"))
        ):
            raise ValueError("serialized mutation effect content invalid")
        for side in ("before", "after"):
            observation = effect.get(side)
            if observation is None:
                continue
            if not isinstance(observation, Mapping) or set(observation) != observation_fields:
                raise ValueError("serialized file observation invalid")
            try:
                FileObservation(
                    sha256=str(observation["sha256"]), mode=int(observation["mode"]),
                    package_owner=(str(observation["package_owner"]) if observation["package_owner"] is not None else None),
                    file_type=str(observation["file_type"]),
                    link_target=(str(observation["link_target"]) if observation["link_target"] is not None else None),
                    uid=int(observation["uid"]), gid=int(observation["gid"]),
                    xattrs_sha256=(str(observation["xattrs_sha256"]) if observation["xattrs_sha256"] is not None else None),
                    security_capability=(str(observation["security_capability"]) if observation["security_capability"] is not None else None),
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("serialized file observation content invalid") from exc
        rows.append((kind, bool(effect["declared"])))
    return _evaluate_effect_rows(
        transaction_id=transaction_id,
        graph_id=graph_id,
        inspection_complete=complete,
        effects=rows,
        known_safe_graph_ids=known_safe_graph_ids,
    )
