#!/usr/bin/env python3
from __future__ import annotations
import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "guardian-r2-contracts"))
from guardian_offline_recovery import DirectoryRecoveryProvider, RecoveryEnvironmentEvidence, plan_offline_recovery
from maho_trust_identity import GenerationID, KernelGenerationID, TrustState

def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: maho_guardian_r2_select.py EVIDENCE_ROOT CAMPAIGN_MANIFEST")
    evidence = pathlib.Path(sys.argv[1])
    campaign = json.loads(pathlib.Path(sys.argv[2]).read_text())
    authority = campaign["selection_authority"]
    env = RecoveryEnvironmentEvidence(
        environment_id=authority["environment_id"],
        trust_state=TrustState(authority["trust_state"]),
        manifest_verified=True,
        verification_authority=authority["verification_authority"],
        verification_kernel_id=authority["verification_kernel_id"],
        revocation_metadata_fresh=True,
    )
    fixture = campaign["selection_fixture"]
    plan = plan_offline_recovery(
        DirectoryRecoveryProvider(evidence), env,
        current_system_generation_id=GenerationID(fixture["current_system_generation_id"]),
        suspected_running_kernel_id=KernelGenerationID(fixture["suspected_kernel_generation_id"]),
        incident_id=fixture["incident_id"],
    )
    out = plan.as_dict()
    out["expected_system_generation_id"] = fixture["expected_system_generation_id"]
    out["expected_kernel_generation_id"] = fixture["expected_kernel_generation_id"]
    out["selection_matches_expected"] = (
        out["outcome"] == "READY"
        and out["target_system_generation_id"] == out["expected_system_generation_id"]
        and out["target_kernel_generation_id"] == out["expected_kernel_generation_id"]
    )
    print(json.dumps(out, sort_keys=True, separators=(",", ":")))
    return 0 if out["selection_matches_expected"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
