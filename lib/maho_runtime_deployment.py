#!/usr/bin/env python3
"""Fail-closed deployment authority for the per-user Maho runtime."""
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DeploymentPlan:
    allowed: bool
    deployment_class: str
    source_revision: str | None
    source_dirty: bool | None
    transition: str
    trust_eligible: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", str(root), *args),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _release_revision(root: Path) -> str | None:
    path = root / "share/maho/release.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    value = raw.get("source_revision") if isinstance(raw, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _current_revision(current: Path | None) -> str | None:
    if current is None:
        return None
    try:
        raw = json.loads((current.resolve(strict=True) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    value = raw.get("source_revision") if isinstance(raw, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def plan_deployment(root: Path, current: Path | None, *, development: bool = False) -> DeploymentPlan:
    root = root.resolve()
    packaged_revision = _release_revision(root)
    head = _git(root, "rev-parse", "HEAD")
    is_checkout = head.returncode == 0
    revision = packaged_revision or (head.stdout.strip() if is_checkout else None)
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all") if is_checkout else None
    dirty = bool(status.stdout.strip()) if status is not None and status.returncode == 0 else None
    old = _current_revision(current)
    reasons: list[str] = []

    if revision is None:
        reasons.append("source_revision_unavailable")
    if packaged_revision is None and not is_checkout:
        reasons.append("source_provenance_unavailable")
    if is_checkout and status is not None and status.returncode != 0:
        reasons.append("source_cleanliness_unavailable")

    if old is None:
        transition = "bootstrap"
    elif old == revision:
        transition = "same-revision"
    elif packaged_revision is not None:
        # A packaged payload is admitted by the distribution package signature
        # boundary; its source tree intentionally contains no Git object graph.
        transition = "packaged-release"
    elif revision is not None and _git(root, "merge-base", "--is-ancestor", old, revision).returncode == 0:
        transition = "fast-forward"
    else:
        known_old = bool(old and _git(root, "cat-file", "-e", f"{old}^{{commit}}").returncode == 0)
        known_new = bool(revision and _git(root, "cat-file", "-e", f"{revision}^{{commit}}").returncode == 0)
        if known_old and known_new and _git(root, "merge-base", "--is-ancestor", revision, old).returncode == 0:
            transition = "downgrade"
        else:
            transition = "unrelated-or-unverifiable"

    if development:
        return DeploymentPlan(
            allowed=revision is not None,
            deployment_class="development",
            source_revision=revision,
            source_dirty=dirty,
            transition=transition,
            trust_eligible=False,
            reasons=tuple(reasons),
        )

    if dirty is True:
        reasons.append("source_checkout_dirty")
    if transition in {"downgrade", "unrelated-or-unverifiable"}:
        reasons.append(f"production_transition_{transition}")
    return DeploymentPlan(
        allowed=not reasons,
        deployment_class="production",
        source_revision=revision,
        source_dirty=dirty,
        transition=transition,
        trust_eligible=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="maho_runtime_deployment.py")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--current", type=Path)
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    plan = plan_deployment(args.source_root, args.current, development=args.development)
    print(json.dumps(plan.as_dict(), sort_keys=True, separators=(",", ":")))
    raise SystemExit(0 if plan.allowed else 1)


if __name__ == "__main__":
    main()
