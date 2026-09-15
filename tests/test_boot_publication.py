#!/usr/bin/env python3
from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_boot_publication import (  # noqa: E402
    PUBLICATION_STEPS, PublicationError, preflight_esp, publish_virtual_generation,
    recover_virtual_publication,
)


def check(name, condition):
    if not condition: raise AssertionError(name)
    print("PASS", name)


def main():
    old = "bootgen-" + "1" * 64
    new = "bootgen-" + "2" * 64
    old_files = {"Normal/limine.efi": b"old-loader", "Normal/limine.conf": b"old-config",
                 "Recovery/limine.efi": b"recovery", "Recovery/limine.conf": b"recovery-config"}
    new_files = {"Normal/limine.efi": b"new-loader", "Normal/limine.conf": b"new-config",
                 "Recovery/limine.efi": b"recovery", "Recovery/limine.conf": b"recovery-config"}
    for step in PUBLICATION_STEPS:
        with tempfile.TemporaryDirectory(prefix="maho-publication-") as td:
            root = Path(td)
            publish_virtual_generation(root, old, old_files)
            base = root / "EFI/MahoOS"
            (base / "previous").write_text(old + "\n")
            (base / "publication.json").unlink()
            try:
                publish_virtual_generation(root, new, new_files, fail_after=step)
            except PublicationError as exc:
                check(f"interruption injected after {step}", "simulated_power_loss" in str(exc))
            state = recover_virtual_publication(root)
            check(f"interruption after {step} has an allowed trusted outcome", state in {"previous", "new", "recovery-required"})
    with tempfile.TemporaryDirectory(prefix="maho-preflight-") as td:
        result = preflight_esp(td, expected_partuuid="one", observed_partuuid="two",
                               expected_filesystem_identity="fat-one", observed_filesystem_identity="fat-two",
                               new_generation_bytes=1, previous_generation_bytes=1,
                               recovery_reserve_bytes=1, journal_reserve_bytes=1)
        check("wrong ESP identities fail preflight", not result.ok and "esp_partuuid_mismatch" in result.reasons)
        full = preflight_esp(td, expected_partuuid="one", observed_partuuid="one",
                             expected_filesystem_identity="fat", observed_filesystem_identity="fat",
                             new_generation_bytes=10**30, previous_generation_bytes=1,
                             recovery_reserve_bytes=1, journal_reserve_bytes=1)
        check("full ESP is rejected before publication", not full.ok and "esp_space_insufficient" in full.reasons)
    print("ALL MAHO BOOT PUBLICATION CONTRACTS PASS")


if __name__ == "__main__": main()
