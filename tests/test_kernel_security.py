#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_kernel_security import ModuleEvidence, evaluate_kernel_enforcement  # noqa: E402

SIGNER = "AB" * 32


def check(name, condition):
    if not condition: raise AssertionError(name)
    print("PASS", name)


def rows():
    return tuple(ModuleEvidence(f"/usr/lib/modules/{kernel}/{role}.ko", kernel, SIGNER, True, role, True)
                 for kernel in ("primary", "lts") for role in ("storage", "network", "filesystem", "nvidia"))


def main():
    valid = evaluate_kernel_enforcement(rows(), primary_kernel="primary", fallback_kernel="lts",
                                        expected_signers=(SIGNER,), lockdown_mode="integrity",
                                        module_sig_enforce=True, kexec_restricted=True)
    check("primary, LTS, NVIDIA and kexec evidence can prove enforcement readiness", valid.ready)
    unsigned = list(rows())
    unsigned[0] = ModuleEvidence(unsigned[0].path, "primary", None, False, "storage", False)
    failed = evaluate_kernel_enforcement(unsigned, primary_kernel="primary", fallback_kernel="lts",
                                         expected_signers=(SIGNER,), lockdown_mode=None,
                                         module_sig_enforce=False, kexec_restricted=False)
    check("unsigned module blocks enforcement", not failed.ready and any("module_signature_invalid" in item for item in failed.blockers))
    wrong = list(rows())
    wrong[1] = ModuleEvidence(wrong[1].path, "primary", "CD" * 32, True, "network", True)
    failed = evaluate_kernel_enforcement(wrong, primary_kernel="primary", fallback_kernel="lts",
                                         expected_signers=(SIGNER,), lockdown_mode="integrity",
                                         module_sig_enforce=True, kexec_restricted=True)
    check("wrong module signer is rejected", any("module_signer_unexpected" in item for item in failed.blockers))
    print("ALL MAHO KERNEL SECURITY CONTRACTS PASS")


if __name__ == "__main__": main()
