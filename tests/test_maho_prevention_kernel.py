#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_admission import EffectKind  # noqa: E402
from maho_mutation_authority import issue_authority, process_identity  # noqa: E402
from maho_prevention_kernel import (  # noqa: E402
    activation_scope_specs, enforcement_roots, kernel_capabilities,
    project_authority,
)
from maho_prevention_policy import MutationOperation  # noqa: E402
import maho_prevention_kernel as kernel  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def main() -> None:
    roots = enforcement_roots(owner_home="/home/example")
    check("root mount object is exact rather than recursive", any(row.path == "/" and not row.recursive for row in roots))
    check("home protection is limited to exact Maho runtime", [row.path for row in roots if row.path.startswith("/home/")] == ["/home/example/.local/share/maho/runtime"])
    check("ordinary project trees are absent from enforcement roots", not any("Projects" in row.path or row.path == "/home" for row in roots))
    capabilities = kernel_capabilities()
    check("host exposes active BPF LSM and kernel BTF", capabilities["bpf_lsm_active"] is True and capabilities["kernel_btf"] is True)

    with tempfile.TemporaryDirectory(prefix="maho-kernel-authority-") as temporary:
        target = Path(temporary) / "exact-target"
        target.write_text("fixture", encoding="utf-8")
        subject = process_identity(os.getpid())
        now = time.clock_gettime_ns(time.CLOCK_BOOTTIME)
        authority = issue_authority(
            secret=b"k" * 32, transaction_id="upd-kernel-fixture",
            parent_authority_id="art-" + "1" * 64,
            parent_kind="maho-update-admission-activation-authority",
            subject=subject, effects=(EffectKind.BOOT_STATE,),
            operations=(MutationOperation.WRITE,), target_prefixes=(str(target),),
            issued_at_ns=now, expires_at_ns=now + 1_000_000_000,
            boot_id="fixture-boot", source_revision="a" * 40,
            generation_id="gen-fixture",
        )
        updates: list[tuple[bytes, bytes]] = []
        original_get, original_update = kernel._object_get, kernel._map_update
        kernel._object_get = lambda path: os.open("/dev/null", os.O_RDONLY)
        kernel._map_update = lambda fd, key, value: updates.append((key, value))
        try:
            count = project_authority(authority, Path("/fixture/map"))
        finally:
            kernel._object_get, kernel._map_update = original_get, original_update
        check("one exact target creates one kernel authority", count == 1 and len(updates) == 1)
        check("kernel key and value match stable C layouts", len(updates[0][0]) == 48 and len(updates[0][1]) == 32)
        check("projection binds target inode rather than protected parent", target.stat().st_ino.to_bytes(8, sys.byteorder) in updates[0][0])
    print("ALL MAHO PREVENTION KERNEL TESTS PASS")


if __name__ == "__main__":
    main()
