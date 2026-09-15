#!/usr/bin/env python3
"""Run signed-boot scenario images under isolated QEMU/OVMF variable stores.

The fixture plan deliberately supplies one independently built disk per
scenario.  The harness never reuses host EFI variables or physical disks.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import re
from typing import Any, Mapping

from qemu_secure_boot_common import REQUIRED_SCENARIOS



class CertificationError(ValueError):
    pass


def validate_plan(value: Mapping[str, Any], root: Path) -> dict[str, tuple[Path, Path, str]]:
    if set(value) != {"schema_version", "ovmf_code", "scenarios", "build_evidence"} or value.get("schema_version") != 2:
        raise CertificationError("certification_plan_fields_invalid")
    scenarios = value.get("scenarios")
    evidence = value.get("build_evidence")
    if not isinstance(scenarios, Mapping) or set(scenarios) != set(REQUIRED_SCENARIOS):
        raise CertificationError("certification_scenarios_incomplete")
    if not isinstance(evidence, Mapping) or set(evidence) != set(REQUIRED_SCENARIOS):
        raise CertificationError("certification_build_evidence_incomplete")
    result: dict[str, tuple[Path, Path, str]] = {}
    for name, expected in REQUIRED_SCENARIOS.items():
        row = scenarios[name]
        if not isinstance(row, Mapping) or set(row) != {"disk", "vars", "expected_serial_state"}:
            raise CertificationError(f"certification_scenario_invalid:{name}")
        if row["expected_serial_state"] != expected:
            raise CertificationError(f"certification_expectation_invalid:{name}")
        disk = (root / str(row["disk"])).resolve()
        variables = (root / str(row["vars"])).resolve()
        try:
            disk.relative_to(root.resolve())
            variables.relative_to(root.resolve())
        except ValueError as exc: raise CertificationError("certification_path_escape") from exc
        result[name] = (disk, variables, expected)
    validate_build_evidence(evidence)
    return result


def validate_build_evidence(evidence: Mapping[str, Any]) -> None:
    expected_mutations = {
        "valid-chain": "none", "recovery-loader": "none", "invalid-loader": "signed_loader_byte",
        "wrong-signer": "none", "config-tamper": "config_byte", "missing-config-enrollment": "none",
        "kernel-tamper": "kernel_byte", "initramfs-tamper": "initramfs_byte",
        "microcode-tamper": "microcode_byte",
        "damaged-normal-recovery-available": "normal_loader_byte_with_valid_recovery",
        "damaged-recovery": "recovery_loader_byte", "old-generation-replay": "none",
        "revoked-generation": "none",
    }
    expected_signatures = {
        "valid-chain": (True, None), "recovery-loader": (None, True),
        "invalid-loader": (False, None), "wrong-signer": (False, None),
        "config-tamper": (True, None), "missing-config-enrollment": (True, None),
        "kernel-tamper": (True, None), "initramfs-tamper": (True, None), "microcode-tamper": (True, None),
        "damaged-normal-recovery-available": (False, True), "damaged-recovery": (None, False),
        "old-generation-replay": (True, None), "revoked-generation": (True, None),
    }
    for name, expected_mutation in expected_mutations.items():
        row = evidence[name]
        required = {"mutation", "normal_loader_verifies_with_device_cert",
                    "recovery_loader_verifies_with_device_cert", "config_enrolled",
                    "original_config_sha256", "published_config_sha256"}
        if not isinstance(row, Mapping) or set(row) != required or row["mutation"] != expected_mutation:
            raise CertificationError(f"certification_build_evidence_invalid:{name}")
        if (row["normal_loader_verifies_with_device_cert"],
            row["recovery_loader_verifies_with_device_cert"]) != expected_signatures[name]:
            raise CertificationError(f"certification_loader_signature_evidence_invalid:{name}")
        if bool(row["config_enrolled"]) != (name != "missing-config-enrollment"):
            raise CertificationError(f"certification_config_enrollment_evidence_invalid:{name}")
        changed = row["original_config_sha256"] != row["published_config_sha256"]
        if changed != (name == "config-tamper"):
            raise CertificationError(f"certification_config_tamper_evidence_invalid:{name}")


def validate_isolated_disk(disk: Path) -> None:
    if disk.suffix != ".qcow2" or disk.is_symlink() or not disk.is_file():
        raise CertificationError("certification_disk_not_isolated_qcow2")
    completed = subprocess.run(("/usr/bin/qemu-img", "info", "--output=json", "--backing-chain", str(disk)),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    try:
        chain = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CertificationError("certification_disk_inspection_failed") from exc
    if completed.returncode != 0 or not isinstance(chain, list) or len(chain) != 1:
        raise CertificationError("certification_disk_backing_file_forbidden")


_ANSI = re.compile(r"\x1b\[[0-9;=?]*[A-Za-z]")


def refusal_evidence(name: str, output: str) -> tuple[str, ...]:
    plain = _ANSI.sub("", output).replace("\r", "")
    patterns = {
        "invalid-loader": ("Access Denied -- rejected probably by Secure Boot", "No bootable option or device was found"),
        "wrong-signer": ("Access Denied -- rejected probably by Secure Boot", "No bootable option or device was found"),
        "damaged-recovery": ("Access Denied -- rejected probably by Secure Boot", "No bootable option or device was found"),
        "config-tamper": ("CHECKSUM MISMATCH FOR CONFIG FILE", "System halted"),
        "kernel-tamper": ("Blake2b hash for URI `boot():/kernel` does not match",),
        "initramfs-tamper": ("Blake2b hash for URI `boot():/initramfs.img` does not match",),
        "microcode-tamper": ("Blake2b hash for URI `boot():/microcode.img` does not match",),
    }
    return tuple(pattern for pattern in patterns.get(name, ()) if pattern in plain)
    if chain[0].get("format") != "qcow2" or chain[0].get("backing-filename"):
        raise CertificationError("certification_disk_backing_file_forbidden")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan")
    parser.add_argument("--qemu", default="/usr/bin/qemu-system-x86_64")
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args(argv)
    plan_path = Path(args.plan).resolve()
    value = json.loads(plan_path.read_text())
    root = plan_path.parent
    scenarios = validate_plan(value, root)
    code = (root / value["ovmf_code"]).resolve()
    if not code.is_file() or not Path(args.qemu).is_file():
        raise CertificationError("qemu_ovmf_fixture_missing")
    results = []
    with tempfile.TemporaryDirectory(prefix="maho-ovmf-cert-") as td:
        temporary = Path(td)
        for name, (disk, vars_template, expected) in scenarios.items():
            if not disk.is_file(): raise CertificationError(f"certification_disk_missing:{name}")
            if not vars_template.is_file(): raise CertificationError(f"certification_vars_missing:{name}")
            validate_isolated_disk(disk)
            variables = temporary / f"{name}.vars.fd"
            shutil.copyfile(vars_template, variables)
            command = (
                args.qemu, "-machine", "q35,smm=on", "-accel", "tcg", "-m", "1024",
                "-global", "driver=cfi.pflash01,property=secure,value=on",
                "-drive", f"if=pflash,format=raw,unit=0,readonly=on,file={code}",
                "-drive", f"if=pflash,format=raw,unit=1,file={variables}",
                "-drive", f"if=virtio,format=qcow2,readonly=on,file={disk}",
                "-display", "none", "-serial", "stdio", "-no-reboot", "-net", "none",
            )
            timed_out = False
            try:
                completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, timeout=args.timeout, check=False)
                output = completed.stdout
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                raw_output = exc.stdout or ""
                output = raw_output.decode(errors="replace") if isinstance(raw_output, bytes) else raw_output
            token = f"MAHO_SECURE_BOOT_CERT:{expected}"
            markers = [line for line in output.splitlines() if "MAHO_SECURE_BOOT_CERT:" in line]
            refusals = refusal_evidence(name, output)
            passed = (token in output and all(token in line for line in markers)) if expected != "REFUSED" else (timed_out and not markers and bool(refusals))
            results.append({"scenario": name, "expected": expected, "passed": passed,
                            "timed_out": timed_out, "receipt_markers": markers, "refusal_evidence": list(refusals),
                            "serial_sha256": __import__("hashlib").sha256(output.encode()).hexdigest()})
    payload = {"schema_version": 1, "isolated_ovmf_variables": True, "results": results,
               "passed": all(item["passed"] for item in results)}
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
