#!/usr/bin/env python3
"""Dependency-light Guardian Recovery terminal interface.

The TUI is a presentation and consent boundary. It renders only plan-bound
Guardian evidence, never selects recovery authority, and never executes
privileged recovery work.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Mapping, Sequence, TextIO

from guardian_offline_recovery import DirectoryRecoveryProvider
from guardian_recovery_r3_executor import parse_envelope
from maho_generation_v2 import GenerationGraph
from maho_kernel_generation import KernelGenerationGraph
from maho_trust_identity import canonical_json
from maho_tui import (
    ANSI, box as _box, clip as _clip, colorize_line as _colorize_line,
    columns as _columns, field_rows as _field_rows, human as _human,
    paint as _paint, read_key as _read_key, short_id as _short_id,
    status_word as _status_word, wrap as _wrap,
)


class TUIEvidenceError(ValueError):
    """Raised when presentation evidence is ambiguous or not plan-bound."""


PAGES = ("Recovery", "Trust", "Generations", "Logs", "Plan")
MIN_TUI_WIDTH = 60
MIN_TUI_HEIGHT = 18
DEFAULT_EVIDENCE_ROOT = Path("/usr/lib/maho/guardian-r3-campaign/r2-evidence")


@dataclass(frozen=True)
class VerificationItem:
    label: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class GenerationRow:
    system_generation_id: str
    kernel_generation_id: str | None
    system_trust: str
    kernel_trust: str
    snapshot: str | None
    marker: str = ""


@dataclass(frozen=True)
class RecoveryPresentation:
    incident_id: str
    plan_sha256: str
    intent_sha256: str
    scope: str
    current_system_generation_id: str
    current_kernel_generation_id: str
    current_kernel_release: str | None
    current_trust_state: str
    lost_trust_reason: str
    selection_reason: str
    target_system_generation_id: str
    target_kernel_generation_id: str
    target_kernel_release: str | None
    target_snapshot_identity: str
    target_trust_state: str
    selection_system_generation_id: str | None
    selection_kernel_generation_id: str | None
    selection_provider: str | None
    operations: tuple[str, ...]
    preserves_home: bool
    mutates_live_root: bool
    requires_user_reboot: bool
    authorization: str
    phase: str
    outcome: str
    progress_completed: int
    progress_total: int
    result_reason: str | None
    mutation_started: bool | None
    firmware_mutated: bool | None
    boot_artifacts_verified: bool | None
    credential_exposure: str | None
    verification: tuple[VerificationItem, ...]
    generations: tuple[GenerationRow, ...]
    generation_history_status: str
    logs: tuple[str, ...]
    evidence: tuple[tuple[str, str], ...]

    @property
    def terminal(self) -> bool:
        return self.outcome in {"SUCCESS", "FAILURE", "REFUSED"}


@dataclass
class UIState:
    page_index: int = 0
    generation_index: int = 0
    log_offset: int = 0
    show_evidence: bool = False
    show_help: bool = False
    focus: str = "nav"


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


def _read_logs(path: str | os.PathLike[str] | None) -> tuple[str, ...]:
    if path is None:
        return ()
    try:
        return tuple(Path(path).read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError as exc:
        raise TUIEvidenceError(f"log_evidence_unreadable:{type(exc).__name__}") from exc


def _plan_digest(plan: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(plan)).encode("utf-8")).hexdigest()


def _selection_evidence(
    report: Mapping[str, Any] | None,
    *,
    r2_campaign_id: str,
    scope: str,
    target_system: str,
    target_kernel: str,
) -> tuple[str, str, str | None, str | None, str | None]:
    if report is None:
        return (
            "Evidence not supplied",
            "Selection evidence not supplied",
            None, None, None,
        )
    if report.get("schema_version") != 2 or report.get("outcome") != "PASS":
        raise TUIEvidenceError("selection_report_not_certified_pass")
    if report.get("campaign_id") != r2_campaign_id:
        raise TUIEvidenceError("selection_report_campaign_mismatch")
    selection = _object(report.get("selection"), "selection")
    if selection.get("outcome") != "READY" or selection.get("selection_matches_expected") is not True:
        raise TUIEvidenceError("selection_report_not_ready")
    selected_system = _text(selection.get("target_system_generation_id"), "selection_system_generation")
    selected_kernel = _text(selection.get("target_kernel_generation_id"), "selection_kernel_generation")
    if selected_kernel != target_kernel:
        raise TUIEvidenceError("selection_report_kernel_target_mismatch")
    if scope == "FULL_GENERATION" and selected_system != target_system:
        raise TUIEvidenceError("selection_report_system_target_mismatch")
    if scope not in {"KERNEL_ONLY", "FULL_GENERATION"}:
        raise TUIEvidenceError("selection_scope_invalid")
    explicit_reason = selection.get("lost_trust_reason")
    lost_reason = explicit_reason if isinstance(explicit_reason, str) and explicit_reason else "Evidence not supplied"
    report_reason = report.get("reason")
    selection_reason = report_reason if isinstance(report_reason, str) and report_reason else "Certified selection"
    provider = selection.get("provider_id")
    if not isinstance(provider, str) or not provider:
        provider = None
    return lost_reason, selection_reason, selected_system, selected_kernel, provider


def _authority_status(
    authority: Mapping[str, Any] | None,
    *,
    intent_sha256: str,
    target_system: str,
    target_kernel: str,
) -> tuple[str, str | None, str | None, tuple[tuple[str, str], ...]]:
    if authority is None:
        return "REQUIRED", None, None, (("authorization_evidence", "not supplied"),)
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
    current_release = None
    suspected = authority.get("suspected_running_kernel")
    if isinstance(suspected, Mapping) and isinstance(suspected.get("release"), str):
        current_release = suspected["release"]
    target_release = authority.get("target_kernel_release")
    if not isinstance(target_release, str) or not target_release:
        target_release = None
    if authority.get("explicit_authorization") is not True:
        return "REFUSED", current_release, target_release, (
            ("authorization_evidence", "explicit authorization absent"),
        )
    return "GRANTED", current_release, target_release, (
        ("authorization_evidence", "exact plan and target binding verified"),
        ("authorization_scope", str(authority.get("certification_scope", "unspecified"))),
    )


def _state_status(
    state: Mapping[str, Any] | None,
    *,
    intent_sha256: str,
    authorization: str,
    total: int,
) -> tuple[str, str, int, str | None, bool | None, bool | None, bool | None, tuple[tuple[str, str], ...]]:
    if state is None:
        phase = "AUTHORIZED" if authorization == "GRANTED" else "AWAITING_AUTHORIZATION"
        outcome = "REFUSED" if authorization == "REFUSED" else "PENDING"
        return phase, outcome, 0, None, None, None, None, (("execution_state", "not supplied"),)
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
    mutation = state.get("mutation_started") if isinstance(state.get("mutation_started"), bool) else None
    firmware = state.get("firmware_mutated") if isinstance(state.get("firmware_mutated"), bool) else None
    boot = state.get("boot_artifacts_verified") if isinstance(state.get("boot_artifacts_verified"), bool) else None
    evidence = (
        ("execution_phase", phase),
        ("execution_outcome", raw_outcome),
        ("mutation_started", "missing" if mutation is None else str(mutation).lower()),
        ("firmware_mutated", "missing" if firmware is None else str(firmware).lower()),
        ("boot_artifacts_verified", "missing" if boot is None else str(boot).lower()),
    )
    return phase, outcome, completed, reason, mutation, firmware, boot, evidence


def _revocation_exposure(
    value: Mapping[str, Any] | None,
    *,
    incident_id: str,
    scope: str,
    current_system: str,
    current_kernel: str,
    target_system: str,
    target_kernel: str,
) -> tuple[str | None, tuple[tuple[str, str], ...]]:
    if value is None:
        return None, (("credential_exposure", "evidence not supplied"),)
    if value.get("schema_version") != 1 or value.get("kind") != "guardian-revocation-recovery-plan":
        raise TUIEvidenceError("revocation_plan_schema_invalid")
    bindings = {
        "incident_id": incident_id,
        "mode": scope,
        "current_system_generation_id": current_system,
        "current_kernel_generation_id": current_kernel,
        "target_system_generation_id": target_system,
        "target_kernel_generation_id": target_kernel,
    }
    for key, expected in bindings.items():
        if value.get(key) != expected:
            raise TUIEvidenceError(f"revocation_plan_{key}_mismatch")
    exposure = _object(value.get("exposure"), "revocation_exposure")
    credential = exposure.get("credential_exposure")
    if credential not in {"none_established", "possible", "unresolved"}:
        raise TUIEvidenceError("revocation_credential_exposure_invalid")
    return str(credential), (("credential_exposure", str(credential)),)


def _generation_rows(
    evidence_root: str | os.PathLike[str] | None,
    *,
    current_system: str,
    target_system: str,
    target_kernel: str,
    selected_system: str | None,
) -> tuple[tuple[GenerationRow, ...], str]:
    if evidence_root is None:
        return (), "Evidence not supplied"
    try:
        provider = DirectoryRecoveryProvider(evidence_root)
        systems = provider.system_generations()
        kernels = provider.kernel_generations()
        if not systems or not kernels:
            return (), "Generation history unavailable"
        system_graph = GenerationGraph(systems)
        kernel_graph = KernelGenerationGraph(kernels)
        by_system = system_graph.generations
        current_id = next((gid for gid in by_system if str(gid) == current_system), None)
        ordered = list(system_graph.lineage(current_id)) if current_id is not None else list(systems)
        present = {item.generation_id for item in ordered}
        ordered.extend(item for item in systems if item.generation_id not in present)
        rows: list[GenerationRow] = []
        for item in ordered:
            sid = str(item.generation_id)
            kid = str(item.kernel_generation_id) if item.kernel_generation_id else None
            kernel_trust = "UNKNOWN"
            if item.kernel_generation_id in kernel_graph.generations:
                kernel_trust = kernel_graph.effective_trust(item.kernel_generation_id).value
            markers = []
            if sid == current_system:
                markers.append("current")
            if sid == target_system:
                markers.append("target" if kid == target_kernel else "target userspace")
            if selected_system and sid == selected_system:
                markers.append("selection source")
            rows.append(GenerationRow(
                system_generation_id=sid,
                kernel_generation_id=kid,
                system_trust=system_graph.effective_trust(item.generation_id).value,
                kernel_trust=kernel_trust,
                snapshot=item.root_identity.snapshot_identity if item.root_identity else None,
                marker=", ".join(dict.fromkeys(markers)),
            ))
        return tuple(rows), f"{len(rows)} generation records"
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return (), f"Generation history unavailable ({type(exc).__name__})"


def _trust_label(scope: str, selection_kernel: str | None) -> str:
    if selection_kernel is None:
        return "Selection evidence missing"
    return "Verified kernel" if scope == "KERNEL_ONLY" else "Verified pair"


def _verification_items(
    *,
    selection_kernel: str | None,
    history_status: str,
    authorization: str,
    state_present: bool,
    boot_verified: bool | None,
) -> tuple[VerificationItem, ...]:
    items = [VerificationItem("Plan identity", "Verified", "intent envelope digest bound")]
    items.append(VerificationItem(
        "Guardian selection",
        "Verified" if selection_kernel else "Missing",
        "independent selection report" if selection_kernel else "selection evidence not supplied",
    ))
    history_ok = history_status.endswith("generation records")
    items.append(VerificationItem(
        "Generation history",
        "Available" if history_ok else "Missing",
        history_status,
    ))
    auth_status = {"GRANTED": "Verified", "REFUSED": "Failed"}.get(authorization, "Needs approval")
    items.append(VerificationItem("Authorization", auth_status, "exact plan binding"))
    if state_present:
        items.append(VerificationItem("Execution state", "Available", "plan-bound state supplied"))
    else:
        items.append(VerificationItem("Execution state", "Missing", "not supplied"))
    if boot_verified is True:
        items.append(VerificationItem("Boot artifacts", "Verified", "state reports verified"))
    elif boot_verified is False:
        items.append(VerificationItem("Boot artifacts", "Failed", "state reports verification failure"))
    else:
        items.append(VerificationItem("Boot artifacts", "Missing", "no explicit verification field"))
    return tuple(items)


def build_presentation(
    plan: Mapping[str, Any],
    *,
    selection_report: Mapping[str, Any] | None = None,
    authority: Mapping[str, Any] | None = None,
    state: Mapping[str, Any] | None = None,
    evidence_root: str | os.PathLike[str] | None = None,
    revocation_plan: Mapping[str, Any] | None = None,
    logs: Sequence[str] = (),
) -> RecoveryPresentation:
    """Validate exact Guardian documents and produce a non-authoritative view."""
    try:
        intent = parse_envelope(plan)
    except (KeyError, TypeError, ValueError) as exc:
        raise TUIEvidenceError(f"guardian_plan_invalid:{exc}") from exc
    raw_intent = _object(plan.get("intent"), "intent")
    intent_sha256 = _text(plan.get("intent_sha256"), "intent_sha256")
    current_system = str(intent.current_system_generation_id)
    current_kernel = str(intent.current_kernel_generation_id)
    target_system = str(intent.target_system_generation_id)
    target_kernel = str(intent.target_kernel_generation_id)
    lost_reason, selection_reason, selected_system, selected_kernel, provider = _selection_evidence(
        selection_report,
        r2_campaign_id=intent.r2_campaign_id,
        scope=intent.mode,
        target_system=target_system,
        target_kernel=target_kernel,
    )
    authorization, current_release, target_release, auth_evidence = _authority_status(
        authority,
        intent_sha256=intent_sha256,
        target_system=target_system,
        target_kernel=target_kernel,
    )
    phase, outcome, completed, result_reason, mutation, firmware, boot_verified, state_evidence = _state_status(
        state,
        intent_sha256=intent_sha256,
        authorization=authorization,
        total=len(intent.operations),
    )
    credential, exposure_evidence = _revocation_exposure(
        revocation_plan,
        incident_id=intent.incident_id,
        scope=intent.mode,
        current_system=current_system,
        current_kernel=current_kernel,
        target_system=target_system,
        target_kernel=target_kernel,
    )
    generations, history_status = _generation_rows(
        evidence_root,
        current_system=current_system,
        target_system=target_system,
        target_kernel=target_kernel,
        selected_system=selected_system,
    )
    verification = _verification_items(
        selection_kernel=selected_kernel,
        history_status=history_status,
        authorization=authorization,
        state_present=state is not None,
        boot_verified=boot_verified,
    )
    plan_sha = _plan_digest(plan)
    evidence = (
        ("plan_sha256", plan_sha),
        ("intent_sha256", intent_sha256),
        ("authority_scope", _text(plan.get("authority_scope"), "authority_scope")),
        ("r2_campaign_id", intent.r2_campaign_id),
        ("selection_reason", selection_reason),
        ("generation_history", history_status),
        ("source_only_plan", str(bool(raw_intent.get("requires_offline_recovery"))).lower()),
        *auth_evidence,
        *state_evidence,
        *exposure_evidence,
    )
    return RecoveryPresentation(
        incident_id=intent.incident_id,
        plan_sha256=plan_sha,
        intent_sha256=intent_sha256,
        scope=intent.mode,
        current_system_generation_id=current_system,
        current_kernel_generation_id=current_kernel,
        current_kernel_release=current_release,
        current_trust_state="Trust lost",
        lost_trust_reason=lost_reason,
        selection_reason=selection_reason,
        target_system_generation_id=target_system,
        target_kernel_generation_id=target_kernel,
        target_kernel_release=target_release,
        target_snapshot_identity=intent.target_snapshot_identity,
        target_trust_state=_trust_label(intent.mode, selected_kernel),
        selection_system_generation_id=selected_system,
        selection_kernel_generation_id=selected_kernel,
        selection_provider=provider,
        operations=intent.operations,
        preserves_home=bool(raw_intent.get("preserves_home")),
        mutates_live_root=bool(raw_intent.get("mutates_live_root")),
        requires_user_reboot=bool(raw_intent.get("requires_user_reboot")),
        authorization=authorization,
        phase=phase,
        outcome=outcome,
        progress_completed=completed,
        progress_total=len(intent.operations),
        result_reason=result_reason,
        mutation_started=mutation,
        firmware_mutated=firmware,
        boot_artifacts_verified=boot_verified,
        credential_exposure=credential,
        verification=verification,
        generations=generations,
        generation_history_status=history_status,
        logs=tuple(str(line) for line in logs),
        evidence=evidence,
    )


def _scope_label(scope: str) -> str:
    return "Kernel only" if scope == "KERNEL_ONLY" else "Full generation"


def _credential_label(value: str | None) -> str:
    return {
        None: "Evidence not supplied",
        "none_established": "None established",
        "possible": "Possible",
        "unresolved": "Unresolved",
    }[value]


def _recovery_body(p: RecoveryPresentation, width: int) -> list[str]:
    wide = width >= 78
    if wide:
        left_box_width = (width - 2) // 2
        right_box_width = width - 2 - left_box_width
        current_field_width = max(20, left_box_width - 4)
        target_field_width = max(20, right_box_width - 4)
    else:
        left_box_width = right_box_width = width
        current_field_width = target_field_width = max(20, width - 4)

    def id_width(field_width: int) -> int:
        label_width = min(18, max(10, field_width // 4))
        return max(12, field_width - label_width - 3)

    current = []
    for label, value in (
        ("System", _short_id(p.current_system_generation_id, id_width(current_field_width))),
        ("Kernel", p.current_kernel_release or _short_id(p.current_kernel_generation_id, id_width(current_field_width))),
        ("State", p.current_trust_state),
        ("Reason", p.lost_trust_reason),
    ):
        current.extend(_field_rows(label, value, current_field_width))
    target = []
    for label, value in (
        ("System", _short_id(p.target_system_generation_id, id_width(target_field_width))),
        ("Kernel", p.target_kernel_release or _short_id(p.target_kernel_generation_id, id_width(target_field_width))),
        ("State", p.target_trust_state),
        ("Scope", _scope_label(p.scope)),
    ):
        target.extend(_field_rows(label, value, target_field_width))

    if wide:
        rows = _columns(_box("Current system", current, left_box_width), _box("Selected recovery", target, right_box_width), width)
    else:
        rows = _box("Current system", current, width) + [""] + _box("Selected recovery", target, width)

    checks = []
    for item in p.verification[:6]:
        marker = {"Verified": "[ok]", "Failed": "[!!]", "Needs approval": "[!]", "Missing": "[?]"}.get(item.status, "[ ]")
        checks.append(f"{marker} {item.label:<20} {item.status}")
    impact = []
    impact.extend(_field_rows("User data", "Preserved" if p.preserves_home else "Plan does not promise preservation", target_field_width))
    impact.extend(_field_rows("Credentials", _credential_label(p.credential_exposure), target_field_width))
    impact.extend(_field_rows("Live root", "Not mutated" if not p.mutates_live_root else "Mutation planned", target_field_width))
    impact.extend(_field_rows("Approval", _status_word(p.authorization), target_field_width))
    if wide:
        rows += [""] + _columns(_box("Verification", checks, left_box_width), _box("Recovery impact", impact, right_box_width), width)
    else:
        rows += [""] + _box("Verification", checks, width) + [""] + _box("Recovery impact", impact, width)
    if p.generations:
        rows += [""] + _box("Recent generations", _generation_table(p, width, 0, min(4, len(p.generations))), width)
    else:
        rows += [""] + _box("Recent generations", [p.generation_history_status], width)
    return rows

def _trust_body(p: RecoveryPresentation, width: int, show_evidence: bool) -> list[str]:
    rows = []
    for item in p.verification:
        detail = f" — {item.detail}" if item.detail else ""
        rows.append(f"{item.label:<24} {item.status}{detail}")
    rows.append("")
    rows.append(f"Selection reason         {p.selection_reason}")
    rows.append(f"Selection provider       {p.selection_provider or 'Evidence not supplied'}")
    rows.append(f"Selection system         {_short_id(p.selection_system_generation_id, max(20, width - 30))}")
    rows.append(f"Selection kernel         {_short_id(p.selection_kernel_generation_id, max(20, width - 30))}")
    rows.append(f"Credential exposure      {_credential_label(p.credential_exposure)}")
    if show_evidence:
        rows.append("")
        rows.append("Technical evidence")
        rows.extend(f"{key:<24} {value}" for key, value in p.evidence)
    else:
        rows.extend(("", "Press [Enter] or [e] to show plan-bound technical evidence."))
    return _box("Trust evidence", rows, width)


def _generation_table(
    p: RecoveryPresentation,
    width: int,
    selected: int,
    visible: int | None = None,
) -> list[str]:
    if not p.generations:
        return [p.generation_history_status]
    visible = visible or max(1, len(p.generations))
    start = max(0, min(selected - visible // 2, max(0, len(p.generations) - visible)))
    rows = p.generations[start:start + visible]
    if width >= 78:
        table_width = max(1, width - 4)
        trust_width = 10
        system_width = 28
        kernel_width = 24
        marker_width = table_width - (7 + system_width + kernel_width + trust_width)
        if marker_width < 12:
            deficit = 12 - marker_width
            shrink = min(deficit, kernel_width - 16)
            kernel_width -= shrink
            deficit -= shrink
            shrink = min(deficit, system_width - 18)
            system_width -= shrink
            marker_width = table_width - (7 + system_width + kernel_width + trust_width)
        marker_width = max(5, marker_width)
        out = [
            f"{'':2} {'System generation':{system_width}} "
            f"{'Kernel':{kernel_width}} {'Trust':{trust_width}} {_clip('Marker', marker_width)}"
        ]
        for absolute, row in enumerate(rows, start):
            cursor = ">" if absolute == selected else " "
            trust = row.system_trust if row.system_trust != "VERIFIED" else row.kernel_trust
            marker = _clip(row.marker or "-", marker_width)
            out.append(
                f"{cursor:2} {_short_id(row.system_generation_id, system_width):{system_width}} "
                f"{_short_id(row.kernel_generation_id, kernel_width):{kernel_width}} "
                f"{trust:{trust_width}} {marker}"
            )
    else:
        out = []
        for absolute, row in enumerate(rows, start):
            cursor = ">" if absolute == selected else " "
            out.append(f"{cursor} {_short_id(row.system_generation_id, width - 8)}")
            out.append(f"  trust {row.system_trust}/{row.kernel_trust}  {row.marker or ''}".rstrip())
    return out

def _generations_body(p: RecoveryPresentation, width: int, selected: int) -> list[str]:
    if not p.generations:
        return _box("Generation history", [p.generation_history_status, "", "No recovery target can be selected from this screen."], width)
    selected = min(max(selected, 0), len(p.generations) - 1)
    table = _generation_table(p, width, selected, max(3, min(10, len(p.generations))))
    row = p.generations[selected]
    details = [
        f"System trust   {row.system_trust}",
        f"Kernel trust   {row.kernel_trust}",
        f"Snapshot       {row.snapshot or 'not supplied'}",
        f"Marker         {row.marker or 'none'}",
        "",
        "Inspection only. Guardian policy owns recovery eligibility.",
    ]
    return _box("Generations", table, width) + [""] + _box("Selected row", details, width)


def _logs_body(p: RecoveryPresentation, width: int, offset: int) -> list[str]:
    if not p.logs:
        return _box("Logs", ["No Guardian runtime log evidence supplied.", "", "The TUI does not invent log entries."], width)
    visible = 12
    offset = min(max(offset, 0), max(0, len(p.logs) - visible))
    rows = []
    for index, line in enumerate(p.logs[offset:offset + visible], offset + 1):
        rows.append(f"{index:>5}  {line}")
    rows.append("")
    rows.append(f"Lines {offset + 1}-{min(offset + visible, len(p.logs))} of {len(p.logs)}")
    return _box("Logs", rows, width)


def _plan_body(p: RecoveryPresentation, width: int) -> list[str]:
    passed = sum(item.status == "Verified" for item in p.verification)
    required = sum(item.status in {"Verified", "Failed", "Needs approval"} for item in p.verification)
    if p.scope == "KERNEL_ONLY":
        changes = "selected kernel and related boot artifacts"
        preserves = "current userspace, configuration, personal data"
    else:
        changes = "selected system generation, kernel and related boot artifacts"
        preserves = "/home and personal data where the plan promises preservation"
    rows = []
    for label, value in (
        ("Recovery target", _short_id(p.target_kernel_generation_id, max(24, width - 24))),
        ("Scope", _scope_label(p.scope)),
        ("Will change", changes),
        ("Will preserve", preserves),
        ("Verification", f"{passed}/{required} evidenced checks passed; missing evidence is not counted"),
        ("Authorization", _status_word(p.authorization)),
        ("Plan", _short_id(p.plan_sha256, max(24, width - 24))),
    ):
        rows.extend(_field_rows(label, value, width - 4))
    if p.authorization == "REQUIRED":
        action = "Approval required. Press [Enter] to request authorization for this exact plan."
    elif p.authorization == "GRANTED":
        action = "Authorization is already granted for this exact plan."
    else:
        action = "Guardian has refused authorization for this plan."
    rows.extend(("", action, "No recovery action is executed by this interface."))
    rows[-1] = "Execution is owned by Guardian; this interface does not perform recovery."
    return _box("Recovery plan", rows, width)


def _help_body(p: RecoveryPresentation, width: int) -> list[str]:
    rows = [
        "Navigation",
        "  [↑↓]       Move between sections",
        "  [Enter/→]  Open the selected section or action",
        "  [←/Esc]    Return from list/log focus",
        "  [?]        Close this help",
        "  [q]        Quit without changing recovery state",
        "",
        "Sections",
        "  Recovery     Current failure, selected recovery, and impact",
        "  Trust        Plan-bound trust and verification evidence",
        "  Generations  Read-only generation inspection",
        "  Logs         Supplied Guardian runtime evidence only",
        "  Plan         Exact recovery scope, preservation, and authorization",
        "",
        "Safety",
        "  Browsing never changes the Guardian-selected recovery target.",
        "  Approval records consent for the exact plan; Guardian remains the authority and executor.",
    ]
    return _box("Help", rows, width)


def _page_body(p: RecoveryPresentation, state: UIState, width: int) -> list[str]:
    if state.show_help:
        return _help_body(p, width)
    page = PAGES[state.page_index]
    if page == "Recovery":
        return _recovery_body(p, width)
    if page == "Trust":
        return _trust_body(p, width, state.show_evidence)
    if page == "Generations":
        return _generations_body(p, width, state.generation_index)
    if page == "Logs":
        return _logs_body(p, width, state.log_offset)
    return _plan_body(p, width)


def _header(p: RecoveryPresentation, width: int) -> list[str]:
    title = "MahoOS / Guardian Recovery"
    status = f"{_scope_label(p.scope)} | {_status_word(p.outcome)}"
    gap = max(1, width - len(title) - len(status))
    return [_clip(title + " " * gap + status, width), "─" * width]


def _footer(page: str, width: int, authorization: str, focus: str, show_help: bool) -> list[str]:
    if show_help:
        help_text = "[?/Esc] Close help  [q] Quit"
    elif focus == "content" and page == "Generations":
        help_text = "[↑↓] Inspect  [←/Esc] Sections  [p] Plan  [?] Help  [q] Quit"
    elif focus == "content" and page == "Logs":
        help_text = "[↑↓] Scroll  [←/Esc] Sections  [p] Plan  [?] Help  [q] Quit"
    elif page == "Recovery":
        help_text = "[↑↓] Section  [Enter/→] Inspect generations  [p] Plan  [?] Help  [q] Quit"
    elif page == "Trust":
        help_text = "[↑↓] Section  [Enter/e] Evidence  [p] Plan  [?] Help  [q] Quit"
    elif page == "Generations":
        help_text = "[↑↓] Section  [Enter/→] Inspect list  [p] Plan  [?] Help  [q] Quit"
    elif page == "Logs":
        help_text = "[↑↓] Section  [Enter/→] Scroll logs  [p] Plan  [?] Help  [q] Quit"
    elif authorization == "REQUIRED":
        help_text = "[↑↓] Section  [Enter] Request approval  [?] Help  [q] Quit"
    else:
        help_text = "[↑↓] Section  [?] Help  [q] Quit"
    return ["─" * width, _clip(help_text, width)]


def _resize_prompt(width: int, height: int) -> str:
    width = max(1, width)
    height = max(1, height)
    message = [
        "MahoOS / Guardian Recovery",
        "",
        "Terminal too small",
        f"Current: {width}x{height}   Required: {MIN_TUI_WIDTH}x{MIN_TUI_HEIGHT}",
        "Resize the terminal to continue.",
        "",
        "[q] Quit",
    ]
    top = max(0, (height - len(message)) // 2)
    lines = [""] * top
    lines.extend(_clip(line, width).center(width) for line in message)
    lines = lines[:height]
    while len(lines) < height:
        lines.append("")
    return "\n".join(lines) + "\n"

def _compose(
    p: RecoveryPresentation,
    state: UIState,
    *,
    width: int,
    height: int,
    color: bool,
) -> str:
    if width < MIN_TUI_WIDTH or height < MIN_TUI_HEIGHT:
        return _resize_prompt(width, height)
    width = min(width, 180)
    page = PAGES[state.page_index]
    header = _header(p, width)
    footer = _footer(page, width, p.authorization, state.focus, state.show_help)
    if width >= 100:
        sidebar_width = 18
        content_width = width - sidebar_width - 3
        body = _page_body(p, state, content_width)
        available = max(1, height - len(header) - len(footer))
        clipped = len(body) > available
        body = body[:available]
        if clipped and body:
            body[-1] = _clip("… more content; resize terminal or open the dedicated section", content_width)
        side = []
        for name in PAGES:
            marker = "›" if name == page else " "
            side.append(f"{marker} {name}")
        while len(side) < len(body):
            side.append("")
        lines = header[:]
        for index, row in enumerate(body):
            left = side[index] if index < len(side) else ""
            lines.append(left.ljust(sidebar_width) + " │ " + _clip(row, content_width))
        while len(lines) < height - len(footer):
            lines.append("")
        lines += footer
    else:
        nav_parts = []
        for name in PAGES:
            nav_parts.append(f"[{name}]" if name == page else name)
        nav = "  ".join(nav_parts)
        body = _page_body(p, state, width)
        available = max(1, height - len(header) - len(footer) - 2)
        clipped = len(body) > available
        body = body[:available]
        if clipped and body:
            body[-1] = _clip("… more content; resize terminal or open the dedicated section", width)
        lines = header + [_clip(nav, width), ""]
        lines += body
        while len(lines) < height - len(footer):
            lines.append("")
        lines += footer
    if color:
        active = f"› {page}"
        painted = []
        for line in lines:
            line = _colorize_line(line)
            if state.focus == "nav":
                line = line.replace(active, _paint(active, "active", True))
            painted.append(line)
        lines = painted
    return "\n".join(_clip(line, width) if not color else line for line in lines) + "\n"


def render(
    presentation: RecoveryPresentation,
    *,
    width: int = 100,
    height: int = 36,
    evidence: bool = False,
    page: str = "Recovery",
    generation_index: int = 0,
    log_offset: int = 0,
    color: bool = False,
) -> str:
    """Render a deterministic screen; no privileged action is reachable here."""
    normalized_page = "Plan" if page.lower() == "confirm" else page.title()
    try:
        page_index = PAGES.index(normalized_page)
    except ValueError as exc:
        raise TUIEvidenceError("unknown_tui_page") from exc
    state = UIState(
        page_index=page_index,
        generation_index=generation_index,
        log_offset=log_offset,
        show_evidence=evidence,
    )
    return _compose(presentation, state, width=width, height=height, color=color)


def render_refusal(reason: str, *, width: int = 80, height: int = 22, color: bool = False) -> str:
    width = min(max(width, 48), 140)
    rows = [
        "Guardian recovery evidence is incomplete, invalid, or not exactly bound.",
        "No authorization request was emitted and no recovery action was performed.",
        "",
        f"Reason: {reason}",
        "",
        "Use independently verified evidence or external recovery before proceeding.",
    ]
    box = _box("Safe refusal", rows, min(width, 94))
    lines = ["MahoOS / Guardian Recovery", "─" * width, ""] + box
    while len(lines) < height - 2:
        lines.append("")
    lines += ["─" * width, "[q] Quit"]
    if color:
        lines = [_paint(line, "bad", True) if "refusal" in line.lower() or "reason:" in line.lower() else line for line in lines]
    return "\n".join(_clip(line, width) if not color else line for line in lines[:height]) + "\n"


def authorization_request(presentation: RecoveryPresentation) -> dict[str, Any]:
    """Create user-consent evidence; this document is never execution authority."""
    if presentation.authorization != "REQUIRED" or presentation.terminal:
        raise TUIEvidenceError("authorization_request_not_applicable")
    return {
        "schema_version": 1,
        "kind": "guardian-recovery-authorization-request",
        "authority": False,
        "incident_id": presentation.incident_id,
        "intent_sha256": presentation.intent_sha256,
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


def _pause(stdin: TextIO, stdout: TextIO, message: str) -> None:
    stdout.write(message + "\n")
    stdout.flush()
    stdin.readline()


def _request_authorization(
    presentation: RecoveryPresentation,
    *,
    request_path: str | None,
    stdin: TextIO,
    stdout: TextIO,
) -> int | None:
    if request_path is None:
        _pause(stdin, stdout, "Authorization broker unavailable; no request was recorded. Press Enter.")
        return None
    if presentation.authorization != "REQUIRED":
        _pause(stdin, stdout, f"Authorization is {_status_word(presentation.authorization)}; no request emitted. Press Enter.")
        return None
    token = presentation.plan_sha256[:12]
    stdout.write(f"Type AUTHORIZE {token} to request this exact plan: ")
    stdout.flush()
    confirmation = stdin.readline().strip()
    if confirmation != f"AUTHORIZE {token}":
        _pause(stdin, stdout, "Authorization request cancelled. Press Enter.")
        return None
    try:
        write_authorization_request(request_path, authorization_request(presentation))
    except (OSError, TUIEvidenceError) as exc:
        _pause(stdin, stdout, f"Request refused: {exc}. Press Enter.")
        return None
    stdout.write("Plan-bound authorization request recorded for Guardian evaluation.\n")
    stdout.flush()
    return 10


def interactive(
    presentation: RecoveryPresentation,
    *,
    request_path: str | None,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    width: int | None = None,
    height: int | None = None,
    color: bool | None = None,
) -> int:
    state = UIState()
    if color is None:
        color = bool(getattr(stdout, "isatty", lambda: False)())
    dynamic_size = width is None or height is None
    last_size: tuple[int, int] | None = None
    dirty = True

    while True:
        terminal = shutil.get_terminal_size((MIN_TUI_WIDTH, 36))
        screen_width = width if width is not None else terminal.columns
        screen_height = height if height is not None else terminal.lines
        size = (screen_width, screen_height)
        too_small = screen_width < MIN_TUI_WIDTH or screen_height < MIN_TUI_HEIGHT

        if dirty or size != last_size:
            stdout.write("\033[2J\033[H")
            stdout.write(_compose(presentation, state, width=screen_width, height=screen_height, color=color))
            stdout.flush()
            last_size = size
            dirty = False

        key = _read_key(stdin, timeout=0.20 if dynamic_size else None)
        if key == "timeout":
            continue
        if key in {"q", "quit", "exit"}:
            return 0
        if too_small:
            continue

        dirty = True
        if state.show_help:
            if key in {"?", "escape", "enter", "left"}:
                state.show_help = False
            continue
        if key == "?":
            state.show_help = True
            continue

        page = PAGES[state.page_index]
        if state.focus == "content":
            if key in {"escape", "left", "h", "tab", "shift-tab"}:
                state.focus = "nav"
                continue
            if key in {"up", "k"}:
                if page == "Generations":
                    state.generation_index = max(0, state.generation_index - 1)
                elif page == "Logs":
                    state.log_offset = max(0, state.log_offset - 1)
                continue
            if key in {"down", "j"}:
                if page == "Generations" and presentation.generations:
                    state.generation_index = min(len(presentation.generations) - 1, state.generation_index + 1)
                elif page == "Logs" and presentation.logs:
                    state.log_offset = min(max(0, len(presentation.logs) - 1), state.log_offset + 1)
                continue
        else:
            if key in {"up", "k"}:
                state.page_index = max(0, state.page_index - 1)
                continue
            if key in {"down", "j"}:
                state.page_index = min(len(PAGES) - 1, state.page_index + 1)
                continue
            if key == "tab":
                state.page_index = (state.page_index + 1) % len(PAGES)
                continue
            if key == "shift-tab":
                state.page_index = (state.page_index - 1) % len(PAGES)
                continue
            if key in {"enter", "right"}:
                if page == "Recovery":
                    state.page_index = PAGES.index("Generations")
                    state.focus = "content" if presentation.generations else "nav"
                    continue
                if page == "Trust":
                    state.show_evidence = not state.show_evidence
                    continue
                if page == "Generations" and presentation.generations:
                    state.focus = "content"
                    continue
                if page == "Logs" and presentation.logs:
                    state.focus = "content"
                    continue
                if page == "Plan" and key == "enter" and presentation.authorization == "REQUIRED":
                    result = _request_authorization(
                        presentation, request_path=request_path, stdin=stdin, stdout=stdout,
                    )
                    if result is not None:
                        return result
                    continue

        page = PAGES[state.page_index]
        if key == "e" and page == "Trust":
            state.show_evidence = not state.show_evidence
            continue
        if key in {"p", "c"}:
            if page != "Plan":
                state.page_index = PAGES.index("Plan")
                state.focus = "nav"
                continue
            if key == "c" and presentation.authorization == "REQUIRED":
                result = _request_authorization(
                    presentation, request_path=request_path, stdin=stdin, stdout=stdout,
                )
                if result is not None:
                    return result
                continue

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, help="Guardian R3 intent envelope JSON")
    parser.add_argument("--selection-report", help="Bound independent-selection report JSON")
    parser.add_argument("--authority", help="Bound native authority manifest JSON")
    parser.add_argument("--state", help="Bound execution or postboot state JSON")
    parser.add_argument("--evidence-root", help="Read-only Guardian generation evidence root")
    parser.add_argument("--revocation-plan", help="Bound revocation recovery plan JSON")
    parser.add_argument("--log-file", help="Existing Guardian log evidence to display")
    parser.add_argument("--request-path", help="New file for a non-authoritative user consent request")
    parser.add_argument("--render", action="store_true", help="Render once instead of reading terminal input")
    parser.add_argument("--evidence", action="store_true", help="Show technical evidence on Trust")
    parser.add_argument("--page", choices=[name.lower() for name in PAGES] + ["confirm"], default="recovery")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--color", action="store_true", help="Enable semantic ANSI color in one-shot render")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    terminal = shutil.get_terminal_size((100, 36))
    width = args.width or terminal.columns
    height = args.height or terminal.lines
    try:
        plan = _read_json(args.plan, "guardian_plan")
        selection = _read_json(args.selection_report, "selection_report") if args.selection_report else None
        authority = _read_json(args.authority, "authorization") if args.authority else None
        state = _read_json(args.state, "execution_state") if args.state else None
        revocation = _read_json(args.revocation_plan, "revocation_plan") if args.revocation_plan else None
        logs = _read_logs(args.log_file)
        evidence_root = args.evidence_root
        if evidence_root is None and DEFAULT_EVIDENCE_ROOT.is_dir():
            evidence_root = str(DEFAULT_EVIDENCE_ROOT)
        presentation = build_presentation(
            plan,
            selection_report=selection,
            authority=authority,
            state=state,
            evidence_root=evidence_root,
            revocation_plan=revocation,
            logs=logs,
        )
    except TUIEvidenceError as exc:
        sys.stdout.write(render_refusal(str(exc), width=width, height=height, color=args.color))
        return 2
    if args.render or not sys.stdin.isatty():
        sys.stdout.write(render(
            presentation,
            width=width,
            height=height,
            evidence=args.evidence,
            page=args.page,
            color=args.color,
        ))
        return 1 if presentation.outcome == "FAILURE" else 0
    return interactive(
        presentation,
        request_path=args.request_path,
        width=args.width,
        height=args.height,
    )


if __name__ == "__main__":
    raise SystemExit(main())
