#!/usr/bin/env python3
"""Journal-bound S1.2 target assembly coordinator."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Protocol

from maho_installer_execute import (
    ASSEMBLY_PHASES,
    FIRST_BOOT_PHASES,
    PHASES,
    _checkpoint,
    _mutation_lock,
    _read_journal,
    _write_json_durable,
)
from maho_installer_payload import validate_payload_manifest
from maho_installer_plan import validate_plan_integrity


class AssemblyInterruption(RuntimeError):
    """Test-only interruption after a durable assembly checkpoint."""


class AssemblyOps(Protocol):
    def verify_target_mount(
        self, plan: Mapping[str, Any], mount_root: Path,
    ) -> Mapping[str, Any]: ...

    def phase_complete(
        self, phase: str, plan: Mapping[str, Any], payload: Mapping[str, Any],
        journal: Mapping[str, Any], mount_root: Path,
    ) -> bool: ...

    def phase_started(
        self, phase: str, plan: Mapping[str, Any], payload: Mapping[str, Any],
        journal: Mapping[str, Any], mount_root: Path,
    ) -> bool: ...

    def apply_phase(
        self, phase: str, plan: Mapping[str, Any], payload: Mapping[str, Any],
        journal: Mapping[str, Any], mount_root: Path,
    ) -> Mapping[str, Any]: ...


def assemble_installed_system(
    plan: Mapping[str, Any], payload: Mapping[str, Any], *, journal_path: Path,
    mount_root: Path, ops: AssemblyOps, fail_after: str | None = None,
    require_root: bool = True,
) -> dict[str, Any]:
    """Continue the exact storage journal through installed-system assembly."""
    validated_plan = validate_plan_integrity(plan)
    validated_payload = validate_payload_manifest(payload)
    if require_root and os.geteuid() != 0:
        raise PermissionError("target assembly requires root")
    if fail_after is not None and fail_after not in ASSEMBLY_PHASES:
        raise ValueError("assembly failure injection phase is invalid")
    mount_root = mount_root.resolve()
    if mount_root == Path("/"):
        raise ValueError("the live root cannot be an installer target")

    with _mutation_lock(journal_path):
        if not journal_path.exists():
            raise RuntimeError("storage journal is required before system assembly")
        journal = _read_journal(journal_path)
        if journal.get("install_attempt_id") != validated_plan["install_attempt_id"]:
            raise RuntimeError("journal belongs to another install attempt")
        if journal.get("installation_uuid") != validated_plan["installation_identity"]["installation_uuid"]:
            raise RuntimeError("journal belongs to another installation")
        if journal.get("plan_id") != validated_plan["plan_id"]:
            raise RuntimeError("journal belongs to another install plan")
        if validated_payload["source_revision"] != validated_plan["source_revision"]:
            raise ValueError("payload source revision does not match the install plan")
        if journal["phase"] in FIRST_BOOT_PHASES:
            return journal
        # UNMOUNTED is intentionally terminal for the live installer. Its
        # target-side markers are no longer reachable, so reopening and
        # rechecking them would itself violate the clean-unmount contract.
        if journal["phase"] == "UNMOUNTED":
            return journal
        mount_evidence = dict(ops.verify_target_mount(validated_plan, mount_root))
        if mount_evidence.get("verified") is not True:
            raise RuntimeError("mounted target does not match the exact install plan")
        if journal["phase"] != "MOUNTED" and journal["phase"] not in ASSEMBLY_PHASES:
            raise RuntimeError("storage transaction has not reached the mounted target")
        in_progress = journal.get("in_progress_phase")
        if in_progress is not None:
            raise RuntimeError(
                f"assembly was interrupted during {in_progress}; explicit inspection is required"
            )

        start = -1 if journal["phase"] == "MOUNTED" else ASSEMBLY_PHASES.index(journal["phase"])
        for completed in ASSEMBLY_PHASES[:start + 1]:
            if not ops.phase_complete(completed, validated_plan, validated_payload, journal, mount_root):
                raise RuntimeError(f"journaled assembly phase no longer verifies: {completed}")

        for phase in ASSEMBLY_PHASES[start + 1:]:
            if ops.phase_complete(phase, validated_plan, validated_payload, journal, mount_root):
                raise RuntimeError(f"unjournaled assembly mutation detected at phase {phase}")
            if ops.phase_started(phase, validated_plan, validated_payload, journal, mount_root):
                raise RuntimeError(f"partial assembly mutation detected at phase {phase}")
            updated = dict(journal)
            updated["in_progress_phase"] = phase
            _write_json_durable(journal_path, updated)
            evidence = dict(ops.apply_phase(
                phase, validated_plan, validated_payload, updated, mount_root,
            ))
            if not ops.phase_complete(phase, validated_plan, validated_payload, updated, mount_root):
                raise RuntimeError(f"assembly phase did not reach its postcondition: {phase}")
            journal = _checkpoint(journal_path, updated, phase, evidence=evidence)
            if fail_after == phase:
                raise AssemblyInterruption(f"simulated interruption after {phase}")
        if journal["phase"] != "UNMOUNTED" or [row.get("phase") for row in journal["history"]] != list(PHASES[:PHASES.index("UNMOUNTED") + 1]):
            raise RuntimeError("assembled installer journal is incoherent")
        return journal
