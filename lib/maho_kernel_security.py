#!/usr/bin/env python3
"""Evidence model for lockdown, modules, NVIDIA, and kexec policy."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from maho_boot_authority import certificate_fingerprint


@dataclass(frozen=True)
class ModuleEvidence:
    path: str
    kernel_version: str
    signer_fingerprint: str | None
    signature_valid: bool | None
    required_role: str
    load_proven: bool

    def __post_init__(self) -> None:
        if not self.path.startswith("/usr/lib/modules/") or not self.kernel_version or not self.required_role:
            raise ValueError("module_evidence_invalid")
        if not self.path.startswith(f"/usr/lib/modules/{self.kernel_version}/"):
            raise ValueError("module_kernel_version_mismatch")
        if self.signer_fingerprint is not None:
            certificate_fingerprint(self.signer_fingerprint)

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "kernel_version": self.kernel_version,
                "signer_fingerprint": self.signer_fingerprint, "signature_valid": self.signature_valid,
                "required_role": self.required_role, "load_proven": self.load_proven}


@dataclass(frozen=True)
class KernelEnforcementResult:
    ready: bool
    blockers: tuple[str, ...]


def evaluate_kernel_enforcement(
    modules: Iterable[ModuleEvidence], *, primary_kernel: str, fallback_kernel: str,
    expected_signers: Iterable[str], lockdown_mode: str | None,
    module_sig_enforce: bool | None, kexec_restricted: bool | None,
) -> KernelEnforcementResult:
    rows = tuple(modules)
    signers = {certificate_fingerprint(item) for item in expected_signers}
    blockers: list[str] = []
    if lockdown_mode not in {"integrity", "confidentiality"}: blockers.append("kernel_lockdown_not_proven")
    if module_sig_enforce is not True: blockers.append("module_signature_enforcement_not_proven")
    if kexec_restricted is not True: blockers.append("kexec_restriction_not_proven")
    for kernel in (primary_kernel, fallback_kernel):
        kernel_rows = [item for item in rows if item.kernel_version == kernel]
        if not kernel_rows: blockers.append(f"module_inventory_missing:{kernel}")
        roles = {item.required_role for item in kernel_rows if item.load_proven}
        for role in ("storage", "network", "filesystem"):
            if role not in roles: blockers.append(f"required_module_role_unproven:{kernel}:{role}")
        for item in kernel_rows:
            if item.signature_valid is not True: blockers.append(f"module_signature_invalid:{item.path}")
            elif item.signer_fingerprint is None: blockers.append(f"module_signer_missing:{item.path}")
            elif certificate_fingerprint(item.signer_fingerprint) not in signers:
                blockers.append(f"module_signer_unexpected:{item.path}")
            if not item.load_proven: blockers.append(f"module_load_unproven:{item.path}")
    if any(item.required_role == "nvidia" for item in rows):
        for kernel in (primary_kernel, fallback_kernel):
            if not any(item.kernel_version == kernel and item.required_role == "nvidia" and item.load_proven for item in rows):
                blockers.append(f"nvidia_module_unproven:{kernel}")
    blockers = sorted(set(blockers))
    return KernelEnforcementResult(not blockers, tuple(blockers))
