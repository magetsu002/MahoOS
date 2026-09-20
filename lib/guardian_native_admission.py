#!/usr/bin/env python3
"""Native candidate-first admission boundary for offline system roots.

The boundary performs no package installation and no promotion.  It inspects an
already isolated candidate against its exact base, evaluates the shared
ALLOW/REVIEW/REJECT policy, and emits promotion authority only for ALLOW.
"""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterable, Mapping, Protocol, Sequence

from guardian_admission import (
    AdmissionDecision, AdmissionOutcome, CandidateDeclaration, EffectKind,
    FileObservation, ListenerObservation, MutationGraph,
    derive_mutation_graph, evaluate_admission,
)
from maho_trust_identity import ArtifactID, TransactionID, canonical_bytes


_EXCLUDED_ROOTS = {
    "/dev", "/home", "/media", "/mnt", "/proc", "/run", "/sys", "/tmp",
    "/var/cache", "/var/tmp",
}
_TRUSTED_RUNTIME_OBSERVERS = {"guardian-native-runtime-observer-v1"}


class NativeAdmissionError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateRoots:
    transaction_id: TransactionID
    candidate_id: str
    base_root: Path
    candidate_root: Path

    @classmethod
    def create(
        cls, *, transaction_id: TransactionID, candidate_id: str,
        base_root: str | os.PathLike[str], candidate_root: str | os.PathLike[str],
    ) -> "CandidateRoots":
        if not isinstance(candidate_id, str) or not candidate_id or len(candidate_id) > 256:
            raise NativeAdmissionError("candidate_identity_invalid")
        base = Path(base_root)
        candidate = Path(candidate_root)
        if not base.is_absolute() or not candidate.is_absolute():
            raise NativeAdmissionError("candidate_roots_must_be_absolute")
        try:
            base = base.resolve(strict=True)
            candidate = candidate.resolve(strict=True)
            base_stat = base.stat()
            candidate_stat = candidate.stat()
        except OSError as exc:
            raise NativeAdmissionError(f"candidate_root_unavailable:{type(exc).__name__}") from exc
        if not base.is_dir() or not candidate.is_dir():
            raise NativeAdmissionError("candidate_roots_must_be_directories")
        if candidate == Path("/") or candidate == base:
            raise NativeAdmissionError("candidate_is_not_isolated")
        if (base_stat.st_dev, base_stat.st_ino) == (candidate_stat.st_dev, candidate_stat.st_ino):
            raise NativeAdmissionError("candidate_aliases_base_root")
        if base in candidate.parents or candidate in base.parents:
            raise NativeAdmissionError("candidate_roots_overlap")
        return cls(transaction_id, candidate_id, base, candidate)


@dataclass(frozen=True)
class RuntimeListenerEvidence:
    candidate_id: str
    transaction_id: TransactionID
    base_root_identity: str
    candidate_root_identity: str
    observer_identity: str
    complete: bool
    isolated: bool
    before: tuple[ListenerObservation, ...]
    after: tuple[ListenerObservation, ...]
    evidence_sha256: str

    @property
    def introduced(self) -> tuple[ListenerObservation, ...]:
        old = {item.subject for item in self.before}
        return tuple(item for item in self.after if item.subject not in old)


@dataclass(frozen=True)
class NativeInspection:
    graph: MutationGraph
    candidate_id: str
    base_root_identity: str
    candidate_root_identity: str
    excluded_roots: tuple[str, ...]
    errors: tuple[str, ...]
    runtime_complete: bool
    runtime_isolated: bool
    runtime_evidence_sha256: str


@dataclass(frozen=True)
class PromotionAuthority:
    authority_id: ArtifactID
    transaction_id: TransactionID
    candidate_id: str
    graph_id: ArtifactID
    candidate_root_identity: str

    def identity_material(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "guardian-native-promotion-authority",
            "authority_scope": "promote-exact-admitted-candidate",
            "transaction_id": str(self.transaction_id),
            "candidate_id": self.candidate_id,
            "graph_id": str(self.graph_id),
            "candidate_root_identity": self.candidate_root_identity,
            "admission_outcome": "ALLOW",
        }

    def as_dict(self) -> dict[str, Any]:
        return self.identity_material() | {"authority_id": str(self.authority_id)}


@dataclass(frozen=True)
class NativeAdmissionResult:
    inspection: NativeInspection
    decision: AdmissionDecision
    promotion_authority: PromotionAuthority | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "guardian-native-admission-result",
            "candidate_id": self.inspection.candidate_id,
            "base_root_identity": self.inspection.base_root_identity,
            "candidate_root_identity": self.inspection.candidate_root_identity,
            "excluded_roots": list(self.inspection.excluded_roots),
            "inspection_errors": list(self.inspection.errors),
            "inspection_complete": self.inspection.graph.inspection_complete,
            "runtime_complete": self.inspection.runtime_complete,
            "runtime_isolated": self.inspection.runtime_isolated,
            "runtime_evidence_sha256": self.inspection.runtime_evidence_sha256,
            "mutation_graph": json.loads(self.inspection.graph.canonical()),
            "decision": self.decision.as_dict(),
            "promotion_authority": self.promotion_authority.as_dict() if self.promotion_authority else None,
        }


class CandidateFactory(Protocol):
    """Privileged provider that creates and observes one isolated generation."""

    def create_isolated_candidate(self, transaction_id: TransactionID) -> CandidateRoots: ...
    def observe_isolated_runtime(self, roots: CandidateRoots) -> RuntimeListenerEvidence: ...


def root_identity(root: Path) -> str:
    st = root.stat()
    material = {"path": str(root), "device": st.st_dev, "inode": st.st_ino}
    return hashlib.sha256(canonical_bytes(material)).hexdigest()


def _package_name(package_dir: Path) -> str | None:
    desc = package_dir / "desc"
    try:
        lines = desc.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeError):
        return None
    for index, line in enumerate(lines[:-1]):
        if line == "%NAME%" and lines[index + 1]:
            return lines[index + 1]
    return None


def package_ownership(root: Path) -> tuple[dict[str, str], tuple[str, ...]]:
    ownership: dict[str, str] = {}
    errors: list[str] = []
    package_names: set[str] = set()
    database = root / "var/lib/pacman/local"
    try:
        package_dirs = sorted(item for item in database.iterdir() if item.is_dir())
    except OSError as exc:
        return {}, (f"package_database_unavailable:{type(exc).__name__}",)
    for package_dir in package_dirs:
        name = _package_name(package_dir)
        if name is None:
            errors.append(f"package_identity_unreadable:{package_dir.name}")
            continue
        if name in package_names:
            errors.append(f"package_identity_ambiguous:{name}")
        package_names.add(name)
        manifest = package_dir / "files"
        try:
            raw_manifest = manifest.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError) as exc:
            errors.append(f"package_file_manifest_unreadable:{package_dir.name}:{type(exc).__name__}")
            continue
        # Pacman represents legitimate zero-file/meta packages with an existing
        # zero-byte local database `files` entry. That is complete ownership
        # evidence for an empty path set, not a missing manifest.
        if raw_manifest == "":
            continue
        lines = raw_manifest.splitlines()
        in_files = False
        for line in lines:
            if line == "%FILES%":
                in_files = True
                continue
            if in_files and line.startswith("%") and line.endswith("%"):
                break
            if not in_files or not line or line.endswith("/"):
                continue
            path = "/" + line.lstrip("/")
            if ".." in path.split("/") or "//" in path:
                errors.append(f"package_manifest_path_invalid:{package_dir.name}")
                continue
            previous = ownership.get(path)
            if previous is not None and previous != name:
                errors.append(f"package_ownership_ambiguous:{path}")
            else:
                ownership[path] = name
        if not in_files:
            errors.append(f"package_file_manifest_missing:{package_dir.name}")
    return ownership, tuple(errors)


def package_identities(root: Path) -> set[str]:
    database = root / "var/lib/pacman/local"
    try:
        names = {_package_name(item) for item in database.iterdir() if item.is_dir()}
    except OSError:
        return set()
    return {item for item in names if item is not None}


def _excluded(path: str) -> bool:
    return any(path == root or path.startswith(root + "/") for root in _EXCLUDED_ROOTS)


def _hash_regular(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _xattr_identity(path: Path) -> tuple[str, str | None]:
    rows: list[tuple[str, str]] = []
    capability: str | None = None
    for name in sorted(os.listxattr(path, follow_symlinks=False)):
        value = os.getxattr(path, name, follow_symlinks=False)
        encoded = value.hex()
        rows.append((name, encoded))
        if name == "security.capability":
            capability = encoded
    return hashlib.sha256(canonical_bytes(rows)).hexdigest(), capability


def filesystem_observations(
    root: Path, ownership: Mapping[str, str],
) -> tuple[dict[str, FileObservation], tuple[str, ...]]:
    observations: dict[str, FileObservation] = {}
    errors: list[str] = []
    root_dev = root.stat().st_dev
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            rel = "/" + str(directory.relative_to(root)) if directory != root else "/"
            errors.append(f"directory_unreadable:{rel}:{type(exc).__name__}")
            continue
        for entry in entries:
            path = Path(entry.path)
            rel = "/" + str(path.relative_to(root))
            if _excluded(rel):
                if rel == "/home" and entry.is_dir(follow_symlinks=False):
                    try:
                        with os.scandir(path) as home_entries:
                            if next(home_entries, None) is not None:
                                errors.append("personal_data_scope_not_isolated:/home")
                    except OSError as exc:
                        errors.append(f"personal_data_scope_unreadable:{type(exc).__name__}")
                continue
            try:
                st = entry.stat(follow_symlinks=False)
                mode = stat.S_IMODE(st.st_mode)
                owner = ownership.get(rel)
                if stat.S_ISDIR(st.st_mode):
                    if st.st_dev != root_dev:
                        errors.append(f"unexpected_mount_boundary:{rel}")
                    else:
                        xattrs, capability = _xattr_identity(path)
                        observations[rel] = FileObservation(
                            hashlib.sha256(b"directory").hexdigest(), mode, owner,
                            file_type="directory", uid=st.st_uid, gid=st.st_gid,
                            xattrs_sha256=xattrs, security_capability=capability,
                        )
                        stack.append(path)
                    continue
                if stat.S_ISREG(st.st_mode):
                    file_type = "file"
                    digest = _hash_regular(path)
                    target = None
                elif stat.S_ISLNK(st.st_mode):
                    file_type = "symlink"
                    target = os.readlink(path)
                    digest = hashlib.sha256(target.encode("utf-8", errors="surrogateescape")).hexdigest()
                else:
                    file_type = "other"
                    target = None
                    if stat.S_ISSOCK(st.st_mode):
                        special_kind = "socket"
                    elif stat.S_ISFIFO(st.st_mode):
                        special_kind = "fifo"
                    elif stat.S_ISCHR(st.st_mode):
                        special_kind = "char"
                    elif stat.S_ISBLK(st.st_mode):
                        special_kind = "block"
                    else:
                        special_kind = "other"
                    digest = hashlib.sha256(canonical_bytes({
                        "kind": special_kind,
                        "rdev": int(st.st_rdev),
                    })).hexdigest()
                xattrs, capability = _xattr_identity(path)
                observations[rel] = FileObservation(
                    digest, mode, owner, file_type=file_type, link_target=target,
                    uid=st.st_uid, gid=st.st_gid, xattrs_sha256=xattrs,
                    security_capability=capability,
                )
            except (OSError, UnicodeError) as exc:
                errors.append(f"path_unreadable:{rel}:{type(exc).__name__}")
    return observations, tuple(errors)


def _listener(value: Mapping[str, Any]) -> ListenerObservation:
    keys = set(value)
    if keys != {"protocol", "address", "port"}:
        raise NativeAdmissionError("runtime_listener_fields_invalid")
    try:
        return ListenerObservation(str(value["protocol"]), str(value["address"]), int(value["port"]))
    except (TypeError, ValueError) as exc:
        raise NativeAdmissionError("runtime_listener_invalid") from exc


def parse_runtime_evidence(value: Mapping[str, Any], *, roots: CandidateRoots) -> RuntimeListenerEvidence:
    required = {
        "schema_version", "kind", "candidate_id", "transaction_id",
        "base_root_identity", "candidate_root_identity", "observer_identity",
        "independently_observed", "network_namespace_isolated",
        "production_root_read_only", "execution_complete", "listeners_before", "listeners_after",
    }
    if set(value) != required or value.get("schema_version") != 1 or value.get("kind") != "candidate-runtime-observation":
        raise NativeAdmissionError("runtime_evidence_schema_invalid")
    if value.get("candidate_id") != roots.candidate_id:
        raise NativeAdmissionError("runtime_evidence_candidate_mismatch")
    if value.get("transaction_id") != str(roots.transaction_id):
        raise NativeAdmissionError("runtime_evidence_transaction_mismatch")
    base_identity = root_identity(roots.base_root)
    candidate_identity = root_identity(roots.candidate_root)
    if value.get("base_root_identity") != base_identity:
        raise NativeAdmissionError("runtime_evidence_base_root_mismatch")
    if value.get("candidate_root_identity") != candidate_identity:
        raise NativeAdmissionError("runtime_evidence_candidate_root_mismatch")
    observer = value.get("observer_identity")
    if observer not in _TRUSTED_RUNTIME_OBSERVERS or value.get("independently_observed") is not True:
        raise NativeAdmissionError("runtime_evidence_observer_invalid")
    before_raw = value.get("listeners_before")
    after_raw = value.get("listeners_after")
    if not isinstance(before_raw, list) or not isinstance(after_raw, list):
        raise NativeAdmissionError("runtime_listener_evidence_invalid")
    before = tuple(sorted((_listener(_mapping(item)) for item in before_raw), key=lambda item: item.subject))
    after = tuple(sorted((_listener(_mapping(item)) for item in after_raw), key=lambda item: item.subject))
    if len({item.subject for item in before}) != len(before) or len({item.subject for item in after}) != len(after):
        raise NativeAdmissionError("runtime_listener_identity_ambiguous")
    complete = value.get("execution_complete") is True
    isolated = value.get("network_namespace_isolated") is True and value.get("production_root_read_only") is True
    digest = hashlib.sha256(canonical_bytes(dict(value))).hexdigest()
    return RuntimeListenerEvidence(
        roots.candidate_id, roots.transaction_id, base_identity, candidate_identity,
        observer, complete, isolated, before, after, digest,
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NativeAdmissionError("evidence_item_not_an_object")
    return value


def inspect_candidate(
    roots: CandidateRoots,
    declaration: CandidateDeclaration,
    runtime: RuntimeListenerEvidence,
) -> NativeInspection:
    if (
        runtime.candidate_id != roots.candidate_id
        or runtime.transaction_id != roots.transaction_id
        or runtime.base_root_identity != root_identity(roots.base_root)
        or runtime.candidate_root_identity != root_identity(roots.candidate_root)
    ):
        raise NativeAdmissionError("runtime_evidence_root_binding_mismatch")
    before_owners, before_owner_errors = package_ownership(roots.base_root)
    after_owners, after_owner_errors = package_ownership(roots.candidate_root)
    before, before_errors = filesystem_observations(roots.base_root, before_owners)
    after, after_errors = filesystem_observations(roots.candidate_root, after_owners)
    errors = tuple(sorted(set(
        (*before_owner_errors, *after_owner_errors, *before_errors, *after_errors)
    )))
    available_packages = package_identities(roots.candidate_root)
    missing_packages = declaration.allowed_package_identities - available_packages
    if missing_packages:
        errors = tuple(sorted((*errors, "candidate_package_identity_unavailable")))
    complete = not errors and runtime.complete and runtime.isolated
    graph = derive_mutation_graph(
        before, after,
        transaction_id=roots.transaction_id,
        declaration=declaration,
        listeners=runtime.introduced,
        inspection_complete=complete,
    )
    return NativeInspection(
        graph=graph,
        candidate_id=roots.candidate_id,
        base_root_identity=root_identity(roots.base_root),
        candidate_root_identity=root_identity(roots.candidate_root),
        excluded_roots=tuple(sorted(_EXCLUDED_ROOTS)),
        errors=errors,
        runtime_complete=runtime.complete,
        runtime_isolated=runtime.isolated,
        runtime_evidence_sha256=runtime.evidence_sha256,
    )


def issue_promotion_authority(
    inspection: NativeInspection, decision: AdmissionDecision,
) -> PromotionAuthority:
    if decision.outcome is not AdmissionOutcome.ALLOW or not decision.promotion_authorized:
        raise NativeAdmissionError("admission_did_not_allow_promotion")
    if not inspection.graph.inspection_complete:
        raise NativeAdmissionError("incomplete_inspection_cannot_authorize_promotion")
    material = {
        "schema_version": 1,
        "kind": "guardian-native-promotion-authority",
        "authority_scope": "promote-exact-admitted-candidate",
        "transaction_id": str(decision.transaction_id),
        "candidate_id": inspection.candidate_id,
        "graph_id": str(decision.graph_id),
        "candidate_root_identity": inspection.candidate_root_identity,
        "admission_outcome": "ALLOW",
    }
    return PromotionAuthority(
        authority_id=ArtifactID.from_content(canonical_bytes(material)),
        transaction_id=decision.transaction_id,
        candidate_id=inspection.candidate_id,
        graph_id=decision.graph_id,
        candidate_root_identity=inspection.candidate_root_identity,
    )


def verify_promotion_authority(
    value: Mapping[str, Any], *, inspection: NativeInspection,
) -> PromotionAuthority:
    if set(value) != {
        "schema_version", "kind", "authority_scope", "transaction_id", "candidate_id",
        "graph_id", "candidate_root_identity", "admission_outcome", "authority_id",
    }:
        raise NativeAdmissionError("promotion_authority_fields_invalid")
    try:
        authority = PromotionAuthority(
            authority_id=ArtifactID(str(value["authority_id"])),
            transaction_id=TransactionID(str(value["transaction_id"])),
            candidate_id=str(value["candidate_id"]),
            graph_id=ArtifactID(str(value["graph_id"])),
            candidate_root_identity=str(value["candidate_root_identity"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise NativeAdmissionError("promotion_authority_invalid") from exc
    if value != authority.as_dict():
        raise NativeAdmissionError("promotion_authority_contract_invalid")
    expected_id = ArtifactID.from_content(canonical_bytes(authority.identity_material()))
    if authority.authority_id != expected_id:
        raise NativeAdmissionError("promotion_authority_digest_mismatch")
    if (
        authority.transaction_id != inspection.graph.transaction_id
        or authority.candidate_id != inspection.candidate_id
        or authority.graph_id != inspection.graph.graph_id
        or authority.candidate_root_identity != inspection.candidate_root_identity
        or not inspection.graph.inspection_complete
    ):
        raise NativeAdmissionError("promotion_authority_binding_mismatch")
    return authority


def revalidate_promotion_authority(
    value: Mapping[str, Any], *, roots: CandidateRoots,
    declaration: CandidateDeclaration, runtime: RuntimeListenerEvidence,
) -> tuple[PromotionAuthority, NativeInspection]:
    """Rescan the candidate at promotion time and reject all post-ALLOW drift."""
    current = inspect_candidate(roots, declaration, runtime)
    authority = verify_promotion_authority(value, inspection=current)
    return authority, current


def admit_candidate(
    roots: CandidateRoots,
    declaration: CandidateDeclaration,
    runtime: RuntimeListenerEvidence,
    *, known_safe_graph_ids: Iterable[ArtifactID] = (),
) -> NativeAdmissionResult:
    inspection = inspect_candidate(roots, declaration, runtime)
    decision = evaluate_admission(inspection.graph, known_safe_graph_ids=known_safe_graph_ids)
    authority = issue_promotion_authority(inspection, decision) if decision.outcome is AdmissionOutcome.ALLOW else None
    return NativeAdmissionResult(inspection, decision, authority)


def candidate_first_admission(
    factory: CandidateFactory,
    *, transaction_id: TransactionID,
    declaration: CandidateDeclaration,
    known_safe_graph_ids: Iterable[ArtifactID] = (),
) -> NativeAdmissionResult:
    """Enforce generation -> isolated observation -> admission ordering."""
    roots = factory.create_isolated_candidate(transaction_id)
    if roots.transaction_id != transaction_id:
        raise NativeAdmissionError("candidate_factory_transaction_mismatch")
    runtime = factory.observe_isolated_runtime(roots)
    return admit_candidate(
        roots, declaration, runtime,
        known_safe_graph_ids=known_safe_graph_ids,
    )


def parse_declaration(value: Mapping[str, Any]) -> CandidateDeclaration:
    version = value.get("schema_version")
    required = {"schema_version", "package_identity", "path_prefixes", "effect_kinds"}
    if version == 1:
        allowed = required
    elif version == 2:
        allowed = required | {"package_identities"}
    else:
        raise NativeAdmissionError("candidate_declaration_schema_invalid")
    if set(value) != allowed:
        raise NativeAdmissionError("candidate_declaration_schema_invalid")
    paths = value.get("path_prefixes")
    effects = value.get("effect_kinds")
    packages = value.get("package_identities", [])
    if not isinstance(paths, list) or not isinstance(effects, list) or not isinstance(packages, list):
        raise NativeAdmissionError("candidate_declaration_lists_invalid")
    try:
        return CandidateDeclaration(
            package_identity=str(value["package_identity"]),
            path_prefixes=tuple(str(item) for item in paths),
            effect_kinds=tuple(EffectKind(str(item)) for item in effects),
            package_identities=tuple(str(item) for item in packages),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise NativeAdmissionError("candidate_declaration_invalid") from exc


def _read_object(path: str, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise NativeAdmissionError(f"{label}_unreadable:{type(exc).__name__}") from exc
    return _mapping(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maho-admit")
    parser.add_argument("--base-root", required=True)
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--transaction-id", required=True)
    parser.add_argument("--declaration", required=True)
    parser.add_argument("--runtime-evidence", required=True)
    args = parser.parse_args(argv)
    try:
        roots = CandidateRoots.create(
            transaction_id=TransactionID(args.transaction_id),
            candidate_id=args.candidate_id,
            base_root=args.base_root,
            candidate_root=args.candidate_root,
        )
        declaration = parse_declaration(_read_object(args.declaration, "candidate_declaration"))
        runtime = parse_runtime_evidence(
            _read_object(args.runtime_evidence, "runtime_evidence"), roots=roots,
        )
        result = admit_candidate(roots, declaration, runtime)
    except (NativeAdmissionError, ValueError) as exc:
        print(json.dumps({
            "schema_version": 1,
            "kind": "guardian-native-admission-refusal",
            "outcome": "REJECT",
            "promotion_authority": None,
            "reason": str(exc),
        }, sort_keys=True))
        return 2
    print(json.dumps(result.as_dict(), sort_keys=True))
    return 0 if result.decision.outcome is AdmissionOutcome.ALLOW else 3


if __name__ == "__main__":
    raise SystemExit(main())
