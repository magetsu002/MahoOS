#!/usr/bin/env python3
"""Canonical verification for immutable Maho runtime releases."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any

_HEX64 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class ReleaseVerification:
    path: str
    verified: bool
    content_sha256: str | None
    source_revision: str | None
    reasons: tuple[str, ...]
    observed_content_sha256: str | None = None
    deployment_class: str | None = None
    source_dirty: bool | None = None
    trust_eligible: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _payload_hash(release: Path) -> str:
    """Match maho-setup's content identity: sorted regular files, manifest excluded."""
    lines: list[bytes] = []
    files = sorted(
        (p for p in release.rglob("*") if p.is_file() and p != release / "manifest.json"),
        key=lambda p: ("./" + p.relative_to(release).as_posix()).encode(),
    )
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rel = "./" + path.relative_to(release).as_posix()
        lines.append(f"{digest}  {rel}\n".encode())
    return hashlib.sha256(b"".join(lines)).hexdigest()


def _has_writable_payload(release: Path) -> bool:
    for path in (release, *release.rglob("*")):
        try:
            mode = path.stat(follow_symlinks=False).st_mode
        except OSError:
            return True
        if mode & 0o222:
            return True
    return False


def verify_release(candidate: str | os.PathLike[str], releases_root: str | os.PathLike[str]) -> ReleaseVerification:
    reasons: list[str] = []
    root = Path(releases_root).expanduser()
    path = Path(candidate).expanduser()
    try:
        root_real = root.resolve(strict=True)
        real = path.resolve(strict=True)
    except OSError:
        return ReleaseVerification(str(path), False, None, None, ("release_unavailable",))

    if real.parent != root_real:
        reasons.append("release_not_direct_child")
    name = real.name
    if _HEX64.fullmatch(name) is None:
        reasons.append("release_identity_invalid")

    manifest: dict[str, Any] | None = None
    try:
        raw = json.loads((real / "manifest.json").read_text(encoding="utf-8"))
        manifest = raw if isinstance(raw, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    if manifest is None:
        reasons.append("manifest_invalid")
        return ReleaseVerification(str(real), False, name if _HEX64.fullmatch(name) else None, None, tuple(reasons))

    if manifest.get("version") != 3:
        reasons.append("manifest_version_invalid")
    content = manifest.get("content_sha256")
    if not isinstance(content, str) or _HEX64.fullmatch(content) is None:
        reasons.append("manifest_content_identity_invalid")
        content = None
    elif content != name:
        reasons.append("manifest_content_identity_mismatch")

    revision = manifest.get("source_revision")
    if not isinstance(revision, str) or not revision.strip():
        reasons.append("source_revision_invalid")
        revision = None
    else:
        revision = revision.strip()

    classified = all(key in manifest for key in ("deployment_class", "source_dirty", "trust_eligible"))
    deployment_class = manifest.get("deployment_class") if classified else "legacy-unclassified"
    source_dirty = manifest.get("source_dirty") if classified else None
    trust_eligible = manifest.get("trust_eligible") if classified else False
    if deployment_class not in {"production", "development", "legacy-unclassified"}:
        reasons.append("deployment_class_invalid")
        deployment_class = None
    if classified and not isinstance(source_dirty, bool):
        reasons.append("source_dirty_invalid")
        source_dirty = None
    if not isinstance(trust_eligible, bool):
        reasons.append("trust_eligible_invalid")
        trust_eligible = False
    if deployment_class == "production" and (source_dirty is not False or trust_eligible is not True):
        reasons.append("production_deployment_authority_invalid")
    if deployment_class == "development" and trust_eligible is not False:
        reasons.append("development_deployment_trust_invalid")

    metadata: dict[str, Any] | None = None
    try:
        raw_metadata = json.loads((real / "share/maho/runtime-deployment.json").read_text(encoding="utf-8"))
        metadata = raw_metadata if isinstance(raw_metadata, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        # Version-3 releases created before deployment classification remain
        # byte-verifiable for rollback, but are not production-trust-eligible.
        metadata = None
    if classified and metadata is None:
        reasons.append("deployment_metadata_missing")
    if metadata is not None and any((
        metadata.get("deployment_class") != deployment_class,
        metadata.get("source_dirty") != source_dirty,
        metadata.get("trust_eligible") != trust_eligible,
    )):
        reasons.append("deployment_metadata_mismatch")

    try:
        provenance = (real / "share/maho/runtime-source-revision").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        provenance = ""
    if revision is None or provenance != revision:
        reasons.append("source_provenance_mismatch")

    try:
        observed_hash = _payload_hash(real)
    except OSError:
        observed_hash = None
        reasons.append("payload_unreadable")
    if observed_hash is not None and observed_hash != name:
        reasons.append("payload_content_identity_mismatch")

    if _has_writable_payload(real):
        reasons.append("immutable_payload_writable")

    reasons = list(dict.fromkeys(reasons))
    return ReleaseVerification(
        str(real),
        not reasons,
        content,
        revision,
        tuple(reasons),
        observed_content_sha256=observed_hash,
        deployment_class=deployment_class,
        source_dirty=source_dirty,
        trust_eligible=bool(trust_eligible and not reasons),
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="maho_runtime_release.py")
    parser.add_argument("candidate")
    parser.add_argument("--releases-root", required=True)
    args = parser.parse_args()
    result = verify_release(args.candidate, args.releases_root)
    print(json.dumps(result.as_dict(), sort_keys=True, separators=(",", ":")))
    raise SystemExit(0 if result.verified else 1)


if __name__ == "__main__":
    main()
