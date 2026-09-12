#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import maho_system_restore_campaign as campaign  # noqa: E402
from maho_system_restore_journal import (  # noqa: E402
    create_journal,
    journal_path,
    read_journal,
    transition_journal,
    write_journal,
)

TX = "l3-20260911T120000Z-deadbeef"
TX2 = "l3-20260911T120001Z-cafebabe"
REV = "a" * 40
MID = "0123456789abcdef0123456789abcdef"
GID = "g3-77e9fa88205b81c87307acfc"
SID = 501
TARGET_UUID = "target-snapshot-uuid"
BACKUP_UUID = "backup-snapshot-uuid"
FSUUID = "ce979d1c-c145-4be0-9ce3-591b6fd0a3a1"
HOME_UUID = "home-subvolume-uuid"
KHASH = "1" * 64
IHASH = "2" * 64


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def expect(name: str, exc_type, func, contains: str | None = None) -> None:
    try:
        func()
    except exc_type as exc:
        if contains is not None and contains not in str(exc):
            raise AssertionError(f"{name}: wrong error: {exc}") from exc
        print(f"PASS {name}")
        return
    raise AssertionError(name)


def target_dict() -> dict:
    return {
        "generation_id": GID,
        "snapshot_id": SID,
        "snapshot_uuid": TARGET_UUID,
        "root_filesystem_uuid": FSUUID,
        "expected_kernel_package": "linux-cachyos",
        "expected_kernel_version": "7.1.8-1",
        "expected_kernel_sha256": KHASH,
        "expected_initramfs_sha256": IHASH,
    }


def provider_dict() -> dict:
    return {
        "path": "/usr/bin/limine-snapper-restore",
        "package": "limine-snapper-sync",
        "version": "1.31.0-1",
        "uid": 0,
        "mode": 0o755,
        "regular_file": True,
        "package_owns_command": True,
        "package_files_ok": True,
    }


def home_dict() -> dict:
    return {
        "filesystem_uuid": FSUUID,
        "fsroot": "/@home",
        "subvolume_uuid": HOME_UUID,
    }


class FakeGeneration:
    generation_id = GID
    eligible = True
    known_good = True
    snapshot = SimpleNamespace(snapshot_id=SID)


class FakeReport:
    current_platform = {
        "recovery_overlay_active": False,
        "root_fstype": "btrfs",
        "root_fsroot": "/@",
        "home_scope": "excluded",
    }
    generations = (FakeGeneration(),)


class FakeHost:
    def __init__(self) -> None:
        self.target_calls: list[str] = []
        self.wait_calls: list[int] = []
        self.uuid_calls: list[int] = []

    def create_known_good_target(self, transaction_id: str) -> int:
        self.target_calls.append(transaction_id)
        return SID

    def wait_for_backup(self, snapshot_id: int) -> dict:
        self.wait_calls.append(snapshot_id)
        return {
            "snapshot_id": snapshot_id,
            "snapshot_uuid": BACKUP_UUID if snapshot_id != SID else TARGET_UUID,
            "exists": True,
            "read_only": True,
            "boot_state_coherent": True,
            "files_verified": True,
            "recovery_overlay_flagged": True,
            "kernel_packages": ["linux-cachyos", "linux-cachyos-lts"],
            "kernel_sha256": KHASH,
            "initramfs_sha256": IHASH,
        }

    def snapshot_uuid(self, snapshot_id: int) -> str:
        self.uuid_calls.append(snapshot_id)
        return TARGET_UUID if snapshot_id == SID else BACKUP_UUID

    def home_identity(self) -> dict:
        return home_dict()


def make_root(base: Path) -> Path:
    root = base / "payload"
    (root / "config").mkdir(parents=True)
    (root / "SOURCE_REVISION").write_text(REV + "\n", encoding="utf-8")
    (root / "config/platform.json").write_text("{}\n", encoding="utf-8")
    return root


def write_seed(boot: Path, txid: str, *, gid: str = GID) -> dict:
    root_marker = f"/var/lib/maho/l3-campaign/{txid}.root-marker"
    home_marker = f"/home/tester/.maho-l3-campaign/{txid}.home-marker"
    seed = campaign._validate_seed({
        "schema_version": 1,
        "transaction_id": txid,
        "source_revision": REV,
        "generation_id": gid,
        "snapshot_id": SID,
        "snapshot_uuid": TARGET_UUID,
        "root_marker": root_marker,
        "home_marker": home_marker,
        "home_user": "tester",
    })
    path = campaign._seed_path(MID, txid, boot)
    campaign._write_json_atomic(path, seed)
    return seed


def write_prepared_journal(boot: Path, txid: str) -> Path:
    path = journal_path(boot, MID, txid)
    payload = create_journal(
        transaction_id=txid,
        source_revision=REV,
        target=target_dict(),
        backup={"snapshot_id": 600, "snapshot_uuid": BACKUP_UUID},
        home=home_dict(),
        provider={
            "command": "/usr/bin/limine-snapper-restore",
            "package": "limine-snapper-sync",
            "version": "1.31.0-1",
        },
    )
    write_journal(path, payload)
    return path


def advance_awaiting(path: Path) -> None:
    payload = read_journal(path)
    for phase in ("restore-started", "provider-returned", "restored-awaiting-reboot"):
        payload = transition_journal(payload, phase)
    write_journal(path, payload)


def main() -> None:
    report = FakeReport()
    blocked_report = SimpleNamespace(
        current_platform={
            "recovery_overlay_active": True,
            "root_fstype": "overlay",
            "root_fsroot": "/",
            "home_scope": "excluded",
        },
        generations=(),
    )
    check(
        "seed blockers reject recovery boot",
        "normal_root_required" in campaign._seed_blockers(blocked_report),
    )
    root_marker, home_marker = campaign.marker_paths(TX, Path("/home/tester"))
    check("root marker path is exact", str(root_marker) == f"/var/lib/maho/l3-campaign/{TX}.root-marker")
    check("home marker path is exact", str(home_marker) == f"/home/tester/.maho-l3-campaign/{TX}.home-marker")

    tampered = {
        "schema_version": 1,
        "transaction_id": TX,
        "source_revision": REV,
        "generation_id": GID,
        "snapshot_id": SID,
        "snapshot_uuid": TARGET_UUID,
        "root_marker": "/etc/passwd",
        "home_marker": str(home_marker),
        "home_user": "tester",
    }
    expect("tampered seed marker path is rejected", ValueError, lambda: campaign._validate_seed(tampered), "marker paths")

    originals = {
        "report": campaign._report,
        "prepare_dirs": campaign._prepare_marker_directories,
        "write_marker": campaign._write_marker,
        "markers_complete": campaign._markers_complete,
        "marker_blockers": campaign._marker_blockers,
        "collect_provider": campaign.collect_provider_evidence,
        "plan_prepare": campaign.plan_system_restore_preparation,
        "prepare_restore": campaign.prepare_restore_transaction,
        "plan_execute": campaign.plan_system_restore,
        "runtime_ops": campaign.SystemRestoreRuntimeOps,
        "execute_restore": campaign.execute_prepared_restore,
        "verify_postboot": campaign.verify_postboot_restore,
    }
    real_geteuid = campaign.os.geteuid
    real_getpwnam = campaign.pwd.getpwnam

    try:
        campaign.os.geteuid = lambda: 0
        campaign.pwd.getpwnam = lambda name: SimpleNamespace(
            pw_uid=1000, pw_gid=1000, pw_dir=f"/home/{name}"
        )
        campaign._report = lambda policy: report
        campaign._prepare_marker_directories = lambda home, user: (
            Path("/var/lib/maho/l3-campaign"), home / ".maho-l3-campaign"
        )
        marker_writes: list[tuple[str, int, int]] = []
        campaign._write_marker = lambda path, text, uid, gid: marker_writes.append((str(path), uid, gid))

        with tempfile.TemporaryDirectory(prefix="maho-l3-campaign-") as td:
            base = Path(td)
            root = make_root(base)
            boot = base / "boot"
            host = FakeHost()

            seeded = campaign.seed_campaign(
                root=root,
                machine_id=MID,
                home=Path("/home/tester"),
                transaction_id=TX,
                ops=host,
                boot_root=boot,
            )
            check("seed creates exactly one target snapshot", host.target_calls == [TX])
            check("seed waits for exact target snapshot", host.wait_calls == [SID])
            check("seed binds exact target generation", seeded["generation_id"] == GID)
            check("seed binds exact target UUID", seeded["snapshot_uuid"] == TARGET_UUID)
            check("seed records exact source revision", seeded["source_revision"] == REV)
            check("seed writes root and home markers only after target", len(marker_writes) == 2)
            check("seed root marker is root-owned", marker_writes[0][1:] == (0, 0))
            check("seed home marker is user-owned", marker_writes[1][1:] == (1000, 1000))
            seed_path = campaign._seed_path(MID, TX, boot)
            check("seed is durable on boot storage", seed_path.is_file())
            check("seed roundtrip validates", campaign._read_seed(seed_path)["generation_id"] == GID)

            campaign._report = lambda policy: blocked_report
            blocked_host = FakeHost()
            expect(
                "seed in recovery boot is blocked before snapshot creation",
                RuntimeError,
                lambda: campaign.seed_campaign(
                    root=root, machine_id=MID, home=Path("/home/tester"),
                    transaction_id=TX2, ops=blocked_host, boot_root=boot,
                ),
                "seed blocked",
            )
            check("blocked seed performs zero mutation", blocked_host.target_calls == [])
            campaign._report = lambda policy: report

            campaign.os.geteuid = lambda: 1000
            nonroot_host = FakeHost()
            expect(
                "non-root seed is rejected before mutation",
                PermissionError,
                lambda: campaign.seed_campaign(
                    root=root, machine_id=MID, home=Path("/home/tester"),
                    transaction_id=TX2, ops=nonroot_host, boot_root=boot,
                ),
            )
            check("non-root seed leaves host untouched", nonroot_host.target_calls == [])
            campaign.os.geteuid = lambda: 0

            campaign._markers_complete = lambda seed: True
            campaign.collect_provider_evidence = lambda policy: provider_dict()
            campaign.plan_system_restore_preparation = lambda report, gid, policy, provider: SimpleNamespace(
                ready=True,
                blockers=(),
                restore_authorized=False,
                generation_id=gid,
                snapshot_id=SID,
                root_filesystem_uuid=FSUUID,
                expected_kernel_package="linux-cachyos",
                expected_kernel_version="7.1.8-1",
                expected_kernel_sha256=KHASH,
                expected_initramfs_sha256=IHASH,
            )
            prepare_calls: list[str] = []

            def fake_prepare(plan, **kwargs):
                prepare_calls.append(kwargs["transaction_id"])
                jpath = journal_path(kwargs["boot_root"], kwargs["machine_id"], kwargs["transaction_id"])
                payload = create_journal(
                    transaction_id=kwargs["transaction_id"],
                    source_revision=kwargs["source_revision"],
                    target=target_dict(),
                    backup={"snapshot_id": 600, "snapshot_uuid": BACKUP_UUID},
                    home=home_dict(),
                    provider={
                        "command": "/usr/bin/limine-snapper-restore",
                        "package": "limine-snapper-sync",
                        "version": "1.31.0-1",
                    },
                )
                write_journal(jpath, payload)
                return SimpleNamespace(
                    transaction_id=kwargs["transaction_id"],
                    journal_path=str(jpath),
                    backup_snapshot_id=600,
                    backup_snapshot_uuid=BACKUP_UUID,
                )

            campaign.prepare_restore_transaction = fake_prepare
            prepared = campaign.prepare_campaign(
                root=root, machine_id=MID, transaction_id=TX,
                generation_id=GID, boot_root=boot, ops=host,
            )
            check("prepare invokes bounded preparation exactly once", prepare_calls == [TX])
            check("prepare never grants restore authority", prepared["restore_authorized"] is False)
            check("prepare binds emergency backup", prepared["backup_snapshot_id"] == 600)
            check("prepared journal is durable", read_journal(Path(prepared["journal_path"]))["phase"] == "prepared")

            expect(
                "prepare rejects generation drift before backup creation",
                RuntimeError,
                lambda: campaign.prepare_campaign(
                    root=root, machine_id=MID, transaction_id=TX,
                    generation_id="g3-ffffffffffffffffffffffff", boot_root=boot, ops=host,
                ),
                "differs from seeded target",
            )
            check("generation drift does not invoke preparation", prepare_calls == [TX])

            (root / "SOURCE_REVISION").write_text("b" * 40 + "\n", encoding="utf-8")
            expect(
                "prepare rejects source revision drift",
                RuntimeError,
                lambda: campaign.prepare_campaign(
                    root=root, machine_id=MID, transaction_id=TX,
                    generation_id=GID, boot_root=boot, ops=host,
                ),
                "source revision drifted",
            )
            check("source drift does not invoke preparation", prepare_calls == [TX])
            (root / "SOURCE_REVISION").write_text(REV + "\n", encoding="utf-8")

            recovery_report = SimpleNamespace(
                current_platform={
                    "recovery_overlay_active": True,
                    "root_fstype": "btrfs",
                    "root_fsroot": f"/@snapshots/{SID}/snapshot",
                    "root_filesystem_uuid": FSUUID,
                    "root_source": f"/dev/fake[/@snapshots/{SID}/snapshot]",
                    "home_scope": "excluded",
                    "current_snapshot_id": None,
                },
                generations=(),
            )
            campaign._report = lambda policy: recovery_report
            planned_reports: list[object] = []

            def fake_plan_execute(report, gid, policy, provider):
                planned_reports.append(report)
                return SimpleNamespace(
                    campaign_ready=True, automatic_allowed=False, requires_confirmation=True,
                    generation_id=gid, snapshot_id=SID, root_filesystem_uuid=FSUUID,
                    expected_kernel_package="linux-cachyos", expected_kernel_version="7.1.8-1",
                    expected_kernel_sha256=KHASH, expected_initramfs_sha256=IHASH,
                )

            campaign.plan_system_restore = fake_plan_execute
            campaign.SystemRestoreRuntimeOps = lambda *args, **kwargs: SimpleNamespace(
                structural_evidence=lambda: object(),
                postboot_evidence=lambda: object(),
            )
            execute_calls: list[str] = []

            def fake_execute(jpath, **kwargs):
                execute_calls.append(str(jpath))
                payload = read_journal(jpath)
                for phase in ("restore-started", "provider-returned", "restored-awaiting-reboot"):
                    payload = transition_journal(payload, phase)
                write_journal(jpath, payload)
                return SimpleNamespace(
                    phase="restored-awaiting-reboot",
                    provider_exit_code=0,
                    mutation_started=True,
                    blockers=(),
                )

            campaign.execute_prepared_restore = fake_execute
            expect(
                "wrong destructive confirmation never reaches provider path",
                RuntimeError,
                lambda: campaign.execute_campaign(
                    root=root, machine_id=MID, transaction_id=TX,
                    generation_id=GID, confirmation="nope",
                    boot_root=boot, ops=host,
                ),
                "confirmation token",
            )
            check("bad confirmation performs zero restore attempts", execute_calls == [])

            wrong_root_report = SimpleNamespace(current_platform={**recovery_report.current_platform, "root_fsroot": "/@snapshots/500/snapshot"}, generations=())
            expect(
                "prepared execute rejects wrong recovery root before provider",
                RuntimeError,
                lambda: campaign._prepared_execution_report(
                    wrong_root_report, campaign._read_seed(campaign._seed_path(MID, TX, boot)),
                    read_journal(journal_path(boot, MID, TX)), host.wait_for_backup(SID),
                ),
                "booted_snapshot_root_mismatch",
            )
            drifted = host.wait_for_backup(SID)
            drifted["kernel_sha256"] = "f" * 64
            expect(
                "prepared execute rejects boot artifact hash drift before provider",
                RuntimeError,
                lambda: campaign._prepared_execution_report(
                    recovery_report, campaign._read_seed(campaign._seed_path(MID, TX, boot)),
                    read_journal(journal_path(boot, MID, TX)), drifted,
                ),
                "target_kernel_hash_drift",
            )

            executed = campaign.execute_campaign(
                root=root, machine_id=MID, transaction_id=TX,
                generation_id=GID,
                confirmation=f"RESTORE:{GID}:{TX}",
                boot_root=boot, ops=host,
            )
            check("recovery execute does not depend on Snapper candidate enumeration", len(planned_reports) == 1 and len(planned_reports[0].generations) == 1)
            check("prepared target reconstructs exact current recovery generation", planned_reports[0].generations[0].generation_id == GID and planned_reports[0].current_platform["current_snapshot_id"] == SID)
            check("exact confirmation performs one bounded restore attempt", len(execute_calls) == 1)
            check("execute stops at reboot-ready state", executed["phase"] == "restored-awaiting-reboot")
            check("execute never reboots automatically", executed["reboot_performed"] is False)
            check("execute journal is awaiting reboot", read_journal(Path(prepared["journal_path"]))["phase"] == "restored-awaiting-reboot")

            verify_calls: list[str] = []
            campaign._marker_blockers = lambda seed: []

            def fake_verify(jpath, evidence):
                verify_calls.append(str(jpath))
                payload = read_journal(jpath)
                payload = transition_journal(payload, "structural-verified")
                write_journal(jpath, payload)
                return SimpleNamespace(phase="structural-verified", blockers=())

            campaign.verify_postboot_restore = fake_verify

            verified = campaign.verify_campaign(
                root=root, machine_id=MID, transaction_id=TX,
                boot_root=boot, ops=host,
            )
            check("postboot verify finalizes exact transaction", verified["phase"] == "structural-verified")
            check("postboot structural verification runs once", verify_calls == [prepared["journal_path"]])
            check("successful native campaign records root rollback", verified["root_marker_removed"] is True)
            check("successful native campaign records home preservation", verified["home_marker_preserved"] is True)

            status = campaign.status_campaign(machine_id=MID, transaction_id=TX, boot_root=boot)
            check("status reports final journal phase", status["journal_phase"] == "structural-verified")
            check("status binds seeded generation", status["generation_id"] == GID)

            write_seed(boot, TX2)
            failed_path = write_prepared_journal(boot, TX2)
            advance_awaiting(failed_path)
            campaign._marker_blockers = lambda seed: ["root_marker_survived_restore"]
            verify_calls_before = list(verify_calls)
            failed = campaign.verify_campaign(
                root=root, machine_id=MID, transaction_id=TX2,
                boot_root=boot, ops=host,
            )
            check("failed root marker proof is terminal", failed["phase"] == "verify-failed")
            check("failed marker proof is durable", read_journal(failed_path)["phase"] == "verify-failed")
            check("failed marker proof never reaches postboot certification", verify_calls == verify_calls_before)
            check("marker failure is explained", failed["blockers"] == ["root_marker_survived_restore"])

    finally:
        campaign._report = originals["report"]
        campaign._prepare_marker_directories = originals["prepare_dirs"]
        campaign._write_marker = originals["write_marker"]
        campaign._markers_complete = originals["markers_complete"]
        campaign._marker_blockers = originals["marker_blockers"]
        campaign.collect_provider_evidence = originals["collect_provider"]
        campaign.plan_system_restore_preparation = originals["plan_prepare"]
        campaign.prepare_restore_transaction = originals["prepare_restore"]
        campaign.plan_system_restore = originals["plan_execute"]
        campaign.SystemRestoreRuntimeOps = originals["runtime_ops"]
        campaign.execute_prepared_restore = originals["execute_restore"]
        campaign.verify_postboot_restore = originals["verify_postboot"]
        campaign.os.geteuid = real_geteuid
        campaign.pwd.getpwnam = real_getpwnam

    print("ALL SYSTEM RESTORE NATIVE CAMPAIGN CONTRACTS PASS")


if __name__ == "__main__":
    main()
