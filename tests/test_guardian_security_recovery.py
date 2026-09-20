#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_causality import CausalGraph, CausalNode, package_file_edge
from guardian_security_recovery import SecurityRecoveryOutcome, plan_security_recovery


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def runtime_incident(package: str = "maho-runtime") -> dict:
    return {
        "incident_id": "inc-runtime-001",
        "status": "active",
        "subject": {"type": "package", "id": package},
        "signals": [{"kind": "integrity-drift", "source": "pacman-mtree", "details": {}}],
    }


def immutable_runtime_incident() -> dict:
    return {
        "incident_id": "inc-runtime-integrity-001",
        "status": "active",
        "subject": {"type": "runtime", "id": "maho-runtime"},
        "signals": [{
            "kind": "runtime-integrity-drift",
            "source": "maho-runtime-verifier",
            "details": {
                "path": "/tmp/runtime/releases/" + "a" * 64,
                "verified": False,
                "reasons": ["payload_content_identity_mismatch"],
            },
        }],
    }


def proven_graph(package: str) -> CausalGraph:
    subject = CausalNode(f"subject:package:{package}", "package", package)
    file_node = CausalNode("file:/usr/bin/maho-runtime", "file", "/usr/bin/maho-runtime")
    edge = package_file_edge(
        subject,
        file_node,
        package_identity=package,
        observed_package=package,
        file_path="/usr/bin/maho-runtime",
        evidence_id="mtree:item:1",
    )
    return CausalGraph((subject, file_node), (edge,))


def main() -> None:
    incident = runtime_incident()
    graph = proven_graph("maho-runtime")

    no_previous = plan_security_recovery(incident, causal_graph=graph)
    check("runtime recovery refuses without verified previous runtime", no_previous.outcome is SecurityRecoveryOutcome.DIAGNOSIS_ONLY)

    needs_auth = plan_security_recovery(incident, causal_graph=graph, previous_runtime_available=True)
    check("security incident cannot self-authorize certified rollback", needs_auth.outcome is SecurityRecoveryOutcome.AUTHORIZATION_REQUIRED)
    check("handoff points at existing runtime provider", needs_auth.provider == "maho-runtime" and needs_auth.action == "rollback-previous")
    check("recovery always requires preserved evidence", needs_auth.evidence_preservation_required)

    ready = plan_security_recovery(
        incident,
        causal_graph=graph,
        previous_runtime_available=True,
        runtime_transaction_authorized=True,
    )
    check("pre-authorized transaction can use certified runtime rollback", ready.outcome is SecurityRecoveryOutcome.READY_RUNTIME_RECOVERY)
    check("postcondition remains explicit", bool(ready.postcondition))

    direct_runtime = immutable_runtime_incident()
    direct_needs_auth = plan_security_recovery(direct_runtime, previous_runtime_available=True)
    check(
        "immutable runtime verifier evidence maps directly to bounded runtime recovery",
        direct_needs_auth.outcome is SecurityRecoveryOutcome.AUTHORIZATION_REQUIRED
        and direct_needs_auth.provider == "maho-runtime"
        and direct_needs_auth.action == "rollback-previous",
    )
    direct_bad_source = immutable_runtime_incident()
    direct_bad_source["signals"][0]["source"] = "untrusted-detector"
    check(
        "runtime subject cannot forge recovery authority without canonical verifier evidence",
        plan_security_recovery(direct_bad_source, previous_runtime_available=True).outcome
        is SecurityRecoveryOutcome.DIAGNOSIS_ONLY,
    )

    unproven = plan_security_recovery(incident, causal_graph=CausalGraph((), ()), previous_runtime_available=True, runtime_transaction_authorized=True)
    check("unproven package contamination cannot reach mutation authority", unproven.outcome is SecurityRecoveryOutcome.DIAGNOSIS_ONLY)

    third_party = plan_security_recovery(runtime_incident("openssl"), causal_graph=proven_graph("openssl"), previous_runtime_available=True, runtime_transaction_authorized=True)
    check("third-party package stays diagnosis-only", third_party.outcome is SecurityRecoveryOutcome.DIAGNOSIS_ONLY)

    maho_unknown = plan_security_recovery(runtime_incident("maho-custom"), causal_graph=proven_graph("maho-custom"), previous_runtime_available=True, runtime_transaction_authorized=True)
    check("uncertified Maho component does not inherit runtime recovery", maho_unknown.outcome is SecurityRecoveryOutcome.DIAGNOSIS_ONLY)

    host = {
        "incident_id": "inc-host-001",
        "status": "active",
        "subject": {"type": "host", "id": "local"},
        "signals": [{"kind": "integrity-drift"}],
    }
    external = plan_security_recovery(host)
    check("system contamination without trusted source requires external recovery", external.outcome is SecurityRecoveryOutcome.EXTERNAL_RECOVERY_REQUIRED)

    offline = {
        "outcome": "READY",
        "provider_id": "offline-certified-1",
        "target_system_generation_id": "sg-clean",
        "target_kernel_generation_id": "kg-clean",
    }
    offline_ready = plan_security_recovery(host, offline_plan=offline)
    check("certified offline plan is routed without executing it", offline_ready.outcome is SecurityRecoveryOutcome.READY_OFFLINE_RECOVERY)
    check("offline handoff preserves exact generation pair", offline_ready.target_system_generation_id == "sg-clean" and offline_ready.target_kernel_generation_id == "kg-clean")
    check("offline handoff still requires explicit recovery authorization", offline_ready.requires_explicit_recovery_authorization)

    print("ALL GUARDIAN SECURITY RECOVERY TESTS PASS")


if __name__ == "__main__":
    main()
