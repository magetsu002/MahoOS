#!/usr/bin/env python3
"""Fail-closed persistence baseline transitions backed by Maho Update authority."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Mapping


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _sections(path: Path) -> dict[str, list[str]]:
    lines = path.read_text(errors="replace").splitlines()
    result: dict[str, list[str]] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("%") and line.endswith("%"):
            key = line.strip("%")
            index += 1
            values: list[str] = []
            while index < len(lines) and lines[index]:
                values.append(lines[index])
                index += 1
            result[key] = values
        index += 1
    return result


def _first(value: Mapping[str, list[str]], key: str) -> str | None:
    rows = value.get(key) or []
    return rows[0] if rows else None


def _package_records(db_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for desc in sorted(db_root.glob("*/desc")) if db_root.is_dir() else ():
        try:
            metadata = _sections(desc)
            files_path = desc.parent / "files"
            files = _sections(files_path).get("FILES", []) if files_path.is_file() else metadata.get("FILES", [])
        except OSError:
            continue
        name = _first(metadata, "NAME")
        version = _first(metadata, "VERSION")
        if name and version:
            records.append({"name": name, "version": version, "files": files, "dir": desc.parent})
    return records


def _decode_mtree_path(value: str) -> str:
    value = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)
    return value.removeprefix("./").lstrip("/")


def _mtree_entry(path: Path, wanted: str) -> dict[str, str] | None:
    try:
        stream = gzip.open(path, "rt", errors="replace")
    except (OSError, gzip.BadGzipFile):
        return None
    defaults: dict[str, str] = {}
    try:
        for raw in stream:
            parts = raw.strip().split()
            if not parts or parts[0].startswith("#"):
                continue
            if parts[0] == "/set":
                for token in parts[1:]:
                    if "=" in token:
                        key, value = token.split("=", 1)
                        defaults[key] = value
                continue
            if parts[0] == "/unset":
                for key in parts[1:]:
                    defaults.pop(key, None)
                continue
            if _decode_mtree_path(parts[0]) != wanted:
                continue
            attributes = dict(defaults)
            for token in parts[1:]:
                if "=" in token:
                    key, value = token.split("=", 1)
                    attributes[key] = value
            return attributes
    finally:
        stream.close()
    return None


def _relative_package_path(path: Path, fs_root: Path) -> str:
    try:
        return str(path.relative_to(fs_root)).lstrip("/")
    except ValueError as exc:
        raise ValueError(f"persistence path is outside the observed filesystem root: {path}") from exc


def _verify_package_file(
    item: Mapping[str, Any], *, db_root: Path, fs_root: Path,
    candidates: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    before = item.get("before")
    after = item.get("after")
    raw_path = item.get("path")
    if not isinstance(raw_path, str) or not isinstance(before, Mapping) or not isinstance(after, Mapping):
        raise ValueError("transition contains a malformed changed-file record")
    if before.get("type") != "file" or after.get("type") != "file":
        raise ValueError(f"package transition only admits regular files: {raw_path}")
    before_sha = before.get("sha256")
    after_sha = after.get("sha256")
    if not isinstance(before_sha, str) or SHA256_RE.fullmatch(before_sha) is None:
        raise ValueError(f"baseline has no exact before digest: {raw_path}")
    if not isinstance(after_sha, str) or SHA256_RE.fullmatch(after_sha) is None:
        raise ValueError(f"current state has no exact after digest: {raw_path}")

    path = Path(raw_path)
    relative = _relative_package_path(path, fs_root)
    owner = None
    for record in _package_records(db_root):
        normalized = {value.strip().lstrip("/") for value in record["files"] if value and not value.endswith("/")}
        if relative in normalized:
            if owner is not None:
                raise ValueError(f"multiple installed packages claim persistence path: {raw_path}")
            owner = record
    if owner is None:
        raise ValueError(f"no installed package owns persistence path: {raw_path}")
    candidate = candidates.get(owner["name"])
    if candidate is None:
        raise ValueError(f"owning package is absent from the authorized update: {owner['name']}")
    if candidate.get("candidate_version") != owner["version"]:
        raise ValueError(f"installed owner version does not match the update candidate: {owner['name']}")
    if not isinstance(candidate.get("installed_version"), str) or not candidate["installed_version"]:
        raise ValueError(f"update has no exact before version for owner: {owner['name']}")

    attributes = _mtree_entry(owner["dir"] / "mtree", relative)
    if not attributes or attributes.get("type") != "file":
        raise ValueError(f"package mtree has no regular-file authority for: {raw_path}")
    mtree_sha = attributes.get("sha256digest", "").lower()
    if mtree_sha != after_sha:
        raise ValueError(f"current persistence digest differs from package metadata: {raw_path}")
    try:
        file_stat = path.lstat()
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError(f"cannot re-read current persistence file: {raw_path}") from exc
    if not stat.S_ISREG(file_stat.st_mode) or actual_sha != after_sha:
        raise ValueError(f"current persistence file changed during verification: {raw_path}")

    return {
        "path": raw_path,
        "kind": after.get("kind"),
        "before": {"type": "file", "sha256": before_sha},
        "after": {"type": "file", "sha256": after_sha},
        "package": owner["name"],
        "before_version": candidate["installed_version"],
        "after_version": owner["version"],
        "package_mtree_sha256": mtree_sha,
    }


def build_transition_plan(
    *, baseline: Mapping[str, Any], check: Mapping[str, Any],
    transaction: Mapping[str, Any], publication: Mapping[str, Any],
    db_root: Path, fs_root: Path, transaction_sha256: str,
    publication_sha256: str,
) -> dict[str, Any]:
    """Return the exact narrow baseline replacement or fail closed."""
    txid = transaction.get("transaction_id")
    package_generation = transaction.get("package_generation")
    if transaction.get("state") != "HEALTHY" or transaction.get("blockers") != []:
        raise ValueError("persistence transition requires an unblocked HEALTHY update")
    activation = transaction.get("activation")
    recovery = transaction.get("recovery")
    if not isinstance(activation, Mapping) or activation.get("native_execution_certified") is not True:
        raise ValueError("persistence transition requires certified native update execution")
    if not isinstance(recovery, Mapping) or recovery.get("native_l3_certified") is not True:
        raise ValueError("persistence transition requires certified native recovery authority")
    if not isinstance(package_generation, Mapping):
        raise ValueError("update package generation is missing")
    package_generation_id = package_generation.get("id")
    if any(publication.get(key) != expected for key, expected in (
        ("transaction_id", txid),
        ("source_revision", transaction.get("source_revision")),
        ("package_generation_id", package_generation_id),
    )):
        raise ValueError("current generation publication does not match the update transaction")
    if publication.get("fsroot") != "/@" or publication.get("previous_root_read_only") is not True:
        raise ValueError("current generation lacks the required post-reboot root proof")
    for key in ("publication_id", "system_generation_id", "kernel_generation_id"):
        if not isinstance(publication.get(key), str) or not publication[key]:
            raise ValueError(f"current generation publication is missing {key}")
    if baseline.get("state_sha256") != check.get("baseline_state_sha256"):
        raise ValueError("persistence check is not bound to the selected baseline")
    if check.get("attention_result") != "changed":
        raise ValueError("there is no unexplained persistence transition to authorize")
    if check.get("unexpected_added") or check.get("unexpected_removed"):
        raise ValueError("package transition does not admit added or removed persistence entries")
    changed = check.get("unexpected_changed")
    if not isinstance(changed, list) or not changed:
        raise ValueError("package transition has no exact changed files")

    packages = package_generation.get("packages")
    if not isinstance(packages, list):
        raise ValueError("update package inventory is missing")
    candidates = {str(item.get("name")): item for item in packages if isinstance(item, Mapping)}
    verified = [
        _verify_package_file(item, db_root=db_root, fs_root=fs_root, candidates=candidates)
        for item in changed
    ]

    inventory = baseline.get("inventory")
    if not isinstance(inventory, Mapping) or not isinstance(inventory.get("items"), list):
        raise ValueError("trusted persistence baseline inventory is malformed")
    target_items = {str(item.get("path")): dict(item) for item in inventory["items"] if isinstance(item, Mapping)}
    for item, proof in zip(changed, verified, strict=True):
        path = proof["path"]
        if target_items.get(path) != item.get("before"):
            raise ValueError(f"changed-file before state does not match the trusted baseline: {path}")
        target_items[path] = dict(item["after"])
    target_inventory = {
        "version": inventory.get("version"),
        "kind": inventory.get("kind"),
        "items": sorted(target_items.values(), key=lambda item: (str(item.get("kind")), str(item.get("path")))),
    }
    target_state = stable_hash(target_inventory)
    material = {
        "kind": "persistence-package-transition-plan",
        "previous_baseline_state_sha256": baseline.get("state_sha256"),
        "target_state_sha256": target_state,
        "transaction_id": txid,
        "transaction_sha256": transaction_sha256,
        "source_revision": transaction.get("source_revision"),
        "package_generation_id": package_generation_id,
        "publication_id": publication["publication_id"],
        "publication_sha256": publication_sha256,
        "system_generation_id": publication["system_generation_id"],
        "kernel_generation_id": publication["kernel_generation_id"],
        "changes": verified,
    }
    return {
        **material,
        "plan_sha256": stable_hash(material),
        "target_inventory": target_inventory,
    }
