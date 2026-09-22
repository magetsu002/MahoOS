#!/usr/bin/env python3
"""Explicit authenticated, one-scope break-glass authorization."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import uuid

from guardian_admission import EffectKind
from maho_mutation_authority import (
    BREAK_GLASS_MAX_LIFETIME_NS, MutationAuthority, MutationAuthorityError,
    create_secret, issue_authority, process_identity,
)
from maho_prevention_kernel import project_authority
from maho_prevention_policy import MutationOperation
from maho_prevention_scope import TargetContext, classify_target


@dataclass(frozen=True)
class BreakGlassRequest:
    pid: int
    target: str
    effect: EffectKind
    operation: MutationOperation
    duration_seconds: int
    caller_uid: int

    @property
    def confirmation(self) -> str:
        return f"BYPASS {self.target} FOR {self.operation.value}"


def validate_request(request: BreakGlassRequest, *, context: TargetContext) -> None:
    if request.pid <= 1 or request.caller_uid < 0:
        raise MutationAuthorityError("break_glass_subject_invalid")
    if not 1 <= request.duration_seconds <= BREAK_GLASS_MAX_LIFETIME_NS // 1_000_000_000:
        raise MutationAuthorityError("break_glass_duration_invalid")
    scope = classify_target(request.target, context=context)
    if not scope.protected or scope.effect is not request.effect:
        raise MutationAuthorityError("break_glass_scope_or_effect_mismatch")


def _audit(path: Path, request: BreakGlassRequest, authority: MutationAuthority) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    record = {
        "schema_version": 1, "kind": "maho-break-glass-audit",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "caller_uid": request.caller_uid, "authority_id": str(authority.authority_id),
        "transaction_id": authority.transaction_id, "target": request.target,
        "effect": request.effect.value, "operation": request.operation.value,
        "expires_at_boot_ns": authority.expires_at_ns,
        "permanent_disable": False,
    }
    try:
        os.write(fd, (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)


def authorize(
    request: BreakGlassRequest, *, confirmation: str, authenticated: bool,
    context: TargetContext, secret_path: Path, map_path: Path, audit_path: Path,
    boot_id: str, source_revision: str | None = None,
) -> MutationAuthority:
    if not authenticated or os.geteuid() != 0:
        raise PermissionError("break glass requires fresh administrative authentication")
    validate_request(request, context=context)
    if confirmation != request.confirmation:
        raise PermissionError("break glass confirmation did not match exact scope and operation")
    create_secret(secret_path)
    secret = secret_path.read_bytes()
    now_ns = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    transaction = "break-glass-" + uuid.uuid4().hex
    authority = issue_authority(
        secret=secret, transaction_id=transaction,
        parent_authority_id="polkit-session-" + uuid.uuid4().hex,
        parent_kind="maho-break-glass-authentication",
        subject=process_identity(request.pid), effects=(request.effect,),
        operations=(request.operation,), target_prefixes=(request.target,),
        issued_at_ns=now_ns,
        expires_at_ns=now_ns + request.duration_seconds * 1_000_000_000,
        boot_id=boot_id, source_revision=source_revision,
        generation_id=None, break_glass=True,
    )
    project_authority(authority, map_path)
    _audit(audit_path, request, authority)
    return authority
