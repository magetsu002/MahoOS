#!/usr/bin/env python3
"""Pure Guardian L4 catastrophic authority model.

L4 is a refusal/handoff authority, never a recovery executor. Inputs are
normalized evidence facts from independently owned observers. This module does
not inspect or mutate the host.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

CONFIRMED = "confirmed"
EVIDENCE_CLASSES = {
    "kernel", "boot", "root-filesystem", "privilege-boundary",
    "package-integrity", "persistence", "runtime", "network",
    "recovery-state", "personal-data-scope", "security-provider",
}
INTRINSIC_CATASTROPHIC = {"kernel", "boot"}
SECURITY_CORROBORATION = {"privilege-boundary", "package-integrity", "persistence"}


@dataclass(frozen=True)
class CatastrophicDecision:
    severity: int
    label: str
    catastrophic: bool
    lifecycle: str
    terminal_state: str
    automatic_recovery_allowed: bool
    automatic_host_mutation_allowed: bool
    trusted_boundaries: tuple[str, ...]
    untrusted_boundaries: tuple[str, ...]
    unknown_boundaries: tuple[str, ...]
    catastrophic_reasons: tuple[str, ...]
    safe_actions: tuple[str, ...]
    unsafe_actions: tuple[str, ...]
    evidence_preservation_required: bool
    recovery_handoff: tuple[str, ...]
    fail_closed: bool
    host_mutation_performed: bool
    prevented: bool
    guardian_authority_degraded: bool

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in (
            "trusted_boundaries", "untrusted_boundaries", "unknown_boundaries",
            "catastrophic_reasons", "safe_actions", "unsafe_actions", "recovery_handoff",
        ):
            data[key] = list(data[key])
        return data


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _bool(mapping: Mapping[str, Any], key: str, default: bool = False) -> bool:
    value = mapping.get(key, default)
    return value if isinstance(value, bool) else default


def _signals(facts: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = facts.get("signals")
    return [x for x in raw if isinstance(x, Mapping)] if isinstance(raw, list) else []


def _confirmed_by_class(facts: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = {}
    for item in _signals(facts):
        cls = item.get("class")
        if cls not in EVIDENCE_CLASSES or item.get("confidence") != CONFIRMED:
            continue
        out.setdefault(str(cls), []).append(item)
    return out


def _status(rows: list[Mapping[str, Any]], *wanted: str) -> bool:
    return any(row.get("status") in wanted for row in rows)


def _availability_handoffs(facts: Mapping[str, Any]) -> tuple[str, ...]:
    availability = _mapping(facts.get("handoff_availability"))
    options: list[str] = []
    for fact, name in (
        ("recovery_console", "recovery-console"),
        ("lts_kernel", "boot-lts"),
        ("recovery_environment", "boot-recovery-environment"),
        ("offline_inspection", "offline-inspection"),
        ("manual_system_restore", "manual-system-restore"),
        ("power_down", "power-down-and-investigate"),
    ):
        if _bool(availability, fact):
            options.append(name)
    return tuple(options)


def _lower_layer_available(facts: Mapping[str, Any]) -> bool:
    lower = _mapping(facts.get("lower_layer_recovery"))
    level = lower.get("level")
    return (
        isinstance(level, int) and not isinstance(level, bool) and level in {1, 2, 3}
        and _bool(lower, "available") and _bool(lower, "certified") and _bool(lower, "trusted")
    )


def assess_catastrophic(facts: Mapping[str, Any]) -> CatastrophicDecision:
    """Return L4 only for qualitative, confirmed catastrophic evidence.

    Duplicate observations are collapsed by evidence class. Unknown state fails
    closed for mutation but is not relabelled catastrophic. A trusted bounded
    lower-layer recovery wins unless the evidence directly invalidates that
    trust boundary.
    """
    confirmed = _confirmed_by_class(facts)
    classes = set(confirmed)
    reasons: list[str] = []
    untrusted: set[str] = set()
    trusted = set(str(x) for x in facts.get("trusted_boundaries", []) if isinstance(x, str))
    unknown = set(str(x) for x in facts.get("unknown_boundaries", []) if isinstance(x, str))

    guardian_health = _mapping(facts.get("guardian_health"))
    guardian_degraded = (
        guardian_health.get("runtime_consistent") is False
        or guardian_health.get("historical_authority_externally_verified") is False
    )

    for cls in INTRINSIC_CATASTROPHIC:
        rows = confirmed.get(cls, [])
        if _status(rows, "compromised", "corrupt", "integrity-lost", "untrusted"):
            reasons.append(f"confirmed {cls} trust loss")
            untrusted.add(cls)

    root_bad = _status(confirmed.get("root-filesystem", []), "corrupt", "incoherent", "untrusted")
    recovery_bad = _status(
        confirmed.get("recovery-state", []),
        "unavailable", "invalid", "contradictory", "incoherent", "untrusted",
    )
    runtime_bad = _status(confirmed.get("runtime", []), "invalid", "untrusted", "verification-failed")
    provider_bad = _status(
        confirmed.get("security-provider", []),
        "compromised", "contradictory", "untrusted", "unavailable",
    )
    personal_unbounded = _status(
        confirmed.get("personal-data-scope", []), "unbounded", "unknown-after-mutation"
    )

    if root_bad and recovery_bad:
        reasons.append("root filesystem is untrusted and no coherent certified recovery state remains")
        untrusted.update({"root-filesystem", "recovery-state"})
    if runtime_bad and recovery_bad:
        reasons.append("Maho runtime is invalid and its bounded recovery state is also invalid")
        untrusted.update({"runtime", "recovery-state"})
    if _status(confirmed.get("recovery-state", []), "contradictory", "incoherent"):
        reasons.append("certified recovery evidence contradicts itself")
        untrusted.add("recovery-state")
    if provider_bad:
        reasons.append("recovery/security provider cannot be trusted to certify live recovery")
        untrusted.add("security-provider")
    if personal_unbounded:
        reasons.append("personal-data impact cannot be bounded")
        untrusted.add("personal-data-scope")

    security_classes = classes & SECURITY_CORROBORATION
    if "privilege-boundary" in security_classes and len(security_classes) >= 2:
        reasons.append("independent confirmed privilege and integrity/persistence boundaries are compromised")
        untrusted.update(security_classes)

    catastrophic = bool(reasons)
    direct_trust_loss = bool(untrusted & {"kernel", "boot", "recovery-state", "security-provider"})
    if catastrophic and _lower_layer_available(facts) and not direct_trust_loss:
        catastrophic = False
        reasons = []
        untrusted.clear()

    unknown_recovery = facts.get("recovery_state_known") is False
    fail_closed = catastrophic or unknown_recovery or guardian_degraded
    handoffs = _availability_handoffs(facts) if catastrophic else ()
    terminal = "handoff-ready" if catastrophic and handoffs else ("unresolved" if catastrophic else "resolved-by-lower-layer" if _lower_layer_available(facts) else "unresolved")

    if catastrophic:
        lifecycle = "handoff-ready" if handoffs else "catastrophic"
        safe = ("preserve-evidence", "stop-unsafe-maho-mutation", "explain-trust-loss") + handoffs
    elif guardian_degraded:
        lifecycle = "degraded-handoff"
        safe = ("diagnose-only", "preserve-evidence")
    else:
        lifecycle = "detected"
        safe = ("diagnose-only",)

    return CatastrophicDecision(
        severity=4 if catastrophic else 0,
        label="catastrophic" if catastrophic else "not-catastrophic",
        catastrophic=catastrophic,
        lifecycle=lifecycle,
        terminal_state=terminal,
        automatic_recovery_allowed=False if fail_closed else True,
        automatic_host_mutation_allowed=False if fail_closed else True,
        trusted_boundaries=tuple(sorted(trusted - untrusted)),
        untrusted_boundaries=tuple(sorted(untrusted)),
        unknown_boundaries=tuple(sorted(unknown)),
        catastrophic_reasons=tuple(reasons),
        safe_actions=tuple(safe),
        unsafe_actions=(
            "automatic-host-recovery", "generic-shell-mutation", "arbitrary-file-edit",
            "arbitrary-process-kill", "indefinite-recovery-retry",
        ) if catastrophic else (),
        evidence_preservation_required=catastrophic or guardian_degraded,
        recovery_handoff=handoffs,
        fail_closed=fail_closed,
        host_mutation_performed=False,
        prevented=False,
        guardian_authority_degraded=guardian_degraded,
    )


def preview_catastrophic_mutation(facts: Mapping[str, Any]) -> CatastrophicDecision:
    """Authority-only destruction preview; it never intercepts or executes shell."""
    root = _bool(facts, "root_affected")
    boot = _bool(facts, "boot_affected")
    reversible = _bool(facts, "operation_reversible")
    certified = _bool(facts, "provider_certified")
    recovery = _bool(facts, "recovery_state_available")
    personal = facts.get("personal_data_scope")
    dangerous = root and boot and (not reversible or not certified or not recovery or personal == "unknown")
    base = assess_catastrophic({
        "signals": ([
            {"class": "recovery-state", "status": "unavailable", "confidence": "confirmed"},
            {"class": "root-filesystem", "status": "untrusted", "confidence": "confirmed"},
        ] if dangerous else []),
        "handoff_availability": _mapping(facts.get("handoff_availability")),
        "recovery_state_known": True,
    })
    if not dangerous:
        return base
    data = base.as_dict()
    data["prevented"] = True
    data["host_mutation_performed"] = False
    data["catastrophic_reasons"] = ["requested mutation crosses root/boot boundaries without a certified bounded reversal"]
    return CatastrophicDecision(**{
        **{k: tuple(v) if k in {"trusted_boundaries","untrusted_boundaries","unknown_boundaries","catastrophic_reasons","safe_actions","unsafe_actions","recovery_handoff"} else v for k,v in data.items()}
    })
