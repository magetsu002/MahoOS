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
from maho_trust_identity import GenerationID, KernelGenerationID  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


SYSTEM = GenerationID.derive({"tui": "system"})
CURRENT_KERNEL = KernelGenerationID.derive({"tui": "suspected"})
TARGET_KERNEL = KernelGenerationID.derive({"tui": "trusted-lts"})


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


def selection_report():
    return {
        "schema_version": 2,
        "outcome": "PASS",
        "reason": "independently_trusted_generation_pair_selected",
        "campaign_id": "r2-20260914T010203Z-1234abcd",
        "selection": {
            "outcome": "READY",
            "selection_matches_expected": True,
            "target_system_generation_id": str(SYSTEM),
            "target_kernel_generation_id": str(TARGET_KERNEL),
        },
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
    }


def main() -> None:
    plan = fixture_plan()
    pending = build_presentation(plan, selection_report=selection_report())
    screen = render(pending, evidence=True)
    kernel_only_selection = selection_report()
    kernel_only_selection["selection"]["target_system_generation_id"] = str(GenerationID.derive({"tui": "older-r2-system"}))
    rebound = build_presentation(plan, selection_report=kernel_only_selection)
    check("kernel-only view accepts R2 kernel selection with preserved current userspace", rebound.scope == "KERNEL_ONLY")

    check("overview shows evidence-sourced trust-loss reason", "independently_trusted_generation_pair_selected" in screen)
    compact_screen = "".join(screen.split())
    check("selected exact system and kernel are visible", str(SYSTEM) in compact_screen and str(TARGET_KERNEL) in compact_screen)
    check("smallest kernel-only scope is prominent", "KERNEL_ONLY" in screen)
    check("missing authorization remains pending", pending.authorization == "REQUIRED" and pending.phase == "AWAITING_AUTHORIZATION")
    check("technical view includes exact plan binding", "plan_sha256" in screen and plan["intent_sha256"] in compact_screen)
    check("renderer never invents operations", all(operation in screen for operation in plan["intent"]["operations"]))

    granted = build_presentation(
        plan,
        selection_report=selection_report(),
        authority=authority(plan),
    )
    check("exact native manifest binding displays granted authorization", granted.authorization == "GRANTED")
    check("certified target release is visible", granted.target_kernel_release == "6.18.42-1-cachyos-lts")
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

    failed_state = dict(awaiting_reboot, outcome="FAIL", phase="FAILED", reason="artifact_stage_digest_mismatch")
    failed = build_presentation(
        plan,
        selection_report=selection_report(),
        authority=authority(plan),
        state=failed_state,
    )
    check("executor failure has a safe result screen", failed.outcome == "FAILURE" and failed.result_reason == "artifact_stage_digest_mismatch")

    wrong_state = dict(awaiting_reboot, intent_sha256="0" * 64)
    try:
        build_presentation(plan, state=wrong_state)
    except TUIEvidenceError as exc:
        check("unbound execution state fails closed", str(exc) == "execution_state_plan_binding_mismatch")
    else:
        raise AssertionError("unbound state accepted")

    tampered_plan = json.loads(json.dumps(plan))
    tampered_plan["intent"]["target_snapshot_identity"] = "btrfs:@evil"
    try:
        build_presentation(tampered_plan)
    except TUIEvidenceError:
        check("tampered Guardian plan reaches safe refusal", "no recovery action was performed" in render_refusal("guardian_plan_invalid"))
    else:
        raise AssertionError("tampered plan accepted")

    request = authorization_request(pending)
    check("consent request is explicitly non-authoritative", request["authority"] is False and "operations" not in request)
    check("consent request binds exact plan and intent", request["plan_sha256"] == pending.plan_sha256 and request["intent_sha256"] == plan["intent_sha256"])

    with tempfile.TemporaryDirectory() as td:
        request_path = Path(td) / "authorization-request.json"
        token = pending.plan_sha256[:12]
        stdin = io.StringIO(f"a\nAUTHORIZE {token}\n")
        stdout = io.StringIO()
        rc = interactive(pending, request_path=str(request_path), stdin=stdin, stdout=stdout)
        written = json.loads(request_path.read_text())
        check("exact typed confirmation emits one broker request", rc == 10 and written["authority"] is False)
        check("request file is private", request_path.stat().st_mode & 0o777 == 0o600)
        stdin = io.StringIO(f"a\nAUTHORIZE {token}\n\nq\n")
        stdout = io.StringIO()
        rc = interactive(pending, request_path=str(request_path), stdin=stdin, stdout=stdout)
        check("existing request cannot be overwritten", rc == 0 and "File exists" in stdout.getvalue())

    source = (ROOT / "lib/guardian_recovery_tui.py").read_text()
    forbidden = ("subprocess", "os.system", "systemctl", "btrfs", "mount ", "reboot ")
    check("TUI contains no repair or privileged command runner", all(item not in source for item in forbidden))
    print("ALL GUARDIAN RECOVERY TUI TESTS PASS")


if __name__ == "__main__":
    main()
