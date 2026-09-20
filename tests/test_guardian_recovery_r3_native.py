#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, pathlib, shutil, subprocess, sys, tempfile
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from maho_guardian_r3_limine import sanitize_text, verify_config

def check(name: str, ok: bool) -> None:
    if not ok:
        raise AssertionError(name)
    print("PASS", name)

def main() -> int:
    verifier = (ROOT / "lib/maho-guardian-recovery-r3").read_text()
    stage = (ROOT / "bin/maho-guardian-recovery-r3-stage").read_text()
    build = (ROOT / "bin/maho-guardian-recovery-r3-build").read_text()
    postboot = (ROOT / "bin/maho-guardian-recovery-r3-postboot").read_text()
    check("R3 native requires independent recovery kernel", "suspected_kernel_cannot_certify_itself" in verifier)
    check("R3 native requires production root read-only", "production_root_not_read_only" in verifier)
    check("R3 native requires explicit authorization", "explicit_authorization_missing" in verifier)
    check("R3 native binds certified R2 selection", "r2_certification_binding_invalid" in verifier)
    check("R3 native preserves current root generation", "current_root_identity_changed" in verifier and "subvolume delete" not in verifier)
    check("R3 native verifies exact modules compatibility", "selected_kernel_modules_incompatible" in verifier)
    check("R3 native switches only to LTS fallback", 'MahoOS/Fallback (LTS)' in verifier)
    check("R3 native records firmware untouched", 'firmware_mutated:false' in verifier)
    forbidden = ("efibootmgr", "BootNext", "BootOrder", "btrfs subvolume delete", "mv /@")
    check("R3 native never mutates firmware or root topology", all(x not in verifier for x in forbidden))
    check("R3 staging leaves Primary default before execution", "R3 staging requires Primary as current default" in stage)
    check("R3 campaign embeds certified content-addressed evidence", "guardian-r2-evidence" in build)
    hook = (ROOT / "config/mkinitcpio/install/sd-maho-guardian-recovery-r3").read_text()
    initrd_deps = ("guardian_recovery_r3.py", "guardian_recovery_r3_executor.py", "guardian_offline_recovery.py",
                   "maho_generation_v2.py", "maho_kernel_generation.py", "maho_trust_identity.py")
    check("R3 initrd carries complete verifier import closure", all(name in hook for name in initrd_deps))
    check("R3 initrd carries dependency-light Guardian Recovery TUI", "maho-guardian-recovery-tui" in hook and "guardian_recovery_tui.py" in hook)
    check("R3 native renders verified plan before mutation", "render_tui\nrollback_boot" in verifier and verifier.index("render_tui\nrollback_boot") < verifier.index("mutation_started=true"))
    check("R3 native renders durable reboot-gate state", 'render_tui "$report"' in verifier and verifier.index('render_tui "$report"') < verifier.index('umount "$ESP_MOUNT" || { durable_fail final_esp_unmount_failed'))
    check("R3 TUI remains presentation-only", '--render' in verifier and '--request-path' not in verifier)
    with tempfile.TemporaryDirectory() as import_td:
        maho = pathlib.Path(import_td) / "usr/lib/maho"; maho.mkdir(parents=True)
        for name in ("guardian_r3_native_verify.py", *initrd_deps):
            shutil.copy2(ROOT / "lib" / name, maho / name)
        probe = subprocess.run([sys.executable, str(maho / "guardian_r3_native_verify.py")], text=True, capture_output=True)
        check("R3 initrd-layout verifier imports successfully", "usage: guardian_r3_native_verify.py COMMAND" in probe.stderr)
        shutil.copy2(ROOT / "lib/guardian_recovery_tui.py", maho / "guardian_recovery_tui.py")
        shutil.copy2(ROOT / "lib/maho_tui.py", maho / "maho_tui.py")
        usr_bin = pathlib.Path(import_td) / "usr/bin"; usr_bin.mkdir()
        shutil.copy2(ROOT / "bin/maho-guardian-recovery-tui", usr_bin / "maho-guardian-recovery-tui")
        wrapper = (usr_bin / "maho-guardian-recovery-tui").read_text().replace('"/usr/lib/maho"', f'"{maho}"')
        (usr_bin / "maho-guardian-recovery-tui").write_text(wrapper)
        tui_probe = subprocess.run(
            [sys.executable, str(usr_bin / "maho-guardian-recovery-tui"), "--help"],
            text=True, capture_output=True,
        )
        check("R3 initrd-layout TUI imports successfully", tui_probe.returncode == 0 and "--plan" in tui_probe.stdout)
    check("R3 build fails before reboot on package drift", "live package set drifted since certified R2 selection" in build)
    check("R3 build fails before reboot on selected modules drift", "live root no longer contains exact selected kernel modules" in build)
    check("R3 postboot requires exact selected kernel", "running kernel is not selected recovery kernel" in postboot)
    check("R3 postboot requires preserved normal root", "normal /@ root is not active" in postboot)
    check("R3 postboot verifies home identity", "home identity changed" in postboot)
    check("R3 postboot preserves recovered LTS authority", "recovered LTS is not persistent boot authority" in postboot)
    check("R3 postboot records durable VERIFIED proof", "native_kernel_recovery_postboot_verified" in postboot)
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        manifest = {
            "root":{"uuid":"ce979d1c-c145-4be0-9ce3-591b6fd0a3a1","fsroot":"/@"},
            "esp":{"partuuid":"54b861fd-685c-476f-b580-3851c1ba7b79"},
            "campaign_id":"r3-20260913T180000Z-1234abcd",
        }
        mp = root / "manifest.json"
        mp.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")
        digest = hashlib.sha256(mp.read_bytes()).hexdigest()
        entry = root / "entry.conf"
        entry.write_text(
            "/Guardian Recovery R3\ncomment: test\nprotocol: linux\n"
            "kernel_cmdline: root=UUID=ce979d1c-c145-4be0-9ce3-591b6fd0a3a1 ro rootflags=subvol=@,ro "
            "maho.guardian_recovery=r3 maho.guardian_authorized=1 "
            f"maho.guardian_manifest_sha256={digest} maho.guardian_esp_partuuid=54b861fd-685c-476f-b580-3851c1ba7b79 "
            "maho.guardian_campaign=r3-20260913T180000Z-1234abcd\n"
        )
        config = root / "limine.conf"
        config.write_text(
            "timeout: 4\ndefault_entry: MahoOS/Primary\n/MahoOS\n//Primary\nprotocol: linux\n"
            "# MAHO-GUARDIAN-R3-BEGIN\n" + entry.read_text() + "# MAHO-GUARDIAN-R3-END\n"
        )
        verify_config(config, entry, mp)
        check("R3 Limine entry binds exact manifest and authorization", True)
        cleaned = sanitize_text(config.read_text())
        check("R3 sanitizer removes only R3 authority", "/Guardian Recovery R3" not in cleaned and "/MahoOS" in cleaned)
    print("ALL GUARDIAN RECOVERY R3 NATIVE CONTRACTS PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
