#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_update_native import (  # noqa: E402
    BOOT_ARTIFACTS,
    NativeBtrfsOps,
    NativeCandidateUpdateOps,
    RootIdentity,
    activation_confirmation,
    backup_name,
    candidate_name,
    sha256_file,
    update_confirmation,
)

TX1 = "upd-20260912T100000Z-abcdef123456"
TX2 = "upd-20260912T100001Z-fedcba654321"
CURRENT_UUID = "11111111-1111-1111-1111-111111111111"
CANDIDATE_UUID = "22222222-2222-2222-2222-222222222222"
FSUUID = "33333333-3333-3333-3333-333333333333"
MACHINE = "a" * 32


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


class FixtureBtrfs(NativeBtrfsOps):
    def __init__(self, transaction_id: str, base: Path, *, fail_after_swap: bool = False) -> None:
        super().__init__(transaction_id, run_root=base / "run", boot_root=base / "boot")
        self.fail_after_swap = fail_after_swap
        self.top.mkdir(parents=True)
        self.boot_root.mkdir(parents=True)

    def require_root(self) -> None:
        return None

    def root_identity(self) -> RootIdentity:
        return RootIdentity(FSUUID, "/@", "/dev/test[/@]", "/dev/test", CURRENT_UUID)

    def _mount_top(self, identity: RootIdentity, *, read_only: bool = False) -> None:
        return None

    def _unmount(self, path: Path) -> None:
        return None

    def close(self) -> None:
        return None

    def _show_uuid(self, path: Path) -> str:
        value = (path / ".uuid").read_text().strip()
        if self.fail_after_swap and path.name == "@" and value == CANDIDATE_UUID:
            return "99999999-9999-9999-9999-999999999999"
        return value

    def _read_only(self, path: Path) -> bool:
        return (path / ".ro").exists()

    def _set_read_only(self, path: Path, value: bool) -> None:
        marker = path / ".ro"
        if value:
            marker.touch()
        elif marker.exists():
            marker.unlink()


def seed_fixture(ops: FixtureBtrfs) -> tuple[dict[str, str], dict[str, bytes]]:
    current = ops.top / "@"
    candidate = ops.top / ops.candidate
    current.mkdir()
    candidate.mkdir()
    (current / ".uuid").write_text(CURRENT_UUID)
    (candidate / ".uuid").write_text(CANDIDATE_UUID)
    (candidate / ".ro").touch()
    old: dict[str, bytes] = {}
    expected: dict[str, str] = {}
    for index, artifact in enumerate(BOOT_ARTIFACTS):
        relative = Path(artifact).relative_to("/boot")
        live = ops.boot_root / relative
        staged = candidate / artifact.lstrip("/")
        live.parent.mkdir(parents=True, exist_ok=True)
        staged.parent.mkdir(parents=True, exist_ok=True)
        old_bytes = f"old-{index}".encode()
        new_bytes = f"new-{index}".encode()
        live.write_bytes(old_bytes)
        staged.write_bytes(new_bytes)
        old[artifact] = old_bytes
        expected[artifact] = sha256_file(staged)
    return expected, old


def main() -> None:
    check("candidate name is transaction-bound", candidate_name(TX1) == "@maho-update-candidate-abcdef123456")
    check("backup name is transaction-bound", backup_name(TX1) == "@maho-update-backup-abcdef123456")
    check("update confirmation binds package generation", update_confirmation(TX1, "pkg-abc") == f"UPDATE:{TX1}:pkg-abc")
    check("activation confirmation binds candidate UUID", activation_confirmation(TX1, CANDIDATE_UUID) == f"ACTIVATE:{TX1}:{CANDIDATE_UUID}")

    with tempfile.TemporaryDirectory(prefix="maho-m4b-sysroot-") as temporary:
        base = Path(temporary)
        candidate = base / "candidate"
        cache = base / "cache"
        config = candidate / "etc/maho/pacman-kernel.conf"
        payload = cache / "linux-cachyos-7.2-1-x86_64.pkg.tar.zst"
        config.parent.mkdir(parents=True)
        config.write_text("[options]\n")
        cache.mkdir()
        payload.write_bytes(b"package")
        plan = SimpleNamespace(payload_paths=(str(payload),), initramfs_presets=())
        native = NativeCandidateUpdateOps(
            candidate,
            cache,
            transaction={},
            expected_versions={"linux-cachyos": "7.2-1", "linux-cachyos-headers": "7.2-1"},
            runtime_user="magetsu",
            runtime_identity={},
            recovery_seed={},
            recovery_journal_path=base / "recovery.json",
            machine_id=MACHINE,
            candidate_uuid=CANDIDATE_UUID,
            btrfs_ops=None,
        )
        install = native.install_command(plan)
        query = native.query_command(plan)
        expected_prefix = ("/usr/bin/pacman", "--sysroot", str(candidate.resolve()), "--config", "/etc/maho/pacman-kernel.conf")
        check("native install uses exact candidate sysroot", install[:5] == expected_prefix)
        check("native query uses exact candidate sysroot", query[:5] == expected_prefix)
        check("native install never uses legacy root or host dbpath", "--root" not in install and "--dbpath" not in install)
        check("native query never uses legacy root or host dbpath", "--root" not in query and "--dbpath" not in query)
        check("native local payload path is preserved under sysroot", install[-1] == str(payload.resolve()))

    with tempfile.TemporaryDirectory(prefix="maho-m4b-native-") as temporary:
        base = Path(temporary)
        ops = FixtureBtrfs(TX1, base)
        expected, old = seed_fixture(ops)
        result = ops.arm_activation(machine_id=MACHINE, expected_candidate_uuid=CANDIDATE_UUID, expected_boot_hashes=expected)
        check("activation swaps exact candidate into /@", (ops.top / "@/.uuid").read_text().strip() == CANDIDATE_UUID)
        check("activation preserves exact previous root", (ops.top / backup_name(TX1) / ".uuid").read_text().strip() == CURRENT_UUID)
        check("successful activation removes candidate name", not (ops.top / candidate_name(TX1)).exists())
        check("activation publishes exact candidate boot artifacts", all(sha256_file(ops.boot_root / Path(a).relative_to('/boot')) == expected[a] for a in BOOT_ARTIFACTS))
        backup_dir = Path(result["boot_backup_dir"])
        check("activation preserves old boot artifacts", all((backup_dir / Path(a).name).read_bytes() == old[a] for a in BOOT_ARTIFACTS))
        check("activation never reboots or mutates firmware", result["reboot_performed"] is False and result["firmware_mutated"] is False)

    with tempfile.TemporaryDirectory(prefix="maho-m4b-rollback-") as temporary:
        base = Path(temporary)
        ops = FixtureBtrfs(TX2, base, fail_after_swap=True)
        expected, old = seed_fixture(ops)
        try:
            ops.arm_activation(machine_id=MACHINE, expected_candidate_uuid=CANDIDATE_UUID, expected_boot_hashes=expected)
        except RuntimeError as exc:
            check("post-swap verification failure is surfaced", "activated /@ UUID" in str(exc))
        else:
            raise AssertionError("forced activation failure unexpectedly succeeded")
        check("failed activation restores original /@", (ops.top / "@/.uuid").read_text().strip() == CURRENT_UUID)
        failed_candidate = ops.top / candidate_name(TX2)
        check("failed activation re-freezes candidate", failed_candidate.is_dir() and (failed_candidate / ".ro").exists())
        check("failed activation restores every live boot artifact", all((ops.boot_root / Path(a).relative_to('/boot')).read_bytes() == old[a] for a in BOOT_ARTIFACTS))

    print("ALL M4B NATIVE ACTIVATION CONTRACTS PASS")


if __name__ == "__main__":
    main()
