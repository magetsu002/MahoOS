#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_update_discovery import CommandResult  # noqa: E402
from maho_update_staging import IsolatedPacmanStaging, stage_transaction, validate_manifest  # noqa: E402
from maho_update_state import create_transaction  # noqa: E402

NOW = datetime(2026, 9, 12, 3, 0, tzinfo=timezone.utc)


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def rejected(name: str, function) -> None:
    try:
        function()
    except (ValueError, PermissionError):
        check(name, True)
        return
    check(name, False)


def transaction() -> dict:
    return create_transaction(
        transaction_id="upd-20260912T030000Z-123456abcdef",
        source_revision="c" * 40,
        packages=[
            {"name": "linux-cachyos", "installed_version": "7.1", "candidate_version": "7.2", "repository": "core", "download_size": 8, "installed_size": 16, "roles": ["kernel"]},
            {"name": "maho-os", "installed_version": "4.0", "candidate_version": "4.1", "repository": "maho", "download_size": 8, "installed_size": 16, "roles": ["maho-runtime"]},
        ],
        activation_requirements=["restart"], recovery_generation_id=None, now=NOW,
    )


class FakePacman:
    def __init__(self, cache: Path, *, missing: str | None = None, download_error: bool = False, incomplete: bool = False, extra_dependency: bool = False) -> None:
        self.cache = cache
        self.missing = missing
        self.download_error = download_error
        self.incomplete = incomplete
        self.extra_dependency = extra_dependency

    def __call__(self, command) -> CommandResult:
        if "--print" in command:
            rows = [("core", "linux-cachyos", "7.2"), ("maho", "maho-os", "4.1")]
            if self.extra_dependency:
                rows.append(("extra", "new-dependency", "1"))
            return CommandResult(0, "".join(f"{repo}\t{name}\t{version}\n" for repo, name, version in rows if name != self.missing))
        if "--downloadonly" in command:
            if self.download_error:
                return CommandResult(1, "", "network unavailable")
            self.cache.mkdir(parents=True, exist_ok=True)
            (self.cache / "linux-cachyos-7.2-x86_64.pkg.tar.zst").write_bytes(b"kernel-payload")
            if not self.incomplete:
                (self.cache / "maho-os-4.1-any.pkg.tar.zst").write_bytes(b"maho-payload")
            return CommandResult(0, "")
        if "--file" in command:
            filename = Path(command[-1]).name
            if "--list" in command:
                if filename.startswith("linux-cachyos-"):
                    return CommandResult(0, "linux-cachyos /usr/lib/modules/7.2/kernel/test.ko.zst\nlinux-cachyos /usr/lib/initcpio/install/linux\n")
                if filename.startswith("maho-os-"):
                    return CommandResult(0, "maho-os /usr/lib/maho/current\nmaho-os /usr/bin/maho-session\n")
                return CommandResult(1, "")
            if filename.startswith("linux-cachyos-"):
                return CommandResult(0, "Name : linux-cachyos\nVersion : 7.2\n")
            if filename.startswith("maho-os-"):
                return CommandResult(0, "Name : maho-os\nVersion : 4.1\n")
            return CommandResult(1, "")
        raise AssertionError(command)


def backend(root: Path, **kwargs) -> IsolatedPacmanStaging:
    database = root / "db"
    database.mkdir(parents=True)
    cache = root / "cache"
    fake = FakePacman(cache, **kwargs)
    return IsolatedPacmanStaging(database, cache, runner=fake)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maho-update-staging-") as temporary:
        root = Path(temporary)
        staging = backend(root)
        stale = staging.cache / "stale-1-any.pkg.tar.zst"
        staging.cache.mkdir(parents=True)
        stale.write_bytes(b"stale")
        result = stage_transaction(transaction(), staging, available_bytes=1024**3, now=NOW)
        check("complete exact payload set reaches STAGED", result.transaction["state"] == "STAGED")
        check("all staged payloads carry hashes and Pacman signature status", all(len(item["sha256"]) == 64 and item["signature_status"] == "verified-by-pacman" for item in result.manifest["payloads"]))
        payloads = {item["name"]: item for item in result.manifest["payloads"]}
        check("repository provenance is independent from effects", payloads["linux-cachyos"]["provenance"]["kind"] == "repository" and payloads["maho-os"]["provenance"]["kind"] == "repository")
        check("exact kernel artifact is boot-critical", payloads["linux-cachyos"]["effects"]["classification"] == "boot-critical")
        check("non-boot Maho artifact remains normal", payloads["maho-os"]["effects"]["classification"] == "normal")
        check("manifest aggregates exact effects", result.manifest["effects"]["boot_critical_packages"] == ["linux-cachyos"] and result.manifest["effects"]["normal_packages"] == ["maho-os"])
        check("exact effects replace preliminary activation guess", result.transaction["activation"]["requirements"] == ["explicit-reboot", "initramfs-or-boot-refresh", "maho-runtime-release"])
        check("STAGED manifest binds the package generation", result.manifest["package_generation_id"] == transaction()["package_generation"]["id"])
        check("bounded cleanup removes stale isolated cache payload", str(stale) in result.cleanup_removed and not stale.exists())
        check("staging never targets live package state", all("/var/lib/pacman" not in command and "/var/cache/pacman/pkg" not in command for command in staging.commands))
        check("staging uses exact repository/name=version targets", any("core/linux-cachyos=7.2" in command and "maho/maho-os=4.1" in command for command in staging.commands))
        resumed_backend = IsolatedPacmanStaging(root / "db", root / "cache", runner=lambda command: (_ for _ in ()).throw(AssertionError("valid resume must not call Pacman")))
        resumed = stage_transaction(transaction(), resumed_backend, available_bytes=1024**3, now=NOW)
        check("verified staging manifest resumes without redownload", resumed.transaction["state"] == "STAGED" and resumed.resumed and not resumed_backend.commands)
        validate_manifest(resumed.manifest, transaction(), resumed_backend.cache)

    with tempfile.TemporaryDirectory(prefix="maho-update-staging-low-") as temporary:
        result = stage_transaction(transaction(), backend(Path(temporary)), available_bytes=1, now=NOW)
        check("low disk blocks before package mutation", result.transaction["state"] == "BLOCKED" and result.transaction["blockers"] == ["insufficient_staging_space"])

    with tempfile.TemporaryDirectory(prefix="maho-update-staging-missing-") as temporary:
        result = stage_transaction(transaction(), backend(Path(temporary), missing="maho-os"), available_bytes=1024**3, now=NOW)
        check("disappeared package blocks exact generation", result.transaction["state"] == "BLOCKED" and "package_unavailable:maho-os" in result.transaction["blockers"])

    with tempfile.TemporaryDirectory(prefix="maho-update-staging-drift-") as temporary:
        result = stage_transaction(transaction(), backend(Path(temporary), extra_dependency=True), available_bytes=1024**3, now=NOW)
        check("new dependency after discovery blocks solver drift", result.transaction["state"] == "BLOCKED" and "package_solver_drift:new-dependency" in result.transaction["blockers"])

    with tempfile.TemporaryDirectory(prefix="maho-update-staging-net-") as temporary:
        result = stage_transaction(transaction(), backend(Path(temporary), download_error=True), available_bytes=1024**3, now=NOW)
        check("network/download failure is bounded and recoverable", result.transaction["state"] == "FAILED_RECOVERABLE")

    with tempfile.TemporaryDirectory(prefix="maho-update-staging-partial-") as temporary:
        result = stage_transaction(transaction(), backend(Path(temporary), incomplete=True), available_bytes=1024**3, now=NOW)
        check("incomplete staging never reaches STAGED", result.transaction["state"] == "FAILED_RECOVERABLE" and result.manifest is None)

    rejected("live package database cannot be staging database", lambda: IsolatedPacmanStaging("/var/lib/pacman", "/tmp/cache"))
    rejected("live package cache cannot be staging cache", lambda: IsolatedPacmanStaging("/tmp/db", "/var/cache/pacman/pkg"))
    with tempfile.TemporaryDirectory(prefix="maho-update-staging-allowlist-") as temporary:
        staging = backend(Path(temporary))
        rejected("live install command is not staging authority", lambda: staging.run(("/usr/bin/pacman", "-S", "linux")))
        rejected("unversioned staging target is refused", lambda: staging.download_command(["linux-cachyos"]))
        rejected("package inspection cannot escape cache", lambda: staging.info_command(Path("/etc/passwd")))

    print("ALL MAHO UPDATE STAGING CONTRACTS PASS")


if __name__ == "__main__":
    main()
