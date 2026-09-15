#!/usr/bin/env python3
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
spec = spec_from_file_location("maho_qemu_cert", ROOT / "tools/qemu-secure-boot-certify.py")
module = module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def check(name, condition):
    if not condition: raise AssertionError(name)
    print("PASS", name)


def main():
    with tempfile.TemporaryDirectory(prefix="maho-qemu-plan-") as td:
        root = Path(td)
        scenarios = {name: {"disk": f"{name}.qcow2", "vars": f"{name}.fd", "expected_serial_state": expected}
                     for name, expected in module.REQUIRED_SCENARIOS.items()}
        mutations = {
            "valid-chain": "none", "recovery-loader": "none", "invalid-loader": "signed_loader_byte",
            "wrong-signer": "none", "config-tamper": "config_byte", "missing-config-enrollment": "none",
            "kernel-tamper": "kernel_byte", "initramfs-tamper": "initramfs_byte", "microcode-tamper": "microcode_byte",
            "damaged-normal-recovery-available": "normal_loader_byte_with_valid_recovery",
            "damaged-recovery": "recovery_loader_byte", "old-generation-replay": "none", "revoked-generation": "none",
        }
        signatures = {
            "valid-chain": (True, None), "recovery-loader": (None, True), "invalid-loader": (False, None),
            "wrong-signer": (False, None), "config-tamper": (True, None), "missing-config-enrollment": (True, None),
            "kernel-tamper": (True, None), "initramfs-tamper": (True, None), "microcode-tamper": (True, None),
            "damaged-normal-recovery-available": (False, True), "damaged-recovery": (None, False),
            "old-generation-replay": (True, None), "revoked-generation": (True, None),
        }
        evidence = {name: {"mutation": mutation,
                           "normal_loader_verifies_with_device_cert": signatures[name][0],
                           "recovery_loader_verifies_with_device_cert": signatures[name][1],
                           "config_enrolled": name != "missing-config-enrollment",
                           "original_config_sha256": "a", "published_config_sha256": "b" if name == "config-tamper" else "a"}
                    for name, mutation in mutations.items()}
        plan = {"schema_version": 2, "ovmf_code": "code.fd", "scenarios": scenarios, "build_evidence": evidence}
        parsed = module.validate_plan(plan, root)
        check("QEMU matrix covers every required Secure Boot scenario", set(parsed) == set(module.REQUIRED_SCENARIOS))
        broken = dict(plan)
        broken["scenarios"] = dict(scenarios)
        broken["scenarios"].pop("wrong-signer")
        try: module.validate_plan(broken, root)
        except module.CertificationError as exc:
            check("incomplete QEMU matrix fails closed", "scenarios_incomplete" in str(exc))
        else: raise AssertionError("incomplete QEMU matrix fails closed")
    print("ALL QEMU CERTIFICATION HARNESS CONTRACTS PASS")


if __name__ == "__main__": main()
