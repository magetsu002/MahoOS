#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_update_discovery import (  # noqa: E402
    CommandResult,
    IsolatedPacmanDiscovery,
    discover_independent_normal_updates,
    discover_updates,
    package_roles,
    parse_name_versions,
    parse_sync_info,
    parse_upgrades,
)

NOW = datetime(2026, 9, 12, 2, 0, tzinfo=timezone.utc)


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def rejected(name: str, function, error=(ValueError, PermissionError, RuntimeError, LookupError)) -> None:
    try:
        function()
    except error:
        check(name, True)
        return
    check(name, False)


class FakeRunner:
    def __call__(self, command) -> CommandResult:
        if "--refresh" in command:
            return CommandResult(0, "")
        if "--query" in command:
            return CommandResult(0, "linux-cachyos 7.1-1\nlinux-cachyos-headers 7.1-1\nmaho-os 4.0-1\n")
        if "--sysupgrade" in command:
            if "--ignore" in command:
                return CommandResult(0, "maho-os\t4.1-1\nnew-runtime-lib\t1.0-1\n")
            return CommandResult(0, "linux-cachyos\t7.2-1\nlinux-cachyos-headers\t7.2-1\nmaho-os\t4.1-1\nnew-runtime-lib\t1.0-1\n")
        if "--info" in command:
            return CommandResult(0, """Repository      : cachyos
Name            : linux-cachyos
Version         : 7.2-1
Download Size   : 128.00 MiB
Installed Size  : 140.00 MiB

Repository      : cachyos
Name            : linux-cachyos-headers
Version         : 7.2-1
Download Size   : 42.00 MiB
Installed Size  : 95.00 MiB

Repository      : maho
Name            : maho-os
Version         : 4.1-1
Download Size   : 3.00 MiB
Installed Size  : 8.00 MiB

Repository      : core
Name            : new-runtime-lib
Version         : 1.0-1
Download Size   : 1.00 MiB
Installed Size  : 2.00 MiB
""")
        raise AssertionError(f"unexpected command: {command!r}")


class SolverFailureRunner:
    def __call__(self, command) -> CommandResult:
        if "--refresh" in command:
            return CommandResult(0, "")
        if "--query" in command:
            return CommandResult(0, "linux-cachyos 7.1-1\n")
        if "--sysupgrade" in command:
            return CommandResult(1, ":: dependency conflict\n", "error: failed to prepare transaction")
        raise AssertionError(f"solver failure should stop before metadata: {command!r}")


def main() -> None:
    upgrades = parse_upgrades("linux 1 -> 2\nmaho-os 3 -> 4\n")
    check("exact candidates parse without partial-upgrade inference", upgrades == [("linux", "1", "2"), ("maho-os", "3", "4")])
    rejected("malformed candidate output fails closed", lambda: parse_upgrades("linux maybe 2"))
    rejected("duplicate candidates fail closed", lambda: parse_upgrades("linux 1 -> 2\nlinux 1 -> 3\n"))
    check("full solver rows parse exact package versions", parse_name_versions("linux\t2\nnew-lib\t1\n", separator="\t") == {"linux": "2", "new-lib": "1"})
    info = parse_sync_info("Repository : core\nName : linux\nVersion : 2\nDownload Size : 1.00 MiB\nInstalled Size : 2.00 MiB\n")
    check("sync metadata binds repository, version, and sizes", info["linux"]["download_size"] == 1024 * 1024)
    check("kernel roles include boot and initramfs implications", set(package_roles("linux-cachyos")) >= {"kernel", "primary-kernel", "initramfs", "boot-artifacts"})
    check("NVIDIA DKMS roles include kernel-module implications", set(package_roles("nvidia-dkms")) >= {"nvidia-kernel", "dkms", "initramfs"})
    check("NVIDIA userspace is not preclassified as boot-critical", package_roles("nvidia-utils") == ["nvidia-userspace"])

    with tempfile.TemporaryDirectory(prefix="maho-update-discovery-") as temporary:
        root = Path(temporary)
        installed = root / "installed-local"
        (installed / "linux-cachyos-7.1-1").mkdir(parents=True)
        backend = IsolatedPacmanDiscovery(root / "isolated", installed_db=installed, runner=FakeRunner())
        result = discover_updates(
            backend,
            source_revision="b" * 40,
            security_evidence={"linux-cachyos": {"trusted": True, "source": "signed-advisory-feed", "relevant": True}},
            now=NOW,
            entropy="123456abcdef",
        )
        transaction = result.transaction
        package_map = {item["name"]: item for item in transaction["package_generation"]["packages"]}
        check("isolated discovery creates authoritative DISCOVERED transaction", transaction["state"] == "DISCOVERED")
        check("exact candidate version is retained", package_map["linux-cachyos"]["candidate_version"] == "7.2-1")
        check("full solver transaction includes newly introduced dependencies", package_map["new-runtime-lib"]["installed_version"] == "<not-installed>")
        check("trusted security evidence is retained", package_map["linux-cachyos"]["security_relevant"] is True and result.security_metadata_source == "signed-advisory-feed")
        provenance = {item["name"]: item for item in transaction["source_provenance"]["packages"]}
        check("source provenance is first-class and repository-bound", provenance["linux-cachyos"]["kind"] == "repository" and provenance["linux-cachyos"]["repository"] == "cachyos")
        check("full discovery records solver selection proof", transaction["selection"]["kind"] == "full" and transaction["selection"]["solver_proof"]["kind"] == "full-system-solver")
        check("untrusted absence never fabricates security metadata", package_map["maho-os"]["security_relevant"] is False)
        check("kernel update activation is explicit", transaction["activation"]["requirements"] == ["boot-artifacts", "initramfs", "maho-runtime-release", "restart"])
        check("discovery emits no notification merely for available updates", result.notifications_emitted == 0)
        check("installed package database is copied rather than linked", (backend.db / "local").is_dir() and not (backend.db / "local").is_symlink())
        check("all commands bind the isolated database", all(str(backend.db) in command for command in backend.commands))
        check("live Pacman database is absent from every command", all("/var/lib/pacman" not in command for command in backend.commands))
        check("discovery command sequence is bounded", len(backend.commands) == 4)
        rejected("unallowlisted live refresh is refused", lambda: backend.run(("/usr/bin/pacman", "-Sy")))
        rejected("unallowlisted package install is refused", lambda: backend.run(("/usr/bin/pacman", "-S", "linux")))
        rejected("candidate shell syntax is refused", lambda: backend.info_command(["linux;reboot"]))

        independent_backend = IsolatedPacmanDiscovery(root / "independent", installed_db=installed, runner=FakeRunner())
        independent = discover_independent_normal_updates(
            independent_backend,
            source_revision="b" * 40,
            now=NOW,
            entropy="fedcba654321",
        )
        selected = {item["name"] for item in independent.transaction["package_generation"]["packages"]}
        check("isolated solver can prove coherent non-boot generation", selected == {"maho-os", "new-runtime-lib"})
        check("boot generation is deferred rather than partially executed", independent.deferred_boot_packages == ("linux-cachyos", "linux-cachyos-headers"))
        check("independent generation records solver-only exclusion proof", independent.transaction["selection"]["solver_proof"]["production_ignore_execution"] is False)
        check("normal generation does not inherit boot activation requirements", independent.transaction["activation"]["requirements"] == ["maho-runtime-release"])
        ignore_commands = [command for command in independent_backend.commands if "--ignore" in command]
        check("boot exclusion is confined to isolated discovery command", len(ignore_commands) == 1 and str(independent_backend.db) in ignore_commands[0])

        failed_backend = IsolatedPacmanDiscovery(root / "solver-failure", installed_db=installed, runner=SolverFailureRunner())
        try:
            discover_updates(failed_backend, source_revision="b" * 40, now=NOW, entropy="abcdef123456")
        except RuntimeError as exc:
            check("nonzero solver is classified before parsing", str(exc).startswith("package_solver_incoherent:"))
            check("solver failure never reaches metadata parsing", len(failed_backend.commands) == 3)
        else:
            check("nonzero solver is classified before parsing", False)

    rejected("isolated root cannot be the live Pacman database", lambda: IsolatedPacmanDiscovery("/var/lib/pacman"))
    rejected("isolated root cannot contain the live Pacman database", lambda: IsolatedPacmanDiscovery("/var/lib"))
    print("ALL MAHO UPDATE DISCOVERY CONTRACTS PASS")


if __name__ == "__main__":
    main()
