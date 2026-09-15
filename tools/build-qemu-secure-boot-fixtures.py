#!/usr/bin/env python3
"""Build disposable Maho signed-boot QEMU/OVMF certification fixtures."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Iterable

from qemu_secure_boot_common import REQUIRED_SCENARIOS


OWNER_GUID = "8d51f90d-2d69-4a86-9074-3f1f8a5ad310"


class BuildError(RuntimeError):
    pass


def run(args: Iterable[str], *, cwd: Path | None = None, input_bytes: bytes | None = None,
        env: dict[str, str] | None = None) -> bytes:
    result = subprocess.run(tuple(args), cwd=cwd, input=input_bytes, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=False, env=env)
    if result.returncode != 0:
        raise BuildError(f"command_failed:{Path(tuple(args)[0]).name}:{result.stdout.decode(errors='replace')}")
    return result.stdout


def blake2b(path: Path) -> str:
    return hashlib.blake2b(path.read_bytes(), digest_size=64).hexdigest()


def make_key(openssl: str, root: Path, name: str) -> tuple[Path, Path]:
    key, cert = root / f"{name}.key.pem", root / f"{name}.cert.pem"
    run((openssl, "req", "-new", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes",
         "-subj", f"/CN=MahoOS QEMU {name}/", "-days", "30", "-keyout", str(key), "-out", str(cert)))
    key.chmod(0o600)
    return key, cert


def make_initramfs(cpio: str, busybox: Path, output: Path, state: str) -> None:
    with tempfile.TemporaryDirectory(prefix="maho-initramfs-") as td:
        root = Path(td)
        (root / "bin").mkdir()
        (root / "dev").mkdir()
        (root / "proc").mkdir()
        shutil.copyfile(busybox, root / "bin/busybox")
        (root / "bin/busybox").chmod(0o755)
        for name in ("sh", "mount", "cat", "poweroff", "sleep", "sync"):
            (root / "bin" / name).symlink_to("busybox")
        init = root / "init"
        init.write_text(
            "#!/bin/busybox sh\n"
            "/bin/mount -t proc proc /proc 2>/dev/null\n"
            f"echo 'MAHO_SECURE_BOOT_CERT:{state}' >/dev/ttyS0\n"
            f"echo 'MAHO_SECURE_BOOT_CERT:{state}'\n"
            "/bin/sync\n/bin/sleep 1\n/bin/poweroff -f\n"
        )
        init.chmod(0o755)
        names = b".\0./bin\0./bin/busybox\0./bin/sh\0./bin/mount\0./bin/cat\0./bin/poweroff\0./bin/sleep\0./bin/sync\0./dev\0./proc\0./init\0"
        archive = run((cpio, "--null", "-o", "--format=newc", "--quiet"), cwd=root, input_bytes=names)
        output.write_bytes(archive)


def make_microcode(cpio: str, output: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="maho-microcode-") as td:
        root = Path(td)
        (root / "kernel/x86/microcode").mkdir(parents=True)
        (root / "kernel/x86/microcode/.keep").write_bytes(b"")
        names = b".\0./kernel\0./kernel/x86\0./kernel/x86/microcode\0./kernel/x86/microcode/.keep\0"
        output.write_bytes(run((cpio, "--null", "-o", "--format=newc", "--quiet"), cwd=root, input_bytes=names))


def config_bytes(kernel: Path, initramfs: Path, microcode: Path, state: str) -> bytes:
    return (
        "timeout: 0\nserial: yes\nverbose: yes\nhash_mismatch_panic: yes\n"
        f"/MahoOS {state}\n protocol: linux\n path: boot():/kernel#{blake2b(kernel)}\n"
        f" module_path: boot():/microcode.img#{blake2b(microcode)}\n"
        f" module_path: boot():/initramfs.img#{blake2b(initramfs)}\n"
        " cmdline: console=ttyS0,115200 earlyprintk=serial,ttyS0 panic=-1 rdinit=/init\n"
    ).encode()


def sealed_loader(limine: str, clean_limine: Path, sbsign: str, key: Path, cert: Path,
                  config: bytes, output: Path, *, enroll: bool = True) -> None:
    unsigned = output.with_suffix(".unsigned.efi")
    shutil.copyfile(clean_limine, unsigned)
    if enroll:
        digest = hashlib.blake2b(config, digest_size=64).hexdigest()
        run((limine, "enroll-config", "--quiet", str(unsigned), digest))
    run((sbsign, "--key", str(key), "--cert", str(cert), "--output", str(output), str(unsigned)))
    unsigned.unlink()


def make_fat_image(mkfs: str, mmd: str, mcopy: str, raw: Path,
                   files: dict[str, Path]) -> None:
    with raw.open("wb") as stream:
        stream.truncate(128 * 1024 * 1024)
    run((mkfs, "-F", "32", "-n", "MAHOCERT", str(raw)))
    directories = {str(Path(path).parent).replace("\\", "/") for path in files}
    expanded: set[str] = set()
    for directory in directories:
        parts = Path(directory).parts
        for index in range(1, len(parts) + 1):
            expanded.add("/".join(parts[:index]))
    for directory in sorted(expanded, key=lambda item: (item.count("/"), item)):
        run((mmd, "-i", str(raw), f"::/{directory}"))
    for destination, source in files.items():
        run((mcopy, "-o", "-i", str(raw), str(source), f"::/{destination}"))


def make_vars(virt_fw_vars: str, pythonpath: str, template: Path, cert: Path, output: Path,
              boot_paths: tuple[str, ...]) -> None:
    command = [virt_fw_vars, "-i", str(template),
               "--set-pk", OWNER_GUID, str(cert),
               "--add-kek", OWNER_GUID, str(cert),
               "--add-db", OWNER_GUID, str(cert), "--no-microsoft", "--sb"]
    for path in boot_paths:
        command.extend(("--append-boot-filepath", path))
    command.extend(("-o", str(output)))
    env = dict(os.environ)
    env["PYTHONPATH"] = pythonpath
    run(command, env=env)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--tool-root", required=True)
    parser.add_argument("--kernel")
    parser.add_argument("--ovmf-code", default="/usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd")
    parser.add_argument("--ovmf-vars", default="/usr/share/edk2/x64/OVMF_VARS.4m.fd")
    parser.add_argument("--limine-efi", default="/usr/share/limine/BOOTX64.EFI")
    args = parser.parse_args(argv)
    output, tools = Path(args.output).resolve(), Path(args.tool_root).resolve()
    forbidden = {Path("/"), Path.home().resolve(), Path.cwd().resolve(), Path.cwd().resolve().parent}
    if output in forbidden or ("maho" not in output.name.lower() and output.parent.name != ".cert-work"):
        raise BuildError("unsafe_fixture_output_path")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    binroot = tools / "usr/bin"
    site_packages = sorted((tools / "usr/lib").glob("python*/site-packages"))
    pythonpath = str(site_packages[-1]) if site_packages else ""
    paths = {name: str(binroot / name) for name in ("sbsign", "sbverify", "mkfs.fat", "mmd", "mcopy", "virt-fw-vars")}
    kernel_candidates = sorted(Path("/usr/lib/modules").glob("*/vmlinuz"))
    kernel = Path(args.kernel) if args.kernel else (kernel_candidates[-1] if kernel_candidates else Path("/nonexistent"))
    clean_limine = Path(args.limine_efi)
    for path in (kernel, clean_limine, Path(args.ovmf_code), Path(args.ovmf_vars), Path(paths["sbsign"]), binroot / "busybox"):
        if not path.is_file(): raise BuildError(f"required_input_missing:{path}")
    keyroot = output / "keys"
    keyroot.mkdir()
    good_key, good_cert = make_key("/usr/bin/openssl", keyroot, "device")
    wrong_key, wrong_cert = make_key("/usr/bin/openssl", keyroot, "wrong")
    artifacts = output / "artifacts"
    artifacts.mkdir()
    shutil.copyfile(kernel, artifacts / "kernel")
    make_microcode("/usr/bin/cpio", artifacts / "microcode.img")
    for state in {"TRUSTED", "TRUSTED-RECOVERY", "UNTRUSTED", "REPLAY-MODELED"}:
        make_initramfs("/usr/bin/cpio", binroot / "busybox", artifacts / f"initramfs-{state}.img", state)

    scenario_rows: dict[str, dict[str, str]] = {}
    build_evidence: dict[str, dict[str, object]] = {}
    for name, expected in REQUIRED_SCENARIOS.items():
        scenario = output / name
        scenario.mkdir()
        state = expected if expected not in {"REFUSED"} else "TRUSTED"
        if name == "revoked-generation": state = "UNTRUSTED"
        initramfs = scenario / "initramfs.img"
        shutil.copyfile(artifacts / f"initramfs-{state}.img", initramfs)
        scenario_kernel, microcode = scenario / "kernel", scenario / "microcode.img"
        shutil.copyfile(artifacts / "kernel", scenario_kernel)
        shutil.copyfile(artifacts / "microcode.img", microcode)
        config = config_bytes(scenario_kernel, initramfs, microcode, state)
        original_config = config
        loader = scenario / "limine.efi"
        signing_key, signing_cert = (wrong_key, wrong_cert) if name == "wrong-signer" else (good_key, good_cert)
        enroll = name != "missing-config-enrollment"
        sealed_loader("/usr/bin/limine", clean_limine, paths["sbsign"], signing_key, signing_cert,
                      original_config, loader, enroll=enroll)
        mutation = "none"
        if name == "invalid-loader":
            data = bytearray(loader.read_bytes()); data[4096] ^= 1; loader.write_bytes(data); mutation = "signed_loader_byte"
        elif name == "config-tamper":
            config += b"#tampered\n"; mutation = "config_byte"
        elif name == "kernel-tamper":
            with scenario_kernel.open("ab") as stream: stream.write(b"tamper")
            mutation = "kernel_byte"
        elif name == "initramfs-tamper":
            with initramfs.open("ab") as stream: stream.write(b"tamper")
            mutation = "initramfs_byte"
        elif name == "microcode-tamper":
            with microcode.open("ab") as stream: stream.write(b"tamper")
            mutation = "microcode_byte"
        elif name == "damaged-recovery":
            data = bytearray(loader.read_bytes()); data[8192] ^= 1; loader.write_bytes(data); mutation = "recovery_loader_byte"

        config_file = scenario / "limine.conf"
        config_file.write_bytes(config)
        files: dict[str, Path]
        boot_paths: tuple[str, ...]
        normal_loader_for_evidence: Path | None = None
        recovery_loader_for_evidence: Path | None = None
        if name == "damaged-normal-recovery-available":
            normal = scenario / "normal-damaged.efi"
            shutil.copyfile(loader, normal)
            data = bytearray(normal.read_bytes()); data[4096] ^= 1; normal.write_bytes(data)
            recovery_init = scenario / "recovery-initramfs.img"
            shutil.copyfile(artifacts / "initramfs-TRUSTED-RECOVERY.img", recovery_init)
            recovery_config = config_bytes(scenario_kernel, recovery_init, microcode, "TRUSTED-RECOVERY")
            recovery_loader = scenario / "recovery.efi"
            sealed_loader("/usr/bin/limine", clean_limine, paths["sbsign"], good_key, good_cert,
                          recovery_config, recovery_loader)
            recovery_conf_file = scenario / "recovery.conf"; recovery_conf_file.write_bytes(recovery_config)
            files = {
                "EFI/MahoOS/Normal/limine.efi": normal,
                "EFI/MahoOS/Normal/limine.conf": config_file,
                "EFI/MahoOS/Recovery/limine.efi": recovery_loader,
                "EFI/MahoOS/Recovery/limine.conf": recovery_conf_file,
                "kernel": scenario_kernel, "initramfs.img": recovery_init, "microcode.img": microcode,
            }
            boot_paths = ("\\EFI\\MahoOS\\Normal\\limine.efi", "\\EFI\\MahoOS\\Recovery\\limine.efi")
            mutation = "normal_loader_byte_with_valid_recovery"
            normal_loader_for_evidence, recovery_loader_for_evidence = normal, recovery_loader
        else:
            directory = "Recovery" if name in {"recovery-loader", "damaged-recovery"} else "Normal"
            files = {f"EFI/MahoOS/{directory}/limine.efi": loader,
                     f"EFI/MahoOS/{directory}/limine.conf": config_file,
                     "kernel": scenario_kernel, "initramfs.img": initramfs, "microcode.img": microcode}
            boot_paths = (f"\\EFI\\MahoOS\\{directory}\\limine.efi",)
            if directory == "Normal": normal_loader_for_evidence = loader
            else: recovery_loader_for_evidence = loader
        raw = scenario / "esp.raw"
        make_fat_image(paths["mkfs.fat"], paths["mmd"], paths["mcopy"], raw, files)
        disk = scenario / "esp.qcow2"
        run(("/usr/bin/qemu-img", "convert", "-f", "raw", "-O", "qcow2", str(raw), str(disk)))
        raw.unlink()
        variables = scenario / "OVMF_VARS.fd"
        make_vars(paths["virt-fw-vars"], pythonpath, Path(args.ovmf_vars), good_cert, variables, boot_paths)
        def verifies(candidate: Path | None) -> bool | None:
            if candidate is None: return None
            return subprocess.run((paths["sbverify"], "--cert", str(good_cert), str(candidate)),
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False).returncode == 0
        scenario_rows[name] = {"disk": str(disk.relative_to(output)), "vars": str(variables.relative_to(output)),
                               "expected_serial_state": expected}
        build_evidence[name] = {"mutation": mutation,
                                "normal_loader_verifies_with_device_cert": verifies(normal_loader_for_evidence),
                                "recovery_loader_verifies_with_device_cert": verifies(recovery_loader_for_evidence),
                                "config_enrolled": enroll, "original_config_sha256": hashlib.sha256(original_config).hexdigest(),
                                "published_config_sha256": hashlib.sha256(config).hexdigest()}
    shutil.copyfile(args.ovmf_code, output / "OVMF_CODE.secboot.fd")
    plan = {"schema_version": 2, "ovmf_code": "OVMF_CODE.secboot.fd", "scenarios": scenario_rows,
            "build_evidence": build_evidence}
    (output / "plan.json").write_text(json.dumps(plan, sort_keys=True, indent=2) + "\n")
    print(output / "plan.json")
    return 0


if __name__ == "__main__": raise SystemExit(main())
