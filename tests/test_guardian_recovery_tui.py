#!/usr/bin/env python3
from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_recovery_r3 import R3RecoveryIntent, intent_envelope  # noqa: E402
from guardian_recovery_tui import (  # noqa: E402
    TUIEvidenceError,
    authorization_request,
    build_presentation,
    interactive,
    render,
    render_refusal,
)
from maho_generation_v2 import RootIdentity, SystemGeneration  # noqa: E402
from maho_kernel_generation import KernelGeneration  # noqa: E402
from maho_trust_identity import (  # noqa: E402
    ArtifactID, GenerationID, KernelGenerationID, ProvenanceID, TransactionID, TrustState,
)


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def make_kernel(name: str, *, parent: KernelGenerationID | None, trust: TrustState) -> KernelGeneration:
    return KernelGeneration.create(
        parent_kernel_generation_id=parent,
        kernel_image_id=ArtifactID.from_content(f"{name}-kernel".encode()),
        initramfs_id=ArtifactID.from_content(f"{name}-initramfs".encode()),
        modules_tree_id=ArtifactID.from_content(f"{name}-modules".encode()),
        dkms_output_ids=(),
        microcode_ids=(ArtifactID.from_content(f"{name}-microcode".encode()),),
        cmdline_contract=f"root={name}",
        package_provider_identity="pacman:test",
        provenance_id=ProvenanceID.derive({"kernel": name}),
        transaction_id=TransactionID.derive({"kernel": name}),
        kernel_abi=f"abi-{name}",
        modules_abi=f"abi-{name}",
        trust_state=trust,
    )


def make_system(
    name: str,
    *,
    parent: GenerationID | None,
    kernel: KernelGenerationID,
    snapshot: str,
    trust: TrustState,
) -> SystemGeneration:
    return SystemGeneration.create(
        parent_generation_id=parent,
        root_identity=RootIdentity(
            snapshot_identity=snapshot,
            filesystem_identity="uuid:12345678-1234-1234-1234-123456789abc",
            root_manifest_sha256=ArtifactID.from_content(f"{name}-root".encode()).removeprefix("art-"),
        ),
        kernel_generation_id=kernel,
        package_set_identity="pkg-" + ArtifactID.from_content(f"{name}-packages".encode()).removeprefix("art-"),
        transaction_id=TransactionID.derive({"system": name}),
        provenance_id=ProvenanceID.derive({"system": name}),
        artifact_ids=(),
        trust_state=trust,
    )


TRUSTED_KERNEL = make_kernel("trusted", parent=None, trust=TrustState.VERIFIED)
CURRENT_KERNEL_OBJ = make_kernel(
    "current", parent=TRUSTED_KERNEL.kernel_generation_id, trust=TrustState.REVOKED,
)
TRUSTED_SYSTEM = make_system(
    "trusted",
    parent=None,
    kernel=TRUSTED_KERNEL.kernel_generation_id,
    snapshot="btrfs:@snapshots/12/snapshot",
    trust=TrustState.VERIFIED,
)
CURRENT_SYSTEM_OBJ = make_system(
    "current",
    parent=TRUSTED_SYSTEM.generation_id,
    kernel=CURRENT_KERNEL_OBJ.kernel_generation_id,
    snapshot="btrfs:@",
    trust=TrustState.VERIFIED,
)

SYSTEM = CURRENT_SYSTEM_OBJ.generation_id
CURRENT_KERNEL = CURRENT_KERNEL_OBJ.kernel_generation_id
TARGET_KERNEL = TRUSTED_KERNEL.kernel_generation_id


def fixture_plan():
    intent = R3RecoveryIntent(
        mode="KERNEL_ONLY",
        incident_id="inc-guardian-tui-test",
        r2_campaign_id="r2-20260914T010203Z-1234abcd",
        current_system_generation_id=SYSTEM,
        current_kernel_generation_id=CURRENT_KERNEL,
        target_system_generation_id=SYSTEM,
        target_kernel_generation_id=TARGET_KERNEL,
        target_snapshot_identity="btrfs:@",
        target_snapshot_id=None,
        operations=(
            "preserve-incident-evidence",
            "verify-selected-generation-again",
            "stage-exact-selected-kernel-artifacts",
            "verify-boot-artifacts-and-current-root-identity",
            "request-reboot",
            "verify-postboot-kernel-and-home-identity",
        ),
    )
    return intent_envelope(intent)


def selection_report(*, explicit_reason: bool = True):
    selection = {
        "outcome": "READY",
        "selection_matches_expected": True,
        "target_system_generation_id": str(TRUSTED_SYSTEM.generation_id),
        "target_kernel_generation_id": str(TARGET_KERNEL),
        "provider_id": "guardian-offline-directory-v1",
    }
    if explicit_reason:
        selection["lost_trust_reason"] = "kernel artifact revoked"
    return {
        "schema_version": 2,
        "outcome": "PASS",
        "reason": "independently_trusted_generation_pair_selected",
        "campaign_id": "r2-20260914T010203Z-1234abcd",
        "selection": selection,
    }


def authority(plan, *, authorized=True):
    intent = plan["intent"]
    return {
        "schema_version": 1,
        "certification_scope": "native-r3-kernel-only-recovery",
        "explicit_authorization": authorized,
        "intent_sha256": plan["intent_sha256"],
        "target_system_generation_id": intent["target_system_generation_id"],
        "target_kernel_generation_id": intent["target_kernel_generation_id"],
        "target_kernel_release": "6.18.42-1-cachyos-lts",
        "suspected_running_kernel": {"release": "6.18.8-2-cachyos"},
    }


def revocation_plan(plan, *, credential="possible"):
    intent = plan["intent"]
    return {
        "schema_version": 1,
        "kind": "guardian-revocation-recovery-plan",
        "outcome": "READY",
        "mode": intent["mode"],
        "incident_id": intent["incident_id"],
        "current_system_generation_id": intent["current_system_generation_id"],
        "current_kernel_generation_id": intent["current_kernel_generation_id"],
        "target_system_generation_id": intent["target_system_generation_id"],
        "target_kernel_generation_id": intent["target_kernel_generation_id"],
        "exposure": {"credential_exposure": credential},
    }


def write_history(root: Path) -> None:
    system_dir = root / "manifests/system"
    kernel_dir = root / "manifests/kernel"
    system_dir.mkdir(parents=True)
    kernel_dir.mkdir(parents=True)
    for item in (TRUSTED_SYSTEM, CURRENT_SYSTEM_OBJ):
        (system_dir / f"{item.generation_id}.json").write_text(
            json.dumps(item.as_dict(), sort_keys=True), encoding="utf-8",
        )
    for item in (TRUSTED_KERNEL, CURRENT_KERNEL_OBJ):
        (kernel_dir / f"{item.kernel_generation_id}.json").write_text(
            json.dumps(item.as_dict(), sort_keys=True), encoding="utf-8",
        )


def main() -> None:
    plan = fixture_plan()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "evidence"
        write_history(root)
        pending = build_presentation(
            plan,
            selection_report=selection_report(),
            evidence_root=root,
            revocation_plan=revocation_plan(plan),
            logs=tuple(f"2026-09-14T12:00:{n:02d}Z INFO event-{n}" for n in range(30)),
        )

        check(
            "kernel-only view accepts older R2 system source while preserving current userspace",
            pending.scope == "KERNEL_ONLY"
            and pending.selection_system_generation_id == str(TRUSTED_SYSTEM.generation_id)
            and pending.target_system_generation_id == str(SYSTEM),
        )
        check(
            "recovery presentation distinguishes current and selected kernel",
            pending.current_kernel_generation_id == str(CURRENT_KERNEL)
            and pending.target_kernel_generation_id == str(TARGET_KERNEL),
        )
        check(
            "explicit trust-loss reason comes from evidence",
            pending.lost_trust_reason == "kernel artifact revoked",
        )
        check(
            "credential exposure is rendered only from bound revocation evidence",
            pending.credential_exposure == "possible",
        )
        check(
            "real generation history exposes current and selection-source rows",
            len(pending.generations) == 2
            and any("current" in row.marker for row in pending.generations)
            and any("selection source" in row.marker for row in pending.generations),
        )
        check(
            "generation trust comes from real manifests",
            any(row.kernel_trust == "REVOKED" for row in pending.generations)
            and any(row.kernel_trust == "VERIFIED" for row in pending.generations),
        )

        recovery = render(pending, width=120, height=40)
        check(
            "main screen answers current failure and selected recovery",
            "Current system" in recovery
            and "Selected recovery" in recovery
            and "kernel artifact revoked" in recovery
            and "Kernel only" in recovery,
        )
        check(
            "main screen shows impact without fabricating missing checks",
            "Recovery impact" in recovery
            and "Possible" in recovery
            and "Needs approval" in recovery
            and "Boot artifacts" in recovery
            and "Missing" in recovery,
        )
        check(
            "top-level sections remain small and recovery focused",
            all(name in recovery for name in ("Recovery", "Trust", "Generations", "Logs", "Confirm")),
        )

        narrow = render(pending, width=52, height=24)
        check(
            "narrow terminal degrades without overflowing",
            all(len(line) <= 52 for line in narrow.splitlines()),
        )
        long_reason = selection_report()
        long_reason["selection"]["lost_trust_reason"] = "x" * 500
        long_view = build_presentation(plan, selection_report=long_reason)
        long_screen = render(long_view, width=56, height=28)
        check("long evidence does not destroy layout", all(len(line) <= 56 for line in long_screen.splitlines()))

        no_optional = build_presentation(plan, selection_report=selection_report(explicit_reason=False))
        trust = render(no_optional, page="trust", width=100, height=36, evidence=True)
        check(
            "incomplete evidence is displayed honestly",
            "Evidence not supplied" in trust
            and "credential_exposure" in trust
            and "evidence not supplied" in trust,
        )

        generation_screen = render(pending, page="generations", generation_index=1, width=116, height=36)
        check(
            "generation browsing is explicitly inspection-only",
            "Inspection only" in generation_screen
            and "Guardian policy owns recovery eligibility" in generation_screen,
        )
        log0 = render(pending, page="logs", log_offset=0, width=100, height=30)
        log10 = render(pending, page="logs", log_offset=10, width=100, height=30)
        check(
            "logs are scrollable and use only supplied entries",
            "event-0" in log0 and "event-10" in log10 and "event-0" not in log10,
        )
        empty_logs = build_presentation(plan, selection_report=selection_report())
        check(
            "empty logs are not fabricated",
            "does not invent log entries" in render(empty_logs, page="logs", width=90, height=24),
        )

        confirm = render(pending, page="confirm", width=100, height=30)
        check(
            "confirmation summarizes exact scope and preservation",
            "Confirm recovery request" in confirm
            and "Kernel only" in confirm
            and "current userspace" in confirm
            and "exact plan" in confirm,
        )

        request = authorization_request(pending)
        check(
            "consent request remains explicitly non-authoritative and plan-bound",
            request["authority"] is False
            and request["plan_sha256"] == pending.plan_sha256
            and request["intent_sha256"] == plan["intent_sha256"],
        )

        request_path = Path(td) / "authorization-request.json"
        stdin = io.StringIO("down\ndown\nenter\ndown\nc\nc\nAUTHORIZE " + pending.plan_sha256[:12] + "\n")
        stdout = io.StringIO()
        rc = interactive(
            pending,
            request_path=str(request_path),
            stdin=stdin,
            stdout=stdout,
            width=100,
            height=28,
            color=False,
        )
        written = json.loads(request_path.read_text())
        check(
            "browsing a generation cannot change the authorized recovery target",
            rc == 10
            and written["plan_sha256"] == pending.plan_sha256
            and written["intent_sha256"] == plan["intent_sha256"],
        )
        check("request file is private", request_path.stat().st_mode & 0o777 == 0o600)

        nav_only = Path(td) / "nav-only.json"
        rc = interactive(
            pending,
            request_path=str(nav_only),
            stdin=io.StringIO("down\ndown\nenter\ndown\nescape\ndown\nq\n"),
            stdout=io.StringIO(),
            width=100,
            height=28,
            color=False,
        )
        check("navigation alone performs no privileged or consent action", rc == 0 and not nav_only.exists())

        nav_stdout = io.StringIO()
        rc = interactive(
            pending,
            request_path=None,
            stdin=io.StringIO("down\nq\n"),
            stdout=nav_stdout,
            width=100,
            height=28,
            color=False,
        )
        check(
            "vertical arrows navigate the vertical section list",
            rc == 0 and "› Trust" in nav_stdout.getvalue() and "[↑↓] Section" in nav_stdout.getvalue(),
        )

        focus_stdout = io.StringIO()
        rc = interactive(
            pending,
            request_path=None,
            stdin=io.StringIO("down\ndown\nright\ndown\nleft\ndown\nq\n"),
            stdout=focus_stdout,
            width=116,
            height=32,
            color=False,
        )
        focus_output = focus_stdout.getvalue()
        check(
            "right enters content and left returns to section navigation",
            rc == 0
            and "[↑↓] Inspect  [←/Esc] Sections" in focus_output
            and "› Logs" in focus_output,
        )

        boundary_stdout = io.StringIO()
        rc = interactive(
            pending,
            request_path=None,
            stdin=io.StringIO("up\nq\n"),
            stdout=boundary_stdout,
            width=100,
            height=28,
            color=False,
        )
        check(
            "section arrows clamp instead of wrapping",
            rc == 0 and "› Recovery" in boundary_stdout.getvalue() and "› Confirm" not in boundary_stdout.getvalue(),
        )

        stdin = io.StringIO("c\nc\nAUTHORIZE " + pending.plan_sha256[:12] + "\n\nq\n")
        stdout = io.StringIO()
        rc = interactive(
            pending,
            request_path=str(request_path),
            stdin=stdin,
            stdout=stdout,
            width=100,
            height=28,
            color=False,
        )
        check("existing request cannot be overwritten", rc == 0 and "File exists" in stdout.getvalue())

    granted = build_presentation(
        plan,
        selection_report=selection_report(),
        authority=authority(plan),
    )
    check("exact native manifest binding displays granted authorization", granted.authorization == "GRANTED")
    check("certified target release is visible", granted.target_kernel_release == "6.18.42-1-cachyos-lts")
    granted_confirm = render(granted, page="confirm", width=100, height=28)
    check(
        "granted confirmation does not request duplicate approval",
        "Authorization is already granted for this exact plan." in granted_confirm
        and "Press [c] to request authorization" not in granted_confirm,
    )
    granted_stdout = io.StringIO()
    rc = interactive(
        granted,
        request_path=None,
        stdin=io.StringIO("c\nc\nq\n"),
        stdout=granted_stdout,
        width=100,
        height=28,
        color=False,
    )
    check(
        "granted confirmation ignores duplicate approval shortcuts",
        rc == 0 and "Authorization is Granted" not in granted_stdout.getvalue(),
    )
    try:
        authorization_request(granted)
    except TUIEvidenceError as exc:
        check("already granted plans cannot emit another consent request", str(exc) == "authorization_request_not_applicable")
    else:
        raise AssertionError("duplicate authorization request accepted")

    refused = build_presentation(
        plan,
        selection_report=selection_report(),
        authority=authority(plan, authorized=False),
    )
    check("absent explicit authority is shown as refusal", refused.authorization == "REFUSED" and refused.outcome == "REFUSED")

    wrong_authority = authority(plan)
    wrong_authority["target_kernel_generation_id"] = str(CURRENT_KERNEL)
    try:
        build_presentation(plan, selection_report=selection_report(), authority=wrong_authority)
    except TUIEvidenceError as exc:
        check("mismatched authority fails closed", str(exc) == "authorization_target_kernel_generation_id_mismatch")
    else:
        raise AssertionError("mismatched authority accepted")

    wrong_selection = selection_report()
    wrong_selection["selection"]["target_kernel_generation_id"] = str(CURRENT_KERNEL)
    try:
        build_presentation(plan, selection_report=wrong_selection)
    except TUIEvidenceError as exc:
        check("unbound selection evidence fails closed", str(exc) == "selection_report_kernel_target_mismatch")
    else:
        raise AssertionError("unbound selection accepted")

    awaiting_reboot = {
        "schema_version": 1,
        "outcome": "PASS",
        "phase": "AWAITING_REBOOT",
        "reason": "exact_selected_kernel_staged",
        "intent_sha256": plan["intent_sha256"],
        "mutation_started": True,
        "firmware_mutated": False,
    }
    progress = build_presentation(
        plan,
        selection_report=selection_report(),
        authority=authority(plan),
        state=awaiting_reboot,
    )
    check("execution progress reflects bound executor state", progress.progress_completed == len(progress.operations) - 1)
    check("pending reboot never claims final success", progress.phase == "AWAITING_REBOOT" and progress.outcome == "PENDING")
    check("missing boot verification is not inferred from phase", progress.boot_artifacts_verified is None)

    verified_state = dict(
        awaiting_reboot,
        phase="VERIFIED",
        boot_artifacts_verified=True,
    )
    verified = build_presentation(
        plan,
        selection_report=selection_report(),
        authority=authority(plan),
        state=verified_state,
    )
    check(
        "explicit boot verification is rendered semantically",
        "Boot artifacts" in render(verified, page="trust", width=100, height=30)
        and "Verified" in render(verified, page="trust", width=100, height=30),
    )

    failed_state = dict(awaiting_reboot, outcome="FAIL", phase="FAILED", reason="artifact_stage_digest_mismatch")
    failed = build_presentation(
        plan,
        selection_report=selection_report(),
        authority=authority(plan),
        state=failed_state,
    )
    check("executor failure has a safe result state", failed.outcome == "FAILURE" and failed.result_reason == "artifact_stage_digest_mismatch")

    wrong_state = dict(awaiting_reboot, intent_sha256="0" * 64)
    try:
        build_presentation(plan, state=wrong_state)
    except TUIEvidenceError as exc:
        check("unbound execution state fails closed", str(exc) == "execution_state_plan_binding_mismatch")
    else:
        raise AssertionError("unbound state accepted")

    wrong_revocation = revocation_plan(plan)
    wrong_revocation["target_kernel_generation_id"] = str(CURRENT_KERNEL)
    try:
        build_presentation(plan, revocation_plan=wrong_revocation)
    except TUIEvidenceError as exc:
        check("unbound revocation evidence fails closed", str(exc) == "revocation_plan_target_kernel_generation_id_mismatch")
    else:
        raise AssertionError("unbound revocation evidence accepted")

    tampered_plan = json.loads(json.dumps(plan))
    tampered_plan["intent"]["target_snapshot_identity"] = "btrfs:@evil"
    try:
        build_presentation(tampered_plan)
    except TUIEvidenceError:
        check(
            "tampered Guardian plan reaches safe refusal",
            "no recovery action was performed" in render_refusal("guardian_plan_invalid"),
        )
    else:
        raise AssertionError("tampered plan accepted")

    source = (ROOT / "lib/guardian_recovery_tui.py").read_text()
    forbidden = ("subprocess", "os.system", "os.exec", "systemctl", "reboot -f")
    check("TUI contains no repair or privileged command runner", all(item not in source for item in forbidden))
    print("ALL GUARDIAN RECOVERY TUI TESTS PASS")


if __name__ == "__main__":
    main()
