#!/usr/bin/env python3
"""Dependency-light terminal interface for an existing Guardian recovery plan.

The interface is deliberately a presentation and consent boundary.  It parses
the same signed-content envelope consumed by the R3 executor, displays only
operations already present in that envelope, and can emit a plan-bound user
authorization *request*.  It never grants authority or executes recovery work.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import textwrap
from typing import Any, Mapping, Sequence, TextIO

from guardian_recovery_r3_executor import parse_envelope
from maho_trust_identity import canonical_json


class TUIEvidenceError(ValueError):
    """Raised when presentation evidence is ambiguous or not plan-bound."""


@dataclass(frozen=True)
class RecoveryPresentation:
    incident_id: str
    plan_sha256: str
    scope: str
    lost_trust_reason: str
    target_system_generation_id: str
    target_kernel_generation_id: str
    target_kernel_release: str | None
    target_snapshot_identity: str
    operations: tuple[str, ...]
    authorization: str
    phase: str
    outcome: str
    progress_completed: int
    progress_total: int
    result_reason: str | None
    evidence: tuple[tuple[str, str], ...]

    @property
    def terminal(self) -> bool:
        return self.outcome in {"SUCCESS", "FAILURE", "REFUSED"}


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TUIEvidenceError(f"{label}_not_an_object")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TUIEvidenceError(f"{label}_missing")
    return value


def _read_json(path: str | os.PathLike[str], label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TUIEvidenceError(f"{label}_unreadable:{type(exc).__name__}") from exc
    return _object(value, label)


def _plan_digest(plan: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(plan)).encode("utf-8")).hexdigest()


def _selection_reason(
    selection_report: Mapping[str, Any] | None,
    *,
    r2_campaign_id: str,
    scope: str,
    target_system: str,
    target_kernel: str,
) -> str:
    if selection_report is None:
        return "lost_trust_evidence_not_supplied"
    if selection_report.get("schema_version") != 2 or selection_report.get("outcome") != "PASS":
        raise TUIEvidenceError("selection_report_not_certified_pass")
    if selection_report.get("campaign_id") != r2_campaign_id:
        raise TUIEvidenceError("selection_report_campaign_mismatch")
    selection = _object(selection_report.get("selection"), "selection")
    if selection.get("outcome") != "READY" or selection.get("selection_matches_expected") is not True:
        raise TUIEvidenceError("selection_report_not_ready")
    if selection.get("target_kernel_generation_id") != target_kernel:
        raise TUIEvidenceError("selection_report_kernel_target_mismatch")
    if scope == "FULL_GENERATION" and selection.get("target_system_generation_id") != target_system:
        raise TUIEvidenceError("selection_report_system_target_mismatch")
    if scope not in {"KERNEL_ONLY", "FULL_GENERATION"}:
        raise TUIEvidenceError("selection_scope_invalid")
    explicit = selection.get("lost_trust_reason")
    if isinstance(explicit, str) and explicit:
        return explicit
    return _text(selection_report.get("reason"), "selection_reason")


def _authority_status(
    authority: Mapping[str, Any] | None,
    *,
    intent_sha256: str,
    target_system: str,
    target_kernel: str,
) -> tuple[str, tuple[tuple[str, str], ...]]:
    if authority is None:
        return "REQUIRED", (("authorization_evidence", "not supplied"),)
    if authority.get("schema_version") != 1:
        raise TUIEvidenceError("authorization_schema_invalid")
    bindings = {
        "intent_sha256": intent_sha256,
        "target_system_generation_id": target_system,
        "target_kernel_generation_id": target_kernel,
    }
    for key, expected in bindings.items():
        if authority.get(key) != expected:
            raise TUIEvidenceError(f"authorization_{key}_mismatch")
    if authority.get("explicit_authorization") is not True:
        return "REFUSED", (("authorization_evidence", "explicit authorization absent"),)
    return "GRANTED", (
        ("authorization_evidence", "exact plan and target binding verified"),
        ("authorization_scope", str(authority.get("certification_scope", "unspecified"))),
    )


def _state_status(
    state: Mapping[str, Any] | None,
    *,
    intent_sha256: str,
    authorization: str,
    total: int,
) -> tuple[str, str, int, str | None, tuple[tuple[str, str], ...]]:
    if state is None:
        phase = "AUTHORIZED" if authorization == "GRANTED" else "AWAITING_AUTHORIZATION"
        outcome = "PENDING" if authorization != "REFUSED" else "REFUSED"
        return phase, outcome, 0, None, (("execution_state", "not started"),)
    if state.get("schema_version") != 1:
        raise TUIEvidenceError("execution_state_schema_invalid")
    if state.get("intent_sha256") != intent_sha256:
        raise TUIEvidenceError("execution_state_plan_binding_mismatch")
    phase = _text(state.get("phase"), "execution_phase")
    raw_outcome = _text(state.get("outcome"), "execution_outcome")
    reason = state.get("reason") if isinstance(state.get("reason"), str) else None
    if raw_outcome == "FAIL" or phase in {"FAILED", "BLOCKED", "MUTATION_FAILED"}:
        outcome = "FAILURE"
    elif phase == "VERIFIED" and raw_outcome == "PASS":
        outcome = "SUCCESS"
    elif raw_outcome == "PASS":
        outcome = "PENDING"
    else:
        raise TUIEvidenceError("execution_state_outcome_unknown")
    completed_raw = state.get("completed_operations")
    if completed_raw is None:
        completed = total if phase == "VERIFIED" else max(total - 1, 0) if phase == "AWAITING_REBOOT" else 0
    elif isinstance(completed_raw, int) and not isinstance(completed_raw, bool) and 0 <= completed_raw <= total:
        completed = completed_raw
    else:
        raise TUIEvidenceError("execution_progress_invalid")
    evidence = (
        ("execution_phase", phase),
        ("execution_outcome", raw_outcome),
        ("mutation_started", str(state.get("mutation_started", False)).lower()),
        ("firmware_mutated", str(state.get("firmware_mutated", False)).lower()),
    )
    return phase, outcome, completed, reason, evidence


def build_presentation(
    plan: Mapping[str, Any],
    *,
    selection_report: Mapping[str, Any] | None = None,
    authority: Mapping[str, Any] | None = None,
    state: Mapping[str, Any] | None = None,
) -> RecoveryPresentation:
    """Validate exact Guardian documents and produce a non-authoritative view."""
    try:
        intent = parse_envelope(plan)
    except (KeyError, TypeError, ValueError) as exc:
        raise TUIEvidenceError(f"guardian_plan_invalid:{exc}") from exc
    raw_intent = _object(plan.get("intent"), "intent")
    intent_sha256 = _text(plan.get("intent_sha256"), "intent_sha256")
    system_id = str(intent.target_system_generation_id)
    kernel_id = str(intent.target_kernel_generation_id)
    auth_status, auth_evidence = _authority_status(
        authority,
        intent_sha256=intent_sha256,
        target_system=system_id,
        target_kernel=kernel_id,
    )
    phase, outcome, completed, result_reason, state_evidence = _state_status(
        state,
        intent_sha256=intent_sha256,
        authorization=auth_status,
        total=len(intent.operations),
    )
    release: str | None = None
    if authority is not None and isinstance(authority.get("target_kernel_release"), str):
        release = authority["target_kernel_release"]
    selection_reason = _selection_reason(
        selection_report,
        r2_campaign_id=intent.r2_campaign_id,
        scope=intent.mode,
        target_system=system_id,
        target_kernel=kernel_id,
    )
    evidence = (
        ("plan_sha256", _plan_digest(plan)),
        ("intent_sha256", intent_sha256),
        ("authority_scope", _text(plan.get("authority_scope"), "authority_scope")),
        ("r2_campaign_id", intent.r2_campaign_id),
        ("selection_reason", selection_reason),
        ("source_only_plan", str(bool(raw_intent.get("requires_offline_recovery"))).lower()),
        *auth_evidence,
        *state_evidence,
    )
    return RecoveryPresentation(
        incident_id=intent.incident_id,
        plan_sha256=_plan_digest(plan),
        scope=intent.mode,
        lost_trust_reason=selection_reason,
        target_system_generation_id=system_id,
        target_kernel_generation_id=kernel_id,
        target_kernel_release=release,
        target_snapshot_identity=intent.target_snapshot_identity,
        operations=intent.operations,
        authorization=auth_status,
        phase=phase,
        outcome=outcome,
        progress_completed=completed,
        progress_total=len(intent.operations),
        result_reason=result_reason,
        evidence=evidence,
    )


def _fit(value: str, width: int) -> list[str]:
    return textwrap.wrap(value, width=max(20, width), replace_whitespace=False) or [""]


def render(presentation: RecoveryPresentation, *, width: int = 80, evidence: bool = False) -> str:
    """Render a deterministic terminal screen without terminal-control dependencies."""
    width = min(max(width, 52), 120)
    inner = width - 4
    lines = ["=" * width, " MAHO GUARDIAN RECOVERY ".center(width, "="), "=" * width]

    def section(title: str) -> None:
        lines.extend(("", title.upper(), "-" * len(title)))

    def field(label: str, value: str) -> None:
        prefix = f"{label}: "
        wrapped = _fit(value, inner - len(prefix))
        lines.append(prefix + wrapped[0])
        lines.extend(" " * len(prefix) + item for item in wrapped[1:])

    section("Overview")
    field("Incident", presentation.incident_id)
    field("Trust status", "LOST / recovery evidence required")
    field("Reason", presentation.lost_trust_reason)
    field("Scope", presentation.scope)

    section("Selected target")
    field("System generation", presentation.target_system_generation_id)
    field("Kernel generation", presentation.target_kernel_generation_id)
    if presentation.target_kernel_release:
        field("Kernel release", presentation.target_kernel_release)
    field("Snapshot", presentation.target_snapshot_identity)

    section("Authorization")
    field("Status", presentation.authorization)
    field("Boundary", "Guardian retains recovery authority; this interface cannot grant or expand it.")

    section("Execution progress")
    total = presentation.progress_total
    completed = presentation.progress_completed
    bar_width = max(10, min(36, inner - 18))
    filled = round(bar_width * completed / total) if total else 0
    field("Progress", f"[{'#' * filled}{'.' * (bar_width - filled)}] {completed}/{total}")
    field("Phase", presentation.phase)
    for index, operation in enumerate(presentation.operations, 1):
        marker = "done" if index <= completed else "pending"
        lines.append(f"  {index:02d}. [{marker:7}] {operation}")

    section("Result")
    field("Outcome", presentation.outcome)
    if presentation.result_reason:
        field("Reason", presentation.result_reason)
    elif presentation.outcome == "PENDING":
        field("Status", "No successful recovery is claimed until postconditions are verified.")

    if evidence:
        section("Technical evidence")
        for label, value in presentation.evidence:
            field(label, value)
    lines.extend(("", "[e] technical evidence   [a] authorization request   [q] exit"))
    return "\n".join(lines) + "\n"


def render_refusal(reason: str, *, width: int = 80) -> str:
    width = min(max(width, 52), 120)
    lines = [
        "=" * width,
        " MAHO GUARDIAN RECOVERY — SAFE REFUSAL ".center(width, "="),
        "=" * width,
        "",
        "Guardian recovery evidence is incomplete, invalid, or not exactly bound.",
        "No authorization request was emitted and no recovery action was performed.",
        "",
        f"Reason: {reason}",
        "",
        "Use independently verified evidence or external recovery before proceeding.",
    ]
    return "\n".join(lines) + "\n"


def authorization_request(presentation: RecoveryPresentation) -> dict[str, Any]:
    """Create user-consent evidence; this document is never execution authority."""
    if presentation.authorization != "REQUIRED" or presentation.terminal:
        raise TUIEvidenceError("authorization_request_not_applicable")
    return {
        "schema_version": 1,
        "kind": "guardian-recovery-authorization-request",
        "authority": False,
        "incident_id": presentation.incident_id,
        "intent_sha256": next(value for key, value in presentation.evidence if key == "intent_sha256"),
        "plan_sha256": presentation.plan_sha256,
        "requested_scope": presentation.scope,
        "requested_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def write_authorization_request(path: str | os.PathLike[str], request: Mapping[str, Any]) -> None:
    """Create, but never replace, one private consent request for an external broker."""
    destination = Path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(destination, flags, 0o600)
    try:
        payload = (canonical_json(dict(request)) + "\n").encode("utf-8")
        offset = 0
        while offset < len(payload):
            offset += os.write(fd, payload[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)


def interactive(
    presentation: RecoveryPresentation,
    *,
    request_path: str | None,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    width: int = 80,
) -> int:
    show_evidence = False
    while True:
        stdout.write("\033[2J\033[H")
        stdout.write(render(presentation, width=width, evidence=show_evidence))
        stdout.write("Selection: ")
        stdout.flush()
        choice = stdin.readline()
        if not choice:
            return 0
        choice = choice.strip().lower()
        if choice in {"q", "quit", "exit"}:
            return 0
        if choice == "e":
            show_evidence = not show_evidence
            continue
        if choice != "a":
            continue
        if request_path is None:
            stdout.write("Authorization broker unavailable; no request was recorded. Press Enter.")
            stdout.flush()
            stdin.readline()
            continue
        token = presentation.plan_sha256[:12]
        stdout.write(f"Type AUTHORIZE {token} to request this exact plan: ")
        stdout.flush()
        confirmation = stdin.readline().strip()
        if confirmation != f"AUTHORIZE {token}":
            stdout.write("Authorization request cancelled. Press Enter.")
            stdout.flush()
            stdin.readline()
            continue
        try:
            write_authorization_request(request_path, authorization_request(presentation))
        except (OSError, TUIEvidenceError) as exc:
            stdout.write(f"Request refused: {exc}. Press Enter.")
            stdout.flush()
            stdin.readline()
            continue
        stdout.write("Plan-bound authorization request recorded for Guardian evaluation.\n")
        return 10


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, help="Guardian R3 intent envelope JSON")
    parser.add_argument("--selection-report", help="Bound independent-selection report JSON")
    parser.add_argument("--authority", help="Bound native authority manifest JSON")
    parser.add_argument("--state", help="Bound execution or postboot state JSON")
    parser.add_argument("--request-path", help="New file for a non-authoritative user consent request")
    parser.add_argument("--render", action="store_true", help="Render once instead of reading terminal input")
    parser.add_argument("--evidence", action="store_true", help="Show technical evidence in rendered output")
    parser.add_argument("--width", type=int, default=80)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan = _read_json(args.plan, "guardian_plan")
        selection = _read_json(args.selection_report, "selection_report") if args.selection_report else None
        authority = _read_json(args.authority, "authorization") if args.authority else None
        state = _read_json(args.state, "execution_state") if args.state else None
        presentation = build_presentation(
            plan, selection_report=selection, authority=authority, state=state,
        )
    except TUIEvidenceError as exc:
        sys.stdout.write(render_refusal(str(exc), width=args.width))
        return 2
    if args.render or not sys.stdin.isatty():
        sys.stdout.write(render(presentation, width=args.width, evidence=args.evidence))
        return 0 if presentation.outcome != "FAILURE" else 1
    return interactive(presentation, request_path=args.request_path, width=args.width)


if __name__ == "__main__":
    raise SystemExit(main())
